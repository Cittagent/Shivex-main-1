from __future__ import annotations

import asyncio
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pymysql
import pytest
import pytest_asyncio
from sqlalchemy import text
from unittest.mock import AsyncMock
from fastapi.encoders import jsonable_encoder

from src.config import settings
from src.models import EnrichmentStatus, OutboxStatus, OutboxTarget, TelemetryPayload, TelemetryPoint
from src.repositories import DLQRepository, OutboxRepository
from src.utils.circuit_breaker import _BREAKERS
from src.services.outbox_relay import OutboxRelayService
from src.services.reconciliation import ReconciliationService
from src.services.retention_cleanup import RetentionCleanupService
from src.services.telemetry_service import TelemetryService


class FakeInfluxRepository:
    def __init__(self, latest_map: dict[str, TelemetryPoint] | None = None):
        self.latest_map = latest_map or {}
        self.writes: list[dict[str, Any]] = []

    def write_telemetry(self, payload) -> bool:
        self.writes.append(payload.model_dump(mode="json"))
        return True

    def get_latest_telemetry_batch(
        self,
        tenant_id: str,
        device_ids: list[str],
    ) -> dict[str, TelemetryPoint | None]:
        return {device_id: self.latest_map.get(device_id) for device_id in device_ids}

    def close(self) -> None:
        return None


class FakeEnrichmentService:
    async def enrich_telemetry(self, payload):
        return payload

    async def close(self) -> None:
        return None


class FakeRuleEngineClient:
    async def evaluate_rules(self, payload, projection_state=None) -> None:
        return None

    async def close(self) -> None:
        return None


class FakeDeviceProjectionClient:
    async def sync_projection(self, payload) -> dict[str, Any]:
        return {
            "load_state": "idle",
            "idle_streak_started_at": payload.timestamp.isoformat(),
            "idle_streak_duration_sec": 0,
        }

    async def close(self) -> None:
        return None


def _mysql_conn():
    return pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_database,
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )


def _telemetry_payload(device_id: str = "DEVICE-OUTBOX-1", *, ts: datetime | None = None) -> dict[str, Any]:
    stamp = ts or datetime.now(timezone.utc)
    return {
        "device_id": device_id,
        "tenant_id": "SH00000001",
        "timestamp": stamp.isoformat(),
        "schema_version": "v1",
        "power": 120.5,
        "current": 0.8,
        "voltage": 229.7,
        "energy_kwh": 12.34,
    }


def _normalize_target(value: str) -> str:
    return value.lower().replace("_", "-")


async def _wait_for_queue(service: TelemetryService) -> None:
    await asyncio.wait_for(service._processing_queue.join(), timeout=5)
    await asyncio.sleep(0.05)


@pytest.fixture
def configure_outbox_settings(monkeypatch):
    monkeypatch.setattr(settings, "device_sync_enabled", True)
    monkeypatch.setattr(settings, "energy_sync_enabled", True)
    monkeypatch.setattr(settings, "outbox_poll_interval_sec", 0.1)
    monkeypatch.setattr(settings, "outbox_batch_size", 10)
    monkeypatch.setattr(settings, "outbox_max_retries", 5)
    monkeypatch.setattr(settings, "reconciliation_drift_warn_minutes", 10)
    monkeypatch.setattr(settings, "reconciliation_drift_resync_minutes", 30)


@pytest.fixture(autouse=True)
def reset_circuit_breakers():
    _BREAKERS.clear()
    yield
    _BREAKERS.clear()


@pytest_asyncio.fixture
async def repositories(configure_outbox_settings):
    outbox_repository = OutboxRepository()
    with _mysql_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS reconciliation_log")
            cur.execute("DROP TABLE IF EXISTS telemetry_outbox")
            cur.execute("DELETE FROM dlq_messages")
    await outbox_repository.ensure_schema()
    dlq_repository = DLQRepository()
    try:
        yield outbox_repository, dlq_repository
    finally:
        await outbox_repository.reset_tables()
        with _mysql_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM dlq_messages")
        dlq_repository.close()
        await outbox_repository.close()


