"""Analytics API endpoints."""

import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select

from src.api.dependencies import get_job_queue, get_result_repository
from src.config.settings import get_settings
from src.infrastructure.database import async_session_maker
from src.infrastructure.mysql_repository import MySQLResultRepository
from src.models.database import WorkerHeartbeat, FailureEventLabel, AccuracyEvaluation
from src.models.schemas import (
    AnalyticsJobResponse,
    AnalyticsRequest,
    AnalyticsResultsResponse,
    AnalyticsType,
    FleetAnalyticsRequest,
    JobStatus,
    JobStatusResponse,
    SupportedModelsResponse,
)
from src.services.result_repository import ResultRepository
from src.utils.exceptions import JobNotFoundError
from src.workers.job_queue import QueueBackend
from services.shared.job_context import BoundJobPayload

from src.services.analytics.accuracy_evaluator import AccuracyEvaluator
from src.services.device_scope import AnalyticsDeviceScopeService
from src.services.job_status_estimator import JobStatusEstimator
from src.services.scaling_policy import AnalyticsScalingPolicy
from services.shared.tenant_context import resolve_request_tenant_id

logger = structlog.get_logger()

router = APIRouter()


async def _build_status_response(job_id: str, job) -> JobStatusResponse:
    async with async_session_maker() as session:
        estimate = await JobStatusEstimator(session).estimate(job)

    return JobStatusResponse(
        job_id=job_id,
        status=JobStatus(job.status),
        progress=job.progress,
        message=job.message,
        error_message=job.error_message,
        error_code=job.error_code,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        queue_position=estimate.queue_position if estimate.queue_position is not None else job.queue_position,
        attempt=job.attempt,
        worker_lease_expires_at=job.worker_lease_expires_at,
        estimated_wait_seconds=estimate.estimated_wait_seconds,
        estimated_completion_seconds=estimate.estimated_completion_seconds,
        estimate_quality=estimate.estimate_quality,
        phase=getattr(job, "phase", None),
        phase_label=getattr(job, "phase_label", None),
        phase_progress=getattr(job, "phase_progress", None),
    )


def get_tenant_id(request: Request) -> str | None:
    return resolve_request_tenant_id(request)


def _request_context(request: Request):
    return getattr(request.state, "tenant_context", None)


async def _resolve_accessible_job_device_ids(request: Request) -> list[str] | None:
    ctx = _request_context(request)
    if ctx is None or ctx.role not in {"plant_manager", "operator", "viewer"}:
        return None
    scope_service = AnalyticsDeviceScopeService(ctx)
    return await scope_service.resolve_accessible_device_ids()


def _build_job_payload(
    *,
    job_type: str,
    tenant_id: str | None,
    device_id: str | None,
    initiated_by_user_id: str,
    initiated_by_role: str,
    payload: dict,
) -> str:
    bound = BoundJobPayload(
        job_type=job_type,
        tenant_id=tenant_id,
        device_id=device_id,
        initiated_by_user_id=initiated_by_user_id,
        initiated_by_role=initiated_by_role,
        payload=payload,
    )
    bound.validate()
    return json.dumps(bound.__dict__, separators=(",", ":"), sort_keys=True, default=str)


async def check_worker_alive() -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=120)
    async with async_session_maker() as session:
        result = await session.execute(
            select(func.count())
            .select_from(WorkerHeartbeat)
            .where(WorkerHeartbeat.last_heartbeat_at > cutoff)
        )
        count = result.scalar() or 0
    return count > 0


def _record_admission_rejection(app_request: Request, category: str) -> None:
    counters = getattr(app_request.app.state, "analytics_rejections", None)
    if isinstance(counters, dict):
        counters[category] = int(counters.get(category, 0) or 0) + 1


async def _enforce_admission_policy(
    *,
    app_request: Request,
    result_repository: ResultRepository,
    tenant_id: str | None,
    requested_jobs: int = 1,
) -> int:
    settings = get_settings()
    decision = await AnalyticsScalingPolicy(settings, result_repository).evaluate_submission(
        tenant_id=tenant_id,
        requested_jobs=requested_jobs,
    )
    if decision.allowed:
        return decision.queue_position

    category = "tenant_cap" if decision.status_code == status.HTTP_429_TOO_MANY_REQUESTS else "overloaded"
    _record_admission_rejection(app_request, category)
    raise HTTPException(
        status_code=decision.status_code,
        detail={
            "error": decision.error_code,
            "message": decision.message,
            **(decision.details or {}),
        },
    )


