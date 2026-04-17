import logging
import asyncio
from contextlib import asynccontextmanager
from contextlib import suppress
from typing import Any

from fastapi import FastAPI, Request, status as http_status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.v1.admin import router as admin_router
from app.api.v1.auth import router as auth_router
from app.api.v1.orgs import router as tenants_router
from app.config import settings
from app.cors import build_allowed_origins
from app.database import AsyncSessionFactory, engine
from app.rate_limit import configure_rate_limiting
from app.services.bootstrap_service import ensure_bootstrap_super_admin
from app.services.token_cleanup_service import refresh_token_cleanup_svc
from services.shared.startup_contract import validate_startup_contract

logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
logger = logging.getLogger("auth-service")

_SENSITIVE_FIELD_NAMES = {
    "authorization",
    "password",
    "confirm_password",
    "refresh_token",
    "access_token",
    "token",
}


def _redact_sensitive_data(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if key.lower() in _SENSITIVE_FIELD_NAMES:
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = _redact_sensitive_data(item)
        return redacted
    if isinstance(value, list):
        return [_redact_sensitive_data(item) for item in value]
    return value


def _sanitize_validation_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for error in errors:
        clean = {key: value for key, value in error.items() if key != "input"}
        if "ctx" in clean:
            clean["ctx"] = _redact_sensitive_data(clean["ctx"])
        sanitized.append(clean)
    return sanitized


class SensitiveDataFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in list(record.__dict__.items()):
            if key.lower() in _SENSITIVE_FIELD_NAMES:
                record.__dict__[key] = "[REDACTED]"
            elif isinstance(value, (dict, list)):
                record.__dict__[key] = _redact_sensitive_data(value)
        return True


for _logger_name in ("auth-service", "auth-service.auth", "auth-service.mailer"):
    logging.getLogger(_logger_name).addFilter(SensitiveDataFilter())


def validate_auth_email_contract() -> None:
    if not settings.EMAIL_ENABLED:
        raise RuntimeError("STARTUP BLOCKED: Email-based invite/reset flows require EMAIL_ENABLED=true.")

    required = {
        "EMAIL_SMTP_HOST": settings.EMAIL_SMTP_HOST,
        "EMAIL_FROM_ADDRESS": settings.EMAIL_FROM_ADDRESS,
        "FRONTEND_BASE_URL": settings.FRONTEND_BASE_URL,
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        raise RuntimeError(f"STARTUP BLOCKED: Missing auth email settings: {missing}")

    if settings.EMAIL_SMTP_USERNAME and not settings.EMAIL_SMTP_PASSWORD:
        raise RuntimeError("STARTUP BLOCKED: EMAIL_SMTP_USERNAME is configured but EMAIL_SMTP_PASSWORD is missing.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_startup_contract()
    validate_auth_email_contract()
    logger.info(f"auth-service starting — environment={settings.ENVIRONMENT}")
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    logger.info("DB connection verified")
    async with AsyncSessionFactory() as session:
        created = await ensure_bootstrap_super_admin(session)
    if created:
        logger.info("Bootstrap super-admin created", extra={"email": settings.BOOTSTRAP_SUPER_ADMIN_EMAIL})
    cleanup_task = asyncio.create_task(refresh_token_cleanup_svc.run_forever())
    yield
    cleanup_task.cancel()
    with suppress(asyncio.CancelledError):
        await cleanup_task
    await engine.dispose()
    logger.info("auth-service shutdown complete")


app = FastAPI(
    title="FactoryOPS Auth Service",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url=None,
)

configure_rate_limiting(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=build_allowed_origins(settings.FRONTEND_BASE_URL),
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|32\.193\.53\.87)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(tenants_router)


@app.get("/health", tags=["ops"])
async def health():
    return {"status": "ok", "service": "auth-service"}


@app.get("/ready", tags=["ops"])
async def ready():
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "not ready"})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "code": "VALIDATION_ERROR",
            "message": "Request validation failed",
            "details": jsonable_encoder(
                _sanitize_validation_errors(exc.errors()),
                custom_encoder={ValueError: str},
            ),
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled exception on {request.method} {request.url.path}")
    return JSONResponse(
        status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"code": "INTERNAL_ERROR", "message": "An unexpected error occurred"},
    )
