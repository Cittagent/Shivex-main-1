import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import inspect, text

from src.database import engine
from src.handlers import waste_router
from src.services.influx_reader import influx_reader
from src.storage.minio_client import minio_client
from shared.auth_middleware import AuthMiddleware
from shared.feature_entitlements import require_feature
from services.shared.startup_contract import validate_startup_contract

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def fail_stale_waste_jobs_on_startup() -> None:
    cutoff = datetime.utcnow() - timedelta(minutes=10)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                UPDATE waste_analysis_jobs
                SET
                    status = 'failed',
                    progress_pct = 100,
                    stage = 'Service restarted',
                    error_code = 'SERVICE_RESTARTED',
                    error_message = 'Service restarted',
                    completed_at = :now
                WHERE
                    status IN ('pending', 'processing')
                    AND created_at < :cutoff
                """
            ),
            {"now": datetime.utcnow(), "cutoff": cutoff},
        )


async def ensure_waste_duplicate_job_index() -> None:
    index_name = "idx_waste_jobs_tenant_duplicate_lookup"
    async with engine.begin() as conn:
        def _ensure(sync_conn) -> None:
            inspector = inspect(sync_conn)
            existing_indexes = {idx["name"]: idx for idx in inspector.get_indexes("waste_analysis_jobs")}
            existing = existing_indexes.get(index_name)
            expected_columns = ["tenant_id", "status", "scope", "start_date", "end_date", "granularity"]
            if existing and existing.get("column_names") == expected_columns:
                return
            if existing:
                sync_conn.execute(text(f"DROP INDEX {index_name} ON waste_analysis_jobs"))
            if "idx_waste_jobs_duplicate_lookup" in existing_indexes:
                sync_conn.execute(text("DROP INDEX idx_waste_jobs_duplicate_lookup ON waste_analysis_jobs"))
            if "idx_waste_jobs_history_tenant_created" not in existing_indexes:
                sync_conn.execute(
                    text(
                        """
                        CREATE INDEX idx_waste_jobs_history_tenant_created
                        ON waste_analysis_jobs (tenant_id, created_at)
                        """
                    )
                )
            if index_name not in existing_indexes or existing is None or existing.get("column_names") != expected_columns:
                sync_conn.execute(
                    text(
                        f"""
                        CREATE INDEX {index_name}
                        ON waste_analysis_jobs (tenant_id, status, scope, start_date, end_date, granularity)
                        """
                    )
                )

        await conn.run_sync(_ensure)


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_startup_contract()
    logger.info("Starting waste-analysis-service...")

    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    await fail_stale_waste_jobs_on_startup()
    logger.info("Stale waste-analysis jobs cleanup complete")
    await ensure_waste_duplicate_job_index()
    logger.info("Waste duplicate job index ensured")

    try:
        influx_reader.client.ping()
    except Exception as exc:  # pragma: no cover
        logger.error("Influx ping failed on startup", exc_info=exc)
        raise

    minio_client.ensure_bucket_exists()
    yield

    influx_reader.close()
    await engine.dispose()


app = FastAPI(title="Waste Analysis Service", version="1.0.0", lifespan=lifespan)
app.add_middleware(AuthMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    logger.exception("Unhandled exception in waste-analysis-service")
    return JSONResponse(
        status_code=500,
        content={
            "error": "INTERNAL_ERROR",
            "message": "Unexpected server error",
            "code": "INTERNAL_ERROR",
        },
    )


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/ready")
async def ready():
    checks = {
        "db": "connected",
        "influx": "connected",
        "minio": "connected",
    }

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        checks["db"] = "disconnected"

    try:
        influx_reader.client.ping()
    except Exception:
        checks["influx"] = "disconnected"

    try:
        minio_client.health_check()
    except Exception:
        checks["minio"] = "disconnected"

    if "disconnected" in set(checks.values()):
        raise HTTPException(
            status_code=503,
            detail={"status": "not_ready", **checks},
        )

    return {"status": "ready", **checks}


app.include_router(waste_router, prefix="/api/v1/waste", dependencies=[Depends(require_feature("waste_analysis"))])
