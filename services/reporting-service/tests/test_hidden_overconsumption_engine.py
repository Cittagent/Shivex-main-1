from __future__ import annotations

import os
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, "/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/reporting-service")
sys.path.insert(1, "/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services")

os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

from src.services.hidden_overconsumption_engine import (  # noqa: E402
    aggregate_hidden_overconsumption_insight,
    calculate_device_hidden_overconsumption_insight,
)


def _ts(hour: int) -> datetime:
    return datetime(2026, 4, 8, hour, 0, tzinfo=timezone.utc)


def test_p75_percentile_uses_power_samples_not_current() -> None:
    rows = [
        {"timestamp": _ts(0), "power": 10000.0, "current": 1.0, "voltage": 230.0},
        {"timestamp": _ts(1), "power": 20000.0, "current": 99.0, "voltage": 230.0},
        {"timestamp": _ts(2), "power": 30000.0, "current": 250.0, "voltage": 230.0},
    ]

    result = calculate_device_hidden_overconsumption_insight(
        rows=rows,
        start_date=date(2026, 4, 8),
        end_date=date(2026, 4, 8),
        daily_actual_energy_kwh={"2026-04-08": 70.0},
        tariff_rate=5.0,
    )

    day = result["daily_breakdown"][0]
    assert day["p75_power_baseline_w"] == 25000.0
    assert day["baseline_energy_kwh"] == 50.0
    assert day["hidden_overconsumption_kwh"] == 20.0


def test_hidden_overconsumption_is_zero_when_actual_is_below_or_equal_baseline() -> None:
    rows = [
        {"timestamp": _ts(0), "power": 10000.0},
        {"timestamp": _ts(1), "power": 20000.0},
        {"timestamp": _ts(2), "power": 30000.0},
    ]

    result = calculate_device_hidden_overconsumption_insight(
        rows=rows,
        start_date=date(2026, 4, 8),
        end_date=date(2026, 4, 8),
        daily_actual_energy_kwh={"2026-04-08": 50.0},
        tariff_rate=6.0,
    )
    day = result["daily_breakdown"][0]
    assert day["baseline_energy_kwh"] == 50.0
    assert day["hidden_overconsumption_kwh"] == 0.0
    assert day["hidden_overconsumption_cost"] == 0.0


def test_hidden_overconsumption_is_positive_when_actual_exceeds_baseline() -> None:
    rows = [
        {"timestamp": _ts(0), "power": 10000.0},
        {"timestamp": _ts(1), "power": 20000.0},
        {"timestamp": _ts(2), "power": 30000.0},
    ]

    result = calculate_device_hidden_overconsumption_insight(
        rows=rows,
        start_date=date(2026, 4, 8),
        end_date=date(2026, 4, 8),
        daily_actual_energy_kwh={"2026-04-08": 70.0},
        tariff_rate=5.0,
    )
    day = result["daily_breakdown"][0]
    assert day["hidden_overconsumption_kwh"] == 20.0
    assert day["hidden_overconsumption_cost"] == 100.0


def test_daily_aggregation_across_multi_day_range_and_total_consistency() -> None:
    rows = [
        {"timestamp": datetime(2026, 4, 8, 0, 0, tzinfo=timezone.utc), "power": 10000.0},
        {"timestamp": datetime(2026, 4, 8, 1, 0, tzinfo=timezone.utc), "power": 10000.0},
        {"timestamp": datetime(2026, 4, 9, 0, 0, tzinfo=timezone.utc), "power": 20000.0},
        {"timestamp": datetime(2026, 4, 9, 1, 0, tzinfo=timezone.utc), "power": 20000.0},
    ]
    device = calculate_device_hidden_overconsumption_insight(
        rows=rows,
        start_date=date(2026, 4, 8),
        end_date=date(2026, 4, 9),
        daily_actual_energy_kwh={"2026-04-08": 14.0, "2026-04-09": 25.0},
        tariff_rate=4.0,
    )
    aggregated = aggregate_hidden_overconsumption_insight(
        per_device_insights=[device],
        start_date=date(2026, 4, 8),
        end_date=date(2026, 4, 9),
        tariff_rate=4.0,
    )

    daily_sum = round(sum(day["hidden_overconsumption_kwh"] for day in aggregated["daily_breakdown"]), 4)
    assert aggregated["summary"]["selected_days"] == 2
    assert aggregated["summary"]["total_hidden_overconsumption_kwh"] == daily_sum
    assert aggregated["summary"]["total_baseline_energy_kwh"] == 30.0
    assert aggregated["summary"]["total_hidden_overconsumption_kwh"] == 9.0
    assert aggregated["summary"]["total_hidden_overconsumption_cost"] == round(
        sum(float(day["hidden_overconsumption_cost"] or 0.0) for day in aggregated["daily_breakdown"]),
        2,
    )


