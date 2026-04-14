from __future__ import annotations

import asyncio
import importlib
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio  # noqa: F401

_SERVICES_DIR = Path(__file__).resolve().parents[1] / "src" / "services"
if "src.services" not in sys.modules:
    fake_services_pkg = types.ModuleType("src.services")
    fake_services_pkg.__path__ = [str(_SERVICES_DIR)]
    sys.modules["src.services"] = fake_services_pkg
    fake_services_pkg.TelemetryService = importlib.import_module("src.services.telemetry_service").TelemetryService
    fake_services_pkg.TelemetryServiceError = importlib.import_module("src.services.telemetry_service").TelemetryServiceError
    fake_services_pkg.DLQRetryService = importlib.import_module("src.services.dlq_retry_service").DLQRetryService
    fake_services_pkg.OutboxRelayService = importlib.import_module("src.services.outbox_relay").OutboxRelayService
    fake_services_pkg.ReconciliationService = importlib.import_module("src.services.reconciliation").ReconciliationService
    fake_services_pkg.EnrichmentService = importlib.import_module("src.services.enrichment_service").EnrichmentService
    fake_services_pkg.EnrichmentServiceError = importlib.import_module("src.services.enrichment_service").EnrichmentServiceError
    fake_services_pkg.RuleEngineClient = importlib.import_module("src.services.rule_engine_client").RuleEngineClient
    fake_services_pkg.RuleEngineError = importlib.import_module("src.services.rule_engine_client").RuleEngineError
    fake_services_pkg.ensure_bucket_retention = importlib.import_module("src.services.influxdb_retention").ensure_bucket_retention

telemetry_service_module = importlib.import_module("src.services.telemetry_service")
QUEUE_OVERFLOW_COUNTER = telemetry_service_module.QUEUE_OVERFLOW_COUNTER
QUEUE_OVERFLOW_TOTAL = telemetry_service_module.QUEUE_OVERFLOW_TOTAL
TelemetryService = telemetry_service_module.TelemetryService


@pytest.fixture(autouse=True)
def reset_queue_overflow_counter():
    QUEUE_OVERFLOW_COUNTER.clear()
    yield
    QUEUE_OVERFLOW_COUNTER.clear()


def _telemetry_payload(device_id: str, *, timestamp: datetime | None = None) -> dict[str, object]:
    stamp = timestamp or datetime.now(timezone.utc)
    return {
        "device_id": device_id,
        "timestamp": stamp.isoformat(),
        "schema_version": "v1",
        "power": 123.4,
        "current": 1.2,
        "voltage": 229.8,
    }


def _build_service(*, queue_maxsize: int = 1) -> tuple[TelemetryService, MagicMock, MagicMock]:
    influx_repository = MagicMock()
    influx_repository.write_telemetry.return_value = True
    influx_repository.close = MagicMock()

    dlq_repository = MagicMock()
    dlq_repository.get_operational_stats = MagicMock(return_value={})

    outbox_repository = MagicMock()
    outbox_repository.ensure_schema = AsyncMock(return_value=None)
    outbox_repository.close = AsyncMock(return_value=None)

    enrichment_service = MagicMock()

    async def _enrich(payload):
        return payload

    enrichment_service.enrich_telemetry = AsyncMock(side_effect=_enrich)
    enrichment_service.close = AsyncMock(return_value=None)

    rule_engine_client = MagicMock()
    rule_engine_client.evaluate_rules = AsyncMock(return_value=None)
    rule_engine_client.close = AsyncMock(return_value=None)

    device_projection_client = MagicMock()
    device_projection_client.sync_projection = AsyncMock(
        return_value={
            "load_state": "idle",
            "idle_streak_started_at": datetime.now(timezone.utc).isoformat(),
            "idle_streak_duration_sec": 0,
        }
    )
    device_projection_client.close = AsyncMock(return_value=None)

    service = TelemetryService(
        influx_repository=influx_repository,
        dlq_repository=dlq_repository,
        outbox_repository=outbox_repository,
        enrichment_service=enrichment_service,
        rule_engine_client=rule_engine_client,
        device_projection_client=device_projection_client,
    )
    service._processing_queue = asyncio.Queue(maxsize=queue_maxsize)
    service._update_queue_depth_metric()
    return service, dlq_repository, outbox_repository


@pytest.mark.asyncio
async def test_overflow_writes_to_dlq():
    service, dlq_repository, _ = _build_service(queue_maxsize=1)
    service._processing_queue.put_nowait({"payload": "existing"})

    accepted = await service.process_telemetry_message(_telemetry_payload("DEVICE-BP-1"))

    assert accepted is False
    dlq_repository.send.assert_called_once()
    call_kwargs = dlq_repository.send.call_args.kwargs
    assert call_kwargs["error_type"] == "QUEUE_OVERFLOW"
    assert call_kwargs["original_payload"]["device_id"] == "DEVICE-BP-1"


@pytest.mark.asyncio
async def test_overflow_increments_counter():
    service, dlq_repository, _ = _build_service(queue_maxsize=1)
    service._processing_queue.put_nowait({"payload": "existing"})

    for index in range(5):
        accepted = await service.process_telemetry_message(_telemetry_payload("DEVICE-BP-2"))
        assert accepted is False

    assert QUEUE_OVERFLOW_COUNTER[service._queue_name] == 5
    assert dlq_repository.send.call_count == 5
    metric_value = QUEUE_OVERFLOW_TOTAL.labels(
        queue_name=service._queue_name,
        device_id="DEVICE-BP-2",
    )._value.get()
    assert metric_value == 5


@pytest.mark.asyncio
async def test_overflow_logs_warning():
    service, _, _ = _build_service(queue_maxsize=1)
    service._processing_queue.put_nowait({"payload": "existing"})

    with patch.object(telemetry_service_module.logger, "warning") as warning_mock:
        accepted = await service.process_telemetry_message(_telemetry_payload("DEVICE-BP-3"))

    assert accepted is False
    warning_mock.assert_called_once()
    assert warning_mock.call_args.kwargs["device_id"] == "DEVICE-BP-3"
    assert warning_mock.call_args.kwargs["queue"] == service._queue_name


@pytest.mark.asyncio
async def test_no_silent_drop():
    service, dlq_repository, _ = _build_service(queue_maxsize=1)
    service._processing_queue.put_nowait({"payload": "existing"})

    for index in range(10):
        accepted = await service.process_telemetry_message(_telemetry_payload(f"DEVICE-BP-4-{index}"))
        assert accepted is False

    assert dlq_repository.send.call_count == 10
    assert QUEUE_OVERFLOW_COUNTER[service._queue_name] == 10


@pytest.mark.asyncio
async def test_queue_drains_on_shutdown():
    service, _, outbox_repository = _build_service(queue_maxsize=100)
    processed_devices: list[str] = []

    async def _slow_process(payload, correlation_id, raw_payload):
        processed_devices.append(payload.device_id)
        await asyncio.sleep(0.02)

    service._process_telemetry_async = AsyncMock(side_effect=_slow_process)

    await service.start()
    for index in range(20):
        accepted = await service.process_telemetry_message(_telemetry_payload(f"DEVICE-BP-5-{index}"))
        assert accepted is True

    await asyncio.wait_for(service.close(), timeout=10)

    assert len(processed_devices) == 20
    assert service._worker_task is None
    assert service._queue_monitor_task is None
