from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SERVICES_DIR = PROJECT_ROOT / "services"
for path in (PROJECT_ROOT, SERVICES_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from src.models import DeviceMetadata, EnrichmentStatus, TelemetryPayload
from src.services.rule_engine_client import RuleEngineClient


class _FakeResponse:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code

    def raise_for_status(self) -> None:
        return None


class _FakeHttpClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def post(self, url: str, json: dict[str, object], headers: dict[str, str]):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return _FakeResponse()

    async def aclose(self) -> None:
        return None


class _FakeCircuitBreaker:
    async def call(self, fn):
        return True, await fn()

    def get_state(self) -> str:
        return "CLOSED"


def _payload(*, tenant_id: str | None, metadata_tenant_id: str | None = None) -> TelemetryPayload:
    metadata = None
    if metadata_tenant_id is not None:
        metadata = DeviceMetadata(
            id="DEVICE-1",
            tenant_id=metadata_tenant_id,
            name="Device 1",
            type="meter",
            location="Plant",
            status="online",
        )
    return TelemetryPayload(
        device_id="DEVICE-1",
        tenant_id=tenant_id,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        enrichment_status=EnrichmentStatus.SUCCESS,
        device_metadata=metadata,
        power=15.0,
    )


@pytest.mark.asyncio
async def test_rule_engine_client_sends_tenant_scoped_internal_headers() -> None:
    client = RuleEngineClient(base_url="http://rule-engine", timeout=1.0, max_retries=1, retry_delay=0.1)
    fake_http = _FakeHttpClient()
    client.client = fake_http
    client.circuit_breaker = _FakeCircuitBreaker()

    await client.evaluate_rules(_payload(tenant_id="ORG-A", metadata_tenant_id="ORG-A"))

    assert len(fake_http.calls) == 1
    headers = fake_http.calls[0]["headers"]
    assert headers == {
        "X-Internal-Service": "data-service",
        "X-Tenant-Id": "ORG-A",
    }
    assert "tenant_id" not in fake_http.calls[0]["json"]
    await client.close()


@pytest.mark.asyncio
async def test_rule_engine_client_fails_closed_without_tenant_scope() -> None:
    client = RuleEngineClient(base_url="http://rule-engine", timeout=1.0, max_retries=1, retry_delay=0.1)
    fake_http = _FakeHttpClient()
    client.client = fake_http
    client.circuit_breaker = _FakeCircuitBreaker()

    await client.evaluate_rules(_payload(tenant_id=None, metadata_tenant_id=None))

    assert fake_http.calls == []
    await client.close()


@pytest.mark.asyncio
async def test_rule_engine_client_rejects_mismatched_payload_and_device_tenants() -> None:
    client = RuleEngineClient(base_url="http://rule-engine", timeout=1.0, max_retries=1, retry_delay=0.1)
    fake_http = _FakeHttpClient()
    client.client = fake_http
    client.circuit_breaker = _FakeCircuitBreaker()

    await client.evaluate_rules(_payload(tenant_id="ORG-A", metadata_tenant_id="ORG-B"))

    assert fake_http.calls == []
    await client.close()