@pytest.mark.asyncio
async def test_outbox_row_created_on_telemetry(repositories, monkeypatch):
    outbox_repository, dlq_repository = repositories
    influx_repository = FakeInfluxRepository()
    telemetry_service = TelemetryService(
        influx_repository=influx_repository,
        dlq_repository=dlq_repository,
        outbox_repository=outbox_repository,
        enrichment_service=FakeEnrichmentService(),
        rule_engine_client=FakeRuleEngineClient(),
        device_projection_client=FakeDeviceProjectionClient(),
    )

    async def _noop_broadcast(*args, **kwargs):
        return None

    monkeypatch.setattr("src.api.websocket.broadcast_telemetry", _noop_broadcast)
    telemetry_service._fetch_tenant_owned_device_ids = AsyncMock(return_value={"DEVICE-OUTBOX-1"})
    await telemetry_service.start()
    try:
        payload = _telemetry_payload()
        accepted = await telemetry_service.process_telemetry_message(payload)
        assert accepted is True
        await telemetry_service._process_telemetry_async(  # noqa: SLF001
            payload=TelemetryPayload(**payload),
            correlation_id="test-outbox-row-created",
            raw_payload=payload,
        )
        await telemetry_service._process_derived_async(  # noqa: SLF001
            payload=TelemetryPayload(**payload),
            correlation_id="test-outbox-row-created",
            outbox_payload=jsonable_encoder(payload),
            projection_synced=True,
            projection_state={"load_state": "idle"},
            projection_error=None,
        )
        async with outbox_repository.session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT target FROM telemetry_outbox "
                    "WHERE status = 'pending' AND device_id = 'DEVICE-OUTBOX-1' "
                    "ORDER BY id ASC"
                )
            )
            rows = [_normalize_target(row["target"]) for row in result.mappings().all()]
        assert len(rows) == 1
        assert set(rows) == {OutboxTarget.ENERGY_SERVICE.value}
    finally:
        await telemetry_service.close()


@pytest.mark.asyncio
async def test_outbox_delivered_on_success(repositories):
    outbox_repository, dlq_repository = repositories
    await outbox_repository.enqueue_telemetry(
        device_id="DEVICE-SUCCESS-1",
        telemetry_payload=_telemetry_payload("DEVICE-SUCCESS-1"),
        targets=[OutboxTarget.DEVICE_SERVICE],
        max_retries=5,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(status_code=200, json={"data": {"device_id": "DEVICE-SUCCESS-1"}})
        return httpx.Response(status_code=200, json={"success": True})

    relay = OutboxRelayService(
        outbox_repository=outbox_repository,
        dlq_repository=dlq_repository,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=10.0),
    )
    try:
        processed = await relay.run_once()
        assert processed >= 1
        rows = [row for row in await outbox_repository.list_messages() if row.device_id == "DEVICE-SUCCESS-1"]
        assert len(rows) == 1
        assert rows[0].status == OutboxStatus.DELIVERED
        assert rows[0].delivered_at is not None
    finally:
        await relay.stop()


@pytest.mark.asyncio
async def test_outbox_retries_on_failure(repositories):
    outbox_repository, dlq_repository = repositories
    await outbox_repository.enqueue_telemetry(
        device_id="DEVICE-RETRY-1",
        telemetry_payload=_telemetry_payload("DEVICE-RETRY-1"),
        targets=[OutboxTarget.DEVICE_SERVICE],
        max_retries=5,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(status_code=200, json={"data": {"device_id": "DEVICE-RETRY-1"}})
        return httpx.Response(status_code=503, json={"success": False})

    relay = OutboxRelayService(
        outbox_repository=outbox_repository,
        dlq_repository=dlq_repository,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=10.0),
    )
    try:
        await relay.run_once()
        row = (await outbox_repository.list_messages())[0]
        assert row.status == OutboxStatus.FAILED
        assert row.retry_count == 1
        assert row.last_attempted_at is not None
    finally:
        await relay.stop()


@pytest.mark.asyncio
async def test_outbox_run_once_drains_multiple_claim_batches(repositories, monkeypatch):
    outbox_repository, dlq_repository = repositories
    monkeypatch.setattr(settings, "outbox_batch_size", 10)
    monkeypatch.setattr(settings, "outbox_max_batches_per_run", 3)

    for idx in range(25):
        device_id = f"DEVICE-MULTI-{idx:03d}"
        await outbox_repository.enqueue_telemetry(
            device_id=device_id,
            telemetry_payload=_telemetry_payload(device_id),
            targets=[OutboxTarget.DEVICE_SERVICE],
            max_retries=5,
        )

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(status_code=200, json={"data": {"device_id": "ok"}})
        return httpx.Response(status_code=200, json={"success": True})

    relay = OutboxRelayService(
        outbox_repository=outbox_repository,
        dlq_repository=dlq_repository,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=10.0),
    )
    try:
        processed = await relay.run_once()
        assert processed == 25
        rows = [row for row in await outbox_repository.list_messages() if row.device_id.startswith("DEVICE-MULTI-")]
        assert len(rows) == 25
        assert all(row.status == OutboxStatus.DELIVERED for row in rows)
    finally:
        await relay.stop()


