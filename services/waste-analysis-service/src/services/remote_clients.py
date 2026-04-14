from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from src.config import settings
from services.shared.tariff_client import fetch_tenant_tariff

logger = logging.getLogger(__name__)
INTERNAL_HEADERS = {"X-Internal-Service": "waste-analysis-service"}


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


@dataclass
class TariffSnapshot:
    rate: Optional[float]
    currency: str
    configured: bool
    stale: bool = False


class TariffCache:
    def __init__(self):
        self._snapshot: dict[str | None, TariffSnapshot] = {}
        self._expires_at: dict[str | None, float] = {}

    async def get(self, tenant_id: str | None) -> TariffSnapshot:
        now = time.time()
        snapshot = self._snapshot.get(tenant_id)
        expires_at = self._expires_at.get(tenant_id, 0.0)
        if snapshot and now < expires_at:
            return snapshot

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                payload = await fetch_tenant_tariff(
                    client,
                    settings.REPORTING_SERVICE_URL,
                    tenant_id,
                    service_name="waste-analysis-service",
                )
                rate = payload.get("rate")
                currency = (payload.get("currency") or "INR").upper()
                configured = bool(payload.get("configured"))
                snapshot = TariffSnapshot(
                    rate=float(rate) if rate is not None else None,
                    currency=currency,
                    configured=configured,
                )
                self._snapshot[tenant_id] = snapshot
                self._expires_at[tenant_id] = now + max(1, settings.TARIFF_CACHE_TTL_SECONDS)
                return snapshot
        except Exception as exc:  # pragma: no cover
            logger.warning("tariff_fetch_failed", error=str(exc))
            if snapshot:
                return TariffSnapshot(
                    rate=snapshot.rate,
                    currency=snapshot.currency,
                    configured=snapshot.configured,
                    stale=True,
                )
            return TariffSnapshot(rate=None, currency="INR", configured=False, stale=True)


class DeviceClient:
    async def list_devices(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {**INTERNAL_HEADERS, **({"X-Tenant-Id": tenant_id} if tenant_id else {})}
            resp = await client.get(
                f"{settings.DEVICE_SERVICE_URL}/api/v1/devices",
                params={"tenant_id": tenant_id} if tenant_id else None,
                headers=headers,
            )
            if resp.status_code != 200:
                return []
            payload = resp.json()
            return payload if isinstance(payload, list) else payload.get("data", [])

    async def get_device(self, device_id: str, tenant_id: str | None = None) -> Optional[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            headers = {**INTERNAL_HEADERS, **({"X-Tenant-Id": tenant_id} if tenant_id else {})}
            resp = await client.get(
                f"{settings.DEVICE_SERVICE_URL}/api/v1/devices/{device_id}",
                params={"tenant_id": tenant_id} if tenant_id else None,
                headers=headers,
            )
            if resp.status_code != 200:
                return None
            payload = resp.json()
            if isinstance(payload, dict):
                return payload.get("data", payload)
            return None

    async def get_shift_config(self, device_id: str, tenant_id: str | None = None) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            headers = {**INTERNAL_HEADERS, **({"X-Tenant-Id": tenant_id} if tenant_id else {})}
            resp = await client.get(
                f"{settings.DEVICE_SERVICE_URL}/api/v1/devices/{device_id}/shifts",
                params={"tenant_id": tenant_id} if tenant_id else None,
                headers=headers,
            )
            if resp.status_code != 200:
                return []
            payload = resp.json()
            return payload.get("data", []) if isinstance(payload, dict) else []

    async def get_idle_config(self, device_id: str, tenant_id: str | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            headers = {**INTERNAL_HEADERS, **({"X-Tenant-Id": tenant_id} if tenant_id else {})}
            resp = await client.get(
                f"{settings.DEVICE_SERVICE_URL}/api/v1/devices/{device_id}/idle-config",
                params={"tenant_id": tenant_id} if tenant_id else None,
                headers=headers,
            )
            if resp.status_code != 200:
                return {}
            payload = resp.json()
            cfg = payload.get("data", payload) if isinstance(payload, dict) else {}
            if not isinstance(cfg, dict):
                return {}
            return {
                "device_id": cfg.get("device_id") or device_id,
                "configured": bool(cfg.get("configured")),
                "full_load_current_a": _to_float(cfg.get("full_load_current_a")),
                "idle_threshold_pct_of_fla": _to_float(cfg.get("idle_threshold_pct_of_fla")),
                "derived_idle_threshold_a": _to_float(
                    cfg.get("derived_idle_threshold_a") or cfg.get("idle_current_threshold")
                ),
                "derived_overconsumption_threshold_a": _to_float(cfg.get("derived_overconsumption_threshold_a")),
                "idle_current_threshold": _to_float(cfg.get("idle_current_threshold")),
            }

    async def get_waste_config(self, device_id: str, tenant_id: str | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            headers = {**INTERNAL_HEADERS, **({"X-Tenant-Id": tenant_id} if tenant_id else {})}
            resp = await client.get(
                f"{settings.DEVICE_SERVICE_URL}/api/v1/devices/{device_id}/waste-config",
                params={"tenant_id": tenant_id} if tenant_id else None,
                headers=headers,
            )
            if resp.status_code != 200:
                return {}
            payload = resp.json()
            cfg = payload.get("data", payload) if isinstance(payload, dict) else {}
            if not isinstance(cfg, dict):
                return {}
            return {
                **cfg,
                "full_load_current_a": _to_float(cfg.get("full_load_current_a")),
                "idle_threshold_pct_of_fla": _to_float(cfg.get("idle_threshold_pct_of_fla")),
                "derived_idle_threshold_a": _to_float(
                    cfg.get("derived_idle_threshold_a") or cfg.get("idle_current_threshold")
                ),
                "derived_overconsumption_threshold_a": _to_float(
                    cfg.get("derived_overconsumption_threshold_a")
                    or cfg.get("overconsumption_current_threshold_a")
                ),
                "idle_current_threshold": _to_float(cfg.get("idle_current_threshold")),
                "overconsumption_current_threshold_a": _to_float(cfg.get("overconsumption_current_threshold_a")),
            }

    async def get_site_waste_config(self, tenant_id: str | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            headers = {**INTERNAL_HEADERS, **({"X-Tenant-Id": tenant_id} if tenant_id else {})}
            resp = await client.get(
                f"{settings.DEVICE_SERVICE_URL}/api/v1/settings/waste-config",
                params={"tenant_id": tenant_id} if tenant_id else None,
                headers=headers,
            )
            if resp.status_code != 200:
                return {}
            payload = resp.json()
            return payload.get("data", payload) if isinstance(payload, dict) else {}


class EnergyClient:
    async def get_device_range(
        self,
        device_id: str,
        start_date: str,
        end_date: str,
        tenant_id: str | None = None,
    ) -> Optional[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=20.0) as client:
            headers = {**INTERNAL_HEADERS, **({"X-Tenant-Id": tenant_id} if tenant_id else {})}
            resp = await client.get(
                f"{settings.ENERGY_SERVICE_URL}/api/v1/energy/device/{device_id}/range",
                params={
                    "start_date": start_date,
                    "end_date": end_date,
                    **({"tenant_id": tenant_id} if tenant_id else {}),
                },
                headers=headers,
            )
            if resp.status_code != 200:
                return None
            payload = resp.json()
            if not isinstance(payload, dict) or not payload.get("success"):
                return None
            return payload


tariff_cache = TariffCache()
device_client = DeviceClient()
energy_client = EnergyClient()
