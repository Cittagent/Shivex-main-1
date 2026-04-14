from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import types

ROOT = Path(__file__).resolve().parents[4]
for path in (ROOT, ROOT / "services", ROOT / "services/analytics-service"):
    resolved = str(path)
    if resolved not in sys.path:
        sys.path.insert(0, resolved)

if "aioboto3" not in sys.modules:
    fake_aioboto3 = types.ModuleType("aioboto3")

    class _FakeSession:
        def __init__(self, *args, **kwargs):
            pass

    fake_aioboto3.Session = _FakeSession
    sys.modules["aioboto3"] = fake_aioboto3

shared_tenant_context = importlib.import_module("shared.tenant_context")
services_pkg = sys.modules.setdefault("services", types.ModuleType("services"))
services_shared_pkg = sys.modules.setdefault("services.shared", types.ModuleType("services.shared"))
services_pkg.shared = services_shared_pkg
services_shared_pkg.tenant_context = shared_tenant_context
sys.modules["services.shared.tenant_context"] = shared_tenant_context
shared_job_context = importlib.import_module("shared.job_context")
services_shared_pkg.job_context = shared_job_context
sys.modules["services.shared.job_context"] = shared_job_context

from shared.tenant_context import TenantContext
from src.api.routes import analytics
from src.models.schemas import AnalyticsRequest, FleetAnalyticsRequest
from src.services.device_scope import AnalyticsDeviceScopeService


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    def __init__(self, responses):
        self._responses = list(responses)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, *args, **kwargs):
        if not self._responses:
            raise AssertionError("No fake response queued for httpx.AsyncClient.get")
        return self._responses.pop(0)


@pytest.mark.asyncio
async def test_device_scope_filters_accessible_devices(monkeypatch):
    ctx = TenantContext(
        tenant_id="SH00000001",
        user_id="user-1",
        role="plant_manager",
        plant_ids=["plant-a"],
        is_super_admin=False,
    )

    fake_payload = {
        "data": [
            {"device_id": "dev-a", "plant_id": "plant-a"},
            {"device_id": "dev-b", "plant_id": "plant-b"},
        ],
        "total_pages": 1,
    }
    monkeypatch.setattr(
        "src.services.device_scope.httpx.AsyncClient",
        lambda *args, **kwargs: _FakeAsyncClient([_FakeResponse(fake_payload)]),
    )

    service = AnalyticsDeviceScopeService(ctx)
    assert await service.resolve_accessible_device_ids() == ["dev-a"]


@pytest.mark.asyncio
async def test_device_scope_rejects_out_of_scope_requested_devices(monkeypatch):
    ctx = TenantContext(
        tenant_id="SH00000001",
        user_id="user-1",
        role="operator",
        plant_ids=["plant-a"],
        is_super_admin=False,
    )

    fake_payload = {
        "data": [
            {"device_id": "dev-a", "plant_id": "plant-a"},
            {"device_id": "dev-b", "plant_id": "plant-b"},
        ],
        "total_pages": 1,
    }
    monkeypatch.setattr(
        "src.services.device_scope.httpx.AsyncClient",
        lambda *args, **kwargs: _FakeAsyncClient([_FakeResponse(fake_payload)]),
    )

    service = AnalyticsDeviceScopeService(ctx)
    with pytest.raises(analytics.HTTPException) as exc_info:
        await service.normalize_requested_device_ids(["dev-b"])
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_run_fleet_analytics_normalizes_device_scope_before_enqueuing(monkeypatch):
    now = datetime.now(timezone.utc)
    request = FleetAnalyticsRequest(
        device_ids=[],
        start_time=now - timedelta(hours=1),
        end_time=now,
        analysis_type="anomaly",
        model_name="anomaly_ensemble",
        parameters={"foo": "bar"},
    )

    ctx = TenantContext(
        tenant_id="SH00000001",
        user_id="user-1",
        role="plant_manager",
        plant_ids=["plant-a"],
        is_super_admin=False,
    )
    app = SimpleNamespace(state=SimpleNamespace(fleet_tasks=set()))
    app_request = SimpleNamespace(app=app, state=SimpleNamespace(tenant_context=ctx))
    result_repo = MagicMock()
    result_repo.create_job = AsyncMock()
    result_repo.update_job_status = AsyncMock()

    recorded = {}

    async def fake_normalize(self, requested_device_ids):
        recorded["requested_device_ids"] = list(requested_device_ids)
        return ["dev-a", "dev-b"]

    async def fake_run_fleet_job(parent_job_id, req, app, **kwargs):
        recorded["job_device_ids"] = list(req.device_ids)
        recorded["job_kwargs"] = kwargs

    def fake_create_task(coro):
        task = asyncio.get_running_loop().create_task(coro)
        return task

    monkeypatch.setattr(analytics, "check_worker_alive", AsyncMock(return_value=True))
    monkeypatch.setattr(
        "src.api.routes.analytics.AnalyticsDeviceScopeService.normalize_requested_device_ids",
        fake_normalize,
    )
    monkeypatch.setattr("src.api.routes.analytics._run_fleet_job", fake_run_fleet_job)
    monkeypatch.setattr("src.api.routes.analytics.asyncio.create_task", fake_create_task)

    response = await analytics.run_fleet_analytics(request, app_request, result_repo)
    await asyncio.sleep(0)

    assert response.status.value == "running"
    assert recorded["requested_device_ids"] == []
    assert request.device_ids == ["dev-a", "dev-b"]
    create_call = result_repo.create_job.await_args.kwargs
    assert create_call["parameters"]["device_ids"] == ["dev-a", "dev-b"]
    assert recorded["job_device_ids"] == ["dev-a", "dev-b"]
    assert recorded["job_kwargs"]["tenant_id"] == "SH00000001"
    assert recorded["job_kwargs"]["initiated_by_user_id"] == "user-1"
    assert recorded["job_kwargs"]["initiated_by_role"] == "plant_manager"