def test_tariff_conversion_and_missing_tariff_behavior() -> None:
    rows = [
        {"timestamp": _ts(0), "power": 10000.0},
        {"timestamp": _ts(1), "power": 20000.0},
        {"timestamp": _ts(2), "power": 30000.0},
    ]
    with_tariff = calculate_device_hidden_overconsumption_insight(
        rows=rows,
        start_date=date(2026, 4, 8),
        end_date=date(2026, 4, 8),
        daily_actual_energy_kwh={"2026-04-08": 70.0},
        tariff_rate=3.5,
    )
    without_tariff = calculate_device_hidden_overconsumption_insight(
        rows=rows,
        start_date=date(2026, 4, 8),
        end_date=date(2026, 4, 8),
        daily_actual_energy_kwh={"2026-04-08": 70.0},
        tariff_rate=None,
    )

    assert with_tariff["daily_breakdown"][0]["hidden_overconsumption_cost"] == 70.0
    assert with_tariff["summary"]["total_hidden_overconsumption_cost"] == 70.0
    assert without_tariff["daily_breakdown"][0]["hidden_overconsumption_cost"] is None
    assert without_tariff["summary"]["total_hidden_overconsumption_cost"] is None


def test_missing_or_insufficient_telemetry_is_safe() -> None:
    rows = [{"timestamp": _ts(0), "power": 5000.0}]
    result = calculate_device_hidden_overconsumption_insight(
        rows=rows,
        start_date=date(2026, 4, 8),
        end_date=date(2026, 4, 8),
        daily_actual_energy_kwh={"2026-04-08": 12.0},
        tariff_rate=4.0,
    )
    day = result["daily_breakdown"][0]

    assert day["sample_count"] == 1
    assert day["covered_duration_hours"] == 0.0
    assert day["baseline_energy_kwh"] is None
    assert day["hidden_overconsumption_kwh"] == 0.0
    assert day["hidden_overconsumption_cost"] == 0.0


def test_summary_totals_are_exact_sum_of_daily_rows_for_device_and_aggregate() -> None:
    rows_device_a = [
        {"timestamp": datetime(2026, 4, 8, 0, 0, tzinfo=timezone.utc), "power": 1333.0},
        {"timestamp": datetime(2026, 4, 8, 1, 0, tzinfo=timezone.utc), "power": 1444.0},
        {"timestamp": datetime(2026, 4, 9, 0, 0, tzinfo=timezone.utc), "power": 1600.0},
        {"timestamp": datetime(2026, 4, 9, 1, 0, tzinfo=timezone.utc), "power": 1700.0},
    ]
    rows_device_b = [
        {"timestamp": datetime(2026, 4, 8, 0, 0, tzinfo=timezone.utc), "power": 800.0},
        {"timestamp": datetime(2026, 4, 8, 1, 0, tzinfo=timezone.utc), "power": 900.0},
        {"timestamp": datetime(2026, 4, 9, 0, 0, tzinfo=timezone.utc), "power": 1200.0},
        {"timestamp": datetime(2026, 4, 9, 1, 0, tzinfo=timezone.utc), "power": 1300.0},
    ]
    a = calculate_device_hidden_overconsumption_insight(
        rows=rows_device_a,
        start_date=date(2026, 4, 8),
        end_date=date(2026, 4, 9),
        daily_actual_energy_kwh={"2026-04-08": 2.1, "2026-04-09": 3.2},
        tariff_rate=8.3,
    )
    b = calculate_device_hidden_overconsumption_insight(
        rows=rows_device_b,
        start_date=date(2026, 4, 8),
        end_date=date(2026, 4, 9),
        daily_actual_energy_kwh={"2026-04-08": 1.4, "2026-04-09": 2.1},
        tariff_rate=8.3,
    )
    merged = aggregate_hidden_overconsumption_insight(
        per_device_insights=[a, b],
        start_date=date(2026, 4, 8),
        end_date=date(2026, 4, 9),
        tariff_rate=8.3,
    )

    for block in (a, b, merged):
        rows = block["daily_breakdown"]
        summary = block["summary"]
        assert summary["total_actual_energy_kwh"] == round(
            sum(float(row["actual_energy_kwh"] or 0.0) for row in rows),
            4,
        )
        assert summary["total_baseline_energy_kwh"] == round(
            sum(float(row["baseline_energy_kwh"] or 0.0) for row in rows if row["baseline_energy_kwh"] is not None),
            4,
        )
        assert summary["total_hidden_overconsumption_kwh"] == round(
            sum(float(row["hidden_overconsumption_kwh"] or 0.0) for row in rows),
            4,
        )
        assert summary["total_hidden_overconsumption_cost"] == round(
            sum(float(row["hidden_overconsumption_cost"] or 0.0) for row in rows if row["hidden_overconsumption_cost"] is not None),
            2,
        )
