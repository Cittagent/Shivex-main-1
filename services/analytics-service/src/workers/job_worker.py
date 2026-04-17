"""Job worker for processing analytics jobs."""

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, Any
import structlog
import socket
from uuid import uuid4

from src.config.settings import get_settings
from src.infrastructure.database import (
    async_session_maker,
    is_transient_disconnect,
    reset_db_connections,
)
from src.infrastructure.mysql_repository import MySQLResultRepository
from src.infrastructure.s3_client import S3Client
from src.models.database import WorkerHeartbeat
from src.services.dataset_service import DatasetService
from src.services.job_runner import JobRunner
from src.models.schemas import AnalyticsRequest, AnalyticsType, FleetAnalyticsRequest, JobStatus
from src.services.progress_tracking import FLEET_PARENT_PHASES
from src.services.readiness_orchestrator import ensure_device_ready
from src.services.result_formatter import ResultFormatter
from src.utils.exceptions import AnalyticsError, DatasetNotFoundError
from src.workers.job_queue import Job, QueueBackend
from services.shared.job_context import BoundJobPayload
from services.shared.tenant_context import TenantContext

logger = structlog.get_logger()


class JobWorker:
    """Worker that processes analytics jobs from the queue."""

    def __init__(
        self,
        job_queue: QueueBackend,
        max_concurrent: int = 3,
    ):
        settings = get_settings()
        self._queue = job_queue
        self._max_concurrent = max(1, max_concurrent)
        self._running = False
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._logger = logger.bind(worker="JobWorker")
        self._current_tasks: set = set()
        self._lease_seconds = settings.job_lease_seconds
        self._heartbeat_seconds = settings.job_heartbeat_seconds
        self._job_timeout_seconds = max(1, int(settings.job_timeout_seconds))
        self._max_attempts = settings.queue_max_attempts
        self._stale_scan_interval_seconds = max(5, int(settings.stale_scan_interval_seconds))
        self._worker_id = settings.redis_consumer_name or f"worker-{socket.gethostname()}"
        self._worker_heartbeat_task: Optional[asyncio.Task] = None
        self._system_ctx = TenantContext(
            tenant_id=None,
            user_id="analytics-worker",
            role="super_admin",
            plant_ids=[],
            is_super_admin=True,
        )

    @staticmethod
    def _is_fleet_parent_job(job_row: Any) -> bool:
        try:
            if str(getattr(job_row, "device_id", "")) == "ALL":
                return True
            params = getattr(job_row, "parameters", None) or {}
            return bool(params.get("fleet_mode"))
        except Exception:
            return False

    @staticmethod
    def _is_fleet_parent_request(request: AnalyticsRequest) -> bool:
        try:
            if str(getattr(request, "device_id", "")) == "ALL":
                return True
            params = getattr(request, "parameters", None) or {}
            return bool(params.get("fleet_mode"))
        except Exception:
            return False

    @staticmethod
    def _default_model_for(analysis_type: str) -> str:
        if analysis_type == AnalyticsType.ANOMALY.value:
            return "anomaly_ensemble"
        return "failure_ensemble"

    @staticmethod
    def _phase_progress_to_absolute(phase: str, phase_progress: float) -> float:
        phase_window = FLEET_PARENT_PHASES.get(phase)
        if phase_window is None:
            return 0.0
        bounded = max(0.0, min(1.0, phase_progress))
        return phase_window.start + (phase_window.end - phase_window.start) * bounded

    async def start(self) -> None:
        """Start the job worker."""
        self._running = True
        self._semaphore = asyncio.Semaphore(self._max_concurrent)

        self._logger.info(
            "worker_started",
            max_concurrent=self._max_concurrent,
        )
        self._worker_heartbeat_task = asyncio.create_task(self._worker_heartbeat_loop())
        await self._recover_stale_running_jobs()
        next_stale_scan = datetime.now(timezone.utc) + timedelta(
            seconds=self._stale_scan_interval_seconds
        )

        while self._running:
            try:
                job = await self._queue.get_job()
                if job is None:
                    now = datetime.now(timezone.utc)
                    if now >= next_stale_scan:
                        await self._recover_stale_running_jobs()
                        next_stale_scan = now + timedelta(
                            seconds=self._stale_scan_interval_seconds
                        )
                    await asyncio.sleep(0.1)
                    continue

                task = asyncio.create_task(
                    self._process_job_with_semaphore(job)
                )
                self._current_tasks.add(task)
                task.add_done_callback(self._current_tasks.discard)

            except asyncio.CancelledError:
                self._logger.info("worker_cancelled")
                break
            except Exception as e:
                if is_transient_disconnect(e):
                    await reset_db_connections()
                    self._logger.info("worker_waiting_for_db_reconnect", error=str(e))
                else:
                    self._logger.error("worker_error", error=str(e))
                await asyncio.sleep(1)

    async def _recover_stale_running_jobs(self) -> None:
        """Requeue jobs left in running state when worker lease is stale/missing."""
        now = datetime.now(timezone.utc)
        async with async_session_maker() as session:
            repo = MySQLResultRepository(session, self._system_ctx)
            running_jobs = await repo.list_jobs(
                status=JobStatus.RUNNING.value, limit=5000, offset=0
            )

            for job in running_jobs:
                lease = getattr(job, "worker_lease_expires_at", None)
                if lease is not None and lease.tzinfo is None:
                    lease = lease.replace(tzinfo=timezone.utc)
                is_stale = lease is None or lease <= now
                if not is_stale:
                    continue

                next_attempt = int(getattr(job, "attempt", 0) or 0) + 1
                if next_attempt > self._max_attempts:
                    await repo.update_job_status(
                        job_id=job.job_id,
                        status=JobStatus.FAILED,
                        completed_at=now,
                        message="Job failed after stale worker recovery attempts exhausted",
                        error_message="STALE_WORKER_LEASE",
                        phase="failed",
                        phase_label="Failed",
                        phase_progress=1.0,
                    )
                    await repo.update_job_queue_metadata(
                        job_id=job.job_id,
                        error_code="STALE_WORKER_LEASE",
                        worker_lease_expires_at=None,
                    )
                    self._logger.error(
                        "stale_running_job_failed",
                        job_id=job.job_id,
                        attempt=next_attempt,
                    )
                    continue

                raw_payload = self._build_requeue_payload(job)
                tenant_key = "tenant_id"
                tenant_id_value = (job.parameters or {}).get(tenant_key)
                await self._queue.submit_job(
                    job_id=job.job_id,
                    raw_payload=raw_payload,
                    attempt=next_attempt,
                )
                await repo.update_job_status(
                    job_id=job.job_id,
                    status=JobStatus.PENDING,
                    progress=0.0,
                    message=f"Requeued after stale worker lease (attempt {next_attempt}/{self._max_attempts})",
                    error_message=None,
                    phase="queued",
                    phase_label="Queued",
                    phase_progress=0.0,
                )
                await repo.update_job_queue_metadata(
                    job_id=job.job_id,
                    attempt=next_attempt,
                    queue_enqueued_at=now,
                    worker_lease_expires_at=None,
                    error_code="STALE_WORKER_LEASE",
                )
                self._logger.warning(
                    "stale_running_job_requeued",
                    job_id=job.job_id,
                    attempt=next_attempt,
                )

    def _build_requeue_payload(self, job_row: Any) -> str:
        params = getattr(job_row, "parameters", None) or {}
        tenant_id_value = params.get("tenant_id")
        if self._is_fleet_parent_job(job_row):
            payload = FleetAnalyticsRequest(
                device_ids=[str(device_id) for device_id in params.get("device_ids", [])],
                start_time=job_row.date_range_start,
                end_time=job_row.date_range_end,
                analysis_type=str(job_row.analysis_type),
                model_name=job_row.model_name,
                parameters=params,
            ).model_dump(mode="json")
            job_type = "fleet_parent_analytics"
            device_id = "ALL"
        else:
            payload = AnalyticsRequest(
                device_id=job_row.device_id,
                analysis_type=job_row.analysis_type,
                model_name=job_row.model_name,
                start_time=job_row.date_range_start,
                end_time=job_row.date_range_end,
                parameters=params,
            ).model_dump(mode="json")
            job_type = "analytics"
            device_id = job_row.device_id

        return json.dumps(
            BoundJobPayload(
                job_type=job_type,
                tenant_id=tenant_id_value,
                device_id=device_id,
                initiated_by_user_id="analytics-worker",
                initiated_by_role="super_admin",
                payload=payload,
            ).__dict__,
            separators=(",", ":"),
            sort_keys=True,
            default=str,
        )

    async def _process_job_with_semaphore(self, job: Job) -> None:
        if self._semaphore:
            async with self._semaphore:
                await self._process_job(job)

    # ---------------------------------------------------------
    # NEW: extract dates from dataset key
    # ---------------------------------------------------------
    def _extract_dates_from_dataset_key(self, dataset_key: str):
        """
        Expected:
          datasets/D1/20260210_20260210.parquet
        """

        m = re.search(r"(\d{8})_(\d{8})", dataset_key)
        if not m:
            raise AnalyticsError(
                f"Invalid dataset key format: {dataset_key}"
            )

        start = datetime.strptime(m.group(1), "%Y%m%d")
        end = datetime.strptime(m.group(2), "%Y%m%d")

        return start, end

    async def _process_job(self, job: Job) -> None:
        job_id = job.job_id
        try:
            raw_payload = json.loads(job.raw_payload)
            bound_payload = BoundJobPayload(**raw_payload)
            bound_payload.validate()
            ctx = bound_payload.to_tenant_context()
            request_type = bound_payload.job_type
            if request_type == "fleet_parent_analytics":
                request = FleetAnalyticsRequest.model_validate(bound_payload.payload)
                if ctx.tenant_id:
                    parameters = dict(request.parameters or {})
                    parameters.setdefault("tenant_id", ctx.tenant_id)
                    request = request.model_copy(update={"parameters": parameters})
            else:
                request = AnalyticsRequest.model_validate(bound_payload.payload)
                if ctx.tenant_id:
                    parameters = dict(request.parameters or {})
                    parameters.setdefault("tenant_id", ctx.tenant_id)
                    request = request.model_copy(update={"parameters": parameters})
        except Exception as exc:
            self._logger.error("job_payload_invalid", job_id=job_id, error=str(exc))
            await self._mark_job_failed(job_id, f"Invalid job payload: {exc}", error_code="INVALID_JOB_PAYLOAD")
            await self._queue.dead_letter(job, f"Invalid job payload: {exc}")
            if job.receipt:
                await self._queue.ack_job(job.receipt)
            return

        self._logger.info(
            "processing_job",
            job_id=job_id,
            analysis_type=getattr(request, "analysis_type", "unknown"),
            job_type=request_type,
        )

        if request_type == "fleet_parent_analytics":
            await self._process_fleet_parent_job(job, ctx, request)
            return

        async with async_session_maker() as session:
            try:
                result_repo = MySQLResultRepository(session, ctx)

                # ---------------------------------------------------------
                # PERMANENT FIX:
                # Fill date_range_* when dataset_key is used
                # ---------------------------------------------------------
                if request.dataset_key:
                    date_range_start, date_range_end = (
                        self._extract_dates_from_dataset_key(
                            request.dataset_key
                        )
                    )
                else:
                    date_range_start = request.start_time
                    date_range_end = request.end_time

                await result_repo.update_job_queue_metadata(
                    job_id=job_id,
                    attempt=job.attempt,
                    queue_started_at=datetime.now(timezone.utc),
                    worker_lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=self._lease_seconds),
                    last_heartbeat_at=datetime.now(timezone.utc),
                )

                s3_client = S3Client()
                dataset_service = DatasetService(s3_client)

                runner = JobRunner(dataset_service, result_repo)
                heartbeat = asyncio.create_task(self._heartbeat_loop(job_id))
                try:
                    await asyncio.wait_for(
                        runner.run_job(job_id, request),
                        timeout=self._job_timeout_seconds,
                    )
                finally:
                    heartbeat.cancel()
                    try:
                        await heartbeat
                    except asyncio.CancelledError:
                        pass
                    await result_repo.update_job_queue_metadata(
                        job_id=job_id,
                        worker_lease_expires_at=None,
                    )

                self._logger.info("job_completed", job_id=job_id)
                if job.receipt:
                    await self._queue.ack_job(job.receipt)

            except asyncio.TimeoutError:
                message = f"Job execution exceeded timeout of {self._job_timeout_seconds} seconds"
                self._logger.error(
                    "job_failed_timeout",
                    job_id=job_id,
                    tenant_id=ctx.tenant_id,
                    device_id=request.device_id,
                    timeout_seconds=self._job_timeout_seconds,
                )
                await self._retry_or_fail(job, "JOB_EXECUTION_TIMEOUT", message)

            except DatasetNotFoundError as e:
                self._logger.error(
                    "job_failed_dataset_not_found",
                    job_id=job_id,
                    tenant_id=ctx.tenant_id,
                    device_id=request.device_id,
                    error=str(e),
                )
                await self._retry_or_fail(job, "DATASET_NOT_FOUND", str(e))

            except AnalyticsError as e:
                self._logger.error(
                    "job_failed_analytics_error",
                    job_id=job_id,
                    tenant_id=ctx.tenant_id,
                    device_id=request.device_id,
                    error=str(e),
                )
                await self._retry_or_fail(job, "ANALYTICS_ERROR", str(e))

            except Exception as e:
                self._logger.error(
                    "job_failed_unexpected",
                    job_id=job_id,
                    tenant_id=ctx.tenant_id,
                    device_id=request.device_id,
                    error=str(e),
                    exc_info=True,
                )
                await self._retry_or_fail(job, "UNEXPECTED_ERROR", f"Unexpected error: {e}")

            finally:
                self._queue.task_done()

    async def _heartbeat_loop(self, job_id: str) -> None:
        while True:
            await asyncio.sleep(self._heartbeat_seconds)
            async with async_session_maker() as session:
                result_repo = MySQLResultRepository(session, self._system_ctx)
                now = datetime.now(timezone.utc)
                await result_repo.update_job_queue_metadata(
                    job_id=job_id,
                    last_heartbeat_at=now,
                    worker_lease_expires_at=now + timedelta(seconds=self._lease_seconds),
                )

    async def _process_fleet_parent_job(
        self,
        job: Job,
        ctx: TenantContext,
        request: FleetAnalyticsRequest,
    ) -> None:
        job_id = job.job_id
        try:
            async with async_session_maker() as session:
                result_repo = MySQLResultRepository(session, ctx)
                await result_repo.update_job_queue_metadata(
                    job_id=job_id,
                    attempt=job.attempt,
                    queue_started_at=datetime.now(timezone.utc),
                    worker_lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=self._lease_seconds),
                    last_heartbeat_at=datetime.now(timezone.utc),
                )
                await result_repo.update_job_status(
                    job_id=job_id,
                    status=JobStatus.RUNNING,
                    started_at=datetime.now(timezone.utc),
                    progress=self._phase_progress_to_absolute("fleet_readiness", 0.0),
                    message="Checking data readiness for fleet analytics",
                    error_message=None,
                    phase="fleet_readiness",
                    phase_label=FLEET_PARENT_PHASES["fleet_readiness"].label,
                    phase_progress=0.0,
                )

            heartbeat = asyncio.create_task(self._heartbeat_loop(job_id))
            try:
                await asyncio.wait_for(
                    self._run_fleet_parent(job_id, request, ctx),
                    timeout=self._job_timeout_seconds,
                )
            finally:
                heartbeat.cancel()
                try:
                    await heartbeat
                except asyncio.CancelledError:
                    pass
                async with async_session_maker() as session:
                    result_repo = MySQLResultRepository(session, self._system_ctx)
                    await result_repo.update_job_queue_metadata(
                        job_id=job_id,
                        worker_lease_expires_at=None,
                    )

            self._logger.info("fleet_parent_completed", job_id=job_id)
            if job.receipt:
                await self._queue.ack_job(job.receipt)
        except asyncio.TimeoutError:
            message = f"Fleet orchestration exceeded timeout of {self._job_timeout_seconds} seconds"
            self._logger.error("fleet_parent_timeout", job_id=job_id, timeout_seconds=self._job_timeout_seconds)
            await self._retry_or_fail(job, "JOB_EXECUTION_TIMEOUT", message)
        except AnalyticsError as exc:
            self._logger.error("fleet_parent_failed_analytics_error", job_id=job_id, error=str(exc))
            await self._retry_or_fail(job, "ANALYTICS_ERROR", str(exc))
        except Exception as exc:
            self._logger.error("fleet_parent_failed_unexpected", job_id=job_id, error=str(exc), exc_info=True)
            await self._retry_or_fail(job, "UNEXPECTED_ERROR", f"Unexpected error: {exc}")
        finally:
            self._queue.task_done()

    async def _run_fleet_parent(
        self,
        parent_job_id: str,
        request: FleetAnalyticsRequest,
        ctx: TenantContext,
    ) -> None:
        device_ids = [str(device_id) for device_id in request.device_ids]
        if not device_ids:
            await self._fail_parent_job(
                parent_job_id,
                "No devices available for fleet analysis",
                {"analysis_type": request.analysis_type, "devices_failed": []},
            )
            return

        async with async_session_maker() as session:
            repo = MySQLResultRepository(session, ctx)
            existing_children = await repo.list_jobs_for_parent(parent_job_id)
            parent_job = await repo.get_job(parent_job_id)
            existing_results = parent_job.results or {}
        child_jobs = {
            str(child.device_id): str(child.job_id)
            for child in existing_children
        }
        skipped_devices = list(existing_results.get("skipped_children") or [])

        if not child_jobs:
            await self._update_parent_progress(
                parent_job_id,
                phase="fleet_readiness",
                phase_progress=0.15,
                message=f"Checking data readiness for {len(device_ids)} devices",
            )
            ready_keys, skipped_devices = await self._resolve_fleet_ready_devices(request, ctx.tenant_id)
            await self._persist_fleet_state(parent_job_id, child_jobs, skipped_devices)
            if not ready_keys:
                await self._fail_parent_job(
                    parent_job_id,
                    "No devices have exact-range datasets ready for the selected window.",
                    {"analysis_type": request.analysis_type, "devices_failed": skipped_devices},
                )
                return

            await self._update_parent_progress(
                parent_job_id,
                phase="child_submission",
                phase_progress=0.2,
                message="Submitting device analytics jobs",
            )
            model_name = request.model_name or self._default_model_for(request.analysis_type)
            for device_id, dataset_key in ready_keys.items():
                child_id = str(uuid4())
                child_parameters = dict(request.parameters or {})
                child_parameters["parent_job_id"] = parent_job_id
                child_request = AnalyticsRequest(
                    device_id=device_id,
                    dataset_key=dataset_key,
                    analysis_type=AnalyticsType(request.analysis_type),
                    model_name=model_name,
                    parameters=child_parameters,
                )
                async with async_session_maker() as session:
                    repo = MySQLResultRepository(session, ctx)
                    await repo.create_job(
                        job_id=child_id,
                        device_id=device_id,
                        analysis_type=request.analysis_type,
                        model_name=model_name,
                        date_range_start=request.start_time,
                        date_range_end=request.end_time,
                        parameters=child_parameters,
                    )
                    await repo.update_job_queue_metadata(
                        job_id=child_id,
                        attempt=1,
                        queue_enqueued_at=datetime.now(timezone.utc),
                    )
                child_raw_payload = json.dumps(
                    BoundJobPayload(
                        job_type="fleet_child_analytics",
                        tenant_id=ctx.tenant_id,
                        device_id=device_id,
                        initiated_by_user_id=ctx.user_id,
                        initiated_by_role=ctx.role,
                        payload=child_request.model_dump(mode="json"),
                    ).__dict__,
                    separators=(",", ":"),
                    sort_keys=True,
                    default=str,
                )
                await self._queue.submit_job(job_id=child_id, raw_payload=child_raw_payload, attempt=1)
                child_jobs[device_id] = child_id
                await self._persist_fleet_state(parent_job_id, child_jobs, skipped_devices)
                await self._update_parent_progress(
                    parent_job_id,
                    phase="child_submission",
                    phase_progress=len(child_jobs) / max(1, len(ready_keys)),
                    message=f"Submitting device analytics jobs ({len(child_jobs)}/{len(ready_keys)})",
                )

        if not child_jobs:
            await self._fail_parent_job(
                parent_job_id,
                "No devices produced child analytics jobs.",
                {"analysis_type": request.analysis_type, "devices_failed": skipped_devices},
            )
            return

        await self._monitor_fleet_parent(
            parent_job_id=parent_job_id,
            analysis_type=request.analysis_type,
            total_selected=len(device_ids),
        )

    async def _resolve_fleet_ready_devices(
        self,
        request: FleetAnalyticsRequest,
        tenant_id: str | None,
    ) -> tuple[dict[str, str], list[dict[str, str]]]:
        settings = get_settings()
        s3_client = S3Client()
        dataset_service = DatasetService(s3_client)
        readiness_limit = max(1, int(settings.data_readiness_max_concurrency))
        readiness_semaphore = asyncio.Semaphore(readiness_limit)

        async def _bounded_ready_check(device_id: str):
            async with readiness_semaphore:
                return await ensure_device_ready(
                    s3_client=s3_client,
                    dataset_service=dataset_service,
                    device_id=device_id,
                    start_time=request.start_time,
                    end_time=request.end_time,
                    tenant_id=tenant_id,
                )

        checks = await asyncio.gather(*[_bounded_ready_check(str(device_id)) for device_id in request.device_ids])
        ready_keys: dict[str, str] = {}
        skipped_devices: list[dict[str, str]] = []
        for device_id, key, meta in checks:
            if key:
                ready_keys[str(device_id)] = str(key)
                continue
            reason = str((meta or {}).get("reason") or "dataset_not_ready")
            skipped_devices.append(
                {
                    "device_id": str(device_id),
                    "reason": reason,
                    "message": {
                        "dataset_not_ready": "Exact-range dataset is not ready yet",
                        "export_timeout": "Export timed out while preparing exact-range dataset",
                        "device_not_found": "Device not found in export pipeline",
                        "no_telemetry_in_range": "No telemetry found in selected date range",
                    }.get(reason, "Data readiness check did not pass"),
                }
            )
        return ready_keys, skipped_devices

    async def _persist_fleet_state(
        self,
        parent_job_id: str,
        child_jobs: dict[str, str],
        skipped_devices: list[dict[str, str]],
    ) -> None:
        async with async_session_maker() as session:
            repo = MySQLResultRepository(session, self._system_ctx)
            current = await repo.get_job(parent_job_id)
            existing_results = current.results or {}
            existing_results["children"] = child_jobs
            existing_results["skipped_children"] = skipped_devices
            await repo.save_results(
                job_id=parent_job_id,
                results=existing_results,
                accuracy_metrics={},
                execution_time_seconds=0,
            )

    async def _monitor_fleet_parent(
        self,
        *,
        parent_job_id: str,
        analysis_type: str,
        total_selected: int,
    ) -> None:
        formatter = ResultFormatter()
        while True:
            await asyncio.sleep(2)
            async with async_session_maker() as session:
                repo = MySQLResultRepository(session, self._system_ctx)
                parent_job = await repo.get_job(parent_job_id)
                state = parent_job.results or {}
                child_jobs = dict(state.get("children") or {})
                skipped_devices = list(state.get("skipped_children") or [])
                child_rows = await repo.list_jobs_for_parent(parent_job_id)

                completed: list[dict] = []
                failed: list[dict] = []
                running_count = 0
                for child in child_rows:
                    child_jobs[str(child.device_id)] = str(child.job_id)
                    if child.status == JobStatus.COMPLETED.value:
                        completed.append(
                            {
                                "device_id": child.device_id,
                                "job_id": child.job_id,
                                "results": child.results or {},
                            }
                        )
                    elif child.status == JobStatus.FAILED.value:
                        failed.append(
                            {
                                "device_id": child.device_id,
                                "job_id": child.job_id,
                                "message": child.error_message or child.message or "Job failed",
                            }
                        )
                    else:
                        running_count += 1

                total = len(child_jobs)
                done = len(completed)
                execution_phase_progress = done / max(1, total)
                await repo.update_job_progress(
                    parent_job_id,
                    progress=self._phase_progress_to_absolute("child_execution", execution_phase_progress),
                    message=f"Running analytics for fleet ({done}/{max(1, total)} completed)",
                    phase="child_execution",
                    phase_label=FLEET_PARENT_PHASES["child_execution"].label,
                    phase_progress=execution_phase_progress,
                )

                if running_count == 0 and (done + len(failed) == total):
                    await repo.update_job_progress(
                        parent_job_id,
                        progress=self._phase_progress_to_absolute("aggregation", 0.5),
                        message="Aggregating fleet parent results",
                        phase="aggregation",
                        phase_label=FLEET_PARENT_PHASES["aggregation"].label,
                        phase_progress=0.5,
                    )
                    device_formatted = []
                    for item in completed:
                        formatted = (item["results"] or {}).get("formatted")
                        if formatted:
                            device_formatted.append(formatted)
                    fleet_formatted = formatter.format_fleet_results(
                        job_id=parent_job_id,
                        analysis_type=analysis_type,
                        device_results=device_formatted,
                        child_job_map=child_jobs,
                    )
                    failed_devices = [
                        {
                            "device_id": str(item["device_id"]),
                            "reason": "child_job_failed",
                            "message": str(item["message"]),
                        }
                        for item in failed
                    ]
                    coverage_pct = round((len(completed) / max(1, total_selected)) * 100, 1)
                    fleet_formatted["execution_metadata"] = {
                        "fleet_policy": "best_effort_exact",
                        "children_count": total,
                        "devices_ready": [str(item["device_id"]) for item in completed],
                        "devices_failed": failed_devices,
                        "devices_skipped": skipped_devices,
                        "skipped_reasons": {
                            str(item.get("device_id")): str(item.get("reason"))
                            for item in skipped_devices
                        },
                        "coverage_pct": coverage_pct,
                        "selected_device_count": total_selected,
                    }
                    await repo.save_results(
                        job_id=parent_job_id,
                        results={
                            "children": child_jobs,
                            "failed_children": failed,
                            "skipped_children": skipped_devices,
                            "formatted": fleet_formatted,
                        },
                        accuracy_metrics={},
                        execution_time_seconds=0,
                    )
                    if completed:
                        message = f"Fleet analysis completed ({len(completed)}/{total_selected} devices analyzed)"
                        if skipped_devices or failed:
                            message += f"; skipped/failed: {len(skipped_devices) + len(failed)}"
                        final_status = JobStatus.COMPLETED
                        error_message = None
                    else:
                        message = "No devices produced successful analytics results"
                        final_status = JobStatus.FAILED
                        error_message = "All fleet child jobs were skipped or failed"
                    await repo.update_job_status(
                        parent_job_id,
                        status=final_status,
                        completed_at=datetime.now(timezone.utc),
                        progress=100.0,
                        message=message,
                        error_message=error_message,
                        phase="completed" if final_status == JobStatus.COMPLETED else "failed",
                        phase_label="Completed" if final_status == JobStatus.COMPLETED else "Failed",
                        phase_progress=1.0,
                    )
                    return

    async def _update_parent_progress(
        self,
        parent_job_id: str,
        *,
        phase: str,
        phase_progress: float,
        message: str,
    ) -> None:
        async with async_session_maker() as session:
            repo = MySQLResultRepository(session, self._system_ctx)
            await repo.update_job_progress(
                parent_job_id,
                progress=self._phase_progress_to_absolute(phase, phase_progress),
                message=message,
                phase=phase,
                phase_label=FLEET_PARENT_PHASES.get(phase).label if FLEET_PARENT_PHASES.get(phase) else phase.replace("_", " ").title(),
                phase_progress=max(0.0, min(1.0, phase_progress)),
            )

    async def _fail_parent_job(self, parent_job_id: str, message: str, details: dict[str, object]) -> None:
        async with async_session_maker() as session:
            repo = MySQLResultRepository(session, self._system_ctx)
            await repo.save_results(
                job_id=parent_job_id,
                results={
                    "formatted": {
                        "analysis_type": "fleet",
                        "job_id": parent_job_id,
                        "fleet_health_score": 0.0,
                        "worst_device_id": None,
                        "worst_device_health": 0.0,
                        "critical_devices": [],
                        "source_analysis_type": details.get("analysis_type", "prediction"),
                        "device_summaries": [],
                        "execution_metadata": {
                            "data_readiness": "not_ready",
                            "devices_failed": details.get("devices_failed", []),
                            "reason": message,
                        },
                    }
                },
                accuracy_metrics={},
                execution_time_seconds=0,
            )
            await repo.update_job_status(
                job_id=parent_job_id,
                status=JobStatus.FAILED,
                completed_at=datetime.now(timezone.utc),
                message=message,
                error_message=message,
                phase="failed",
                phase_label="Failed",
                phase_progress=1.0,
            )

    async def _retry_or_fail(self, job: Job, error_code: str, error_message: str) -> None:
        non_retryable = {
            "DATASET_NOT_READY_TIMEOUT",
            "DEVICE_NOT_FOUND",
            "NO_TELEMETRY_IN_RANGE",
        }
        msg_lower = (error_message or "").lower()
        if "dataset_not_ready_timeout" in msg_lower:
            error_code = "DATASET_NOT_READY_TIMEOUT"
        elif "job execution exceeded timeout" in msg_lower:
            error_code = "JOB_EXECUTION_TIMEOUT"
        elif "device_not_found" in msg_lower:
            error_code = "DEVICE_NOT_FOUND"
        elif "no_telemetry_in_range" in msg_lower:
            error_code = "NO_TELEMETRY_IN_RANGE"

        if error_code in non_retryable:
            await self._mark_job_failed(job.job_id, error_message, error_code=error_code)
            await self._queue.dead_letter(job, error_message)
            return

        if job.attempt < self._max_attempts:
            backoff = min(30, 2 ** (job.attempt - 1))
            await asyncio.sleep(backoff)
            if job.receipt:
                await self._queue.ack_job(job.receipt)
            await self._queue.submit_job(
                job.job_id,
                raw_payload=job.raw_payload,
                attempt=job.attempt + 1,
            )
            async with async_session_maker() as session:
                repo = MySQLResultRepository(session, self._system_ctx)
                await repo.update_job_status(
                    job_id=job.job_id,
                    status=JobStatus.PENDING,
                    progress=0.0,
                    message=f"Retrying job (attempt {job.attempt + 1}/{self._max_attempts})",
                    error_message=None,
                    phase="queued",
                    phase_label="Queued",
                    phase_progress=0.0,
                )
                await repo.update_job_queue_metadata(
                    job_id=job.job_id,
                    attempt=job.attempt + 1,
                    error_code=error_code,
                    queue_enqueued_at=datetime.now(timezone.utc),
                    worker_lease_expires_at=None,
                )
            return

        await self._mark_job_failed(job.job_id, error_message, error_code=error_code)
        await self._queue.dead_letter(job, error_message)

    async def _mark_job_failed(self, job_id: str, error_message: str, error_code: Optional[str] = None) -> None:
        try:
            async with async_session_maker() as session:
                result_repo = MySQLResultRepository(session, self._system_ctx)
                msg = "Job failed"
                lower = (error_message or "").lower()
                if "dataset_not_ready_timeout" in lower or "export_timeout" in lower:
                    msg = "Dataset preparation timed out for selected range. Retry shortly."
                elif "dataset not found" in lower or "no such key" in lower:
                    msg = "No exact-range dataset is available for selected date range."
                elif "device_not_found" in lower:
                    msg = "Selected device could not be found in export pipeline."
                elif "no_telemetry_in_range" in lower:
                    msg = "No telemetry found in selected time range."
                elif "no numeric columns" in lower or "insufficient" in lower:
                    msg = "Insufficient signal/data for reliable analytics. Please collect more telemetry."
                elif "job execution exceeded timeout" in lower:
                    msg = "Analytics job timed out before completion."

                await result_repo.update_job_status(
                    job_id=job_id,
                    status=JobStatus.FAILED,
                    completed_at=datetime.utcnow(),
                    message=msg,
                    error_message=error_message,
                    phase="failed",
                    phase_label="Failed",
                    phase_progress=1.0,
                )
                await result_repo.update_job_queue_metadata(
                    job_id=job_id,
                    error_code=error_code,
                    worker_lease_expires_at=None,
                )
        except Exception as e:
            self._logger.error(
                "failed_to_mark_job_failed",
                job_id=job_id,
                error=str(e),
            )

    async def stop(self) -> None:
        self._logger.info("stopping_worker")
        self._running = False
        if self._worker_heartbeat_task:
            self._worker_heartbeat_task.cancel()
            try:
                await self._worker_heartbeat_task
            except asyncio.CancelledError:
                pass

        if self._current_tasks:
            self._logger.info(
                "waiting_for_tasks",
                task_count=len(self._current_tasks),
            )
            await asyncio.gather(*self._current_tasks, return_exceptions=True)

        self._logger.info("worker_stopped")

    async def _worker_heartbeat_loop(self) -> None:
        while self._running:
            now = datetime.now(timezone.utc)
            try:
                await self._write_worker_heartbeat(now)
            except Exception as exc:
                if is_transient_disconnect(exc):
                    try:
                        await reset_db_connections()
                        await self._write_worker_heartbeat(now)
                        self._logger.info("worker_heartbeat_recovered_after_disconnect")
                    except Exception as retry_exc:
                        if is_transient_disconnect(retry_exc):
                            self._logger.info("worker_heartbeat_waiting_for_db_reconnect", error=str(retry_exc))
                        else:
                            self._logger.warning("worker_heartbeat_failed", error=str(retry_exc))
                else:
                    self._logger.warning("worker_heartbeat_failed", error=str(exc))
            await asyncio.sleep(max(5, self._heartbeat_seconds))

    async def _write_worker_heartbeat(self, now: datetime) -> None:
        async with async_session_maker() as session:
            row = await session.get(WorkerHeartbeat, self._worker_id)
            if row is None:
                row = WorkerHeartbeat(
                    worker_id=self._worker_id,
                    app_role="worker",
                    status="alive",
                    last_heartbeat_at=now,
                )
                session.add(row)
            else:
                row.status = "alive"
                row.last_heartbeat_at = now
            await session.commit()
