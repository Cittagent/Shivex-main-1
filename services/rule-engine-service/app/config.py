"""Application configuration management for Rule Engine Service."""

import logging
import os

from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )
    
    # Application
    SERVICE_NAME: str = "rule-engine-service"
    APP_NAME: str = "rule-engine-service"
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
    
    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"
    
    # Rule Engine
    RULE_EVALUATION_TIMEOUT: int = 5  # seconds
    NOTIFICATION_COOLDOWN_MINUTES: int = 15
    MAX_RULES_PER_DEVICE: int = 100
    PLATFORM_TIMEZONE: str = "Asia/Kolkata"
    
    # Notification Adapters
    EMAIL_ENABLED: bool = True
    EMAIL_SMTP_HOST: str | None = os.getenv("EMAIL_SMTP_HOST", None)
    EMAIL_SMTP_PORT: int = 587
    EMAIL_SMTP_USERNAME: str | None = os.getenv("EMAIL_SMTP_USERNAME", None)
    EMAIL_SMTP_PASSWORD: str | None = os.getenv("EMAIL_SMTP_PASSWORD", None)
    EMAIL_FROM_ADDRESS: str = "alerts@energy-platform.com"

    SMS_ENABLED: bool = False
    TWILIO_ACCOUNT_SID: str | None = os.getenv("TWILIO_ACCOUNT_SID", None)
    TWILIO_AUTH_TOKEN: str | None = os.getenv("TWILIO_AUTH_TOKEN", None)
    TWILIO_SMS_FROM_NUMBER: str | None = os.getenv("TWILIO_SMS_FROM_NUMBER", None)

    WHATSAPP_ENABLED: bool = False
    TWILIO_WHATSAPP_FROM_NUMBER: str | None = os.getenv("TWILIO_WHATSAPP_FROM_NUMBER", None)
    DEVICE_SERVICE_URL: str | None = os.getenv("DEVICE_SERVICE_URL", None)
    
    # Multi-tenancy (Phase-2 ready)
    TENANT_ID_HEADER: str = "X-Tenant-ID"

    def model_post_init(self, __context):
        if self.EMAIL_SMTP_PASSWORD is not None:
            self.EMAIL_SMTP_PASSWORD = self.EMAIL_SMTP_PASSWORD.replace(" ", "")
    

settings = Settings()

for _name in (
    "DATABASE_URL",
    "EMAIL_SMTP_HOST",
    "EMAIL_SMTP_USERNAME",
    "EMAIL_SMTP_PASSWORD",
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_SMS_FROM_NUMBER",
    "TWILIO_WHATSAPP_FROM_NUMBER",
    "DEVICE_SERVICE_URL",
):
    if getattr(settings, _name) is None:
        logger.warning("Missing environment variable for rule-engine-service setting: %s", _name)
