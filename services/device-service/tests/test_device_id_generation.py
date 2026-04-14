from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

BASE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
SERVICES_DIR = REPO_ROOT / "services"
for path in (REPO_ROOT, SERVICES_DIR, BASE_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

os.environ["DATABASE_URL"] = "mysql+aiomysql://test:test@127.0.0.1:3306/test_db"
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-at-least-32-characters-long")

import app as device_app_module
from app.api.v1 import devices as devices_api
from app.api.v1.router import api_router
from app.database import Base, get_db
from app.models.device import Device, DeviceIdSequence
from app.services.device_errors import DeviceAlreadyExistsError
from app.services.device_identity import format_device_id
from services.shared.tenant_context import TenantContext

DEVICE_ID_PATTERN = re.compile(r"^(AD|TD|VD)\d{8}$")


async def _seed_sequences(session_factory) -> None:
    async with session_factory() as session:
        session.add_all(
            [
                DeviceIdSequence(prefix="AD", next_value=1),
                DeviceIdSequence(prefix="TD", next_value=1),
                DeviceIdSequence(prefix="VD", next_value=1),
            ]
        )
        await session.commit()


@pytest_asyncio.fixture
async def device_app():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.add_exception_handler(
        device_app_module.RequestValidationError,
        device_app_module.validation_exception_handler,
    )
    app.add_exception_handler(
        device_app_module.HTTPException,
        device_app_module.http_exception_handler,
    )
    app.add_exception_handler(
        Exception,
        device_app_module.unhandled_exception_handler,
    )

    async def _override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db

    try:
        await _seed_sequences(session_factory)
        yield app, session_factory
    finally:
        await engine.dispose()


@pytest.fixture
def auth_context(monkeypatch):
    monkeypatch.setattr(
        devices_api,
        "get_auth_state",
        lambda request: {
            "user_id": "user-1",
            "tenant_id": "ORG-1",
            "role": "org_admin",
            "plant_ids": [],
            "is_authenticated": True,
        },
    )
    monkeypatch.setattr(
        devices_api.TenantContext,
        "from_request",
        classmethod(
            lambda cls, request: TenantContext(
                tenant_id="ORG-1",
                user_id="user-1",
                role="org_admin",
                plant_ids=[],
                is_super_admin=False,
            )
        ),
    )
    monkeypatch.setattr(devices_api, "_list_tenant_plants", AsyncMock(return_value=[{"id": "PLANT-1", "name": "Plant 1"}]))


@pytest.mark.asyncio
async def test_create_device_generates_device_id_without_user_input(device_app, auth_context):
    app, session_factory = device_app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/api/v1/devices",
            headers={"X-Tenant-Id": "ORG-1", "Authorization": "Bearer token"},
            json={
                "device_name": "Compressor 05",
                "device_type": "compressor",
                "device_id_class": "active",
                "data_source_type": "metered",
                "plant_id": "PLANT-1",
            },
        )

    assert response.status_code == 201
    payload = response.json()["data"]
    assert payload["device_id"] == "AD00000001"
    assert payload["device_id_class"] == "active"

    async with session_factory() as session:
        device = await session.get(Device, {"device_id": payload["device_id"], "tenant_id": "ORG-1"})

    assert device is not None
    assert device.plant_id == "PLANT-1"
    assert device.device_name == "Compressor 05"


@pytest.mark.asyncio
async def test_create_device_honors_user_supplied_device_id(device_app, auth_context):
    app, session_factory = device_app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/api/v1/devices",
            headers={"X-Tenant-Id": "ORG-1", "Authorization": "Bearer token"},
            json={
                "device_id": "USER-SUPPLIED-ID",
                "device_name": "Compressor 06",
                "device_type": "compressor",
                "device_id_class": "active",
                "data_source_type": "metered",
                "plant_id": "PLANT-1",
            },
        )

    assert response.status_code == 201
    payload = response.json()["data"]
    assert payload["device_id"] == "USER-SUPPLIED-ID"

    async with session_factory() as session:
        supplied_device = await session.get(Device, {"device_id": "USER-SUPPLIED-ID", "tenant_id": "ORG-1"})

    assert supplied_device is not None


