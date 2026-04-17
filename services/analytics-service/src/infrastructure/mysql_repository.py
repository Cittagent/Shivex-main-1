"""MySQL implementation of result repository."""

from datetime import datetime
from typing import Any, Dict, List, Optional

import math
import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from services.shared.tenant_context import TenantContext
from src.models.database import AnalyticsJob, ModelArtifact
from src.models.schemas import JobStatus
from src.services.result_repository import ResultRepository, UNSET
from src.utils.exceptions import JobNotFoundError

logger = structlog.get_logger()


class MySQLResultRepository(ResultRepository):
    """MySQL implementation of result repository."""

    def __init__(self, session: AsyncSession, ctx: TenantContext | None = None):
        self._session = session
        self._ctx = ctx
        self._logger = logger.bind(repository="MySQLResultRepository")

    def _sanitize_json(self, value: Any) -> Any:
        """Recursively replace NaN / inf values so JSON inserts never fail."""

        if value is None:
            return None

        if isinstance(value, float):
            if math.isnan(value) or math.isinf(value):
                return None
            return value

        if hasattr(value, "tolist") and not isinstance(value, (str, bytes, bytearray)):
            try:
                return self._sanitize_json(value.tolist())
            except Exception:
                pass

        if isinstance(value, list):
            return [self._sanitize_json(v) for v in value]

        if isinstance(value, dict):
            return {k: self._sanitize_json(v) for k, v in value.items()}

        return value

    async def create_job(
        self,
        job_id: str,
        device_id: str,
        analysis_type: str,
        model_name: str,
        date_range_start: datetime,
        date_range_end: datetime,
        parameters: Optional[Dict[str, Any]],
    ) -> None:
        job = AnalyticsJob(
            job_id=job_id,
            device_id=device_id,
            analysis_type=analysis_type,
            model_name=model_name,
            date_range_start=date_range_start,
            date_range_end=date_range_end,
            parameters=self._sanitize_json(parameters),
            status=JobStatus.PENDING.value,
            progress=0.0,
            phase="queued",
            phase_label="Queued",
            phase_progress=0.0,
        )

        self._session.add(job)
        await self._session.commit()

        self._logger.info("job_created", job_id=job_id, device_id=device_id)

    async def get_job(self, job_id: str) -> AnalyticsJob:
        result = await self._session.execute(
            select(AnalyticsJob).where(AnalyticsJob.job_id == job_id)
        )
        job = result.scalar_one_or_none()

        if not job:
            raise JobNotFoundError(f"Job {job_id} not found")

        return job

    def _extract_job_device_ids(self, job: AnalyticsJob) -> list[str]:
        if str(job.device_id or "").strip() and str(job.device_id) != "ALL":
            return [str(job.device_id)]

        params = job.parameters if isinstance(job.parameters, dict) else {}
        raw_device_ids = params.get("device_ids")
        if not isinstance(raw_device_ids, list):
            return []

        normalized: list[str] = []
        seen: set[str] = set()
        for device_id in raw_device_ids:
            normalized_id = str(device_id).strip()
            if normalized_id and normalized_id not in seen:
                seen.add(normalized_id)
                normalized.append(normalized_id)
        return normalized

    def _job_is_visible(
        self,
        job: AnalyticsJob,
        *,
        tenant_id: Optional[str] = None,
        accessible_device_ids: Optional[list[str]] = None,
    ) -> bool:
        params = job.parameters if isinstance(job.parameters, dict) else {}
        if tenant_id is not None and params.get("tenant_id") != tenant_id:
            return False

        if accessible_device_ids is None:
            return True

        referenced_device_ids = self._extract_job_device_ids(job)
        if not referenced_device_ids:
            return False

        accessible_set = set(str(device_id) for device_id in accessible_device_ids)
        return all(device_id in accessible_set for device_id in referenced_device_ids)

    def _list_jobs_base_query(
        self,
        *,
        status: Optional[str] = None,
        device_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ):
        query = (
            select(AnalyticsJob)
            .options(
                load_only(
                    AnalyticsJob.job_id,
                    AnalyticsJob.device_id,
                    AnalyticsJob.analysis_type,
                    AnalyticsJob.model_name,
                    AnalyticsJob.date_range_start,
                    AnalyticsJob.date_range_end,
                    AnalyticsJob.parameters,
                    AnalyticsJob.status,
                    AnalyticsJob.progress,
                    AnalyticsJob.phase,
                    AnalyticsJob.phase_label,
                    AnalyticsJob.phase_progress,
                    AnalyticsJob.message,
                    AnalyticsJob.error_message,
                    AnalyticsJob.created_at,
                    AnalyticsJob.started_at,
                    AnalyticsJob.completed_at,
                    AnalyticsJob.attempt,
                    AnalyticsJob.queue_position,
                    AnalyticsJob.queue_enqueued_at,
                    AnalyticsJob.queue_started_at,
                    AnalyticsJob.worker_lease_expires_at,
                    AnalyticsJob.last_heartbeat_at,
                    AnalyticsJob.error_code,
                )
            )
            .order_by(AnalyticsJob.created_at.desc())
        )

        if status:
            query = query.where(AnalyticsJob.status == status)
        if device_id:
            query = query.where(AnalyticsJob.device_id == device_id)
        if tenant_id:
            query = query.where(
                func.json_unquote(
                    func.json_extract(AnalyticsJob.parameters, "$.tenant_id")
                )
                == tenant_id
            )

        return query

    async def get_job_scoped(
        self,
        job_id: str,
        tenant_id: Optional[str] = None,
        accessible_device_ids: Optional[list[str]] = None,
    ) -> AnalyticsJob:
        job = await self.get_job(job_id)
        if not self._job_is_visible(job, tenant_id=tenant_id, accessible_device_ids=accessible_device_ids):
            raise JobNotFoundError(f"Job {job_id} not found")
        return job

    async def update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
        progress: Optional[float] = None,
        message: Optional[str] = None,
        error_message: Optional[str] = None,
        phase: Optional[str] = None,
        phase_label: Optional[str] = None,
        phase_progress: Optional[float] = None,
    ) -> None:

        job = await self.get_job(job_id)

        job.status = status.value

        if started_at:
            job.started_at = started_at
        if completed_at:
            job.completed_at = completed_at
        if progress is not None:
            job.progress = progress
        if message:
            job.message = message
        if error_message:
            job.error_message = error_message
        if phase is not None:
            job.phase = phase
        if phase_label is not None:
            job.phase_label = phase_label
        if phase_progress is not None:
            job.phase_progress = float(max(0.0, min(1.0, phase_progress)))

        await self._session.commit()

        self._logger.debug(
            "job_status_updated",
            job_id=job_id,
            status=status.value,
            progress=progress,
        )

    async def update_job_progress(
        self,
        job_id: str,
        progress: float,
        message: str,
        phase: Optional[str] = None,
        phase_label: Optional[str] = None,
        phase_progress: Optional[float] = None,
    ) -> None:

        job = await self.get_job(job_id)

        job.progress = progress
        job.message = message
        if phase is not None:
            job.phase = phase
        if phase_label is not None:
            job.phase_label = phase_label
        if phase_progress is not None:
            job.phase_progress = float(max(0.0, min(1.0, phase_progress)))

        await self._session.commit()

    async def save_results(
        self,
        job_id: str,
        results: Dict[str, Any],
        accuracy_metrics: Optional[Dict[str, float]],
        execution_time_seconds: int,
    ) -> None:

        job = await self.get_job(job_id)

        job.results = self._sanitize_json(results)
        job.accuracy_metrics = self._sanitize_json(accuracy_metrics)
        job.execution_time_seconds = execution_time_seconds

        await self._session.commit()

        self._logger.info(
            "results_saved",
            job_id=job_id,
            execution_time_seconds=execution_time_seconds,
        )

    async def list_jobs(
        self,
        status: Optional[str] = None,
        device_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        accessible_device_ids: Optional[list[str]] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[AnalyticsJob]:
        limit = max(1, int(limit))
        offset = max(0, int(offset))
        query = self._list_jobs_base_query(
            status=status,
            device_id=device_id,
            tenant_id=tenant_id,
        )

        if accessible_device_ids is None:
            result = await self._session.execute(query.offset(offset).limit(limit))
            return list(result.scalars().all())

        visible_jobs: list[AnalyticsJob] = []
        scanned_matches = 0
        db_offset = 0
        batch_size = max(limit + offset, 100)

        while len(visible_jobs) < limit:
            result = await self._session.execute(query.offset(db_offset).limit(batch_size))
            jobs = list(result.scalars().all())
            if not jobs:
                break

            for job in jobs:
                if not self._job_is_visible(
                    job,
                    tenant_id=tenant_id,
                    accessible_device_ids=accessible_device_ids,
                ):
                    continue

                if scanned_matches < offset:
                    scanned_matches += 1
                    continue

                visible_jobs.append(job)
                if len(visible_jobs) >= limit:
                    break

            db_offset += len(jobs)

        return visible_jobs

    async def update_job_queue_metadata(
        self,
        job_id: str,
        attempt: Optional[int] = None,
        queue_position: Optional[int] = None,
        queue_enqueued_at: Optional[datetime] | object = UNSET,
        queue_started_at: Optional[datetime] | object = UNSET,
        worker_lease_expires_at: Optional[datetime] | object = UNSET,
        last_heartbeat_at: Optional[datetime] | object = UNSET,
        error_code: Optional[str] | object = UNSET,
    ) -> None:
        job = await self.get_job(job_id)

        if attempt is not None:
            job.attempt = int(attempt)
        if queue_position is not None:
            job.queue_position = int(queue_position)
        if queue_enqueued_at is not UNSET:
            job.queue_enqueued_at = queue_enqueued_at
        if queue_started_at is not UNSET:
            job.queue_started_at = queue_started_at
        if worker_lease_expires_at is not UNSET:
            job.worker_lease_expires_at = worker_lease_expires_at
        if last_heartbeat_at is not UNSET:
            job.last_heartbeat_at = last_heartbeat_at
        if error_code is not UNSET:
            job.error_code = error_code

        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()

    async def count_jobs(
        self,
        statuses: Optional[list[str]] = None,
        tenant_id: Optional[str] = None,
        attempts_gte: Optional[int] = None,
    ) -> int:
        query = select(func.count()).select_from(AnalyticsJob)

        if statuses:
            query = query.where(AnalyticsJob.status.in_(statuses))
        if tenant_id:
            query = query.where(
                func.json_unquote(
                    func.json_extract(AnalyticsJob.parameters, "$.tenant_id")
                )
                == tenant_id
            )
        if attempts_gte is not None:
            query = query.where(AnalyticsJob.attempt >= int(attempts_gte))

        result = await self._session.execute(query)
        return int(result.scalar() or 0)

    async def list_tenant_job_counts(
        self,
        statuses: Optional[list[str]] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        tenant_expr = func.json_unquote(func.json_extract(AnalyticsJob.parameters, "$.tenant_id"))
        query = (
            select(
                tenant_expr.label("tenant_id"),
                func.count().label("job_count"),
            )
            .select_from(AnalyticsJob)
            .where(tenant_expr.is_not(None))
            .group_by(tenant_expr)
            .order_by(func.count().desc())
            .limit(max(1, int(limit)))
        )

        if statuses:
            query = query.where(AnalyticsJob.status.in_(statuses))

        result = await self._session.execute(query)
        rows = result.all()
        return [
            {
                "tenant_id": str(row.tenant_id),
                "job_count": int(row.job_count or 0),
            }
            for row in rows
            if row.tenant_id
        ]

    async def list_jobs_for_parent(
        self,
        parent_job_id: str,
    ) -> List[AnalyticsJob]:
        query = (
            select(AnalyticsJob)
            .where(
                func.json_unquote(
                    func.json_extract(AnalyticsJob.parameters, "$.parent_job_id")
                )
                == parent_job_id
            )
            .order_by(AnalyticsJob.created_at.asc())
        )
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def get_model_artifact(
        self,
        device_id: str,
        analysis_type: str,
        model_key: str,
    ) -> Optional[Dict[str, Any]]:
        result = await self._session.execute(
            select(ModelArtifact)
            .where(ModelArtifact.device_id == device_id)
            .where(ModelArtifact.analysis_type == analysis_type)
            .where(ModelArtifact.model_key == model_key)
            .order_by(ModelArtifact.updated_at.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if not row:
            return None
        return {
            "feature_schema_hash": row.feature_schema_hash,
            "artifact_payload": row.artifact_payload,
            "model_version": row.model_version,
            "metrics": row.metrics or {},
            "updated_at": row.updated_at,
            "expires_at": row.expires_at,
        }

    async def upsert_model_artifact(
        self,
        device_id: str,
        analysis_type: str,
        model_key: str,
        feature_schema_hash: str,
        artifact_payload: bytes,
        model_version: str = "v1",
        metrics: Optional[Dict[str, Any]] = None,
        expires_at: Optional[datetime] = None,
    ) -> None:
        if not artifact_payload:
            return

        existing = await self._session.execute(
            select(ModelArtifact)
            .where(ModelArtifact.device_id == device_id)
            .where(ModelArtifact.analysis_type == analysis_type)
            .where(ModelArtifact.model_key == model_key)
            .where(ModelArtifact.feature_schema_hash == feature_schema_hash)
            .limit(1)
        )
        artifact = existing.scalar_one_or_none()
        if artifact is None:
            artifact = ModelArtifact(
                device_id=device_id,
                analysis_type=analysis_type,
                model_key=model_key,
                feature_schema_hash=feature_schema_hash,
                model_version=model_version,
                artifact_payload=artifact_payload,
                metrics=self._sanitize_json(metrics),
                expires_at=expires_at,
            )
            self._session.add(artifact)
        else:
            artifact.model_version = model_version
            artifact.artifact_payload = artifact_payload
            artifact.metrics = self._sanitize_json(metrics)
            artifact.expires_at = expires_at

        await self._session.commit()
