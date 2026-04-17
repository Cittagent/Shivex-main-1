"""History-backed queue and completion estimates for analytics jobs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.database import AnalyticsJob, WorkerHeartbeat
from src.models.schemas import JobStatus


@dataclass
class RuntimeEstimate:
    queue_position: int | None
    estimated_wait_seconds: int | None
    estimated_completion_seconds: int | None
    estimate_quality: str | None


def _is_fleet_parent(job: AnalyticsJob) -> bool:
    params = job.parameters if isinstance(job.parameters, dict) else {}
    return str(job.device_id) == "ALL" or bool(params.get("fleet_mode"))


def _duration(values: Iterable[float]) -> float | None:
    cleaned = [float(v) for v in values if float(v) > 0]
    if not cleaned:
        return None
    return float(median(cleaned))


def _estimate_quality(sample_size: int, spread_ratio: float | None) -> str:
    if sample_size >= 20 and spread_ratio is not None and spread_ratio <= 0.6:
        return "high"
    if sample_size >= 8:
        return "medium"
    return "low"


def _spread_ratio(values: list[float]) -> float | None:
    if len(values) < 4:
        return None
    sorted_vals = sorted(values)
    q1 = sorted_vals[len(sorted_vals) // 4]
    q3 = sorted_vals[(len(sorted_vals) * 3) // 4]
    med = _duration(values)
    if not med or med <= 0:
        return None
    return max(0.0, (q3 - q1) / med)


def _range_days(job: AnalyticsJob) -> float:
    start = getattr(job, "date_range_start", None)
    end = getattr(job, "date_range_end", None)
    if not start or not end:
        return 1.0
    delta = end - start
    return max(1.0 / 24.0, float(delta.total_seconds()) / 86400.0)


class JobStatusEstimator:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def estimate(self, job: AnalyticsJob) -> RuntimeEstimate:
        target_is_fleet = _is_fleet_parent(job)
        target_days = _range_days(job)

        completed_q = (
            select(
                AnalyticsJob.execution_time_seconds,
                AnalyticsJob.date_range_start,
                AnalyticsJob.date_range_end,
                AnalyticsJob.device_id,
                AnalyticsJob.parameters,
            )
            .where(AnalyticsJob.status == JobStatus.COMPLETED.value)
            .where(AnalyticsJob.analysis_type == job.analysis_type)
            .where(AnalyticsJob.execution_time_seconds.is_not(None))
            .order_by(AnalyticsJob.completed_at.desc())
            .limit(60)
        )
        completed_rows = list((await self._session.execute(completed_q)).all())

        durations: list[float] = []
        day_spans: list[float] = []
        for row in completed_rows:
            row_is_fleet = str(row.device_id) == "ALL" or bool((row.parameters or {}).get("fleet_mode"))
            if row_is_fleet != target_is_fleet:
                continue
            duration = float(row.execution_time_seconds or 0)
            if duration <= 0:
                continue
            start = row.date_range_start
            end = row.date_range_end
            span_days = 1.0
            if start is not None and end is not None:
                span_days = max(1.0 / 24.0, float((end - start).total_seconds()) / 86400.0)
            durations.append(duration)
            day_spans.append(span_days)

        sample_size = len(durations)
        baseline = _duration(durations)
        span_baseline = _duration(day_spans) if day_spans else 1.0
        if baseline is None:
            baseline = 45.0 if target_is_fleet else 30.0
            span_baseline = 1.0

        workload_factor = max(0.4, min(4.5, target_days / max(1e-6, float(span_baseline or 1.0))))
        expected_runtime = int(max(10.0, baseline * workload_factor))

        spread = _spread_ratio(durations)
        quality = _estimate_quality(sample_size, spread)

        active_workers = await self._active_workers()
        queue_position = await self._queue_position(job)

        wait_seconds: int | None = None
        completion_seconds: int | None = None

        if job.status == JobStatus.PENDING.value:
            if queue_position is None:
                queue_position = 0
            wait_seconds = int(max(0, (queue_position + 1) * expected_runtime / max(1, active_workers)))
            completion_seconds = wait_seconds + expected_runtime
        elif job.status == JobStatus.RUNNING.value:
            started_at = getattr(job, "started_at", None)
            if started_at is not None:
                elapsed = max(0.0, (self._utc_now() - self._as_utc(started_at)).total_seconds())
                remaining = int(expected_runtime - elapsed)
                completion_seconds = max(1, remaining)

        return RuntimeEstimate(
            queue_position=queue_position,
            estimated_wait_seconds=wait_seconds,
            estimated_completion_seconds=completion_seconds,
            estimate_quality=quality,
        )

    async def _active_workers(self) -> int:
        cutoff = self._utc_now() - timedelta(seconds=120)
        q = (
            select(func.count())
            .select_from(WorkerHeartbeat)
            .where(WorkerHeartbeat.last_heartbeat_at >= cutoff)
        )
        row = await self._session.execute(q)
        return max(1, int(row.scalar() or 0))

    async def _queue_position(self, job: AnalyticsJob) -> int | None:
        if job.status != JobStatus.PENDING.value:
            return None
        q = (
            select(func.count())
            .select_from(AnalyticsJob)
            .where(AnalyticsJob.status == JobStatus.PENDING.value)
            .where(AnalyticsJob.created_at < job.created_at)
        )
        result = await self._session.execute(q)
        return max(0, int(result.scalar() or 0))

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
