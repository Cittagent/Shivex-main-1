"""Analytics Service entry point."""

import os
import sys
import importlib.abc

APP_ROLE = os.environ.get("APP_ROLE", "").strip().lower()
VALID_ROLES = {"api", "worker"}

if APP_ROLE not in VALID_ROLES:
    raise RuntimeError(
        f"APP_ROLE must be one of {VALID_ROLES}, got '{APP_ROLE}'. "
        "Set APP_ROLE=api for the API server or APP_ROLE=worker for the ML worker."
    )

if APP_ROLE == "api":
    ML_LIBRARIES = ["tensorflow", "torch", "xgboost", "sklearn", "prophet", "shap"]
    for lib in ML_LIBRARIES:
        if lib in sys.modules:
            raise RuntimeError(
                f"ML library '{lib}' was imported in the API process (APP_ROLE=api). "
                "This blocks the event loop. Move ML imports to the worker process only."
            )

    class _APIModuleGuard(importlib.abc.MetaPathFinder):
        def __init__(self, blocked_modules: set[str]):
            self._blocked_modules = blocked_modules

        def find_spec(self, fullname: str, path, target=None):  # type: ignore[override]
            for blocked in self._blocked_modules:
                if fullname == blocked or fullname.startswith(f"{blocked}."):
                    raise AssertionError(
                        f"Module '{fullname}' may not be imported when APP_ROLE=api"
                    )
            return None

    if not any(getattr(finder, "__class__", None).__name__ == "_APIModuleGuard" for finder in sys.meta_path):
        sys.meta_path.insert(
            0,
            _APIModuleGuard(
                {
                    "src.workers.job_worker",
                    "tensorflow",
                    "torch",
                    "xgboost",
                    "sklearn",
                    "prophet",
                    "shap",
                }
            ),
        )

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text

from src.api.routes import analytics, health
from src.config.logging_config import configure_logging
from src.config.settings import Settings, get_settings
from src.infrastructure.database import async_session_maker
from src.workers.job_queue import InMemoryJobQueue, RedisJobQueue
from shared.auth_middleware import AuthMiddleware
from shared.feature_entitlements import require_feature
from services.shared.startup_contract import validate_startup_contract

logger = structlog.get_logger()


async def cleanup_stale_jobs(max_age_minutes: int | None = 30) -> int:
    cutoff = (
        datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
        if max_age_minutes is not None
        else None
    )
    where_clause = "WHERE status IN ('running', 'queued', 'pending')"
    params: dict[str, object] = {}
    if cutoff is not None:
        where_clause += " AND created_at < :cutoff"
        params["cutoff"] = cutoff

    async with async_session_maker() as session:
        result = await session.execute(
            text(
                f"""
                UPDATE analytics_jobs
                SET status = 'failed',
                    error_code = 'SERVICE_RESTART',
                    error_message = 'Job was interrupted by a service restart. Please resubmit.',
                    message = 'Job was interrupted by a service restart. Please resubmit.',
                    completed_at = UTC_TIMESTAMP(),
                    updated_at = UTC_TIMESTAMP()
                {where_clause}
                """
            ),
            params,
        )
        await session.commit()
        return int(result.rowcount or 0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle."""
    validate_startup_contract()
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info("analytics_service_starting", version="1.0.0")
    cleanup_window_minutes = 30
    cleaned_jobs = await cleanup_stale_jobs(cleanup_window_minutes)
    if cleaned_jobs:
        logger.warning(
            "analytics_stale_jobs_cleaned",
            count=cleaned_jobs,
            app_role=settings.app_role,
            cleanup_window_minutes=cleanup_window_minutes,
        )
    
    if settings.queue_backend == "redis":
        job_queue = RedisJobQueue(
            redis_url=settings.redis_url,
            stream_name=settings.redis_stream_name,
            dead_letter_stream=settings.redis_dead_letter_stream,
            consumer_group=settings.redis_consumer_group,
            consumer_name=settings.redis_consumer_name,
        )
    else:
        job_queue = InMemoryJobQueue()

    job_worker = None
    worker_task = None
    app.state.job_queue = job_queue
    app.state.fleet_tasks = set()
    app.state.pending_jobs = {}
    app.state.queue_backend = settings.queue_backend

    if settings.app_role == "worker":
        from src.workers.job_worker import JobWorker

        job_worker = JobWorker(job_queue, max_concurrent=settings.max_concurrent_jobs)
        app.state.job_worker = job_worker
        worker_task = asyncio.create_task(job_worker.start())

    _retrainer = None
    if settings.ml_weekly_retrainer_enabled and settings.app_role == "worker":
        from src.infrastructure.s3_client import S3Client
        from src.services.analytics.retrainer import WeeklyRetrainer
        from src.services.dataset_service import DatasetService

        _retrainer = WeeklyRetrainer(
            job_queue=job_queue,
            dataset_service=DatasetService(S3Client()),
        )
        await _retrainer.start(device_ids=[])
        app.state.retrainer = _retrainer
    
    logger.info("analytics_service_ready")
    
    yield
    
    logger.info("analytics_service_shutting_down")
    if job_worker is not None:
        await job_worker.stop()
    for task in list(app.state.fleet_tasks):
        task.cancel()
    if app.state.fleet_tasks:
        await asyncio.gather(*app.state.fleet_tasks, return_exceptions=True)
    if worker_task is not None:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass

    if settings.ml_weekly_retrainer_enabled and hasattr(app.state, "retrainer") and _retrainer:
        await _retrainer.stop()
    logger.info("analytics_service_stopped")


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    settings = get_settings()
    
    app = FastAPI(
        title="Analytics Service",
        description="ML Analytics Service for Energy Intelligence Platform",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    app.add_middleware(AuthMiddleware)
    
    app.include_router(health.router, prefix="/health", tags=["health"])
    app.include_router(
        analytics.router,
        prefix="/api/v1/analytics",
        tags=["analytics"],
        dependencies=[Depends(require_feature("analytics"))],
    )

    @app.get("/health")
    async def health_compat() -> dict[str, str]:
        return {
            "status": "healthy",
            "service": "analytics-service",
        }

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "error": "VALIDATION_ERROR",
                "message": "Invalid request payload",
                "code": "VALIDATION_ERROR",
                "details": exc.errors(),
            },
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        if isinstance(exc.detail, dict):
            payload = dict(exc.detail)
            payload.setdefault("code", payload.get("error", "HTTP_ERROR"))
            payload.setdefault("message", "Request failed")
            return JSONResponse(status_code=exc.status_code, content=payload)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": "HTTP_ERROR", "message": str(exc.detail), "code": "HTTP_ERROR"},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception in analytics-service")
        return JSONResponse(
            status_code=500,
            content={
                "error": "INTERNAL_ERROR",
                "message": "Unexpected server error",
                "code": "INTERNAL_ERROR",
            },
        )
    
    return app


app = create_app()
