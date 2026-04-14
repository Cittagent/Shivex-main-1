from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import os
import sys

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

BASE_DIR = Path(__file__).resolve().parents[1]
SERVICES_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
for path in (BASE_DIR, SERVICES_DIR, PROJECT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

os.environ.setdefault("DATABASE_URL", "mysql+aiomysql://test:test@127.0.0.1:3306/test_db")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

from app.database import Base
from app.models.device import Device, DeviceLiveState, TELEMETRY_TIMEOUT_SECONDS
from app.services.dashboard import DashboardService
from app.services.idle_running import IdleRunningService
from app.services.live_dashboard import LiveDashboardService
from app.services.live_projection import LiveProjectionService
from services.shared.tenant_context import TenantContext


def _tenant_ctx(tenant_id: str = "ORG-1") -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        user_id="tester",
        role="system",
        plant_ids=[],
        is_super_admin=False,
    )


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _seed_running_idle_device(
    session,
    *,
    device_id: str = "DEVICE-1",
    tenant_id: str = "ORG-1",
    first_telemetry_timestamp: datetime | None = None,
) -> datetime:
    now = datetime.now(timezone.utc)
    session.add(
        Device(
            device_id=device_id,
            tenant_id=tenant_id,
            device_name="Machine 1",
            device_type="compressor",
            location="Plant 1",
            idle_current_threshold=5.0,
            last_seen_timestamp=now,
            first_telemetry_timestamp=first_telemetry_timestamp or (now - timedelta(minutes=5)),
        )
    )
    session.add(
        DeviceLiveState(
            device_id=device_id,
            tenant_id=tenant_id,
            runtime_status="running",
            load_state="idle",
            last_telemetry_ts=now,
            last_sample_ts=now,
            last_current_a=1.25,
            last_voltage_v=230.0,
            version=7,
        )
    )
    await session.commit()
    return now


@pytest.mark.asyncio
async def test_current_state_uses_projected_idle_state_when_latest_raw_telemetry_is_incomplete(session_factory, monkeypatch):
    async with session_factory() as session:
        now = await _seed_running_idle_device(session)

        async def fake_fetch_telemetry(self, device_id: str, **kwargs):
            return [{"timestamp": now.isoformat(), "power": 250.0}]

        monkeypatch.setattr(IdleRunningService, "_fetch_telemetry", fake_fetch_telemetry)

        service = IdleRunningService(session, _tenant_ctx())
        state = await service.get_current_state("DEVICE-1", "ORG-1")

        assert state["state"] == "idle"
        assert state["current"] == pytest.approx(1.25)
        assert state["voltage"] == pytest.approx(230.0)
        assert state["current_field"] is None
        assert state["voltage_field"] is None


@pytest.mark.asyncio
async def test_current_state_returns_unknown_when_authoritative_live_projection_is_stale(session_factory, monkeypatch):
    async with session_factory() as session:
        now = await _seed_running_idle_device(session)
        stale_at = now - timedelta(seconds=TELEMETRY_TIMEOUT_SECONDS + 5)
        live_state = await session.get(DeviceLiveState, {"device_id": "DEVICE-1", "tenant_id": "ORG-1"})
        assert live_state is not None
        live_state.last_telemetry_ts = stale_at
        live_state.last_sample_ts = stale_at
        await session.commit()

        async def fake_fetch_telemetry(self, device_id: str, **kwargs):
            return [{"timestamp": stale_at.isoformat(), "power": 250.0}]

        monkeypatch.setattr(IdleRunningService, "_fetch_telemetry", fake_fetch_telemetry)

        service = IdleRunningService(session, _tenant_ctx())
        state = await service.get_current_state("DEVICE-1", "ORG-1")

        assert state["state"] == "unknown"
        assert state["current"] == pytest.approx(1.25)
        assert state["voltage"] == pytest.approx(230.0)


