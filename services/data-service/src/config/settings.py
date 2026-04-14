"""Application configuration settings."""

import logging
import os
from typing import List, Optional
from pathlib import Path
from urllib.parse import quote_plus

from pydantic import Field, validator, AliasChoices
from pydantic_settings import BaseSettings


ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    app_name: str = Field(default="data-service", description="Service name")
    app_version: str = Field(default="1.0.0", description="Service version")
    environment: str = Field(default="development", description="Environment")
    log_level: str = Field(default="INFO", description="Logging level")

    # Server
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8081, description="Server port")

    # MQTT Configuration
    mqtt_broker_host: str = Field(default="localhost", description="MQTT broker host")
    mqtt_broker_port: int = Field(default=1883, description="MQTT broker port")
    mqtt_username: Optional[str] = Field(default=None, description="MQTT username")
    mqtt_password: Optional[str] = Field(default=os.getenv("MQTT_PASSWORD", None), description="MQTT password")
    mqtt_topic: str = Field(default="devices/+/telemetry", description="MQTT subscription topic")
    mqtt_qos: int = Field(default=1, description="MQTT QoS level")
    mqtt_reconnect_interval: int = Field(default=5, description="MQTT reconnect interval in seconds")
    mqtt_max_reconnect_attempts: int = Field(default=10, description="Max MQTT reconnect attempts")
    mqtt_keepalive: int = Field(default=60, description="MQTT keepalive interval")

    # InfluxDB Configuration
    influxdb_url: str | None = Field(default=os.getenv("INFLUXDB_URL", None), description="InfluxDB URL")
    influxdb_token: str | None = Field(default=os.getenv("INFLUXDB_TOKEN", None), description="InfluxDB token")
    influxdb_org: str = Field(default="energy-platform", description="InfluxDB organization")
    influxdb_bucket: str = Field(default="telemetry", description="InfluxDB bucket")
    influxdb_timeout: int = Field(default=5000, description="InfluxDB timeout in milliseconds")
    influx_batch_size: int = Field(default=100, description="InfluxDB batch size")
    influx_flush_interval_ms: int = Field(default=1000, description="InfluxDB batch flush interval in milliseconds")
    influx_max_retries: int = Field(default=3, description="Max retries for batched InfluxDB writes")

    # Device Service Configuration
    device_service_url: str | None = Field(
        default=os.getenv("DEVICE_SERVICE_URL", None),
        description="Device service base URL",
        validation_alias=AliasChoices(
            "device_service_url",
            "device_service_base_url",
        ),
    )
    device_service_timeout: float = Field(default=5.0, description="Device service timeout in seconds")
    device_service_max_retries: int = Field(default=3, description="Max retries for device service")
    device_sync_enabled: bool = Field(default=True, description="Enable async device heartbeat/property sync")
    device_sync_workers: int = Field(default=2, description="Number of device sync workers")
    device_sync_queue_maxsize: int = Field(default=5000, description="Max queued device sync tasks")
    device_sync_max_retries: int = Field(default=3, description="Max retries for each device sync task")
    device_sync_retry_backoff_sec: float = Field(default=0.5, description="Initial sync retry backoff in seconds")
    device_sync_retry_backoff_max_sec: float = Field(default=5.0, description="Max sync retry backoff in seconds")
    energy_service_url: str | None = Field(default=os.getenv("ENERGY_SERVICE_URL", None), description="Energy service base URL")
    energy_sync_enabled: bool = Field(default=True, description="Enable async energy projection sync")
    queue_overflow_log_level: str = Field(default="WARNING", description="Log level for queue overflow events")
    queue_depth_check_interval_sec: int = Field(default=10, description="Queue depth monitoring interval in seconds")
    queue_drain_timeout_sec: int = Field(default=30, description="Maximum seconds to wait for queue drain on shutdown")

    # MySQL Configuration (for durable DLQ backend)
    mysql_host: str = Field(default="mysql", description="MySQL host")
    mysql_port: int = Field(default=3306, description="MySQL port")
    mysql_database: str = Field(default="ai_factoryops", description="MySQL database name")
    mysql_user: str = Field(default="energy", description="MySQL username")
    mysql_password: str | None = Field(default=os.getenv("MYSQL_PASSWORD", None), description="MySQL password")

    # Outbox / Reconciliation
    outbox_poll_interval_sec: float = Field(default=2.0, description="Outbox relay polling interval in seconds")
    outbox_batch_size: int = Field(default=50, description="Max outbox rows claimed per relay batch")
    outbox_max_retries: int = Field(default=5, description="Max delivery retries before dead lettering")
    outbox_delivered_retention_days: int = Field(default=7, description="Days to keep delivered outbox rows")
    outbox_dead_retention_days: int = Field(default=14, description="Days to keep dead outbox rows")
    reconciliation_log_retention_days: int = Field(default=14, description="Days to keep reconciliation log rows")
    retention_cleanup_interval_sec: int = Field(default=3600, description="Retention cleanup interval in seconds")
    retention_cleanup_batch_size: int = Field(default=5000, description="Max rows to purge per table per cleanup pass")
    reconciliation_interval_sec: int = Field(default=300, description="Reconciliation run interval in seconds")
    reconciliation_drift_warn_minutes: int = Field(default=10, description="Warn threshold in minutes")
    reconciliation_drift_resync_minutes: int = Field(default=30, description="Resync threshold in minutes")
    circuit_breaker_failure_threshold: int = Field(default=5, description="Failures before opening a circuit breaker")
    circuit_breaker_open_timeout_sec: int = Field(default=30, description="Open state timeout before half-open probe")
    circuit_breaker_success_threshold: int = Field(default=2, description="Half-open successes required to close a breaker")

    # Rule Engine Configuration
    rule_engine_url: str | None = Field(
        default=os.getenv("RULE_ENGINE_URL", None),
        description="Rule engine service URL",
        validation_alias=AliasChoices(
            "rule_engine_url",
            "rule_engine_base_url",
        ),
    )
    rule_engine_timeout: float = Field(default=5.0, description="Rule engine timeout")
    rule_engine_max_retries: int = Field(default=3, description="Max retries for rule engine")
    rule_engine_retry_delay: float = Field(default=1.0, description="Initial retry delay")

    # DLQ Configuration
    dlq_enabled: bool = Field(default=True, description="Enable dead letter queue")
    dlq_backend: str = Field(default="mysql", description="DLQ backend: mysql or file")
    dlq_directory: str = Field(default="./dlq", description="DLQ file directory")
    dlq_max_file_size: int = Field(default=10 * 1024 * 1024, description="Max DLQ file size in bytes")
    dlq_max_files: int = Field(default=10, description="Max number of DLQ files")
    dlq_retention_days: int = Field(default=14, description="DLQ retention days for durable backend")
    dlq_flush_batch_size: int = Field(default=100, description="Batch size for DLQ backend operations")

    # Telemetry Validation
    telemetry_schema_version: str = Field(default="v1", description="Supported schema version")
    telemetry_max_voltage: float = Field(default=250.0, description="Max voltage value")
    telemetry_min_voltage: float = Field(default=200.0, description="Min voltage value")
    telemetry_max_current: float = Field(default=2.0, description="Max current value")
    telemetry_min_current: float = Field(default=0.0, description="Min current value")
    telemetry_max_power: float = Field(default=500.0, description="Max power value")
    telemetry_min_power: float = Field(default=0.0, description="Min power value")
    telemetry_max_temperature: float = Field(default=80.0, description="Max temperature value")
    telemetry_min_temperature: float = Field(default=20.0, description="Min temperature value")
    telemetry_default_lookback_hours: int = Field(
        default=720,
        description="Default telemetry query window when start_time is not provided",
    )

    # WebSocket Configuration
    ws_heartbeat_interval: int = Field(default=30, description="WebSocket heartbeat interval")
    ws_max_connections: int = Field(default=100, description="Max WebSocket connections")

    # API Configuration
    # ✅ MUST MATCH UI
    api_prefix: str = Field(default="/api/v1/data", description="API route prefix")

    cors_origins: List[str] = Field(default=["*"], description="CORS allowed origins")

    @validator("mqtt_qos")
    def validate_mqtt_qos(cls, v: int) -> int:
        if v not in [0, 1, 2]:
            raise ValueError("MQTT QoS must be 0, 1, or 2")
        return v

    @validator("log_level")
    def validate_log_level(cls, v: str) -> str:
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"Log level must be one of {valid_levels}")
        return v.upper()

    @validator("dlq_backend")
    def validate_dlq_backend(cls, v: str) -> str:
        normalized = v.lower().strip()
        if normalized not in {"mysql", "file"}:
            raise ValueError("dlq_backend must be either 'mysql' or 'file'")
        return normalized

    @validator("queue_overflow_log_level")
    def validate_queue_overflow_log_level(cls, v: str) -> str:
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        normalized = v.upper().strip()
        if normalized not in valid_levels:
            raise ValueError(f"queue_overflow_log_level must be one of {valid_levels}")
        return normalized

    class Config:
        env_file = str(ENV_PATH)
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"

    @property
    def mysql_async_url(self) -> str:
        password = quote_plus(self.mysql_password or "")
        return (
            f"mysql+aiomysql://{self.mysql_user}:{password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
        )

    @property
    def mysql_sync_url(self) -> str:
        password = quote_plus(self.mysql_password or "")
        return (
            f"mysql+pymysql://{self.mysql_user}:{password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
        )


settings = Settings()

for _name in (
    "MQTT_PASSWORD",
    "INFLUXDB_URL",
    "INFLUXDB_TOKEN",
    "DEVICE_SERVICE_URL",
    "ENERGY_SERVICE_URL",
    "MYSQL_PASSWORD",
    "RULE_ENGINE_URL",
):
    if getattr(settings, _name.lower() if _name.isupper() else _name) is None:
        logger.warning("Missing environment variable for data-service setting: %s", _name)
