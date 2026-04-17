from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request

ROOT = Path(__file__).resolve().parents[1]
SERVICES_ROOT = ROOT.parent
sys.path = [p for p in sys.path if p not in {str(ROOT), str(SERVICES_ROOT)}]
sys.path.insert(0, str(SERVICES_ROOT))
sys.path.insert(0, str(ROOT))

from app.api import routes
from app.schemas import LiveUpdateBatchRequest


def _request() -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/energy/live-update/batch",
        "headers": [(b"x-tenant-id", b"SH00000001"), (b"x-internal-service", b"data-service")],
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_live_update_batch_isolates_invalid_rows(monkeypatch):
    publish_many_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(routes.energy_broadcaster, "publish_many", publish_many_mock)
    monkeypatch.setattr(routes, "resolve_request_tenant_id", lambda request, explicit_tenant_id=None: explicit_tenant_id or "SH00000001")

    class _FakeEngine:
        def __init__(self, _db):
            self.calls = []

        async def apply_live_updates_batch(self, *, tenant_id=None, updates=None):
            results = []
            for update in updates or []:
                telemetry = update["telemetry"]
                device_id = telemetry["device_id"]
                if device_id == "DEVICE-BAD":
                    results.append(
                        {
                            "success": False,
                            "device_id": device_id,
                            "error": "bad telemetry",
                            "error_code": "ENERGY_LIVE_UPDATE_ERROR",
                            "retryable": True,
                        }
                    )
                    continue
                results.append(
                    {
                        "success": True,
                        "device_id": device_id,
                        "data": {"device_id": device_id, "version": 1, "freshness_ts": telemetry["timestamp"]},
                        "retryable": False,
                    }
                )
            return results

    monkeypatch.setattr(routes, "EnergyEngine", _FakeEngine)

    payload = LiveUpdateBatchRequest(
        tenant_id="SH00000001",
        updates=[
            {"telemetry": {"device_id": "DEVICE-GOOD", "timestamp": "2026-04-17T00:00:00Z"}},
            {"telemetry": {"device_id": "DEVICE-BAD", "timestamp": "2026-04-17T00:00:01Z"}},
        ],
    )

    response = await routes.live_update_batch(_request(), payload, db=object())

    assert response["success"] is True
    assert response["results"][0]["success"] is True
    assert response["results"][0]["device_id"] == "DEVICE-GOOD"
    assert response["results"][1]["success"] is False
    assert response["results"][1]["device_id"] == "DEVICE-BAD"
    assert response["results"][1]["error_code"] == "ENERGY_LIVE_UPDATE_ERROR"
    publish_many_mock.assert_awaited_once()
