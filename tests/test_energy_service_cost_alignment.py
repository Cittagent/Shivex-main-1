from __future__ import annotations

import asyncio
import sys
from datetime import date
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "energy-service"
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from app.services.energy_engine import EnergyEngine
from app.services import energy_engine as energy_engine_module
from app.services import tariff_cache as energy_tariff_cache
from services.shared.telemetry_normalization import normalize_telemetry_sample


class _RowsResult:
    def __init__(self, rows: list[object]):
        self._rows = rows

    def scalars(self) -> "_RowsResult":
        return self

    def all(self) -> list[object]:
        return list(self._rows)


class _QueuedSession:
    def __init__(self, results: list[list[object]]):
        self._results = results

    async def execute(self, _query):  # noqa: ANN001
        if not self._results:
            raise AssertionError("Unexpected extra query")
        return _RowsResult(self._results.pop(0))


@pytest.fixture(autouse=True)
def clear_tariff_cache():
    energy_tariff_cache.tariff_cache._snapshot = {None: {"rate": 0.0, "currency": "INR", "configured": False}}
    energy_tariff_cache.tariff_cache._expires_at.clear()
    yield


def _row(**values: object) -> object:
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_energy_summary_recomputes_costs_from_tenant_tariff(monkeypatch):
    session = _QueuedSession(
        [
            [
                _row(device_id="DEV-1", energy_kwh=4.0, loss_kwh=1.0, version=2),
            ],
            [
                _row(device_id="DEV-1", energy_kwh=10.0, loss_kwh=2.0, version=3),
            ],
        ]
    )

    async def fake_allowed_ids(self, tenant_id):  # noqa: ANN001
        return {"DEV-1"}

    async def fake_tariff_get(tenant_id=None):  # noqa: ANN001
        return {"rate": 3.0, "currency": "INR", "configured": True, "source": "tenant_tariffs"}

    monkeypatch.setattr(EnergyEngine, "_get_allowed_device_ids", fake_allowed_ids)
    monkeypatch.setattr(energy_tariff_cache.tariff_cache, "get", fake_tariff_get)

    payload = await EnergyEngine(session).get_summary(tenant_id="TENANT-1")

    widgets = payload["energy_widgets"]
    assert widgets["today_energy_kwh"] == 4.0
    assert widgets["today_energy_cost_inr"] == 12.0
    assert widgets["today_loss_kwh"] == 1.0
    assert widgets["today_loss_cost_inr"] == 3.0
    assert widgets["month_energy_kwh"] == 10.0
    assert widgets["month_energy_cost_inr"] == 30.0
    assert widgets["currency"] == "INR"


@pytest.mark.asyncio
async def test_today_loss_breakdown_recomputes_costs_from_tenant_tariff(monkeypatch):
    session = _QueuedSession(
        [
            [
                _row(
                    device_id="DEV-1",
                    idle_kwh=0.5,
                    offhours_kwh=0.2,
                    overconsumption_kwh=0.3,
                    loss_kwh=1.0,
                    energy_kwh=2.0,
                    energy_cost_inr=0.25,
                    loss_cost_inr=0.25,
                    version=5,
                ),
            ]
        ]
    )

    async def fake_allowed_ids(self, tenant_id):  # noqa: ANN001
        return {"DEV-1"}

    async def fake_meta_get(device_id, tenant_id=None):  # noqa: ANN001
        return {"device_name": "COMPRESSOR"}

    async def fake_tariff_get(tenant_id=None):  # noqa: ANN001
        return {"rate": 5.0, "currency": "INR", "configured": True, "source": "tenant_tariffs"}

    monkeypatch.setattr(EnergyEngine, "_get_allowed_device_ids", fake_allowed_ids)
    monkeypatch.setattr(energy_tariff_cache.tariff_cache, "get", fake_tariff_get)
    monkeypatch.setattr(energy_engine_module.meta_cache, "get", fake_meta_get)

    payload = await EnergyEngine(session).get_today_loss_breakdown(tenant_id="TENANT-1")

    totals = payload["totals"]
    assert totals["idle_kwh"] == 0.5
    assert totals["idle_cost_inr"] == 2.5
    assert totals["off_hours_cost_inr"] == 1.0
    assert totals["overconsumption_cost_inr"] == 1.5
    assert totals["total_loss_cost_inr"] == 5.0
    assert totals["today_energy_cost_inr"] == 10.0
    assert payload["rows"][0]["idle_cost_inr"] == 2.5
    assert payload["rows"][0]["total_loss_cost_inr"] == 5.0


@pytest.mark.asyncio
async def test_compute_delta_counts_outside_shift_running_as_offhours(monkeypatch):
    engine = EnergyEngine(_QueuedSession([]))

    monkeypatch.setattr(energy_engine_module, "_get_platform_tz", lambda: ZoneInfo("Asia/Kolkata"))

    previous_sample = normalize_telemetry_sample(
        {
            "timestamp": "2026-04-01T14:29:00Z",
            "energy_kwh": 10.0,
            "current": 0.7,
            "voltage": 230.0,
            "active_power_kw": 1.0,
        },
        {},
    )
    current_sample = normalize_telemetry_sample(
        {
            "timestamp": "2026-04-01T14:30:00Z",
            "energy_kwh": 10.02,
            "current": 0.7,
            "voltage": 230.0,
            "active_power_kw": 1.0,
        },
        {},
    )

    delta = engine._compute_delta(
        ts=datetime(2026, 4, 1, 14, 30, tzinfo=timezone.utc),
        state=SimpleNamespace(version=1),
        previous_sample=previous_sample,
        current_sample=current_sample,
        idle_threshold=1.0,
        over_threshold=None,
        shifts=[{"day_of_week": 2, "shift_start": "09:00", "shift_end": "17:00", "is_active": True}],
    )

    assert delta.idle_kwh == 0.0
    assert delta.offhours_kwh > 0
    assert delta.loss_kwh == delta.offhours_kwh
    assert delta.energy_kwh == pytest.approx(0.02, abs=1e-6)


@pytest.mark.asyncio
async def test_monthly_calendar_recomputes_costs_from_tenant_tariff(monkeypatch):
    session = _QueuedSession(
        [
            [
                _row(device_id="DEV-1", day=date(2026, 3, 1), energy_kwh=1.5, version=1),
                _row(device_id="DEV-1", day=date(2026, 3, 2), energy_kwh=2.0, version=2),
            ]
        ]
    )

    async def fake_allowed_ids(self, tenant_id):  # noqa: ANN001
        return {"DEV-1"}

    async def fake_tariff_get(tenant_id=None):  # noqa: ANN001
        return {"rate": 4.0, "currency": "INR", "configured": True, "source": "tenant_tariffs"}

    monkeypatch.setattr(EnergyEngine, "_get_allowed_device_ids", fake_allowed_ids)
    monkeypatch.setattr(energy_tariff_cache.tariff_cache, "get", fake_tariff_get)

    payload = await EnergyEngine(session).get_monthly_calendar(2026, 3, tenant_id="TENANT-1")

    assert payload["summary"]["total_energy_kwh"] == 3.5
    assert payload["summary"]["total_energy_cost_inr"] == 14.0
    assert payload["days"][0]["energy_cost_inr"] == 6.0
    assert payload["days"][1]["energy_cost_inr"] == 8.0
