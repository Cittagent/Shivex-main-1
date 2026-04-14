from pathlib import Path
from types import SimpleNamespace
import importlib.util
import os
import sys
from unittest.mock import AsyncMock

import pytest

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ["DATABASE_URL"] = "mysql+aiomysql://test:test@127.0.0.1:3306/test_db"

spec = importlib.util.spec_from_file_location(
    "device_service_app_init",
    BASE_DIR / "app" / "__init__.py",
)
device_app_module = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
spec.loader.exec_module(device_app_module)


@pytest.mark.asyncio
async def test_reconciliation_cycle_refreshes_fleet_snapshot_when_repairs_found(monkeypatch):
    tenant_id = "ORG-1"
    session_markers = []

    class _FakeSessionContext:
        def __init__(self, marker):
            self.marker = marker

        async def __aenter__(self):
            session_markers.append(self.marker)
            return self.marker

        async def __aexit__(self, exc_type, exc, tb):
            return False

    contexts = iter([
        _FakeSessionContext("discovery-session"),
        _FakeSessionContext("tenant-session"),
    ])

    monkeypatch.setattr(
        device_app_module,
        "_load_active_tenant_ids",
        AsyncMock(return_value=[tenant_id]),
    )
    monkeypatch.setitem(sys.modules, "app.database", SimpleNamespace(AsyncSessionLocal=lambda: next(contexts)))

    reconcile_mock = AsyncMock(return_value={"scanned": 1, "repaired": 1, "repaired_device_ids": ["DEVICE-1"]})
    materialize_mock = AsyncMock()

    class _ProjectionService:
        def __init__(self, session, ctx):
            assert session == "tenant-session"
            assert ctx.tenant_id == tenant_id

        reconcile_recent_projections = reconcile_mock

    class _DashboardService:
        def __init__(self, session, ctx):
            assert session == "tenant-session"
            assert ctx.tenant_id == tenant_id

        materialize_fleet_state_snapshot = materialize_mock

    fake_live_projection_module = SimpleNamespace(LiveProjectionService=_ProjectionService)
    fake_dashboard_module = SimpleNamespace(DashboardService=_DashboardService)
    monkeypatch.setitem(sys.modules, "app.services.live_projection", fake_live_projection_module)
    monkeypatch.setitem(sys.modules, "app.services.dashboard", fake_dashboard_module)

    await device_app_module._run_live_projection_reconciliation_cycle(refresh_fleet_snapshot=True)

    assert session_markers == ["discovery-session", "tenant-session"]
    reconcile_mock.assert_awaited_once_with(max_devices=500)
    materialize_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_reconciliation_cycle_skips_fleet_snapshot_refresh_without_repairs(monkeypatch):
    tenant_id = "ORG-1"

    class _FakeSessionContext:
        async def __aenter__(self):
            return "session"

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        device_app_module,
        "_load_active_tenant_ids",
        AsyncMock(return_value=[tenant_id]),
    )
    contexts = iter([_FakeSessionContext(), _FakeSessionContext()])
    monkeypatch.setitem(sys.modules, "app.database", SimpleNamespace(AsyncSessionLocal=lambda: next(contexts)))

    reconcile_mock = AsyncMock(return_value={"scanned": 1, "repaired": 0, "repaired_device_ids": []})
    materialize_mock = AsyncMock()

    class _ProjectionService:
        def __init__(self, session, ctx):
            assert ctx.tenant_id == tenant_id

        reconcile_recent_projections = reconcile_mock

    class _DashboardService:
        def __init__(self, session, ctx):
            assert ctx.tenant_id == tenant_id

        materialize_fleet_state_snapshot = materialize_mock

    fake_live_projection_module = SimpleNamespace(LiveProjectionService=_ProjectionService)
    fake_dashboard_module = SimpleNamespace(DashboardService=_DashboardService)
    monkeypatch.setitem(sys.modules, "app.services.live_projection", fake_live_projection_module)
    monkeypatch.setitem(sys.modules, "app.services.dashboard", fake_dashboard_module)

    await device_app_module._run_live_projection_reconciliation_cycle(refresh_fleet_snapshot=True)

    reconcile_mock.assert_awaited_once_with(max_devices=500)
    materialize_mock.assert_not_awaited()
