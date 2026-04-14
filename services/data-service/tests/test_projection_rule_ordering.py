from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import sys
from unittest.mock import AsyncMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SERVICES_DIR = PROJECT_ROOT / "services"
for path in (PROJECT_ROOT, SERVICES_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from src.config import settings
from src.models import EnrichmentStatus, TelemetryPayload
from src.services.telemetry_service import TelemetryService


class _FakeInfluxRepository:
    def __init__(self) -> None:
        self.writes: list[TelemetryPayload] = []

    def write_telemetry(self, payload) -> bool:
        self.writes.append(payload)
        return True

    def close(self) -> None:
        return None


class _FakeDlqRepository:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    def send(self, **kwargs) -> None:
        self.messages.append(kwargs)
        return None

    def get_operational_stats(self) -> dict[str, Any]:
        return {}

    def close(self) -> None:
        return None


class _FakeOutboxRepository:
    def __init__(self) -> None:
        self.enqueued: list[dict[str, Any]] = []

    async def ensure_schema(self) -> None:
        return None

    async def enqueue_telemetry(self, **kwargs) -> None:
        self.enqueued.append(kwargs)

    async def close(self) -> None:
        return None


class _FakeEnrichmentService:
    async def enrich_telemetry(self, payload: TelemetryPayload) -> TelemetryPayload:
        payload.tenant_id = payload.tenant_id or "TENANT-A"
        payload.enrichment_status = EnrichmentStatus.SUCCESS
        return payload

    async def close(self) -> None:
        return None


class _FakeProjectionClient:
    def __init__(self, order: list[str], *, fail: bool = False) -> None:
        self.order = order
        self.fail = fail

    async def sync_projection(self, payload: TelemetryPayload) -> dict[str, Any]:
        self.order.append("projection")
        if self.fail:
            raise RuntimeError("projection unavailable")
        return {
            "load_state": "idle",
            "idle_streak_started_at": payload.timestamp.isoformat(),
            "idle_streak_duration_sec": 40 * 60,
        }

    async def close(self) -> None:
        return None


class _FakeRuleEngineClient:
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.calls: list[dict[str, Any]] = []

    async def evaluate_rules(self, payload: TelemetryPayload, projection_state=None) -> None:
        self.order.append("rules")
        self.calls.append(
            {
                "device_id": payload.device_id,
                "projection_state": projection_state,
            }
        )

    async def close(self) -> None:
        return None


async def _wait_for_queue(service: TelemetryService) -> None:
    await asyncio.wait_for(service._processing_queue.join(), timeout=5)
    await asyncio.sleep(0.05)


def _payload() -> dict[str, Any]:
    return {
        "device_id": "DEVICE-ORDER-1",
        "tenant_id": "TENANT-A",
        "timestamp": datetime(2026, 4, 12, 10, 40, 0, tzinfo=timezone.utc).isoformat(),
        "schema_version": "v1",
        "current": 2.0,
        "voltage": 230.0,
        "power": 460.0,
    }


@pytest.mark.asyncio
async def test_rule_evaluation_runs_after_projection_sync(monkeypatch):
    order: list[str] = []
    monkeypatch.setattr(settings, "device_sync_enabled", True)
    monkeypatch.setattr(settings, "energy_sync_enabled", False)
    outbox = _FakeOutboxRepository()
    rule_engine = _FakeRuleEngineClient(order)
    service = TelemetryService(
        influx_repository=_FakeInfluxRepository(),
        dlq_repository=_FakeDlqRepository(),
        outbox_repository=outbox,
        enrichment_service=_FakeEnrichmentService(),
        rule_engine_client=rule_engine,
        device_projection_client=_FakeProjectionClient(order),
    )
    service._fetch_tenant_owned_device_ids = AsyncMock(return_value={"DEVICE-ORDER-1"})

    async def _noop_broadcast(*args, **kwargs):
        return None

    monkeypatch.setattr("src.api.websocket.broadcast_telemetry", _noop_broadcast)
    await service.start()
    try:
        accepted = await service.process_telemetry_message(_payload())
        assert accepted is True
        await _wait_for_queue(service)

        assert order == ["projection", "rules"]
        assert len(rule_engine.calls) == 1
        assert rule_engine.calls[0]["projection_state"]["idle_streak_duration_sec"] == 40 * 60
        assert len(outbox.enqueued) == 0
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_rule_evaluation_is_skipped_when_projection_sync_fails(monkeypatch):
    order: list[str] = []
    monkeypatch.setattr(settings, "device_sync_enabled", True)
    monkeypatch.setattr(settings, "energy_sync_enabled", False)
    outbox = _FakeOutboxRepository()
    rule_engine = _FakeRuleEngineClient(order)
    service = TelemetryService(
        influx_repository=_FakeInfluxRepository(),
        dlq_repository=_FakeDlqRepository(),
        outbox_repository=outbox,
        enrichment_service=_FakeEnrichmentService(),
        rule_engine_client=rule_engine,
        device_projection_client=_FakeProjectionClient(order, fail=True),
    )
    service._fetch_tenant_owned_device_ids = AsyncMock(return_value={"DEVICE-ORDER-1"})

    async def _noop_broadcast(*args, **kwargs):
        return None

    monkeypatch.setattr("src.api.websocket.broadcast_telemetry", _noop_broadcast)
    await service.start()
    try:
        accepted = await service.process_telemetry_message(_payload())
        assert accepted is True
        await _wait_for_queue(service)

        assert order == ["projection"]
        assert rule_engine.calls == []
        assert len(outbox.enqueued) == 1
        assert outbox.enqueued[0]["targets"]
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_nonexistent_device_is_rejected_before_influx_and_outbox(monkeypatch):
    order: list[str] = []
    monkeypatch.setattr(settings, "device_sync_enabled", True)
    monkeypatch.setattr(settings, "energy_sync_enabled", True)
    influx = _FakeInfluxRepository()
    dlq = _FakeDlqRepository()
    outbox = _FakeOutboxRepository()
    service = TelemetryService(
        influx_repository=influx,
        dlq_repository=dlq,
        outbox_repository=outbox,
        enrichment_service=_FakeEnrichmentService(),
        rule_engine_client=_FakeRuleEngineClient(order),
        device_projection_client=_FakeProjectionClient(order),
    )
    service._fetch_tenant_owned_device_ids = AsyncMock(return_value=set())

    await service._process_telemetry_async(
        payload=TelemetryPayload(**_payload()),
        correlation_id="ownership-missing",
        raw_payload=_payload(),
    )

    assert influx.writes == []
    assert outbox.enqueued == []
    assert order == []
    assert dlq.messages[-1]["error_type"] == "device_ownership_error"


@pytest.mark.asyncio
async def test_wrong_tenant_device_is_rejected_before_downstream_churn(monkeypatch):
    order: list[str] = []
    monkeypatch.setattr(settings, "device_sync_enabled", True)
    monkeypatch.setattr(settings, "energy_sync_enabled", True)
    influx = _FakeInfluxRepository()
    dlq = _FakeDlqRepository()
    outbox = _FakeOutboxRepository()
    service = TelemetryService(
        influx_repository=influx,
        dlq_repository=dlq,
        outbox_repository=outbox,
        enrichment_service=_FakeEnrichmentService(),
        rule_engine_client=_FakeRuleEngineClient(order),
        device_projection_client=_FakeProjectionClient(order),
    )
    service._fetch_tenant_owned_device_ids = AsyncMock(return_value={"OTHER-DEVICE"})

    await service._process_telemetry_async(
        payload=TelemetryPayload(**_payload()),
        correlation_id="ownership-wrong-tenant",
        raw_payload=_payload(),
    )

    assert influx.writes == []
    assert outbox.enqueued == []
    assert order == []
    assert dlq.messages[-1]["error_type"] == "device_ownership_error"
