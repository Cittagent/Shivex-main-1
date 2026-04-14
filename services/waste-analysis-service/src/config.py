import logging
import os

from pydantic_settings import BaseSettings, SettingsConfigDict


logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    DATABASE_URL: str | None = os.getenv("DATABASE_URL", None)
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20
    DATABASE_POOL_TIMEOUT: int = 30
    DATABASE_POOL_RECYCLE: int = 3600

    INFLUXDB_URL: str | None = os.getenv("INFLUXDB_URL", None)
    INFLUXDB_TOKEN: str | None = os.getenv("INFLUXDB_TOKEN", None)
    INFLUXDB_ORG: str = "energy-org"
    INFLUXDB_BUCKET: str = "telemetry"
    INFLUXDB_MEASUREMENT: str = "device_telemetry"
    INFLUX_AGGREGATION_WINDOW: str = "5m"
    INFLUX_MAX_POINTS: int = 10000

    DEVICE_SERVICE_URL: str | None = os.getenv("DEVICE_SERVICE_URL", None)
    REPORTING_SERVICE_URL: str | None = os.getenv("REPORTING_SERVICE_URL", None)
    ENERGY_SERVICE_URL: str | None = os.getenv("ENERGY_SERVICE_URL", None)

    MINIO_ENDPOINT: str | None = os.getenv("MINIO_ENDPOINT", None)
    MINIO_EXTERNAL_URL: str | None = os.getenv("MINIO_EXTERNAL_URL", None)
    MINIO_ACCESS_KEY: str | None = os.getenv("MINIO_ACCESS_KEY", None)
    MINIO_SECRET_KEY: str | None = os.getenv("MINIO_SECRET_KEY", None)
    MINIO_BUCKET: str = "factoryops-waste-reports"
    MINIO_SECURE: bool = False
    PLATFORM_TIMEZONE: str = "Asia/Kolkata"

    TARIFF_CACHE_TTL_SECONDS: int = 60
    WASTE_STRICT_QUALITY_GATE: bool = False
    WASTE_JOB_TIMEOUT_SECONDS: int = 600
    WASTE_DEVICE_CONCURRENCY: int = 16
    WASTE_DB_BATCH_SIZE: int = 500
    WASTE_PDF_MAX_DEVICES: int = 200


settings = Settings()

for _name in (
    "DATABASE_URL",
    "INFLUXDB_URL",
    "INFLUXDB_TOKEN",
    "DEVICE_SERVICE_URL",
    "REPORTING_SERVICE_URL",
    "ENERGY_SERVICE_URL",
    "MINIO_ENDPOINT",
    "MINIO_EXTERNAL_URL",
    "MINIO_ACCESS_KEY",
    "MINIO_SECRET_KEY",
):
    if getattr(settings, _name) is None:
        logger.warning("Missing environment variable for waste-analysis-service setting: %s", _name)