@pytest.mark.asyncio
async def test_run_analytics_normalizes_single_device_scope_before_enqueuing(monkeypatch):
    now = datetime.now(timezone.utc)
    request = AnalyticsRequest(
        device_id="dev-b",
        start_time=now - timedelta(hours=1),
        end_time=now,
        analysis_type="anomaly",
        model_name="anomaly_ensemble",
    )

    ctx = TenantContext(
        tenant_id="SH00000001",
        user_id="user-1",
        role="plant_manager",
        plant_ids=["plant-a"],
        is_super_admin=False,
    )
    app_request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()), state=SimpleNamespace(tenant_context=ctx))
    result_repo = MagicMock()
    result_repo.create_job = AsyncMock()
    result_repo.update_job_queue_metadata = AsyncMock()
    job_queue = MagicMock()
    job_queue.submit_job = AsyncMock()
    job_queue.size = MagicMock(return_value=0)

    recorded = {}

    async def fake_normalize(self, requested_device_ids):
        recorded["requested_device_ids"] = list(requested_device_ids)
        return ["dev-a"]

    monkeypatch.setattr(analytics, "check_worker_alive", AsyncMock(return_value=True))
    monkeypatch.setattr(
        "src.api.routes.analytics.AnalyticsDeviceScopeService.normalize_requested_device_ids",
        fake_normalize,
    )

    response = await analytics.run_analytics(request, app_request, job_queue, result_repo)

    assert response.status.value == "pending"
    assert recorded["requested_device_ids"] == ["dev-b"]
    assert request.device_id == "dev-a"
    create_call = result_repo.create_job.await_args.kwargs
    assert create_call["device_id"] == "dev-a"
    submit_call = job_queue.submit_job.await_args.kwargs
    assert submit_call["job_id"] == response.job_id


@pytest.mark.asyncio
async def test_run_analytics_rejects_out_of_scope_single_device(monkeypatch):
    now = datetime.now(timezone.utc)
    request = AnalyticsRequest(
        device_id="dev-b",
        start_time=now - timedelta(hours=1),
        end_time=now,
        analysis_type="anomaly",
        model_name="anomaly_ensemble",
    )

    ctx = TenantContext(
        tenant_id="SH00000001",
        user_id="user-1",
        role="plant_manager",
        plant_ids=["plant-a"],
        is_super_admin=False,
    )
    app_request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()), state=SimpleNamespace(tenant_context=ctx))
    result_repo = MagicMock()
    result_repo.create_job = AsyncMock()
    result_repo.update_job_queue_metadata = AsyncMock()
    job_queue = MagicMock()
    job_queue.submit_job = AsyncMock()
    job_queue.size = MagicMock(return_value=0)

    monkeypatch.setattr(analytics, "check_worker_alive", AsyncMock(return_value=True))

    async def fake_normalize(self, requested_device_ids):
        raise analytics.HTTPException(
            status_code=403,
            detail={
                "error": "ANALYTICS_SCOPE_FORBIDDEN",
                "message": "Fleet analytics can only run for devices inside your assigned plant scope.",
            },
        )

    monkeypatch.setattr(
        "src.api.routes.analytics.AnalyticsDeviceScopeService.normalize_requested_device_ids",
        fake_normalize,
    )

    with pytest.raises(analytics.HTTPException) as exc_info:
        await analytics.run_analytics(request, app_request, job_queue, result_repo)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["error"] == "ANALYTICS_SCOPE_FORBIDDEN"
    result_repo.create_job.assert_not_awaited()
    job_queue.submit_job.assert_not_awaited()
