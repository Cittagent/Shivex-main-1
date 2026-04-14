
"""
Data Service Main Application

Entry point for the Data Service that handles telemetry ingestion,
validation, enrichment, and persistence.
"""

# ✅ PERMANENT FIX FOR direct execution
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SERVICES_DIR = BASE_DIR.parent
PROJECT_ROOT = SERVICES_DIR.parent
for path in (PROJECT_ROOT, SERVICES_DIR, BASE_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

# --------------------------------------------------

import asyncio
import signal
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.config import settings
from src.handlers import MQTTHandler
from src.services import (
    DLQRetryService,
    OutboxRelayService,
    ReconciliationService,
    RetentionCleanupService,
    TelemetryService,
    ensure_bucket_retention,
)
from src.api import create_router, create_websocket_router
from src.utils.circuit_breaker import get_circuit_breaker_metrics
from src.utils import configure_logging, get_logger
from shared.auth_middleware import AuthMiddleware
from services.shared.startup_contract import validate_startup_contract


configure_logging(settings.log_level)
logger = get_logger(__name__)


class ApplicationState:
    """Global application state management."""

    def __init__(self):
        self.telemetry_service: TelemetryService | None = None
        self.dlq_retry_service: DLQRetryService | None = None
        self.outbox_relay_service: OutboxRelayService | None = None
        self.reconciliation_service: ReconciliationService | None = None
        self.retention_cleanup_service: RetentionCleanupService | None = None
        self.mqtt_handler: MQTTHandler | None = None
        self._shutdown_event = asyncio.Event()

    async def startup(self) -> None:
        logger.info(
            "Starting Data Service",
            version=settings.app_version,
            environment=settings.environment,
        )

        self.telemetry_service = TelemetryService()
        await self.telemetry_service.start()
        await ensure_bucket_retention(self.telemetry_service.influx_repository.client)

        self.outbox_relay_service = OutboxRelayService(
            outbox_repository=self.telemetry_service.outbox_repository,
            dlq_repository=self.telemetry_service.dlq_repository,
        )
        await self.outbox_relay_service.start()

        self.reconciliation_service = ReconciliationService(
            influx_repository=self.telemetry_service.influx_repository,
            outbox_repository=self.telemetry_service.outbox_repository,
        )
        await self.reconciliation_service.start()

        self.retention_cleanup_service = RetentionCleanupService(
            outbox_repository=self.telemetry_service.outbox_repository,
            dlq_repository=self.telemetry_service.dlq_repository,
        )
        await self.retention_cleanup_service.start()

        self.dlq_retry_service = DLQRetryService(
            telemetry_service=self.telemetry_service,
            dlq_repository=self.telemetry_service.dlq_repository,
        )
        await self.dlq_retry_service.start()

        self.mqtt_handler = MQTTHandler(
            telemetry_service=self.telemetry_service,
        )
        self.mqtt_handler.connect()

        logger.info("Data Service startup complete")

    async def shutdown(self) -> None:
        logger.info("Shutting down Data Service...")

        if self.mqtt_handler:
            self.mqtt_handler.disconnect()

        if self.reconciliation_service:
            await self.reconciliation_service.stop()
            self.reconciliation_service = None

        if self.retention_cleanup_service:
            await self.retention_cleanup_service.stop()
            self.retention_cleanup_service = None

        if self.outbox_relay_service:
            await self.outbox_relay_service.stop()
            self.outbox_relay_service = None

        if self.dlq_retry_service:
            await self.dlq_retry_service.stop()
            self.dlq_retry_service = None

        if self.telemetry_service:
            await self.telemetry_service.close()
            self.telemetry_service = None

        self._shutdown_event.set()

        logger.info("Data Service shutdown complete")

    async def wait_for_shutdown(self) -> None:
        await self._shutdown_event.wait()


app_state = ApplicationState()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    validate_startup_contract()
    await app_state.startup()
    yield
    await app_state.shutdown()


def create_application() -> FastAPI:
    app = FastAPI(
        title="Data Service",
        description="Telemetry ingestion, validation, and persistence service",
        version=settings.app_version,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    app.add_middleware(AuthMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ✅ SINGLE REST API ROUTER
    api_router = create_router()
    app.include_router(api_router)

    # ✅ WebSocket routes
    ws_router = create_websocket_router()
    app.include_router(ws_router)

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
        logger.exception("Unhandled exception in data-service")
        return JSONResponse(
            status_code=500,
            content={
                "error": "INTERNAL_ERROR",
                "message": "Unexpected server error",
                "code": "INTERNAL_ERROR",
            },
        )

    return app


def handle_signal(sig: int, frame) -> None:
    logger.info("Received shutdown signal", signal=sig)
    asyncio.create_task(app_state.shutdown())


app = create_application()


@app.get("/")
async def root():
    return {
        "service": "Data Service",
        "version": settings.app_version,
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "data-service",
        "version": settings.app_version,
        "circuit_breakers": get_circuit_breaker_metrics(),
    }


signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)


if __name__ == "__main__":
    import uvicorn

    logger.info(
        "Starting Data Service server",
        host=settings.host,
        port=settings.port,
    )

    uvicorn.run(
        "src.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        reload=settings.environment == "development",
    )