@pytest.mark.asyncio
async def test_create_device_rejects_duplicate_user_supplied_device_id(device_app, auth_context):
    app, _session_factory = device_app
    payload = {
        "device_id": "USER-SUPPLIED-DUP",
        "device_name": "Compressor Duplicate",
        "device_type": "compressor",
        "device_id_class": "active",
        "data_source_type": "metered",
        "plant_id": "PLANT-1",
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        first = await client.post(
            "/api/v1/devices",
            headers={"X-Tenant-Id": "ORG-1", "Authorization": "Bearer token"},
            json=payload,
        )
        second = await client.post(
            "/api/v1/devices",
            headers={"X-Tenant-Id": "ORG-1", "Authorization": "Bearer token"},
            json={**payload, "device_name": "Compressor Duplicate 2"},
        )

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "DEVICE_ALREADY_EXISTS"


@pytest.mark.asyncio
async def test_device_id_sequences_increment_per_prefix(device_app, auth_context):
    app, _session_factory = device_app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        first = await client.post(
            "/api/v1/devices",
            headers={"X-Tenant-Id": "ORG-1", "Authorization": "Bearer token"},
            json={
                "device_name": "Compressor 07",
                "device_type": "compressor",
                "device_id_class": "active",
                "data_source_type": "metered",
                "plant_id": "PLANT-1",
            },
        )
        second = await client.post(
            "/api/v1/devices",
            headers={"X-Tenant-Id": "ORG-1", "Authorization": "Bearer token"},
            json={
                "device_name": "Test Device 08",
                "device_type": "compressor",
                "device_id_class": "test",
                "data_source_type": "metered",
                "plant_id": "PLANT-1",
            },
        )
        third = await client.post(
            "/api/v1/devices",
            headers={"X-Tenant-Id": "ORG-1", "Authorization": "Bearer token"},
            json={
                "device_name": "Compressor 09",
                "device_type": "compressor",
                "device_id_class": "active",
                "data_source_type": "metered",
                "plant_id": "PLANT-1",
            },
        )
        fourth = await client.post(
            "/api/v1/devices",
            headers={"X-Tenant-Id": "ORG-1", "Authorization": "Bearer token"},
            json={
                "device_name": "Virtual Device 10",
                "device_type": "compressor",
                "device_id_class": "virtual",
                "data_source_type": "metered",
                "plant_id": "PLANT-1",
            },
        )

    assert first.status_code == 201
    assert second.status_code == 201
    assert third.status_code == 201
    assert fourth.status_code == 201
    assert first.json()["data"]["device_id"] == "AD00000001"
    assert second.json()["data"]["device_id"] == "TD00000001"
    assert third.json()["data"]["device_id"] == "AD00000002"
    assert fourth.json()["data"]["device_id"] == "VD00000001"


@pytest.mark.asyncio
async def test_legacy_devices_continue_loading_unchanged(device_app, auth_context):
    app, session_factory = device_app

    async with session_factory() as session:
        session.add(
            Device(
                device_id="COMPRESSOR-LEGACY-01",
                tenant_id="ORG-1",
                plant_id="PLANT-1",
                device_name="Legacy Compressor",
                device_type="compressor",
            )
        )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get(
            "/api/v1/devices/COMPRESSOR-LEGACY-01",
            headers={"X-Tenant-Id": "ORG-1", "Authorization": "Bearer token"},
        )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["device_id"] == "COMPRESSOR-LEGACY-01"
    assert payload["device_name"] == "Legacy Compressor"


@pytest.mark.asyncio
async def test_allocator_retries_without_collision_under_concurrent_create(tmp_path):
    database_path = tmp_path / "device_identity.sqlite"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    await _seed_sequences(session_factory)

    async def _create(index: int) -> str:
        async with session_factory() as session:
            service = devices_api.DeviceService(
                session,
                TenantContext(
                    tenant_id="ORG-1",
                    user_id=f"user-{index}",
                    role="org_admin",
                    plant_ids=[],
                    is_super_admin=False,
                ),
            )
            created = await service.create_device(
                devices_api.DeviceCreate(
                    tenant_id="ORG-1",
                    plant_id="PLANT-1",
                    device_name=f"Concurrent {index}",
                    device_type="compressor",
                    device_id_class="active",
                    data_source_type="metered",
                )
            )
            return created.device_id

    created_ids = await asyncio.gather(*[_create(index) for index in range(1, 9)])

    assert sorted(created_ids) == [format_device_id("AD", index) for index in range(1, 9)]
    await engine.dispose()


@pytest.mark.asyncio
async def test_device_type_meaning_remains_machine_category(device_app, auth_context):
    app, session_factory = device_app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/api/v1/devices",
            headers={"X-Tenant-Id": "ORG-1", "Authorization": "Bearer token"},
            json={
                "device_name": "Motor Test Rig",
                "device_type": "motor",
                "device_id_class": "test",
                "data_source_type": "metered",
                "plant_id": "PLANT-1",
            },
        )

    assert response.status_code == 201
    payload = response.json()["data"]
    assert payload["device_id"] == "TD00000001"
    assert payload["device_type"] == "motor"
    assert payload["device_id_class"] == "test"

    async with session_factory() as session:
        device = await session.get(Device, {"device_id": payload["device_id"], "tenant_id": "ORG-1"})

    assert device is not None
    assert device.device_type == "motor"
    assert device.device_id_class == "test"