@router.post(
    "/run",
    response_model=AnalyticsJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_analytics(
    request: AnalyticsRequest,
    app_request: Request,
    job_queue: QueueBackend = Depends(get_job_queue),
    result_repository: ResultRepository = Depends(get_result_repository),
) -> AnalyticsJobResponse:
    """
    Submit a new analytics job.

    The job will be queued and processed asynchronously.
    Use the returned job_id to check status and retrieve results.
    """
    if not await check_worker_alive():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "WORKER_UNAVAILABLE",
                "message": "Analytics worker is starting up or unavailable. Please wait 30 seconds and try again.",
            },
        )

    tenant_id = get_tenant_id(app_request)
    ctx = _request_context(app_request)
    if ctx is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "MISSING_AUTH_CONTEXT", "message": "Authentication context missing"},
        )
    normalized_device_ids = await AnalyticsDeviceScopeService(ctx).normalize_requested_device_ids([request.device_id])
    request.device_id = normalized_device_ids[0]
    queue_position = await _enforce_admission_policy(
        app_request=app_request,
        result_repository=result_repository,
        tenant_id=tenant_id,
        requested_jobs=1,
    )
    job_id = str(uuid4())

    logger.info(
        "analytics_job_submitted",
        job_id=job_id,
        analysis_type=request.analysis_type.value,
        model_name=request.model_name,
        device_id=request.device_id,
    )

    start_time = request.start_time or datetime.now(timezone.utc)
    end_time = request.end_time or start_time
    parameters = dict(request.parameters or {})
    if tenant_id is not None:
        parameters["tenant_id"] = tenant_id
    await result_repository.create_job(
        job_id=job_id,
        device_id=request.device_id,
        analysis_type=request.analysis_type.value,
        model_name=request.model_name,
        date_range_start=start_time,
        date_range_end=end_time,
        parameters=parameters,
    )
    await result_repository.update_job_queue_metadata(
        job_id=job_id,
        attempt=1,
        queue_enqueued_at=datetime.now(timezone.utc),
        queue_position=max(0, int(queue_position)),
    )

    raw_payload = _build_job_payload(
        job_type="analytics",
        tenant_id=tenant_id,
        device_id=request.device_id,
        initiated_by_user_id=ctx.user_id,
        initiated_by_role=ctx.role,
        payload=request.model_dump(mode="json"),
    )
    await job_queue.submit_job(job_id=job_id, raw_payload=raw_payload, attempt=1)
    if not hasattr(app_request.app.state, "pending_jobs"):
        app_request.app.state.pending_jobs = {}
    app_request.app.state.pending_jobs[job_id] = {
        "created_at": datetime.now(timezone.utc),
        "message": "Job queued successfully",
    }

    return AnalyticsJobResponse(
        job_id=job_id,
        status=JobStatus.PENDING,
        message="Job queued successfully",
    )


def _default_model_for(analysis_type: str) -> str:
    if analysis_type == AnalyticsType.ANOMALY.value:
        return "anomaly_ensemble"
    return "failure_ensemble"


@router.post(
    "/run-fleet",
    response_model=AnalyticsJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_fleet_analytics(
    request: FleetAnalyticsRequest,
    app_request: Request,
    job_queue: QueueBackend = Depends(get_job_queue),
    result_repo: ResultRepository = Depends(get_result_repository),
) -> AnalyticsJobResponse:
    """
    Submit strict fleet analytics as a parent job.
    Parent status fails if any child device fails.
    """
    if not await check_worker_alive():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "WORKER_UNAVAILABLE",
                "message": "Analytics worker is starting up or unavailable. Please wait 30 seconds and try again.",
            },
        )

    tenant_id = get_tenant_id(app_request)
    ctx = _request_context(app_request)
    if ctx is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "MISSING_AUTH_CONTEXT", "message": "Authentication context missing"},
        )

    scope_service = AnalyticsDeviceScopeService(ctx)
    normalized_device_ids = await scope_service.normalize_requested_device_ids(list(request.device_ids or []))
    if not normalized_device_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "NO_ACCESSIBLE_DEVICES",
                "message": "No accessible devices are available for fleet analysis.",
            },
        )

    request.device_ids = normalized_device_ids
    await _enforce_admission_policy(
        app_request=app_request,
        result_repository=result_repo,
        tenant_id=tenant_id,
        requested_jobs=len(normalized_device_ids),
    )
    parent_job_id = str(uuid4())
    request.parameters = {**(request.parameters or {}), **({"tenant_id": tenant_id} if tenant_id else {})}

    await result_repo.create_job(
        job_id=parent_job_id,
        device_id="ALL",
        analysis_type=request.analysis_type,
        model_name=request.model_name or _default_model_for(request.analysis_type),
        date_range_start=request.start_time,
        date_range_end=request.end_time,
        parameters={
            "fleet_mode": "best_effort_exact",
            "device_ids": normalized_device_ids,
            **(request.parameters or {}),
        },
    )
    await result_repo.update_job_status(
        job_id=parent_job_id,
        status=JobStatus.PENDING,
        progress=0.0,
        message="Fleet job queued",
        phase="queued",
        phase_label="Queued",
        phase_progress=0.0,
    )
    await result_repo.update_job_queue_metadata(
        job_id=parent_job_id,
        attempt=1,
        queue_enqueued_at=datetime.now(timezone.utc),
    )
    raw_payload = _build_job_payload(
        job_type="fleet_parent_analytics",
        tenant_id=tenant_id,
        device_id="ALL",
        initiated_by_user_id=ctx.user_id,
        initiated_by_role=ctx.role,
        payload=request.model_dump(mode="json"),
    )
    await job_queue.submit_job(job_id=parent_job_id, raw_payload=raw_payload, attempt=1)

    return AnalyticsJobResponse(
        job_id=parent_job_id,
        status=JobStatus.PENDING,
        message="Fleet job queued",
    )


