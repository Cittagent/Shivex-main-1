from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.config import settings


def get_platform_tz() -> ZoneInfo:
    return ZoneInfo(settings.PLATFORM_TIMEZONE)


def format_platform_timestamp(value: Any, fallback: str = "N/A", include_tz: bool = True) -> str:
    if not value:
        return fallback
    try:
        if isinstance(value, datetime):
            dt = value
        else:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        local_dt = dt.astimezone(get_platform_tz())
        formatted = local_dt.strftime("%d %b %Y, %I:%M %p")
        return f"{formatted} {get_platform_tz().key}" if include_tz else formatted
    except Exception:
        return str(value)


def currency_symbol(currency: str | None) -> str:
    normalized = (currency or "").upper()
    return {
        "INR": "Rs.",
        "USD": "$",
        "EUR": "EUR",
        "GBP": "GBP",
    }.get(normalized, normalized or "")
