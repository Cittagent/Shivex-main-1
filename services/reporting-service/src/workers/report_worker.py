from __future__ import annotations

import asyncio
import logging
import socket
from datetime import timedelta

from src.config import settings
from src.database import AsyncSessionLocal
from src.queue import ReportJob, ReportQueue, get_report_queue
from src.repositories.report_repository import ReportRepository
from src.services.report_executor import execute_report


logger = logging.getLogger(__name__)


class ReportWorker:
    def __init__(self, queue: ReportQueue | None = None, concurrency: int | None = None) -> None:
        self._queue = queue or get_report_queue()
        self._concurrency = max(1, concurrency or settings.REPORT_WORKER_CONCURRENCY)
        self._worker_id = f"{settings.REPORT_QUEUE_CONSUMER_NAME}-{socket.gethostname()}"
        self._tasks: list[asyncio.Task] = []
        self._stopping = False

    async def start(self) -> None:
        logger.info("report_worker_started", extra={"concurrency": self._concurrency, "worker_id": self._worker_id})
        self._tasks = [asyncio.create_task(self._worker_loop(slot)) for slot in range(self._concurrency)]
        await asyncio.gather(*self._tasks)

    async def stop(self) -> None:
        self._stopping = True
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

    async def _worker_loop(self, slot: int) -> None:
        while not self._stopping:
            job = await self._queue.get_job()
            if job is None:
                continue
            try:
                await self._process_job(job, slot)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("report_worker_loop_error", extra={"report_id": job.report_id, "slot": slot})

    async def _process_job(self, job: ReportJob, slot: int) -> None:
        async with AsyncSessionLocal() as db:
            repo = ReportRepository(db)
            claimed = await repo.claim_report_for_processing(
                job.report_id,
                worker_id=f"{self._worker_id}-{slot}",
                tenant_id=job.tenant_id,
                stale_after=timedelta(seconds=max(settings.REPORT_JOB_TIMEOUT_SECONDS, 1)),
            )
            if not claimed:
                await self._queue.ack(job)
                return

            report = await repo.load_report_for_worker(job.report_id, tenant_id=job.tenant_id)
            if report is None:
                await self._queue.ack(job)
                return
            params = report.params or {}

        try:
            await asyncio.wait_for(
                execute_report(job.report_id, job.report_type, params),
                timeout=max(1, settings.REPORT_JOB_TIMEOUT_SECONDS),
            )
        except asyncio.TimeoutError:
            await self._retry_or_fail(
                job,
                error_code="JOB_TIMEOUT",
                error_message=f"Report exceeded timeout ({settings.REPORT_JOB_TIMEOUT_SECONDS}s)",
                increment_timeout=True,
            )
            return
        except Exception as exc:
            await self._retry_or_fail(
                job,
                error_code="WORKER_ERROR",
                error_message=str(exc),
            )
            return

        async with AsyncSessionLocal() as db:
            repo = ReportRepository(db)
            report = await repo.load_report_for_worker(job.report_id, tenant_id=job.tenant_id)
            if report is None:
                await self._queue.ack(job)
                return
            status = report.status.value if hasattr(report.status, "value") else str(report.status)
            if status == "completed":
                await repo.clear_processing_claim(job.report_id, tenant_id=job.tenant_id)
                await self._queue.ack(job)
                return
            if status == "failed":
                should_retry = (report.error_code or "") in {"INTERNAL_ERROR", "JOB_TIMEOUT", "WORKER_ERROR"}
                if should_retry:
                    await self._retry_or_fail(
                        job,
                        error_code=report.error_code or "INTERNAL_ERROR",
                        error_message=report.error_message or "Report execution failed",
                        increment_timeout=(report.error_code == "JOB_TIMEOUT"),
                    )
                    return
                await repo.clear_processing_claim(job.report_id, tenant_id=job.tenant_id)
                await self._queue.ack(job)
                return

            await self._retry_or_fail(
                job,
                error_code="WORKER_INCOMPLETE",
                error_message="Worker finished without terminal report state",
            )

    async def _retry_or_fail(
        self,
        job: ReportJob,
        *,
        error_code: str,
        error_message: str,
        increment_timeout: bool = False,
    ) -> None:
        async with AsyncSessionLocal() as db:
            repo = ReportRepository(db)
            report = await repo.load_report_for_worker(job.report_id, tenant_id=job.tenant_id)
            current_retry_count = int(getattr(report, "retry_count", 0) or 0) if report else 0
            next_attempt = current_retry_count + 1
            if next_attempt >= settings.REPORT_JOB_MAX_RETRIES:
                await repo.fail_report(
                    job.report_id,
                    tenant_id=job.tenant_id,
                    error_code=error_code,
                    error_message=error_message,
                    increment_retry=True,
                    increment_timeout=increment_timeout,
                )
                await self._queue.dead_letter(job, error_message)
                return

            await repo.requeue_report(
                job.report_id,
                tenant_id=job.tenant_id,
                error_code=error_code,
                error_message=error_message,
                increment_retry=True,
                increment_timeout=increment_timeout,
            )
        await self._queue.ack(job)
        await self._queue.enqueue(
            ReportJob(
                report_id=job.report_id,
                tenant_id=job.tenant_id,
                report_type=job.report_type,
                attempt=job.attempt + 1,
            )
        )