@router.get(
    "/status/{job_id}",
    response_model=JobStatusResponse,
)
async def get_job_status(
    job_id: str,
    app_request: Request,
    result_repo: ResultRepository = Depends(get_result_repository),
) -> JobStatusResponse:
    """Get the current status of an analytics job."""
    try:
        tenant_id = get_tenant_id(app_request)
        accessible_device_ids = await _resolve_accessible_job_device_ids(app_request)
        job = await result_repo.get_job_scoped(
            job_id,
            tenant_id=tenant_id,
            accessible_device_ids=accessible_device_ids,
        )
        return await _build_status_response(job_id, job)
    except JobNotFoundError:
        pending_jobs = getattr(app_request.app.state, "pending_jobs", {})
        pending = pending_jobs.get(job_id)
        if pending:
            return JobStatusResponse(
                job_id=job_id,
                status=JobStatus.PENDING,
                progress=0,
                message=pending.get("message") or "Job queued successfully",
                created_at=pending.get("created_at"),
                phase="queued",
                phase_label="Queued",
                phase_progress=0.0,
                estimate_quality="low",
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )


@router.get(
    "/results/{job_id}",
    response_model=AnalyticsResultsResponse,
)
async def get_analytics_results(
    job_id: str,
    request: Request,
    result_repo: ResultRepository = Depends(get_result_repository),
) -> AnalyticsResultsResponse:
    """
    Retrieve results of a completed analytics job.

    Returns model outputs, accuracy metrics, and execution details.
    """
    try:
        tenant_id = get_tenant_id(request)
        accessible_device_ids = await _resolve_accessible_job_device_ids(request)
        job = await result_repo.get_job_scoped(
            job_id,
            tenant_id=tenant_id,
            accessible_device_ids=accessible_device_ids,
        )

        if job.status != JobStatus.COMPLETED.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Job {job_id} is not completed (current status: {job.status})",
            )

        return AnalyticsResultsResponse(
            job_id=job_id,
            status=JobStatus(job.status),
            device_id=job.device_id,
            analysis_type=AnalyticsType(job.analysis_type),
            model_name=job.model_name,
            date_range_start=job.date_range_start,
            date_range_end=job.date_range_end,
            results=job.results,
            accuracy_metrics=job.accuracy_metrics,
            execution_time_seconds=job.execution_time_seconds,
            completed_at=job.completed_at,
        )
    except JobNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )


