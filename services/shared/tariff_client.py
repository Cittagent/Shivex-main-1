from __future__ import annotations

from typing import Any, Optional

import httpx

from services.shared.tenant_context import build_internal_headers


async def fetch_tenant_tariff(
    client: httpx.AsyncClient,
    reporting_base_url: str,
    tenant_id: Optional[str],
    *,
    service_name: str,
) -> dict[str, Any]:
    base = (reporting_base_url or "").rstrip("/")
    if not base:
        return {"rate": 0.0, "currency": "INR", "configured": False, "source": "missing_base_url"}

    if not tenant_id:
        return {"rate": 0.0, "currency": "INR", "configured": False, "source": "tenant_scope_required"}

    response = await client.get(
        f"{base}/api/v1/settings/tariff",
        headers=build_internal_headers(service_name, tenant_id),
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data", payload) if isinstance(payload, dict) else {}
    rate = data.get("rate")
    configured = rate is not None
    return {
        "rate": float(rate) if configured else 0.0,
        "currency": str(data.get("currency") or "INR"),
        "configured": configured,
        "source": "tenant_tariffs" if configured else "default_unconfigured",
    }
