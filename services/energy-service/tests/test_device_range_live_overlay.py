from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVICES_ROOT = ROOT.parent
sys.path = [p for p in sys.path if p not in {str(ROOT), str(SERVICES_ROOT)}]
sys.path.insert(0, str(SERVICES_ROOT))
sys.path.insert(0, str(ROOT))

from app.services.energy_engine import EnergyEngine


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _SessionStub:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, _query):
        return _ScalarResult(self.rows)


@pytest.mark.asyncio
async def test_get_device_range_overlays_current_day_with_live_state(monkeypatch):
    engine = EnergyEngine(_SessionStub([
        SimpleNamespace(
            day=date(2026, 4, 5),
            energy_kwh=0.1661,
            loss_kwh=0.1661,
            idle_kwh=0.0,
            offhours_kwh=0.1661,
            overconsumption_kwh=0.0,
            quality_flags='["counter_missing","fallback_integration"]',
            version=11,
        )
    ]))

    async def fake_allowed(_tenant_id):
        return None

    async def fake_tariff(_tenant_id):
        return {"rate": 0.0, "currency": "INR"}

    async def fake_live(_device_id, _tenant_id):
        return {
            "date": "2026-04-05",
            "energy_kwh": 0.2095,
            "loss_kwh": 0.2095,
            "idle_kwh": 0.0,
            "offhours_kwh": 0.2095,
            "overconsumption_kwh": 0.0,
        }

    class _FrozenDatetime:
        @staticmethod
        def now(tz):
            import datetime as _dt

            return _dt.datetime(2026, 4, 5, 21, 0, 0, tzinfo=tz)

    monkeypatch.setattr(engine, "_get_allowed_device_ids", fake_allowed)
    monkeypatch.setattr("app.services.energy_engine.tariff_cache.get", fake_tariff)
    monkeypatch.setattr(engine, "_fetch_live_current_day_totals", fake_live)
    monkeypatch.setattr("app.services.energy_engine.datetime", _FrozenDatetime)

    result = await engine.get_device_range("SMOKE_A", date(2026, 4, 4), date(2026, 4, 5), tenant_id="tenant-1")

    assert result["totals"]["energy_kwh"] == 0.2095
    assert result["totals"]["loss_kwh"] == 0.2095
    assert result["days"] == [
        {
            "date": "2026-04-05",
            "energy_kwh": 0.2095,
            "energy_cost_inr": 0.0,
            "idle_kwh": 0.0,
            "offhours_kwh": 0.2095,
            "overconsumption_kwh": 0.0,
            "loss_kwh": 0.2095,
            "loss_cost_inr": 0.0,
            "quality_flags": ["live_projection_overlay"],
            "version": 11,
        }
    ]


@pytest.mark.asyncio
async def test_get_device_range_keeps_historical_day_without_live_overlay(monkeypatch):
    engine = EnergyEngine(_SessionStub([
        SimpleNamespace(
            day=date(2026, 4, 4),
            energy_kwh=0.1111,
            loss_kwh=0.1111,
            idle_kwh=0.0,
            offhours_kwh=0.1111,
            overconsumption_kwh=0.0,
            quality_flags='["fallback_integration"]',
            version=7,
        )
    ]))

    async def fake_allowed(_tenant_id):
        return None

    async def fake_tariff(_tenant_id):
        return {"rate": 0.0, "currency": "INR"}

    async def fail_live(*_args, **_kwargs):
        raise AssertionError("live overlay should not be called for historical-only range")

    class _FrozenDatetime:
        @staticmethod
        def now(tz):
            import datetime as _dt

            return _dt.datetime(2026, 4, 5, 21, 0, 0, tzinfo=tz)

    monkeypatch.setattr(engine, "_get_allowed_device_ids", fake_allowed)
    monkeypatch.setattr("app.services.energy_engine.tariff_cache.get", fake_tariff)
    monkeypatch.setattr(engine, "_fetch_live_current_day_totals", fail_live)
    monkeypatch.setattr("app.services.energy_engine.datetime", _FrozenDatetime)

    result = await engine.get_device_range("SMOKE_A", date(2026, 4, 4), date(2026, 4, 4), tenant_id="tenant-1")

    assert result["totals"]["energy_kwh"] == 0.1111
    assert result["totals"]["loss_kwh"] == 0.1111
    assert result["days"][0]["quality_flags"] == ["fallback_integration"]


