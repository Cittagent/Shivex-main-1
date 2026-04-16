from datetime import datetime, timedelta, timezone

from src.services.telemetry_normalizer import extract_current, extract_voltage
from src.services.waste_engine import compute_device_waste, summarize_insights


def _rows(count: int = 5):
    start = datetime(2026, 3, 13, 0, 0, tzinfo=timezone.utc)
    out = []
    for i in range(count):
        out.append(
            {
                "timestamp": start + timedelta(minutes=i),
                "power": 1000.0,
                "current": 6.0,
                "voltage": 230.0,
            }
        )
    return out


def test_unoccupied_is_disabled_by_policy():
    res = compute_device_waste(
        device_id="D1",
        device_name="Device 1",
        data_source_type="metered",
        rows=_rows(),
        threshold=2.0,
        overconsumption_threshold=5.0,
        tariff_rate=8.5,
        shifts=[{"day_of_week": 4, "shift_start": "08:00", "shift_end": "18:00"}],
    )

    assert res.unoccupied_duration_sec is None
    assert res.unoccupied_energy_kwh is None
    assert res.unoccupied_cost is None
    assert res.unoccupied_skipped_reason == "Disabled by policy"
    assert res.unoccupied_pf_estimated is False


def test_power_watts_not_inflated_for_offhours():
    rows = [
        {
            "timestamp": datetime(2026, 3, 13, 0, 0, tzinfo=timezone.utc),
            "power": 250.0,  # watts
            "current": 6.0,
            "voltage": 230.0,
        },
        {
            "timestamp": datetime(2026, 3, 13, 0, 1, tzinfo=timezone.utc),
            "power": 250.0,
            "current": 6.0,
            "voltage": 230.0,
        },
        {
            "timestamp": datetime(2026, 3, 13, 0, 2, tzinfo=timezone.utc),
            "power": 250.0,
            "current": 6.0,
            "voltage": 230.0,
        },
    ]
    res = compute_device_waste(
        device_id="D2",
        device_name="Device 2",
        data_source_type="metered",
        rows=rows,
        threshold=2.0,
        overconsumption_threshold=10.0,
        tariff_rate=8.5,
        shifts=[{"day_of_week": 4, "shift_start": "08:00", "shift_end": "18:00"}],
    )
    assert res.total_energy_kwh < 0.02
    assert res.offhours_energy_kwh is not None and res.offhours_energy_kwh < 0.02
    assert res.total_cost is not None and res.offhours_cost is not None
    assert res.offhours_cost <= res.total_cost + 0.01


def test_outside_shift_low_current_is_classified_as_offhours_not_idle():
    rows = [
        {
            "timestamp": datetime(2026, 3, 13, 0, 0, tzinfo=timezone.utc),
            "power": 160.0,
            "current": 0.7,
            "voltage": 230.0,
        },
        {
            "timestamp": datetime(2026, 3, 13, 0, 10, tzinfo=timezone.utc),
            "power": 160.0,
            "current": 0.7,
            "voltage": 230.0,
        },
    ]
    res = compute_device_waste(
        device_id="D3",
        device_name="Device 3",
        data_source_type="metered",
        rows=rows,
        threshold=1.0,
        overconsumption_threshold=10.0,
        tariff_rate=8.5,
        shifts=[{"day_of_week": 4, "shift_start": "08:00", "shift_end": "18:00"}],
    )
    assert res.idle_energy_kwh == 0.0
    assert res.idle_duration_sec == 0
    assert res.offhours_energy_kwh is not None and res.offhours_energy_kwh > 0
    assert res.offhours_duration_sec is not None and res.offhours_duration_sec > 0


def test_no_shift_configuration_treats_running_intervals_as_offhours_consistently():
    rows = [
        {
            "timestamp": datetime(2026, 3, 13, 0, 0, tzinfo=timezone.utc),
            "power": 160.0,
            "current": 0.7,
            "voltage": 230.0,
        },
        {
            "timestamp": datetime(2026, 3, 13, 0, 10, tzinfo=timezone.utc),
            "power": 160.0,
            "current": 0.7,
            "voltage": 230.0,
        },
    ]
    res = compute_device_waste(
        device_id="D4",
        device_name="Device 4",
        data_source_type="metered",
        rows=rows,
        threshold=1.0,
        overconsumption_threshold=10.0,
        tariff_rate=8.5,
        shifts=[],
    )

    assert res.offhours_skipped_reason is None
    assert res.offhours_energy_kwh is not None and res.offhours_energy_kwh > 0
    assert res.offhours_duration_sec is not None and res.offhours_duration_sec > 0
    assert res.idle_energy_kwh == 0.0
    assert res.standby_energy_kwh == 0.0