@pytest.mark.asyncio
async def test_outbox_dead_after_max_retries(repositories):
    outbox_repository, dlq_repository = repositories
    await outbox_repository.enqueue_telemetry(
        device_id="DEVICE-DEAD-1",
        telemetry_payload=_telemetry_payload("DEVICE-DEAD-1"),
        targets=[OutboxTarget.DEVICE_SERVICE],
        max_retries=1,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(status_code=200, json={"data": {"device_id": "DEVICE-DEAD-1"}})
        return httpx.Response(status_code=503, text="downstream unavailable")

    relay = OutboxRelayService(
        outbox_repository=outbox_repository,
        dlq_repository=dlq_repository,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=10.0),
    )
    try:
        await relay.run_once()
        row = (await outbox_repository.list_messages())[0]
        assert row.status == OutboxStatus.DEAD
        assert row.retry_count == 1
        with _mysql_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS count FROM dlq_messages WHERE error_type = 'outbox_delivery_dead'"
                )
                dlq_count = cur.fetchone()["count"]
        assert dlq_count == 1
    finally:
        await relay.stop()


@pytest.mark.asyncio
async def test_energy_outbox_is_delivered_via_batched_request(repositories, monkeypatch):
    outbox_repository, dlq_repository = repositories
    await outbox_repository.enqueue_telemetry_batch(
        entries=[
            ("DEVICE-ENERGY-B1", _telemetry_payload("DEVICE-ENERGY-B1"), [OutboxTarget.ENERGY_SERVICE]),
            ("DEVICE-ENERGY-B2", _telemetry_payload("DEVICE-ENERGY-B2"), [OutboxTarget.ENERGY_SERVICE]),
        ],
        max_retries=5,
    )
    monkeypatch.setattr(settings, "outbox_energy_delivery_batch_size", 10)
    seen_posts: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen_posts.append(request.url.path)
            return httpx.Response(
                status_code=200,
                json={
                    "success": True,
                    "results": [
                        {"success": True, "device_id": "DEVICE-ENERGY-B1", "retryable": False},
                        {"success": True, "device_id": "DEVICE-ENERGY-B2", "retryable": False},
                    ],
                },
            )
        return httpx.Response(status_code=404)

    relay = OutboxRelayService(
        outbox_repository=outbox_repository,
        dlq_repository=dlq_repository,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=10.0),
    )
    try:
        processed = await relay.run_once()
        assert processed == 2
        assert seen_posts == ["/api/v1/energy/live-update/batch"]
        rows = [row for row in await outbox_repository.list_messages() if row.device_id.startswith("DEVICE-ENERGY-B")]
        assert {row.status for row in rows} == {OutboxStatus.DELIVERED}
    finally:
        await relay.stop()


@pytest.mark.asyncio
async def test_energy_batch_partial_failure_isolated_per_row(repositories, monkeypatch):
    outbox_repository, dlq_repository = repositories
    await outbox_repository.enqueue_telemetry_batch(
        entries=[
            ("DEVICE-ENERGY-P1", _telemetry_payload("DEVICE-ENERGY-P1"), [OutboxTarget.ENERGY_SERVICE]),
            ("DEVICE-ENERGY-P2", _telemetry_payload("DEVICE-ENERGY-P2"), [OutboxTarget.ENERGY_SERVICE]),
        ],
        max_retries=5,
    )
    monkeypatch.setattr(settings, "outbox_energy_delivery_batch_size", 10)

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                status_code=200,
                json={
                    "success": True,
                    "results": [
                        {"success": True, "device_id": "DEVICE-ENERGY-P1", "retryable": False},
                        {
                            "success": False,
                            "device_id": "DEVICE-ENERGY-P2",
                            "error": "bad input",
                            "error_code": "INVALID_ENERGY_PAYLOAD",
                            "retryable": False,
                        },
                    ],
                },
            )
        return httpx.Response(status_code=404)

    relay = OutboxRelayService(
        outbox_repository=outbox_repository,
        dlq_repository=dlq_repository,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=10.0),
    )
    try:
        await relay.run_once()
        rows = {row.device_id: row for row in await outbox_repository.list_messages() if row.device_id.startswith("DEVICE-ENERGY-P")}
        assert rows["DEVICE-ENERGY-P1"].status == OutboxStatus.DELIVERED
        assert rows["DEVICE-ENERGY-P2"].status == OutboxStatus.DEAD
        assert rows["DEVICE-ENERGY-P2"].retry_count == 0
    finally:
        await relay.stop()


