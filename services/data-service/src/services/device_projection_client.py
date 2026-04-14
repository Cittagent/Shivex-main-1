"""Client for synchronous device live projection updates."""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.config import settings
from src.models import TelemetryPayload
from src.utils import get_logger
from src.utils.circuit_breaker import get_or_create_circuit_breaker
from services.shared.tenant_context import build_internal_headers

logger = get_logger(__name__)


class DeviceProjectionSyncError(Exception):
    """Raised when live projection sync fails."""

    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


class DeviceProjectionClient:
    """Synchronously updates device-service live projection for accepted telemetry."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        self.base_url = (base_url or settings.device_service_url).rstrip("/")
        self.timeout = timeout or settings.device_service_timeout
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout),
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
        )
        self.circuit_breaker = get_or_create_circuit_breaker(
            "device-service-live-update",
            failure_threshold=settings.circuit_breaker_failure_threshold,
            success_threshold=settings.circuit_breaker_success_threshold,
            open_timeout_sec=settings.circuit_breaker_open_timeout_sec,
        )

    async def sync_projection(self, payload: TelemetryPayload) -> dict[str, Any]:
        tenant_id = self._resolve_tenant_id(payload)
        request_body = self._build_request_data(payload, tenant_id)
        success, response = await self.circuit_breaker.call(
            lambda: self._send_projection_request(payload.device_id, tenant_id, request_body)
        )
        if not success or response is None:
            raise DeviceProjectionSyncError("device_projection_circuit_open", retryable=True)

        if response.status_code >= 400:
            if 400 <= response.status_code < 500:
                raise DeviceProjectionSyncError(
                    f"device_projection_client_error:{response.status_code}",
                    retryable=False,
                )
            raise DeviceProjectionSyncError(
                f"device_projection_server_error:{response.status_code}",
                retryable=True,
            )

        payload_json = response.json()
        device_payload = payload_json.get("device") if isinstance(payload_json, dict) else None
        if not isinstance(device_payload, dict):
            raise DeviceProjectionSyncError("device_projection_invalid_response", retryable=True)
        return device_payload

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, asyncio.TimeoutError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _send_projection_request(
        self,
        device_id: str,
        tenant_id: str,
        request_body: dict[str, Any],
    ) -> httpx.Response:
        response = await self.client.post(
            f"{self.base_url}/api/v1/devices/{device_id}/live-update",
            json=request_body,
            headers=build_internal_headers("data-service", tenant_id),
        )
        if response.status_code >= 500:
            response.raise_for_status()
        return response

    @staticmethod
    def _resolve_tenant_id(payload: TelemetryPayload) -> str:
        payload_tenant_id = DeviceProjectionClient._normalize_tenant_id(payload.tenant_id)
        metadata_tenant_id = DeviceProjectionClient._normalize_tenant_id(
            None if payload.device_metadata is None else payload.device_metadata.tenant_id
        )

        if payload_tenant_id and metadata_tenant_id and payload_tenant_id != metadata_tenant_id:
            raise DeviceProjectionSyncError(
                "Telemetry tenant scope does not match device metadata tenant.",
                retryable=False,
            )

        tenant_id = payload_tenant_id or metadata_tenant_id
        if tenant_id is None:
            raise DeviceProjectionSyncError(
                "Telemetry tenant scope is required for projection sync.",
                retryable=False,
            )
        return tenant_id

    @staticmethod
    def _normalize_tenant_id(value: object | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @staticmethod
    def _build_request_data(payload: TelemetryPayload, tenant_id: str) -> dict[str, Any]:
        dynamic_fields = payload.get_dynamic_fields()
        telemetry_payload = payload.model_dump(mode="json")
        return {
            "tenant_id": tenant_id,
            "telemetry": telemetry_payload,
            "dynamic_fields": dynamic_fields,
        }

    async def close(self) -> None:
        await self.client.aclose()
        logger.info("DeviceProjectionClient HTTP client closed")