def test_fla_threshold_metadata_is_reported_from_device_service_contract():
    rows = [
        {
            "timestamp": datetime(2026, 3, 13, 9, 0, tzinfo=timezone.utc),
            "power": 5000.0,
            "current": 12.0,
            "voltage": 230.0,
        },
        {
            "timestamp": datetime(2026, 3, 13, 9, 10, tzinfo=timezone.utc),
            "power": 5200.0,
            "current": 12.0,
            "voltage": 230.0,
        },
    ]
    res = compute_device_waste(
        device_id="D5",
        device_name="Device 5",
        data_source_type="metered",
        rows=rows,
        threshold=2.5,
        overconsumption_threshold=10.0,
        tariff_rate=8.5,
        shifts=[{"day_of_week": 4, "shift_start": "08:00", "shift_end": "18:00"}],
        threshold_config={
            "full_load_current_a": 10.0,
            "idle_threshold_pct_of_fla": 0.25,
        },
    )

    assert res.overconsumption_config_source == "device_service_derived"
    assert res.overconsumption_config_used == {
        "full_load_current_a": 10.0,
        "idle_threshold_pct_of_fla": 0.25,
        "derived_idle_threshold_a": 2.5,
        "derived_overconsumption_threshold_a": 10.0,
    }


def test_overconsumption_uses_measured_interval_energy_ratio():
    rows = [
        {
            "timestamp": datetime(2026, 3, 13, 9, 0, tzinfo=timezone.utc),
            "energy_kwh": 100.0,
            "current": 25.0,
            "voltage": 230.0,
        },
        {
            "timestamp": datetime(2026, 3, 13, 9, 1, tzinfo=timezone.utc),
            "energy_kwh": 100.2,
            "current": 25.0,
            "voltage": 230.0,
        },
    ]
    res = compute_device_waste(
        device_id="D6",
        device_name="Device 6",
        data_source_type="metered",
        rows=rows,
        threshold=5.0,
        overconsumption_threshold=20.0,
        tariff_rate=8.5,
        shifts=[{"shift_start": "08:00", "shift_end": "18:00"}],
        threshold_config={
            "full_load_current_a": 20.0,
            "idle_threshold_pct_of_fla": 0.25,
        },
    )

    assert res.idle_energy_kwh == 0.0
    assert res.offhours_energy_kwh == 0.0
    assert res.overconsumption_energy_kwh == 0.04


def test_waste_normalizer_does_not_use_phase_diagnostics_as_business_current_voltage():
    row = {
        "timestamp": datetime(2026, 3, 13, 0, 0, tzinfo=timezone.utc),
        "current_l1": 100.0,
        "current_l2": 101.0,
        "current_l3": 102.0,
        "voltage_l1": 230.0,
        "voltage_l2": 231.0,
        "voltage_l3": 229.0,
    }

    assert extract_current(row) == (None, None)
    assert extract_voltage(row) == (None, None)


def test_waste_normalizer_keeps_authoritative_aggregate_over_phase_diagnostics():
    row = {
        "timestamp": datetime(2026, 3, 13, 0, 0, tzinfo=timezone.utc),
        "current": 10.0,
        "voltage": 230.0,
        "current_l1": 1000.0,
        "voltage_l1": 9999.0,
    }

    assert extract_current(row) == (10.0, "current")
    assert extract_voltage(row) == (230.0, "voltage")


def test_summarize_insights_excludes_standby_based_messages():
    rows = [
        {
            "timestamp": datetime(2026, 3, 13, 0, 0, tzinfo=timezone.utc),
            "power": 200.0,
            "current": 2.0,
            "voltage": 230.0,
        },
        {
            "timestamp": datetime(2026, 3, 13, 0, 30, tzinfo=timezone.utc),
            "power": 200.0,
            "current": 2.0,
            "voltage": 230.0,
        },
    ]
    result = compute_device_waste(
        device_id="D7",
        device_name="Device 7",
        data_source_type="metered",
        rows=rows,
        threshold=3.0,
        overconsumption_threshold=10.0,
        tariff_rate=8.5,
        shifts=[{"day_of_week": 4, "shift_start": "08:00", "shift_end": "18:00"}],
    )
    insights = summarize_insights([result], "INR")
    joined = " | ".join(insights).lower()
    assert "standby" not in joined
    assert "highest standby consumers" not in joined