# ------------------------------------------------------------------
# ✅ PERMANENT FIX – advertise only runnable models
# ------------------------------------------------------------------
@router.get(
    "/models",
    response_model=SupportedModelsResponse,
)
async def get_supported_models() -> SupportedModelsResponse:
    """Get list of supported analytics models by type."""

    forecasting_models = ["prophet", "arima"]

    return SupportedModelsResponse(
        anomaly_detection=[
            "isolation_forest",
            "lstm_autoencoder",
            "cusum",
        ],
        failure_prediction=[
            "xgboost",
            "lstm_classifier",
            "degradation_tracker",
        ],
        forecasting=forecasting_models,
        ensembles=[
            {
                "id": "anomaly_ensemble",
                "display_name": "Anomaly Detection — 3 Model Ensemble",
                "models": [
                    {"name": "isolation_forest", "trains": True},
                    {
                        "name": "lstm_autoencoder",
                        "trains": True,
                        "min_data": "50 sequences (~80 min)",
                    },
                    {
                        "name": "cusum",
                        "trains": False,
                        "note": "Works from minute 1",
                    },
                ],
                "voting_rule": "Alert when 2 of 3 models flag",
            },
            {
                "id": "failure_ensemble",
                "display_name": "Failure Prediction — 3 Model Ensemble",
                "models": [
                    {"name": "xgboost", "trains": True},
                    {
                        "name": "lstm_classifier",
                        "trains": True,
                        "min_data": "50 sequences (~80 min)",
                    },
                    {
                        "name": "degradation_tracker",
                        "trains": False,
                        "note": "Physics-based — no training needed",
                    },
                ],
                "voting_rule": "CRITICAL=3/3, WARNING=2/3, WATCH=1/3",
            },
        ],
    )


@router.get(
    "/jobs",
    response_model=List[JobStatusResponse],
)
async def list_jobs(
    request: Request,
    status: Optional[JobStatus] = None,
    device_id: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    result_repo: ResultRepository = Depends(get_result_repository),
) -> List[JobStatusResponse]:
    """List analytics jobs with optional filtering."""
    tenant_id = get_tenant_id(request)
    accessible_device_ids = await _resolve_accessible_job_device_ids(request)
    jobs = await result_repo.list_jobs(
        status=status.value if status else None,
        device_id=device_id,
        tenant_id=tenant_id,
        accessible_device_ids=accessible_device_ids,
        limit=limit,
        offset=offset,
    )

    return [await _build_status_response(job.job_id, job) for job in jobs]


@router.get("/ops/queue")
async def get_queue_ops_snapshot(
    app_request: Request,
    result_repo: ResultRepository = Depends(get_result_repository),
) -> Dict[str, object]:
    """Operational queue snapshot for SRE dashboards."""
    settings = get_settings()
    pending_count = await result_repo.count_jobs(statuses=[JobStatus.PENDING.value])
    running_count = await result_repo.count_jobs(statuses=[JobStatus.RUNNING.value])
    failed_count = await result_repo.count_jobs(statuses=[JobStatus.FAILED.value])
    retry_count = await result_repo.count_jobs(attempts_gte=2)
    top_tenants = await result_repo.list_tenant_job_counts(
        statuses=[JobStatus.RUNNING.value],
        limit=settings.ops_top_tenants_limit,
    )
    active_workers = 0
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(10, settings.worker_heartbeat_ttl_seconds))
    async with async_session_maker() as session:
        rows = await session.execute(select(WorkerHeartbeat).where(WorkerHeartbeat.last_heartbeat_at >= cutoff))
        active_workers = len(list(rows.scalars().all()))
    job_queue = getattr(app_request.app.state, "job_queue", None)
    queue_metrics_fetcher = getattr(job_queue, "metrics", None)
    queue_metrics = await queue_metrics_fetcher() if callable(queue_metrics_fetcher) else {}
    rejection_counters = getattr(app_request.app.state, "analytics_rejections", {}) or {}

    return {
        "queue_depth": pending_count,
        "consumer_lag_estimate": pending_count,
        "failed_job_count": failed_count,
        "active_workers": active_workers,
        "running_jobs": running_count,
        "retry_count": retry_count,
        "dead_letter_jobs": int(queue_metrics.get("dead_letter_messages", 0)),
        "claimed_messages": int(queue_metrics.get("claimed_messages", 0)),
        "stream_depth": int(queue_metrics.get("queued_messages", 0)),
        "top_tenants_by_active_jobs": top_tenants,
        "rejected_submissions": {
            "tenant_cap": int(rejection_counters.get("tenant_cap", 0) or 0),
            "overloaded": int(rejection_counters.get("overloaded", 0) or 0),
        },
        "capacity_policy": {
            "max_concurrent_jobs_per_worker": settings.max_concurrent_jobs,
            "global_active_job_limit": settings.global_active_job_limit,
            "queue_backlog_reject_threshold": settings.queue_backlog_reject_threshold,
            "tenant_max_queued_jobs": settings.tenant_max_queued_jobs,
            "tenant_max_active_jobs": settings.tenant_max_active_jobs,
            "queue_max_attempts": settings.queue_max_attempts,
            "stale_scan_interval_seconds": settings.stale_scan_interval_seconds,
        },
        "queue_backend": getattr(app_request.app.state, "queue_backend", "unknown"),
    }


