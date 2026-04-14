"""Application configuration management."""

import logging
import os
import socket
from urllib.parse import urlparse

from typing import Any, Optional

from pydantic_settings import BaseSettings


logger = logging.getLogger(__name__)


DEPENDENCY_URL_ENV_VARS = (
    "AUTH_SERVICE_BASE_URL",
    "DATA_SERVICE_BASE_URL",
    "ENERGY_SERVICE_BASE_URL",
    "RULE_ENGINE_SERVICE_BASE_URL",
    "REPORTING_SERVICE_BASE_URL",
)


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Application
    SERVICE_NAME: Optional[str] = None 
    APP_NAME: str = "device-service"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    
    # Database
    DATABASE_URL: str | None = os.getenv("DATABASE_URL", None)
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20
    DATABASE_POOL_TIMEOUT: int = 30
    DATABASE_POOL_RECYCLE: int = 1800
    
    # API
    API_PREFIX: str = "/api/v1"

    # Service integration
    AUTH_SERVICE_BASE_URL: str | None = os.getenv("AUTH_SERVICE_URL", os.getenv("AUTH_SERVICE_BASE_URL", None))
    DATA_SERVICE_BASE_URL: str | None = os.getenv("DATA_SERVICE_BASE_URL", None)
    RULE_ENGINE_SERVICE_BASE_URL: str | None = os.getenv("RULE_ENGINE_SERVICE_BASE_URL", None)
    REPORTING_SERVICE_BASE_URL: str | None = os.getenv("REPORTING_SERVICE_BASE_URL", None)
    ENERGY_SERVICE_BASE_URL: str | None = os.getenv("ENERGY_SERVICE_BASE_URL", None)
    ENERGY_SERVICE_TIMEOUT_SECONDS: float = 2.5

    # Performance trends
    PERFORMANCE_TRENDS_ENABLED: bool = True
    PERFORMANCE_TRENDS_CRON_ENABLED: bool = True
    PERFORMANCE_TRENDS_INTERVAL_MINUTES: int = 5
    PERFORMANCE_TRENDS_RETENTION_DAYS: int = 35
    PERFORMANCE_TRENDS_MAX_POINTS: int = 600
    PERFORMANCE_TRENDS_TIMEZONE: str = "Asia/Kolkata"
    PLATFORM_TIMEZONE: str = "Asia/Kolkata"

    # Dashboard snapshot materialization
    DASHBOARD_SNAPSHOT_ENABLED: bool = False
    DASHBOARD_SNAPSHOT_INTERVAL_SECONDS: int = 5
    DASHBOARD_ENERGY_REFRESH_SECONDS: int = 300
    DASHBOARD_SNAPSHOT_STALE_AFTER_SECONDS: int = 15
    DASHBOARD_SCHEDULER_MAX_DRIFT_SECONDS: int = 10
    DASHBOARD_DOWNSTREAM_TIMEOUT_SECONDS: float = 2.5
    DASHBOARD_DOWNSTREAM_RETRIES: int = 1
    DASHBOARD_CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = 3
    DASHBOARD_CIRCUIT_BREAKER_COOLDOWN_SECONDS: int = 20
    DASHBOARD_STREAM_HEARTBEAT_SECONDS: int = 5
    DASHBOARD_STREAM_QUEUE_SIZE: int = 64
    DASHBOARD_STREAM_SEND_TIMEOUT_SECONDS: int = 10
    DASHBOARD_COST_FRESHNESS_SECONDS: int = 15
    DASHBOARD_RECONCILE_INTERVAL_SECONDS: int = 600
    SNAPSHOT_STORAGE_BACKEND: str = os.getenv("SNAPSHOT_STORAGE_BACKEND", "minio")
    SNAPSHOT_MINIO_BUCKET: str = os.getenv("SNAPSHOT_MINIO_BUCKET", "dashboard-snapshots")
    SNAPSHOT_MINIO_ENDPOINT: str = os.getenv("SNAPSHOT_MINIO_ENDPOINT", os.getenv("MINIO_ENDPOINT", "minio:9000"))
    SNAPSHOT_MINIO_ACCESS_KEY: str = os.getenv("SNAPSHOT_MINIO_ACCESS_KEY", os.getenv("MINIO_ROOT_USER", "minio"))
    SNAPSHOT_MINIO_SECRET_KEY: str = os.getenv("SNAPSHOT_MINIO_SECRET_KEY", os.getenv("MINIO_ROOT_PASSWORD", "minio123"))
    SNAPSHOT_MINIO_SECURE: bool = os.getenv("SNAPSHOT_MINIO_SECURE", "false").lower() in {"1", "true", "yes", "on"}
    MIGRATE_SNAPSHOTS_TO_MINIO: bool = os.getenv("MIGRATE_SNAPSHOTS_TO_MINIO", "false").lower() in {"1", "true", "yes", "on"}

    # Fleet stream distribution (multi-instance safe fanout)
    REDIS_URL: Optional[str] = os.getenv("REDIS_URL", None)
    FLEET_STREAM_REDIS_CHANNEL_TEMPLATE: str = "factoryops:fleet_stream:{tenant_id}:v1"

    # Demo / local bootstrap
    BOOTSTRAP_DEMO_DEVICES: bool = False
    
    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore"


settings = Settings()

_dependency_dns_status: dict[str, dict[str, Any]] = {}


def _extract_host_port(raw_url: Optional[str]) -> tuple[Optional[str], Optional[int]]:
    if not raw_url:
        return None, None
    parsed = urlparse(raw_url)
    return parsed.hostname, parsed.port


def validate_dependency_dns(*, log_failures: bool = True) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for env_var in DEPENDENCY_URL_ENV_VARS:
        raw_url = getattr(settings, env_var, None)
        host, port = _extract_host_port(raw_url)
        try:
            if not host:
                raise OSError("missing host")
            addrinfo = socket.getaddrinfo(host, port or 80)
            resolved_addresses = sorted({entry[4][0] for entry in addrinfo if entry[4]})
            results[env_var] = {
                "url": raw_url,
                "host": host,
                "port": port,
                "resolved": True,
                "addresses": resolved_addresses,
                "error": None,
            }
        except OSError as exc:
            if log_failures:
                logger.critical(
                    "Dependency DNS resolution failed for %s=%s",
                    env_var,
                    raw_url,
                    extra={"env_var": env_var, "url": raw_url, "error": str(exc)},
                )
            results[env_var] = {
                "url": raw_url,
                "host": host,
                "port": port,
                "resolved": False,
                "addresses": [],
                "error": str(exc),
            }
    global _dependency_dns_status
    _dependency_dns_status = results
    return results


def get_dependency_dns_status() -> dict[str, dict[str, Any]]:
    if not _dependency_dns_status:
        return validate_dependency_dns(log_failures=False)
    return dict(_dependency_dns_status)

for _name in (
    "DATABASE_URL",
    "AUTH_SERVICE_BASE_URL",
    "DATA_SERVICE_BASE_URL",
    "RULE_ENGINE_SERVICE_BASE_URL",
    "REPORTING_SERVICE_BASE_URL",
    "ENERGY_SERVICE_BASE_URL",
    "REDIS_URL",
):
    if getattr(settings, _name) is None:
        logger.warning("Missing environment variable for device-service setting: %s", _name)