@pytest.mark.asyncio
async def test_reconciliation_detects_drift(repositories):
    outbox_repository, _ = repositories
    now = datetime.now(timezone.utc)
    latest_point = TelemetryPoint(
        timestamp=now,
        device_id="DEVICE-DRIFT-1",
        schema_version="v1",
        enrichment_status=EnrichmentStatus.SUCCESS,
        power=50.0,
    )
    influx_repository = FakeInfluxRepository(latest_map={"DEVICE-DRIFT-1": latest_point})

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/internal/active-tenant-ids"):
            return httpx.Response(status_code=200, json={"tenant_ids": ["SH00000001"]})
        assert request.url.path.endswith("/api/v1/devices/dashboard/fleet-snapshot")
        assert request.headers["x-internal-service"] == "data-service"
        assert request.headers["x-tenant-id"] == "SH00000001"
        assert request.url.params["page_size"] == "200"
        assert request.url.params["sort"] == "device_name"
        payload = {
            "success": True,
            "page": 1,
            "page_size": 200,
            "total_pages": 1,
            "devices": [
                {
                    "device_id": "DEVICE-DRIFT-1",
                    "last_seen_timestamp": (now - timedelta(minutes=40)).isoformat(),
                }
            ],
        }
        return httpx.Response(status_code=200, json=payload)

    service = ReconciliationService(
        influx_repository=influx_repository,
        outbox_repository=outbox_repository,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=10.0),
    )
    try:
        await service.run_once()
        rows = [
            row
            for row in await outbox_repository.list_messages(status=OutboxStatus.PENDING)
            if row.device_id == "DEVICE-DRIFT-1"
        ]
        assert len(rows) == 2
        async with outbox_repository.session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT drift_seconds, action_taken FROM reconciliation_log "
                    "WHERE device_id = 'DEVICE-DRIFT-1' ORDER BY id DESC LIMIT 1"
                )
            )
            record = result.mappings().one()
        assert record["action_taken"] == "resync_enqueued"
        assert int(record["drift_seconds"]) >= 1800
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_no_double_delivery(repositories, monkeypatch):
    outbox_repository, dlq_repository = repositories
    monkeypatch.setattr(settings, "outbox_batch_size", 2)
    delivery_counts: Counter[str] = Counter()

    for index in range(6):
        await outbox_repository.enqueue_telemetry(
            device_id=f"DEVICE-LOCK-{index}",
            telemetry_payload=_telemetry_payload(f"DEVICE-LOCK-{index}"),
            targets=[OutboxTarget.DEVICE_SERVICE],
            max_retries=5,
        )

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            device_id = request.url.path.rstrip("/").split("/")[-1]
            return httpx.Response(status_code=200, json={"data": {"device_id": device_id}})
        device_id = request.url.path.split("/")[-2]
        delivery_counts[device_id] += 1
        await asyncio.sleep(0.05)
        return httpx.Response(status_code=200, json={"success": True})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=10.0)
    relay_one = OutboxRelayService(
        outbox_repository=outbox_repository,
        dlq_repository=dlq_repository,
        http_client=client,
    )
    relay_two = OutboxRelayService(
        outbox_repository=outbox_repository,
        dlq_repository=dlq_repository,
        http_client=client,
    )

    try:
        await relay_one.start()
        await relay_two.start()
        await asyncio.sleep(1.0)
        async with outbox_repository.session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT COUNT(*) AS count FROM telemetry_outbox "
                    "WHERE status = 'delivered' AND device_id LIKE 'DEVICE-LOCK-%'"
                )
            )
            delivered_count = result.mappings().one()["count"]
        assert delivered_count == 6
        relevant_counts = {
            device_id: count
            for device_id, count in delivery_counts.items()
            if device_id.startswith("DEVICE-LOCK-")
        }
        assert all(count == 1 for count in relevant_counts.values())
        assert len(relevant_counts) == 6
    finally:
        await relay_one.stop()
        await relay_two.stop()


