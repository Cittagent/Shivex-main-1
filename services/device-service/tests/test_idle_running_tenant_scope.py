from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

BASE_DIR = Path(__file__).resolve().parents[1]
SERVICES_DIR = Path(__file__).resolve().parents[2]
for path in (BASE_DIR, SERVICES_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

os.environ["DATABASE_URL"] = "mysql+aiomysql://test:test@127.0.0.1:3306/test_db"

from app.database import Base
from app.models.device import Device, IdleRunningLog
from app.services import idle_running
from app.services.idle_running import IdleRunningService
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
async def test_idle_stats_persists_tenant_scoped_log(session_factory, monkeypatch):
    async with session_factory() as session:
        await session.execute(
            IdleRunningLog.__table__.delete().where(
                IdleRunningLog.device_id == "DASH-DEVICE",
                IdleRunningLog.tenant_id == "TENANT-1",
            )
        )
        await session.execute(
            Device.__table__.delete().where(
                Device.device_id == "DASH-DEVICE",
                Device.tenant_id == "TENANT-1",
            )
        )
        await session.commit()

        session.add(
            Device(
                device_id="DASH-DEVICE",
                tenant_id="TENANT-1",
                device_name="Dashboard Device",
                device_type="compressor",
                data_source_type="metered",
                idle_current_threshold=1.0,
            )
        )
        await session.commit()

        async def fake_tariff_get(cls, tenant_id):
            return {"configured": True, "rate": 2.5, "currency": "INR", "stale": False, "cache": "miss"}

        async def fake_fetch_telemetry(self, *args, **kwargs):
            return []

        monkeypatch.setattr(idle_running.TariffCache, "get", classmethod(fake_tariff_get))
        monkeypatch.setattr(IdleRunningService, "_fetch_telemetry", fake_fetch_telemetry)

        async def fake_get_or_create_day_log(self, device_id: str, day_start: datetime, now_utc: datetime):
            entity = IdleRunningLog(
                id=1,
                device_id=device_id,
                tenant_id="TENANT-1",
                period_start=day_start,
                period_end=day_start,
                idle_duration_sec=0,
                idle_energy_kwh=0,
                idle_cost=0,
                currency="INR",
                tariff_rate_used=0,
                pf_estimated=False,
                created_at=now_utc,
                updated_at=now_utc,
            )
            self._session.add(entity)
            await self._session.flush()
            return entity

        monkeypatch.setattr(IdleRunningService, "_get_or_create_day_log", fake_get_or_create_day_log)

        service = IdleRunningService(
            session,
            TenantContext(
                tenant_id="TENANT-1",
                user_id="test-user",
                role="system",
                plant_ids=[],
                is_super_admin=False,
            ),
        )
        result = await service.get_idle_stats("DASH-DEVICE", "TENANT-1")

        log = (
            await session.execute(
                IdleRunningLog.__table__.select().where(
                    IdleRunningLog.device_id == "DASH-DEVICE",
                    IdleRunningLog.tenant_id == "TENANT-1",
                )
            )
        ).first()

    assert result["device_id"] == "DASH-DEVICE"
    assert log is not None
    assert log._mapping["tenant_id"] == "TENANT-1"
