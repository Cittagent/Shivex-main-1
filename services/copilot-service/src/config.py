import logging
import os
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_PATH),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(default="copilot-service")
    app_version: str = Field(default="1.0.0")
    log_level: str = Field(default="INFO")

    ai_provider: str = Field(default="groq")
    groq_api_key: str | None = Field(default=os.getenv("GROQ_API_KEY", None))
    groq_model: str = Field(default=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"))
    gemini_api_key: str | None = Field(default=os.getenv("GEMINI_API_KEY", None))
    openai_api_key: str | None = Field(default=os.getenv("OPENAI_API_KEY", None))

    mysql_url: str | None = Field(default=os.getenv("MYSQL_URL", None))
    mysql_readonly_url: str | None = Field(default=os.getenv("MYSQL_READONLY_URL", os.getenv("MYSQL_URL", None)))
    data_service_url: str | None = Field(default=os.getenv("DATA_SERVICE_URL", None))
    reporting_service_url: str | None = Field(default=os.getenv("REPORTING_SERVICE_URL", None))
    energy_service_url: str | None = Field(default=os.getenv("ENERGY_SERVICE_URL", None))
    factory_timezone: str = Field(default="Asia/Kolkata")

    max_query_rows: int = Field(default=200)
    query_timeout_sec: int = Field(default=10)
    max_history_turns: int = Field(default=5)

    stage1_max_tokens: int = Field(default=500)
    stage2_max_tokens: int = Field(default=900)


settings = Settings()

for _name in (
    "GROQ_API_KEY",
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "MYSQL_URL",
    "MYSQL_READONLY_URL",
    "DATA_SERVICE_URL",
    "REPORTING_SERVICE_URL",
    "ENERGY_SERVICE_URL",
):
    if getattr(settings, _name.lower()) is None:
        logger.warning("Missing environment variable for copilot-service setting: %s", _name)
