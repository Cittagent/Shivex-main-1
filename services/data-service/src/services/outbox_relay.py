"""Background relay that delivers telemetry outbox rows to downstream services."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx

from src.config import settings
from src.models import OutboxMessage, OutboxStatus, OutboxTarget
from src.repositories import DLQRepository, OutboxRepository
from services.shared.telemetry_normalization import normalize_telemetry_sample
from services.shared.tenant_context import build_internal_headers
from src.utils.circuit_breaker import get_or_create_circuit_breaker
from src.utils import get_logger

logger = get_logger(__name__)


def _dynamic_fields(payload: dict[str, Any]) -> dict[str, Any]:
    excluded = {
        "device_id",
        "tenant_id",
        "timestamp",
        "schema_version",
        "enrichment_status",
        "device_metadata",
        "enriched_at",
    }
    return {key: value for key, value in payload.items() if key not in excluded}


def _tenant_id_from_payload(payload: dict[str, Any]) -> str | None:
    tenant_id = payload.get("tenant_id")
    if tenant_id is None:
        return None
    tenant_id_str = str(tenant_id).strip()
    return tenant_id_str or None


class OutboxRelayService:
    """Polls and delivers pending outbox rows."""

    def __init__(
        self,
        *,
        outbox_repository: OutboxRepository | None = None,
        dlq_repository: DLQRepository | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.outbox_repository = outbox_repository or OutboxRepository()
        self.dlq_repository = dlq_repository or DLQRepository()
        self._http_client = http_client
        self._owns_http_client = http_client is None
        self._task: asyncio.Task | None = None
        self._stopped = asyncio.Event()
        self.device_circuit_breaker = get_or_create_circuit_breaker(
            "device-service",
            failure_threshold=settings.circuit_breaker_failure_threshold,
            success_threshold=settings.circuit_breaker_success_threshold,
            open_timeout_sec=settings.circuit_breaker_open_timeout_sec,
        )
        self.energy_circuit_breaker = get_or_create_circuit_breaker(
            "energy-service",
            failure_threshold=settings.circuit_breaker_failure_threshold,
            success_threshold=settings.circuit_breaker_success_threshold,
            open_timeout_sec=settings.circuit_breaker_open_timeout_sec,
        )

    async def start(self) -> None:
        await self.outbox_repository.ensure_schema()
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=10.0)
        self._stopped.clear()
        self._task = asyncio.create_task(self._run(), name="telemetry-outbox-relay")
        logger.info("Outbox relay started")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._owns_http_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None
        self._stopped.set()
        logger.info("Outbox relay stopped")

    async def run_once(self) -> int:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=10.0)
            self._owns_http_client = True
        async with self.outbox_repository.session_factory() as session:
            async with session.begin():
                messages = await self.outbox_repository.claim_pending_batch(
                    session=session,
                    batch_size=max(1, settings.outbox_batch_size),
                    backoff_base_seconds=max(1, int(settings.outbox_poll_interval_sec)),
                )
                for message in messages:
                    await self._deliver_claimed_message(session=session, message=message)
                return len(messages)

    async def _run(self) -> None:
        while True:
            try:
                processed = await self.run_once()
                if processed == 0:
                    await asyncio.sleep(max(0.1, settings.outbox_poll_interval_sec))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Outbox relay loop failed", error=str(exc))
                await asyncio.sleep(max(0.5, settings.outbox_poll_interval_sec))

    async def _deliver_claimed_message(self, *, session, message: OutboxMessage) -> None:
        attempted_at = datetime.now(timezone.utc)
        telemetry_payload = dict(message.telemetry_json or {})
        tenant_id = _tenant_id_from_payload(telemetry_payload)
        if tenant_id is None:
            error_message = "MISSING_TENANT_ID"
            await self.outbox_repository.mark_dead_without_retry_increment(
                session=session,
                message=message,
                error_message=error_message,
                attempted_at=attempted_at,
            )
            await self._write_dead_letter(message=message, error_message=error_message)
            return
        try:
            response = await self._post_to_target(message=message, tenant_id=tenant_id)
        except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPError) as exc:
            next_retry_count = int(message.retry_count or 0) + 1
            if next_retry_count >= int(message.max_retries or settings.outbox_max_retries):
                await self.outbox_repository.mark_dead(
                    session=session,
                    message=message,
                    error_message=str(exc),
                    attempted_at=attempted_at,
                )
                await self._write_dead_letter(message=message, error_message=str(exc))
            else:
                await self.outbox_repository.mark_retryable_failure(
                    session=session,
                    message=message,
                    error_message=str(exc),
                    attempted_at=attempted_at,
                )
            return

        if 200 <= response.status_code < 300:
            await self.outbox_repository.mark_delivered(
                session=session,
                message=message,
                delivered_at=attempted_at,
            )
            return

        error_message = f"HTTP {response.status_code}: {response.text[:512]}"
        if 400 <= response.status_code < 500:
            await self.outbox_repository.mark_dead_without_retry_increment(
                session=session,
                message=message,
                error_message=error_message,
                attempted_at=attempted_at,
            )
            await self._write_dead_letter(message=message, error_message=error_message)
            return

        next_retry_count = int(message.retry_count or 0) + 1
        if next_retry_count >= int(message.max_retries or settings.outbox_max_retries):
            await self.outbox_repository.mark_dead(
                session=session,
                message=message,
                error_message=error_message,
                attempted_at=attempted_at,
            )
            await self._write_dead_letter(message=message, error_message=error_message)
            return

        await self.outbox_repository.mark_retryable_failure(
            session=session,
            message=message,
            error_message=error_message,
            attempted_at=attempted_at,
        )

    async def _post_to_target(self, *, message: OutboxMessage, tenant_id: str | None) -> httpx.Response:
        assert self._http_client is not None
        telemetry_payload = dict(message.telemetry_json or {})
        device_id = message.device_id
        if tenant_id is None:
            raise ValueError("tenant_id is None")
        normalized_fields = await self._build_normalized_fields(
            device_id=device_id,
            telemetry_payload=telemetry_payload,
            tenant_id=tenant_id,
        )
        payload = {
            "telemetry": telemetry_payload,
            "dynamic_fields": _dynamic_fields(telemetry_payload),
            "normalized_fields": normalized_fields,
            "tenant_id": tenant_id,
        }
        if message.target == OutboxTarget.DEVICE_SERVICE:
            base_url = (settings.device_service_url or "http://device-service:8000").rstrip("/")
            url = f"{base_url}/api/v1/devices/{device_id}/live-update"
            breaker = self.device_circuit_breaker
        else:
            base_url = (settings.energy_service_url or "http://energy-service:8010").rstrip("/")
            url = f"{base_url}/api/v1/energy/live-update"
            breaker = self.energy_circuit_breaker

        async def _request():
            response = await self._http_client.post(
                url,
                json=payload,
                headers=build_internal_headers("data-service", tenant_id),
            )
            if response.status_code >= 500:
                response.raise_for_status()
            return response

        success, response = await breaker.call(_request)
        if not success or response is None:
            raise httpx.RequestError(
                f"{message.target.value} circuit open or downstream unavailable",
                request=httpx.Request("POST", url),
            )
        return response

    async def _build_normalized_fields(
        self,
        *,
        device_id: str,
        telemetry_payload: dict[str, Any],
        tenant_id: str,
    ) -> dict[str, Any] | None:
        config = await self._fetch_device_power_config(device_id=device_id, tenant_id=tenant_id)
        if config is None:
            return None
        return normalize_telemetry_sample(telemetry_payload, config).to_dict()

    async def _fetch_device_power_config(self, *, device_id: str, tenant_id: str) -> dict[str, Any] | None:
        assert self._http_client is not None
        base_url = (settings.device_service_url or "http://device-service:8000").rstrip("/")
        url = f"{base_url}/api/v1/devices/{device_id}"
        try:
            response = await self._http_client.get(
                url,
                headers=build_internal_headers("data-service", tenant_id),
            )
            if response.status_code != 200:
                return None
            payload = response.json()
            device = payload.get("data", payload) if isinstance(payload, dict) else {}
            if not isinstance(device, dict):
                return None
            return {
                "energy_flow_mode": device.get("energy_flow_mode"),
                "polarity_mode": device.get("polarity_mode"),
            }
        except Exception:
            return None

    async def _write_dead_letter(self, *, message: OutboxMessage, error_message: str) -> None:
        await asyncio.to_thread(
            self.dlq_repository.send,
            original_payload={
                "device_id": message.device_id,
                "target": message.target.value,
                "telemetry": message.telemetry_json,
                "outbox_id": message.id,
            },
            error_type="outbox_delivery_dead",
            error_message=error_message,
            retry_count=int(message.retry_count or 0),
        )