@router.post("/labels/failure-events")
async def ingest_failure_event_label(payload: Dict[str, object]) -> Dict[str, object]:
    """Add a maintenance/failure ground-truth label event."""
    device_id = str(payload.get("device_id") or "").strip()
    event_time_raw = payload.get("event_time")
    if not device_id or not event_time_raw:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="device_id and event_time are required",
        )
    try:
        event_time = datetime.fromisoformat(str(event_time_raw).replace("Z", "+00:00"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid event_time: {exc}",
        )

    row = FailureEventLabel(
        device_id=device_id,
        event_time=event_time,
        event_type=str(payload.get("event_type") or "failure"),
        severity=str(payload.get("severity") or "") or None,
        source=str(payload.get("source") or "") or "manual",
        metadata_json=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
    )
    async with async_session_maker() as session:
        session.add(row)
        await session.commit()

    return {"status": "accepted", "id": row.id}


@router.post("/accuracy/evaluate")
async def evaluate_accuracy(
    device_id: Optional[str] = Query(default=None),
    lookback_days: int = Query(default=90, ge=1, le=3650),
    lead_window_hours: int = Query(default=24, ge=1, le=720),
) -> Dict[str, object]:
    """Run backtest evaluation against labeled events and persist summary."""
    async with async_session_maker() as session:
        result = await AccuracyEvaluator.evaluate_failure_predictions(
            session=session,
            device_id=device_id,
            lookback_days=lookback_days,
            lead_window_hours=lead_window_hours,
        )
    return {
        "analysis_type": "prediction",
        "scope_device_id": device_id,
        **result.as_dict(),
    }


@router.get("/accuracy/latest")
async def get_latest_accuracy(device_id: Optional[str] = Query(default=None)) -> Dict[str, object]:
    """Fetch latest persisted accuracy evaluation record."""
    async with async_session_maker() as session:
        q = (
            select(AccuracyEvaluation)
            .where(AccuracyEvaluation.analysis_type == "prediction")
            .order_by(AccuracyEvaluation.created_at.desc())
            .limit(1)
        )
        if device_id:
            q = q.where(AccuracyEvaluation.scope_device_id == device_id)
        row = (await session.execute(q)).scalar_one_or_none()

    if not row:
        return {"analysis_type": "prediction", "scope_device_id": device_id, "status": "no_evaluation"}

    return {
        "analysis_type": row.analysis_type,
        "scope_device_id": row.scope_device_id,
        "sample_size": row.sample_size,
        "labeled_events": row.labeled_events,
        "precision": row.precision,
        "recall": row.recall,
        "f1_score": row.f1_score,
        "false_alert_rate": row.false_alert_rate,
        "avg_lead_hours": row.avg_lead_hours,
        "is_certified": bool(row.is_certified),
        "notes": row.notes,
        "created_at": row.created_at,
    }


# ------------------------------------------------------------------
# ✅ STEP-1 – Dataset listing endpoint
# ------------------------------------------------------------------

@router.get("/datasets")
async def list_datasets(
    device_id: str = Query(..., description="Device ID"),
):
    """
    List available exported datasets for a device.

    This reads directly from S3/MinIO and returns available dataset objects.
    """

    s3_client = S3Client()
    dataset_service = DatasetService(s3_client)

    datasets = await dataset_service.list_available_datasets(
        device_id=device_id
    )

    return {
        "device_id": device_id,
        "datasets": datasets,
    }


@router.get("/retrain-status")
async def get_retrain_status(request: Request) -> dict:
    """Returns the last auto-retrain status per device."""
    retrainer = getattr(request.app.state, "retrainer", None)
    if not retrainer:
        return {}
    return retrainer.get_status()


@router.get("/formatted-results/{job_id}")
async def get_formatted_results(
    job_id: str,
    request: Request,
    result_repo: ResultRepository = Depends(get_result_repository),
) -> dict:
    """
    Returns dashboard-ready structured results for a completed job.
    """
    try:
        tenant_id = get_tenant_id(request)
        getter = getattr(result_repo, "get_job_scoped", result_repo.get_job)
        job = await getter(job_id, tenant_id)
        if job.status != JobStatus.COMPLETED.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Job {job_id} is not completed (status: {job.status})",
            )
        formatted = (job.results or {}).get("formatted")
        if not formatted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Formatted results not available for this job",
            )
        return formatted
    except JobNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )
