from __future__ import annotations

import os
import sys
from datetime import datetime, time, timezone
from pathlib import Path
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

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

os.environ["DATABASE_URL"] = "mysql+aiomysql://test:test@127.0.0.1:3306/test_db"

from app.database import Base
from app.models.device import Device, DeviceLiveState, DeviceShift
from app.services.idle_running import TariffCache
from app.services.live_dashboard import LiveDashboardService
from services.shared.tenant_context import TenantContext


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


@pytest.mark.asyncio
async def test_live_dashboard_summary_is_tenant_scoped_without_loading_full_fleet_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    session_factory,
):
    local_day = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Kolkata")).date()
    async with session_factory() as session:
        session.add_all(
            [
                Device(
                    device_id="SHARED-DEVICE-A",
                    tenant_id="TENANT-A",
                    plant_id="PLANT-1",
                    device_name="Shared A",
                    device_type="compressor",
                    data_source_type="metered",
                ),
                Device(
                    device_id="SHARED-DEVICE-B",
                    tenant_id="TENANT-B",
                    plant_id="PLANT-1",
                    device_name="Shared B",
                    device_type="compressor",
                    data_source_type="metered",
                ),
                DeviceLiveState(
                    device_id="SHARED-DEVICE-A",
                    tenant_id="TENANT-A",
                    runtime_status="running",
                    load_state="running",
                    health_score=82.5,
                    uptime_percentage=94.0,
                    day_bucket=local_day,
                    today_energy_kwh=14.5,
                    today_loss_kwh=1.5,
                    month_energy_kwh=70.0,
                    last_telemetry_ts=datetime.now(timezone.utc),
                ),
                DeviceLiveState(
                    device_id="SHARED-DEVICE-B",
                    tenant_id="TENANT-B",
                    runtime_status="stopped",
                    health_score=41.0,
                    uptime_percentage=52.0,
                    day_bucket=local_day,
                    today_energy_kwh=9.0,
                    today_loss_kwh=0.5,
                    month_energy_kwh=33.0,
                ),
                DeviceShift(
                    device_id="SHARED-DEVICE-A",
                    tenant_id="TENANT-A",
                    shift_name="A",
                    shift_start=time(8, 0),
                    shift_end=time(16, 0),
                    maintenance_break_minutes=30,
                    is_active=True,
                ),
            ]
        )
        await session.commit()

        monkeypatch.setattr(
            LiveDashboardService,
            "get_fleet_snapshot",
            AsyncMock(side_effect=AssertionError("summary should not load full fleet snapshot")),
        )
        monkeypatch.setattr(
            LiveDashboardService,
            "_fetch_energy_json",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(
            TariffCache,
            "get",
            AsyncMock(return_value={"configured": True, "rate": 10.0, "currency": "INR"}),
        )

        payload = await LiveDashboardService(session).get_dashboard_summary(tenant_id="TENANT-A")

    assert payload["summary"]["total_devices"] == 1
    assert payload["summary"]["running_devices"] == 1
    assert payload["summary"]["stopped_devices"] == 0
    assert payload["summary"]["idle_devices"] == 0
    assert payload["summary"]["in_load_devices"] == 1
    assert payload["summary"]["overconsumption_devices"] == 0
    assert payload["summary"]["unknown_devices"] == 0
    assert payload["summary"]["status_counts"] == {
        "unknown": 0,
        "stopped": 0,
        "idle": 0,
        "running": 1,
        "overconsumption": 0,
    }
    assert payload["summary"]["devices_with_health_data"] == 1
    assert payload["summary"]["devices_with_uptime_configured"] == 1
    assert payload["summary"]["devices_missing_uptime_config"] == 0
    assert payload["summary"]["system_health"] == 82.5
    assert payload["summary"]["average_efficiency"] == 94.0
    assert payload["devices"] == []
    assert payload["energy_widgets"]["today_energy_kwh"] == 14.5
    assert payload["energy_widgets"]["today_loss_kwh"] == 1.5
    assert payload["energy_widgets"]["month_energy_kwh"] == 70.0
    assert payload["energy_widgets"]["today_loss_cost_inr"] == 15.0


@pytest.mark.asyncio
async def test_dashboard_summary_uses_live_loss_totals_even_when_energy_service_loss_lags(
    monkeypatch: pytest.MonkeyPatch,
    session_factory,
):
    local_day = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Kolkata")).date()
    async with session_factory() as session:
        session.add_all(
            [
                Device(
                    device_id="LOSS-DEVICE",
                    tenant_id="TENANT-A",
                    plant_id="PLANT-1",
                    device_name="Loss A",
                    device_type="compressor",
                    data_source_type="metered",
                ),
                DeviceLiveState(
                    device_id="LOSS-DEVICE",
                    tenant_id="TENANT-A",
                    runtime_status="running",
                    load_state="overconsumption",
                    health_score=80.0,
                    uptime_percentage=90.0,
                    day_bucket=local_day,
                    month_bucket=local_day.replace(day=1),
                    today_energy_kwh=12.0,
                    month_energy_kwh=80.0,
                    today_idle_kwh=0.4,
                    today_offhours_kwh=0.3,
                    today_overconsumption_kwh=0.8,
                    today_loss_kwh=1.5,
                    last_telemetry_ts=datetime.now(timezone.utc),
                ),
            ]
        )
        await session.commit()

        monkeypatch.setattr(
            LiveDashboardService,
            "_fetch_energy_json",
            AsyncMock(
                return_value={
                    "success": True,
                    "energy_widgets": {
                        "month_energy_kwh": 70.0,
                        "today_energy_kwh": 9.0,
                        "today_loss_kwh": 0.1,
                        "month_energy_cost_inr": 700.0,
                        "today_energy_cost_inr": 90.0,
                        "today_loss_cost_inr": 1.0,
                        "currency": "INR",
                    },
                }
            ),
        )
        monkeypatch.setattr(
            TariffCache,
            "get",
            AsyncMock(return_value={"configured": True, "rate": 10.0, "currency": "INR"}),
        )

        payload = await LiveDashboardService(session).get_dashboard_summary(tenant_id="TENANT-A")

    assert payload["energy_widgets"]["today_energy_kwh"] == 12.0
    assert payload["energy_widgets"]["today_energy_cost_inr"] == 120.0
    assert payload["energy_widgets"]["today_loss_kwh"] == 1.5
    assert payload["energy_widgets"]["today_loss_cost_inr"] == 15.0
    assert payload["energy_widgets"]["month_energy_kwh"] == 80.0
    assert payload["energy_widgets"]["month_energy_cost_inr"] == 800.0
    assert payload["summary"]["status_counts"]["overconsumption"] == 1
    assert payload["summary"]["overconsumption_devices"] == 1


@pytest.mark.asyncio
async def test_dashboard_summary_uses_live_month_energy_when_energy_service_month_lags(
    monkeypatch: pytest.MonkeyPatch,
    session_factory,
):
    local_day = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Kolkata")).date()
    month_bucket = local_day.replace(day=1)
    async with session_factory() as session:
        session.add_all(
            [
                Device(
                    device_id="MONTH-DEVICE",
                    tenant_id="TENANT-A",
                    plant_id="PLANT-1",
                    device_name="Month Device",
                    device_type="compressor",
                    data_source_type="metered",
                ),
                DeviceLiveState(
                    device_id="MONTH-DEVICE",
                    tenant_id="TENANT-A",
                    runtime_status="running",
                    day_bucket=local_day,
                    month_bucket=month_bucket,
                    today_energy_kwh=0.57,
                    month_energy_kwh=0.93,
                    today_idle_kwh=0.23,
                    today_offhours_kwh=0.40,
                    today_loss_kwh=0.63,
                ),
            ]
        )
        await session.commit()

        monkeypatch.setattr(
            LiveDashboardService,
            "_fetch_energy_json",
            AsyncMock(
                return_value={
                    "success": True,
                    "energy_widgets": {
                        "month_energy_kwh": 0.57,
                        "today_energy_kwh": 0.57,
                        "today_loss_kwh": 0.10,
                        "month_energy_cost_inr": 5.70,
                        "today_energy_cost_inr": 5.70,
                        "today_loss_cost_inr": 1.0,
                        "currency": "INR",
                    },
                }
            ),
        )
        monkeypatch.setattr(
            TariffCache,
            "get",
            AsyncMock(return_value={"configured": True, "rate": 10.0, "currency": "INR"}),
        )

        payload = await LiveDashboardService(session).get_dashboard_summary(tenant_id="TENANT-A")

    assert payload["energy_widgets"]["month_energy_kwh"] == 0.93
    assert payload["energy_widgets"]["month_energy_cost_inr"] == 9.3
    assert payload["energy_widgets"]["today_loss_kwh"] == 0.63
    assert payload["energy_widgets"]["month_energy_kwh"] >= payload["energy_widgets"]["today_loss_kwh"]


@pytest.mark.asyncio
async def test_dashboard_summary_today_loss_matches_breakdown_and_live_device_totals(
    monkeypatch: pytest.MonkeyPatch,
    session_factory,
):
    local_day = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Kolkata")).date()
    async with session_factory() as session:
        session.add_all(
            [
                Device(device_id="D1", tenant_id="TENANT-A", plant_id="PLANT-1", device_name="Device 1", device_type="compressor"),
                Device(device_id="D2", tenant_id="TENANT-A", plant_id="PLANT-1", device_name="Device 2", device_type="compressor"),
                DeviceLiveState(
                    device_id="D1",
                    tenant_id="TENANT-A",
                    runtime_status="running",
                    day_bucket=local_day,
                    today_energy_kwh=10.0,
                    today_idle_kwh=0.5,
                    today_offhours_kwh=0.0,
                    today_overconsumption_kwh=0.5,
                    today_loss_kwh=1.0,
                ),
                DeviceLiveState(
                    device_id="D2",
                    tenant_id="TENANT-A",
                    runtime_status="running",
                    day_bucket=local_day,
                    today_energy_kwh=5.0,
                    today_idle_kwh=0.1,
                    today_offhours_kwh=0.2,
                    today_overconsumption_kwh=0.0,
                    today_loss_kwh=0.3,
                ),
            ]
        )
        await session.commit()

        monkeypatch.setattr(LiveDashboardService, "_fetch_energy_json", AsyncMock(return_value=None))
        monkeypatch.setattr(
            TariffCache,
            "get",
            AsyncMock(return_value={"configured": True, "rate": 10.0, "currency": "INR"}),
        )

        service = LiveDashboardService(session)
        summary = await service.get_dashboard_summary(tenant_id="TENANT-A")
        breakdown = await service.get_today_loss_breakdown(tenant_id="TENANT-A")

    assert summary["energy_widgets"]["today_loss_kwh"] == 1.3
    assert summary["energy_widgets"]["today_loss_kwh"] == breakdown["totals"]["total_loss_kwh"]
    assert summary["energy_widgets"]["today_loss_cost_inr"] == breakdown["totals"]["total_loss_cost_inr"]
    assert breakdown["totals"]["total_loss_kwh"] == 1.3
    assert breakdown["totals"]["total_loss_cost_inr"] == 13.0
    assert sum(row["total_loss_kwh"] for row in breakdown["rows"]) == pytest.approx(1.3, abs=1e-4)


@pytest.mark.asyncio
async def test_today_loss_breakdown_is_tenant_scoped_and_uses_current_day_live_state(
    monkeypatch: pytest.MonkeyPatch,
    session_factory,
):
    local_day = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Kolkata")).date()
    async with session_factory() as session:
        session.add_all(
            [
                Device(device_id="SHARED-DEVICE-A", tenant_id="TENANT-A", plant_id="PLANT-1", device_name="A", device_type="compressor"),
                Device(device_id="SHARED-DEVICE-B", tenant_id="TENANT-B", plant_id="PLANT-1", device_name="B", device_type="compressor"),
                DeviceLiveState(
                    device_id="SHARED-DEVICE-A",
                    tenant_id="TENANT-A",
                    runtime_status="running",
                    day_bucket=local_day,
                    today_energy_kwh=3.0,
                    today_idle_kwh=0.2,
                    today_offhours_kwh=0.1,
                    today_overconsumption_kwh=0.3,
                    today_loss_kwh=0.6,
                ),
                DeviceLiveState(
                    device_id="SHARED-DEVICE-B",
                    tenant_id="TENANT-B",
                    runtime_status="running",
                    day_bucket=local_day,
                    today_energy_kwh=8.0,
                    today_idle_kwh=1.0,
                    today_offhours_kwh=1.0,
                    today_overconsumption_kwh=1.0,
                    today_loss_kwh=3.0,
                ),
            ]
        )
        await session.commit()

        monkeypatch.setattr(
            TariffCache,
            "get",
            AsyncMock(return_value={"configured": True, "rate": 5.0, "currency": "INR"}),
        )

        payload = await LiveDashboardService(session).get_today_loss_breakdown(tenant_id="TENANT-A")

    assert payload["totals"]["total_loss_kwh"] == 0.6
    assert payload["totals"]["total_loss_cost_inr"] == 3.0
    assert len(payload["rows"]) == 1
    assert payload["rows"][0]["device_id"] == "SHARED-DEVICE-A"
    assert payload["rows"][0]["total_loss_kwh"] == 0.6


@pytest.mark.asyncio
async def test_dashboard_summary_scopes_plant_roles_to_assigned_plants(
    monkeypatch: pytest.MonkeyPatch,
    session_factory,
):
    local_day = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Kolkata")).date()
    async with session_factory() as session:
        session.add_all(
            [
                Device(device_id="P1", tenant_id="TENANT-A", plant_id="PLANT-1", device_name="Plant 1", device_type="compressor"),
                Device(device_id="P2", tenant_id="TENANT-A", plant_id="PLANT-2", device_name="Plant 2", device_type="compressor"),
                DeviceLiveState(
                    device_id="P1",
                    tenant_id="TENANT-A",
                    runtime_status="running",
                    health_score=80.0,
                    uptime_percentage=90.0,
                    day_bucket=local_day,
                    today_energy_kwh=10.0,
                    today_loss_kwh=1.0,
                    month_energy_kwh=100.0,
                ),
                DeviceLiveState(
                    device_id="P2",
                    tenant_id="TENANT-A",
                    runtime_status="running",
                    health_score=40.0,
                    uptime_percentage=50.0,
                    day_bucket=local_day,
                    today_energy_kwh=5.0,
                    today_loss_kwh=0.5,
                    month_energy_kwh=50.0,
                ),
            ]
        )
        await session.commit()

        monkeypatch.setattr(LiveDashboardService, "_fetch_energy_json", AsyncMock(return_value=None))
        monkeypatch.setattr(
            TariffCache,
            "get",
            AsyncMock(return_value={"configured": True, "rate": 10.0, "currency": "INR"}),
        )

        service = LiveDashboardService(
            session,
            TenantContext(
                tenant_id="TENANT-A",
                user_id="operator-1",
                role="operator",
                plant_ids=["PLANT-1"],
                is_super_admin=False,
            ),
        )
        payload = await service.get_dashboard_summary(tenant_id="TENANT-A")
        breakdown = await service.get_today_loss_breakdown(tenant_id="TENANT-A")

    assert payload["summary"]["total_devices"] == 1
    assert payload["summary"]["system_health"] == 80.0
    assert payload["energy_widgets"]["today_energy_kwh"] == 10.0
    assert payload["energy_widgets"]["today_loss_kwh"] == 1.0
    assert payload["energy_widgets"]["month_energy_kwh"] == 100.0
    assert breakdown["totals"]["total_loss_kwh"] == 1.0
    assert [row["device_id"] for row in breakdown["rows"]] == ["P1"]


@pytest.mark.asyncio
async def test_dashboard_summary_scopes_to_selected_plant_within_assigned_scope(
    monkeypatch: pytest.MonkeyPatch,
    session_factory,
):
    local_day = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Kolkata")).date()
    async with session_factory() as session:
        session.add_all(
            [
                Device(device_id="P1", tenant_id="TENANT-A", plant_id="PLANT-1", device_name="Plant 1", device_type="compressor"),
                Device(device_id="P2", tenant_id="TENANT-A", plant_id="PLANT-2", device_name="Plant 2", device_type="compressor"),
                DeviceLiveState(
                    device_id="P1",
                    tenant_id="TENANT-A",
                    runtime_status="running",
                    health_score=80.0,
                    uptime_percentage=90.0,
                    day_bucket=local_day,
                    today_energy_kwh=10.0,
                    today_loss_kwh=1.0,
                    month_energy_kwh=100.0,
                ),
                DeviceLiveState(
                    device_id="P2",
                    tenant_id="TENANT-A",
                    runtime_status="running",
                    health_score=60.0,
                    uptime_percentage=70.0,
                    day_bucket=local_day,
                    today_energy_kwh=6.0,
                    today_loss_kwh=0.6,
                    month_energy_kwh=60.0,
                ),
            ]
        )
        await session.commit()

        monkeypatch.setattr(LiveDashboardService, "_fetch_energy_json", AsyncMock(return_value=None))
        monkeypatch.setattr(
            TariffCache,
            "get",
            AsyncMock(return_value={"configured": True, "rate": 10.0, "currency": "INR"}),
        )

        service = LiveDashboardService(
            session,
            TenantContext(
                tenant_id="TENANT-A",
                user_id="plant-manager-1",
                role="plant_manager",
                plant_ids=["PLANT-1", "PLANT-2", "PLANT-3"],
                is_super_admin=False,
            ),
        )
        payload = await service.get_dashboard_summary(tenant_id="TENANT-A", plant_id="PLANT-2")
        breakdown = await service.get_today_loss_breakdown(tenant_id="TENANT-A", plant_id="PLANT-2")

    assert payload["summary"]["total_devices"] == 1
    assert payload["energy_widgets"]["today_energy_kwh"] == 6.0
    assert payload["energy_widgets"]["today_loss_kwh"] == 0.6
    assert payload["energy_widgets"]["month_energy_kwh"] == 60.0
    assert breakdown["totals"]["total_loss_kwh"] == 0.6
    assert [row["device_id"] for row in breakdown["rows"]] == ["P2"]


@pytest.mark.asyncio
async def test_dashboard_summary_and_breakdown_use_explicit_accessible_plant_scope(
    monkeypatch: pytest.MonkeyPatch,
    session_factory,
):
    local_day = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Kolkata")).date()
    async with session_factory() as session:
        session.add_all(
            [
                Device(device_id="P1", tenant_id="TENANT-A", plant_id="PLANT-1", device_name="Plant 1", device_type="compressor"),
                Device(device_id="P2", tenant_id="TENANT-A", plant_id="PLANT-2", device_name="Plant 2", device_type="compressor"),
                DeviceLiveState(
                    device_id="P1",
                    tenant_id="TENANT-A",
                    runtime_status="running",
                    health_score=80.0,
                    uptime_percentage=90.0,
                    day_bucket=local_day,
                    today_energy_kwh=10.0,
                    today_idle_kwh=0.3,
                    today_offhours_kwh=0.2,
                    today_overconsumption_kwh=0.1,
                    today_loss_kwh=0.6,
                    month_energy_kwh=100.0,
                ),
                DeviceLiveState(
                    device_id="P2",
                    tenant_id="TENANT-A",
                    runtime_status="running",
                    health_score=60.0,
                    uptime_percentage=70.0,
                    day_bucket=local_day,
                    today_energy_kwh=6.0,
                    today_idle_kwh=0.0,
                    today_offhours_kwh=0.4,
                    today_overconsumption_kwh=0.2,
                    today_loss_kwh=0.6,
                    month_energy_kwh=60.0,
                ),
            ]
        )
        await session.commit()

        monkeypatch.setattr(LiveDashboardService, "_fetch_energy_json", AsyncMock(return_value=None))
        monkeypatch.setattr(
            TariffCache,
            "get",
            AsyncMock(return_value={"configured": True, "rate": 10.0, "currency": "INR"}),
        )

        service = LiveDashboardService(
            session,
            TenantContext(
                tenant_id="TENANT-A",
                user_id="org-admin-1",
                role="org_admin",
                plant_ids=[],
                is_super_admin=False,
            ),
        )
        summary = await service.get_dashboard_summary(
            tenant_id="TENANT-A",
            accessible_plant_ids=["PLANT-1"],
        )
        breakdown = await service.get_today_loss_breakdown(
            tenant_id="TENANT-A",
            accessible_plant_ids=["PLANT-1"],
        )

    assert summary["summary"]["total_devices"] == 1
    assert summary["energy_widgets"]["today_energy_kwh"] == 10.0
    assert summary["energy_widgets"]["today_loss_kwh"] == 0.6
    assert summary["energy_widgets"]["month_energy_kwh"] == 100.0
    assert breakdown["totals"]["total_loss_kwh"] == 0.6
    assert [row["device_id"] for row in breakdown["rows"]] == ["P1"]


@pytest.mark.asyncio
async def test_fleet_snapshot_uses_explicit_accessible_plant_scope(
    session_factory,
):
    async with session_factory() as session:
        session.add_all(
            [
                Device(device_id="P1", tenant_id="TENANT-A", plant_id="PLANT-1", device_name="Plant 1", device_type="compressor"),
                Device(device_id="P2", tenant_id="TENANT-A", plant_id="PLANT-2", device_name="Plant 2", device_type="compressor"),
                Device(device_id="P3", tenant_id="TENANT-A", plant_id="PLANT-3", device_name="Plant 3", device_type="compressor"),
            ]
        )
        await session.commit()

        payload = await LiveDashboardService(session).get_fleet_snapshot(
            tenant_id="TENANT-A",
            accessible_plant_ids=["PLANT-1", "PLANT-2"],
        )

    assert payload["total"] == 2
    assert [device["device_id"] for device in payload["devices"]] == ["P1", "P2"]


@pytest.mark.asyncio
async def test_dashboard_summary_totals_match_sum_of_plant_filtered_views(
    monkeypatch: pytest.MonkeyPatch,
    session_factory,
):
    local_day = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Kolkata")).date()
    async with session_factory() as session:
        session.add_all(
            [
                Device(
                    device_id="PLANT-1-DEVICE",
                    tenant_id="TENANT-A",
                    plant_id="PLANT-1",
                    device_name="Plant 1 Device",
                    device_type="compressor",
                    data_source_type="metered",
                ),
                Device(
                    device_id="PLANT-2-DEVICE",
                    tenant_id="TENANT-A",
                    plant_id="PLANT-2",
                    device_name="Plant 2 Device",
                    device_type="compressor",
                    data_source_type="metered",
                ),
                DeviceLiveState(
                    device_id="PLANT-1-DEVICE",
                    tenant_id="TENANT-A",
                    runtime_status="running",
                    day_bucket=local_day,
                ),
                DeviceLiveState(
                    device_id="PLANT-2-DEVICE",
                    tenant_id="TENANT-A",
                    runtime_status="stopped",
                    day_bucket=local_day,
                ),
            ]
        )
        await session.commit()

        monkeypatch.setattr(LiveDashboardService, "_fetch_energy_json", AsyncMock(return_value=None))
        monkeypatch.setattr(TariffCache, "get", AsyncMock(return_value=None))

        service = LiveDashboardService(session)
        all_plants = await service.get_dashboard_summary(tenant_id="TENANT-A")
        plant_one = await service.get_dashboard_summary(tenant_id="TENANT-A", plant_id="PLANT-1")
        plant_two = await service.get_dashboard_summary(tenant_id="TENANT-A", plant_id="PLANT-2")

    assert all_plants["summary"]["total_devices"] == 2
    assert plant_one["summary"]["total_devices"] == 1
    assert plant_two["summary"]["total_devices"] == 1
    assert all_plants["summary"]["total_devices"] == (
        plant_one["summary"]["total_devices"] + plant_two["summary"]["total_devices"]
    )