@pytest.mark.asyncio
async def test_dashboard_bootstrap_uses_authoritative_live_projection_for_current_state(session_factory, monkeypatch):
    async with session_factory() as session:
        now = await _seed_running_idle_device(session)

        async def fake_fetch_telemetry(self, device_id: str, **kwargs):
            return [{"timestamp": now.isoformat(), "power": 250.0}]

        async def fake_http_get_json(self, service_key: str, url: str, params=None, tenant_id=None):
            return {
                "data": {
                    "items": [{"timestamp": now.isoformat(), "power": 250.0}],
                }
            }, None

        async def fake_idle_stats(self, device_id: str, tenant_id: str):
            return {
                "device_id": device_id,
                "today": {"idle_minutes": 12},
                "month": {"idle_minutes": 40},
                "tariff_configured": False,
                "pf_estimated": False,
                "threshold_configured": True,
                "idle_current_threshold": 5.0,
                "data_source_type": "metered",
            }

        monkeypatch.setattr(IdleRunningService, "_fetch_telemetry", fake_fetch_telemetry)
        monkeypatch.setattr(IdleRunningService, "get_idle_stats", fake_idle_stats)
        monkeypatch.setattr(DashboardService, "_http_get_json", fake_http_get_json)

        payload = await DashboardService(session, _tenant_ctx()).get_dashboard_bootstrap("DEVICE-1", "ORG-1")

        assert payload["version"] == 7
        assert payload["current_state"]["state"] == "idle"
        assert payload["current_state"]["current"] == pytest.approx(1.25)
        assert payload["current_state"]["voltage"] == pytest.approx(230.0)
        assert payload["device"].first_telemetry_timestamp is not None


@pytest.mark.asyncio
async def test_materialized_fleet_snapshot_uses_live_projection_load_state(session_factory):
    async with session_factory() as session:
        now = await _seed_running_idle_device(session)

        payload = await DashboardService(session, _tenant_ctx())._build_fleet_state_snapshot()

        assert payload["devices"][0]["device_id"] == "DEVICE-1"
        assert payload["devices"][0]["runtime_status"] == "running"
        assert payload["devices"][0]["load_state"] == "idle"
        assert payload["devices"][0]["first_telemetry_timestamp"] is not None
        assert payload["devices"][0]["last_seen_timestamp"].startswith(now.replace(tzinfo=None).isoformat())


@pytest.mark.asyncio
async def test_materialized_fleet_snapshot_marks_stale_projection_stopped(session_factory):
    async with session_factory() as session:
        now = await _seed_running_idle_device(session)
        stale_at = now - timedelta(seconds=TELEMETRY_TIMEOUT_SECONDS + 5)
        live_state = await session.get(DeviceLiveState, {"device_id": "DEVICE-1", "tenant_id": "ORG-1"})
        assert live_state is not None
        live_state.last_telemetry_ts = stale_at
        live_state.last_sample_ts = stale_at
        live_state.runtime_status = "running"
        live_state.load_state = "idle"
        await session.commit()

        payload = await DashboardService(session, _tenant_ctx())._build_fleet_state_snapshot()

        assert payload["devices"][0]["runtime_status"] == "stopped"
        assert payload["devices"][0]["load_state"] == "unknown"
        assert payload["devices"][0]["first_telemetry_timestamp"] is not None


@pytest.mark.asyncio
async def test_live_dashboard_snapshot_marks_stale_projection_stopped(session_factory):
    async with session_factory() as session:
        now = await _seed_running_idle_device(session)
        stale_at = now - timedelta(seconds=TELEMETRY_TIMEOUT_SECONDS + 5)
        live_state = await session.get(DeviceLiveState, {"device_id": "DEVICE-1", "tenant_id": "ORG-1"})
        assert live_state is not None
        live_state.last_telemetry_ts = stale_at
        live_state.last_sample_ts = stale_at
        live_state.runtime_status = "running"
        live_state.load_state = "idle"
        await session.commit()

        payload = await LiveDashboardService(session, _tenant_ctx()).get_fleet_snapshot(tenant_id="ORG-1")

        assert payload["devices"][0]["runtime_status"] == "stopped"
        assert payload["devices"][0]["load_state"] == "unknown"
        assert payload["devices"][0]["first_telemetry_timestamp"] is not None


@pytest.mark.asyncio
async def test_live_projection_snapshot_item_marks_stale_projection_stopped(session_factory):
    async with session_factory() as session:
        now = await _seed_running_idle_device(session)
        stale_at = now - timedelta(seconds=TELEMETRY_TIMEOUT_SECONDS + 5)
        live_state = await session.get(DeviceLiveState, {"device_id": "DEVICE-1", "tenant_id": "ORG-1"})
        assert live_state is not None
        live_state.last_telemetry_ts = stale_at
        live_state.last_sample_ts = stale_at
        live_state.runtime_status = "running"
        live_state.load_state = "idle"
        await session.commit()

        payload = await LiveProjectionService(session, _tenant_ctx()).get_device_snapshot_item("DEVICE-1", "ORG-1")

        assert payload["runtime_status"] == "stopped"
        assert payload["load_state"] == "unknown"
        assert payload["first_telemetry_timestamp"] is not None
