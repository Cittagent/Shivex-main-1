from __future__ import annotations

import asyncio

import httpx

from services.shared.tariff_client import build_internal_headers, fetch_tenant_tariff


class _FakeAsyncClient:
    def __init__(self, responses: list[tuple[int, dict[str, object]]]):
        self._responses = responses
        self.calls: list[tuple[str, dict[str, str] | None]] = []

    async def get(self, url: str, headers: dict[str, str] | None = None):
        self.calls.append((url, headers))
        status, payload = self._responses[len(self.calls) - 1]
        request = httpx.Request("GET", url)
        return httpx.Response(status, json=payload, request=request)


def test_fetch_tenant_tariff_prefers_tenant_route_and_sets_internal_headers():
    client = _FakeAsyncClient(
        [
            (
                200,
                {
                    "rate": 12.5,
                    "currency": "INR",
                    "updated_at": "2026-04-03T00:00:00",
                },
            )
        ]
    )

    payload = asyncio.run(
        fetch_tenant_tariff(
            client,  # type: ignore[arg-type]
            "http://reporting-service",
            "tenant-123",
            service_name="device-service",
        )
    )

    assert payload["rate"] == 12.5
    assert payload["currency"] == "INR"
    assert payload["source"] == "tenant_tariffs"
    assert len(client.calls) == 1
    url, headers = client.calls[0]
    assert url.endswith("/api/v1/settings/tariff")
    assert headers == build_internal_headers("device-service", "tenant-123")


def test_fetch_tenant_tariff_returns_unconfigured_without_fallback_when_missing():
    client = _FakeAsyncClient(
        [
            (200, {"rate": None, "currency": "INR", "updated_at": None}),
        ]
    )

    payload = asyncio.run(
        fetch_tenant_tariff(
            client,  # type: ignore[arg-type]
            "http://reporting-service",
            "tenant-456",
            service_name="device-service",
        )
    )

    assert payload["rate"] == 0.0
    assert payload["currency"] == "INR"
    assert payload["configured"] is False
    assert payload["source"] == "default_unconfigured"
    assert len(client.calls) == 1
    assert client.calls[0][0].endswith("/api/v1/settings/tariff")


def test_fetch_tenant_tariff_fails_closed_without_tenant_scope():
    client = _FakeAsyncClient([])

    payload = asyncio.run(
        fetch_tenant_tariff(
            client,  # type: ignore[arg-type]
            "http://reporting-service",
            None,
            service_name="device-service",
        )
    )

    assert payload == {
        "rate": 0.0,
        "currency": "INR",
        "configured": False,
        "source": "tenant_scope_required",
    }
    assert client.calls == []