@pytest.mark.asyncio
async def test_get_monthly_calendar_overlays_current_day_with_live_dashboard_summary(monkeypatch):
    engine = EnergyEngine(_SessionStub([
        SimpleNamespace(day=date(2026, 4, 4), energy_kwh=0.2000, version=2),
        SimpleNamespace(day=date(2026, 4, 5), energy_kwh=0.1400, version=7),
    ]))

    async def fake_allowed(_tenant_id):
        return {"SMOKE_A"}

    async def fake_tariff(_tenant_id):
        return {"rate": 6.0, "currency": "INR"}

    async def fake_widgets(_tenant_id):
        return {
            "month_energy_kwh": 0.35,
            "today_energy_kwh": 0.15,
        }

    class _FrozenDatetime:
        @staticmethod
        def now(tz):
            import datetime as _dt

            return _dt.datetime(2026, 4, 5, 23, 6, 0, tzinfo=tz)

    monkeypatch.setattr(engine, "_get_allowed_device_ids", fake_allowed)
    monkeypatch.setattr("app.services.energy_engine.tariff_cache.get", fake_tariff)
    monkeypatch.setattr(engine, "_fetch_live_dashboard_energy_widgets", fake_widgets)
    monkeypatch.setattr("app.services.energy_engine.datetime", _FrozenDatetime)

    result = await engine.get_monthly_calendar(2026, 4, tenant_id="tenant-1")

    assert result["summary"]["total_energy_kwh"] == 0.35
    assert result["summary"]["total_energy_cost_inr"] == 2.1
    assert result["days"][3] == {
        "date": "2026-04-04",
        "energy_kwh": 0.2,
        "energy_cost_inr": 1.2,
    }
    assert result["days"][4] == {
        "date": "2026-04-05",
        "energy_kwh": 0.15,
        "energy_cost_inr": 0.9,
    }


@pytest.mark.asyncio
async def test_get_monthly_calendar_keeps_historical_month_without_live_overlay(monkeypatch):
    engine = EnergyEngine(_SessionStub([
        SimpleNamespace(day=date(2026, 3, 31), energy_kwh=0.1200, version=3),
    ]))

    async def fake_allowed(_tenant_id):
        return {"SMOKE_A"}

    async def fake_tariff(_tenant_id):
        return {"rate": 6.0, "currency": "INR"}

    async def fail_widgets(*_args, **_kwargs):
        raise AssertionError("dashboard live overlay should not be called for historical month")

    class _FrozenDatetime:
        @staticmethod
        def now(tz):
            import datetime as _dt

            return _dt.datetime(2026, 4, 5, 23, 6, 0, tzinfo=tz)

    monkeypatch.setattr(engine, "_get_allowed_device_ids", fake_allowed)
    monkeypatch.setattr("app.services.energy_engine.tariff_cache.get", fake_tariff)
    monkeypatch.setattr(engine, "_fetch_live_dashboard_energy_widgets", fail_widgets)
    monkeypatch.setattr("app.services.energy_engine.datetime", _FrozenDatetime)

    result = await engine.get_monthly_calendar(2026, 3, tenant_id="tenant-1")

    assert result["summary"]["total_energy_kwh"] == 0.12
    assert result["summary"]["total_energy_cost_inr"] == 0.72
    assert result["days"][30] == {
        "date": "2026-03-31",
        "energy_kwh": 0.12,
        "energy_cost_inr": 0.72,
    }


@pytest.mark.asyncio
async def test_get_summary_overlays_tenant_live_dashboard_widgets(monkeypatch):
    engine = EnergyEngine(_SessionStub([
        SimpleNamespace(day=date(2026, 4, 5), energy_kwh=0.41, loss_kwh=0.29, version=3),
        SimpleNamespace(month=date(2026, 4, 1), energy_kwh=0.41, loss_kwh=0.29, version=4),
    ]))

    call_count = {"value": 0}

    async def fake_allowed(_tenant_id):
        return {"SMOKE_A"}

    async def fake_tariff(_tenant_id):
        return {"rate": 10.0, "currency": "INR"}

    async def fake_widgets(_tenant_id):
        return {
            "month_energy_kwh": 0.4667,
            "today_energy_kwh": 0.4667,
            "today_loss_kwh": 0.3667,
        }

    class _SummarySessionStub:
        async def execute(self, _query):
            call_count["value"] += 1
            if call_count["value"] == 1:
                return _ScalarResult([SimpleNamespace(energy_kwh=0.41, loss_kwh=0.29, version=3)])
            return _ScalarResult([SimpleNamespace(energy_kwh=0.41, loss_kwh=0.29, version=4)])

    engine = EnergyEngine(_SummarySessionStub())
    monkeypatch.setattr(engine, "_get_allowed_device_ids", fake_allowed)
    monkeypatch.setattr("app.services.energy_engine.tariff_cache.get", fake_tariff)
    monkeypatch.setattr(engine, "_fetch_live_dashboard_energy_widgets", fake_widgets)

    result = await engine.get_summary(tenant_id="tenant-1")

    assert result["energy_widgets"]["today_energy_kwh"] == 0.4667
    assert result["energy_widgets"]["today_loss_kwh"] == 0.3667
    assert result["energy_widgets"]["month_energy_kwh"] == 0.4667
    assert result["energy_widgets"]["today_energy_cost_inr"] == 4.667
    assert result["energy_widgets"]["today_loss_cost_inr"] == 3.667
    assert result["energy_widgets"]["month_energy_cost_inr"] == 4.667