@pytest.mark.asyncio
async def test_create_device_returns_503_when_device_id_allocation_fails(device_app, auth_context):
    app, session_factory = device_app

    async with session_factory() as session:
        await session.execute(delete(DeviceIdSequence).where(DeviceIdSequence.prefix == "AD"))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/api/v1/devices",
            headers={"X-Tenant-Id": "ORG-1", "Authorization": "Bearer token"},
            json={
                "device_name": "Compressor 10",
                "device_type": "compressor",
                "device_id_class": "active",
                "data_source_type": "metered",
                "plant_id": "PLANT-1",
            },
        )

    assert response.status_code == 503
    payload = response.json()
    assert payload["error"]["code"] == "DEVICE_ID_ALLOCATION_FAILED"
    assert "Device ID sequence is not configured for prefix 'AD'" in payload["error"]["message"]


@pytest.mark.asyncio
async def test_create_device_maps_true_conflict_to_409(device_app, auth_context, monkeypatch):
    app, _session_factory = device_app

    async def _raise_conflict(self, _device_data):
        raise DeviceAlreadyExistsError("Device with ID 'CONFLICT-ID' already exists")

    monkeypatch.setattr("app.api.v1.devices.DeviceService.create_device", _raise_conflict)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/api/v1/devices",
            headers={"X-Tenant-Id": "ORG-1", "Authorization": "Bearer token"},
            json={
                "device_name": "Compressor 11",
                "device_type": "compressor",
                "device_id_class": "active",
                "data_source_type": "metered",
                "plant_id": "PLANT-1",
            },
        )

    assert response.status_code == 409
    payload = response.json()
    assert payload["error"]["code"] == "DEVICE_ALREADY_EXISTS"
    assert payload["error"]["message"] == "Device with ID 'CONFLICT-ID' already exists"


@pytest.mark.asyncio
async def test_invalid_device_id_class_returns_validation_error(device_app, auth_context):
    app, _session_factory = device_app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/api/v1/devices",
            headers={"X-Tenant-Id": "ORG-1", "Authorization": "Bearer token"},
            json={
                "device_name": "Broken Class Device",
                "device_type": "compressor",
                "device_id_class": "broken",
                "data_source_type": "metered",
                "plant_id": "PLANT-1",
            },
        )

    assert response.status_code == 422
    payload = response.json()
    assert payload["code"] == "VALIDATION_ERROR"
    assert payload["message"] == "Invalid request payload"
    assert payload["details"][0]["msg"] == "Value error, device_id_class must be 'active', 'test', or 'virtual'"
    assert payload["details"][0]["ctx"]["error"] == "device_id_class must be 'active', 'test', or 'virtual'"
