from __future__ import annotations

import os
import sys
from datetime import date

sys.path.insert(0, "/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/reporting-service")
sys.path.insert(1, "/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services")

os.environ.setdefault("DEVICE_SERVICE_URL", "http://device-service:8001")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

from src.handlers.energy_reports import normalize_dates_to_utc, validate_date_duration_seconds


def test_same_day_range_counts_as_full_day_for_report_validation() -> None:
    start_dt, end_dt = normalize_dates_to_utc(date(2026, 4, 9), date(2026, 4, 9))

    assert validate_date_duration_seconds(start_dt, end_dt) is True


def test_sub_day_window_still_fails_report_validation() -> None:
    start_dt, _ = normalize_dates_to_utc(date(2026, 4, 9), date(2026, 4, 9))
    end_dt = start_dt.replace(hour=23, minute=0, second=0)

    assert validate_date_duration_seconds(start_dt, end_dt) is False
