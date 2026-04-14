from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any

import httpx

from app.config import settings
from app.utils.circuit_breaker import get_or_create_circuit_breaker
from app.services.internal_http import internal_get


class DeviceMetaCache:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._cache: dict[tuple[str | None, str], tuple[float, dict[str, Any]]] = {}
        self._breaker = get_or_create_circuit_breaker(
            "device-service",
            failure_threshold=settings.CIRCUIT_BREAKER_FAILURE_THRESHOLD,
            success_threshold=settings.CIRCUIT_BREAKER_SUCCESS_THRESHOLD,
            open_timeout_sec=settings.CIRCUIT_BREAKER_OPEN_TIMEOUT_SEC,
        )

    async def get(self, device_id: str, tenant_id: str | None = None) -> dict[str, Any]:
        now = time.monotonic()
        cache_key = (tenant_id, device_id)
        cached = self._cache.get(cache_key)
        if cached and cached[0] > now:
            return cached[1]

        async with self._lock:
            now = time.monotonic()
            cached = self._cache.get(cache_key)
            if cached and cached[0] > now:
                return cached[1]

            data = {
                "idle_threshold": None,
                "over_threshold": None,
                "shifts": [],
                "device_name": device_id,
                "energy_flow_mode": "consumption_only",
                "polarity_mode": "normal",
            }
            try:
                async with httpx.AsyncClient(timeout=2.5) as client:
                    success, dev_r = await self._breaker.call(
                        lambda: internal_get(
                            client,
                            f"{settings.DEVICE_SERVICE_BASE_URL}/api/v1/devices/{device_id}",
                            service_name="energy-service",
                            tenant_id=tenant_id,
                        )
                    )
                    if not success or dev_r is None:
                        self._cache[cache_key] = (time.monotonic() + 60.0, data)
                        return data
                    if dev_r.status_code == 200:
                        dev_payload = dev_r.json()
                        dev_data = dev_payload.get("data", dev_payload)
                        if isinstance(dev_data, dict):
                            data["device_name"] = dev_data.get("device_name") or device_id
                            data["energy_flow_mode"] = dev_data.get("energy_flow_mode") or "consumption_only"
                            data["polarity_mode"] = dev_data.get("polarity_mode") or "normal"
                    success, idle_r = await self._breaker.call(
                        lambda: internal_get(
                            client,
                            f"{settings.DEVICE_SERVICE_BASE_URL}/api/v1/devices/{device_id}/idle-config",
                            service_name="energy-service",
                            tenant_id=tenant_id,
                        )
                    )
                    if not success or idle_r is None:
                        self._cache[cache_key] = (time.monotonic() + 60.0, data)
                        return data
                    if idle_r.status_code == 200:
                        idle_payload = idle_r.json()
                        idle = idle_payload.get("data", idle_payload) if isinstance(idle_payload, dict) else {}
                        if isinstance(idle, dict):
                            data["idle_threshold"] = idle.get("idle_current_threshold")
                    success, waste_r = await self._breaker.call(
                        lambda: internal_get(
                            client,
                            f"{settings.DEVICE_SERVICE_BASE_URL}/api/v1/devices/{device_id}/waste-config",
                            service_name="energy-service",
                            tenant_id=tenant_id,
                        )
                    )
                    if not success or waste_r is None:
                        self._cache[cache_key] = (time.monotonic() + 60.0, data)
                        return data
                    if waste_r.status_code == 200:
                        waste_payload = waste_r.json()
                        waste = waste_payload.get("data", waste_payload) if isinstance(waste_payload, dict) else {}
                        if isinstance(waste, dict):
                            data["over_threshold"] = waste.get("overconsumption_current_threshold_a")
                    success, shift_r = await self._breaker.call(
                        lambda: internal_get(
                            client,
                            f"{settings.DEVICE_SERVICE_BASE_URL}/api/v1/devices/{device_id}/shifts",
                            service_name="energy-service",
                            tenant_id=tenant_id,
                        )
                    )
                    if not success or shift_r is None:
                        self._cache[cache_key] = (time.monotonic() + 60.0, data)
                        return data
                    if shift_r.status_code == 200:
                        shift_payload = shift_r.json()
                        rows = shift_payload.get("data", shift_payload if isinstance(shift_payload, list) else [])
                        if isinstance(rows, list):
                            data["shifts"] = [s for s in rows if isinstance(s, dict) and s.get("is_active", True)]
            except Exception:
                pass

            self._cache[cache_key] = (time.monotonic() + 60.0, data)
            return data


meta_cache = DeviceMetaCache()


def parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=datetime.UTC)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=datetime.UTC)