@pytest.mark.asyncio
async def test_get_today_loss_breakdown_overlays_current_day_live_totals(monkeypatch):
    engine = EnergyEngine(_SessionStub([
        SimpleNamespace(
            device_id="SMOKE_A",
            day=date(2026, 4, 5),
            energy_kwh=0.10,
            loss_kwh=0.08,
            idle_kwh=0.01,
            offhours_kwh=0.07,
            overconsumption_kwh=0.0,
            version=2,
        ),
        SimpleNamespace(
            device_id="SMOKE_B",
            day=date(2026, 4, 5),
            energy_kwh=0.20,
            loss_kwh=0.18,
            idle_kwh=0.02,
            offhours_kwh=0.16,
            overconsumption_kwh=0.0,
            version=3,
        ),
    ]))

    async def fake_allowed(_tenant_id):
        return {"SMOKE_A", "SMOKE_B"}

    async def fake_tariff(_tenant_id):
        return {"rate": 10.0, "currency": "INR"}

    async def fake_live(device_id, _tenant_id):
        if device_id == "SMOKE_A":
            return {
                "date": "2026-04-05",
                "energy_kwh": 0.1667,
                "loss_kwh": 0.1667,
                "idle_kwh": 0.0,
                "offhours_kwh": 0.1667,
                "overconsumption_kwh": 0.0,
            }
        return {
            "date": "2026-04-05",
            "energy_kwh": 0.1,
            "loss_kwh": 0.1,
            "idle_kwh": 0.0,
            "offhours_kwh": 0.1,
            "overconsumption_kwh": 0.0,
        }

    async def fake_meta(device_id, tenant_id):
        return {"device_name": device_id}

    class _FrozenDatetime:
        @staticmethod
        def now(tz):
            import datetime as _dt

            return _dt.datetime(2026, 4, 5, 23, 6, 0, tzinfo=tz)

    monkeypatch.setattr(engine, "_get_allowed_device_ids", fake_allowed)
    monkeypatch.setattr("app.services.energy_engine.tariff_cache.get", fake_tariff)
    monkeypatch.setattr(engine, "_fetch_live_current_day_totals", fake_live)
    monkeypatch.setattr("app.services.energy_engine.meta_cache.get", fake_meta)
    monkeypatch.setattr("app.services.energy_engine.datetime", _FrozenDatetime)

    result = await engine.get_today_loss_breakdown(tenant_id="tenant-1")

    assert result["totals"]["today_energy_kwh"] == 0.2667
    assert result["totals"]["total_loss_kwh"] == 0.2667
    assert result["totals"]["today_energy_cost_inr"] == 2.667
    assert result["totals"]["total_loss_cost_inr"] == 2.667
    assert result["rows"] == [
        {
            "device_id": "SMOKE_A",
            "device_name": "SMOKE_A",
            "idle_kwh": 0.0,
            "idle_cost_inr": 0.0,
            "off_hours_kwh": 0.1667,
            "off_hours_cost_inr": 1.667,
            "overconsumption_kwh": 0.0,
            "overconsumption_cost_inr": 0.0,
            "total_loss_kwh": 0.1667,
            "total_loss_cost_inr": 1.667,
            "status": "computed",
            "reason": "live_projection_overlay",
        },
        {
            "device_id": "SMOKE_B",
            "device_name": "SMOKE_B",
            "idle_kwh": 0.0,
            "idle_cost_inr": 0.0,
            "off_hours_kwh": 0.1,
            "off_hours_cost_inr": 1.0,
            "overconsumption_kwh": 0.0,
            "overconsumption_cost_inr": 0.0,
            "total_loss_kwh": 0.1,
            "total_loss_cost_inr": 1.0,
            "status": "computed",
            "reason": "live_projection_overlay",
        },
    ]