@pytest.mark.asyncio
async def test_retention_cleanup_purges_old_operational_rows(repositories, monkeypatch):
    outbox_repository, dlq_repository = repositories
    old_ts = datetime.utcnow() - timedelta(days=30)
    recent_ts = datetime.utcnow()
    monkeypatch.setattr(settings, "outbox_delivered_retention_days", 7)
    monkeypatch.setattr(settings, "outbox_dead_retention_days", 14)
    monkeypatch.setattr(settings, "reconciliation_log_retention_days", 14)
    monkeypatch.setattr(settings, "dlq_retention_days", 14)

    async with outbox_repository.session_factory() as session:
        async with session.begin():
            await session.execute(
                text(
                    """
                    INSERT INTO telemetry_outbox
                      (device_id, telemetry_json, target, status, retry_count, max_retries, created_at, delivered_at, last_attempted_at)
                    VALUES
                      ('OLD-DELIVERED', '{}', 'device-service', 'delivered', 0, 5, :old_ts, :old_ts, :old_ts),
                      ('OLD-DEAD', '{}', 'device-service', 'dead', 5, 5, :old_ts, NULL, :old_ts),
                      ('RECENT-DELIVERED', '{}', 'device-service', 'delivered', 0, 5, :recent_ts, :recent_ts, :recent_ts),
                      ('OLD-PENDING', '{}', 'device-service', 'pending', 0, 5, :old_ts, NULL, NULL)
                    """
                ),
                {"old_ts": old_ts, "recent_ts": recent_ts},
            )
            await session.execute(
                text(
                    """
                    INSERT INTO reconciliation_log
                      (device_id, checked_at, action_taken)
                    VALUES ('OLD-RECON', :old_ts, 'noop')
                    """
                ),
                {"old_ts": old_ts},
            )

    with _mysql_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO dlq_messages
                  (timestamp, error_type, error_message, retry_count, original_payload, status, created_at)
                VALUES
                  (%s, 'parse_error', 'old', 0, JSON_OBJECT('device_id', 'OLD-DLQ'), 'pending', %s),
                  (%s, 'parse_error', 'recent', 0, JSON_OBJECT('device_id', 'RECENT-DLQ'), 'pending', %s)
                """,
                (old_ts, old_ts, recent_ts, recent_ts),
            )

    cleanup = RetentionCleanupService(
        outbox_repository=outbox_repository,
        dlq_repository=dlq_repository,
        interval_seconds=3600,
        batch_size=100,
    )
    counts = await cleanup.run_once()

    assert counts["telemetry_outbox_delivered"] == 1
    assert counts["telemetry_outbox_dead"] == 1
    assert counts["reconciliation_log"] == 1
    assert counts["dlq_messages"] == 1

    async with outbox_repository.session_factory() as session:
        result = await session.execute(
            text(
                """
                SELECT device_id FROM telemetry_outbox
                WHERE device_id IN ('OLD-DEAD', 'OLD-DELIVERED', 'RECENT-DELIVERED', 'OLD-PENDING')
                ORDER BY device_id ASC
                """
            )
        )
        remaining_outbox = [row["device_id"] for row in result.mappings().all()]
    assert remaining_outbox == ["OLD-PENDING", "RECENT-DELIVERED"]

    with _mysql_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT JSON_UNQUOTE(JSON_EXTRACT(original_payload, '$.device_id')) AS device_id
                FROM dlq_messages
                WHERE JSON_UNQUOTE(JSON_EXTRACT(original_payload, '$.device_id')) IN ('OLD-DLQ', 'RECENT-DLQ')
                """
            )
            remaining_dlq = [row["device_id"] for row in cur.fetchall()]
    assert remaining_dlq == ["RECENT-DLQ"]


@pytest.mark.asyncio
async def test_retention_cleanup_reclassifies_non_retryable_pending_dlq_rows(repositories, monkeypatch):
    outbox_repository, dlq_repository = repositories
    now = datetime.utcnow()
    monkeypatch.setattr(settings, "dlq_retryable_error_types", ["parse_error"])

    with _mysql_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO dlq_messages
                  (timestamp, error_type, error_message, retry_count, original_payload, status, created_at)
                VALUES
                  (%s, 'rule_engine_circuit_open', 'circuit open', 0, JSON_OBJECT('device_id', 'NONRETRY-DLQ'), 'pending', %s),
                  (%s, 'parse_error', 'retryable', 0, JSON_OBJECT('device_id', 'RETRYABLE-DLQ'), 'pending', %s)
                """,
                (now, now, now, now),
            )

    cleanup = RetentionCleanupService(
        outbox_repository=outbox_repository,
        dlq_repository=dlq_repository,
        interval_seconds=3600,
        batch_size=100,
    )
    counts = await cleanup.run_once()

    assert counts["dlq_reclassified_non_retryable"] == 1

    with _mysql_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  JSON_UNQUOTE(JSON_EXTRACT(original_payload, '$.device_id')) AS device_id,
                  status
                FROM dlq_messages
                WHERE JSON_UNQUOTE(JSON_EXTRACT(original_payload, '$.device_id')) IN ('NONRETRY-DLQ', 'RETRYABLE-DLQ')
                ORDER BY device_id ASC
                """
            )
            rows = cur.fetchall()

    by_device = {row["device_id"]: row["status"] for row in rows}
    assert by_device["NONRETRY-DLQ"] == "dead"
    assert by_device["RETRYABLE-DLQ"] == "pending"
