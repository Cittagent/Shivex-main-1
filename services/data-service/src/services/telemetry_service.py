"""Telemetry processing service."""

import asyncio
import re
import uuid
from collections import defaultdict
from contextlib import suppress
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import HTTPException, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import bindparam, text

try:
    from prometheus_client import Counter, Gauge
except ImportError:  # pragma: no cover - fallback for minimal runtime images
    class _MetricValue:
        def __init__(self) -> None:
            self.value = 0

        def get(self) -> int:
            return self.value

    class _MetricChild:
        def __init__(self) -> None:
            self._value = _MetricValue()

        def inc(self, amount: int = 1) -> None:
            self._value.value += amount

        def set(self, value: int | float) -> None:
            self._value.value = value

    class _Metric:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._children: dict[tuple[tuple[str, Any], ...], _MetricChild] = {}

        def labels(self, **labels: Any) -> _MetricChild:
            key = tuple(sorted(labels.items()))
            if key not in self._children:
                self._children[key] = _MetricChild()
            return self._children[key]

    Counter = Gauge = _Metric  # type: ignore[assignment]

from src.config import settings
from src.models import OutboxTarget
from src.models import TelemetryPayload
from src.repositories import DLQRepository, InfluxDBRepository, OutboxRepository
from src.services.device_projection_client import DeviceProjectionClient, DeviceProjectionSyncError
from src.services.enrichment_service import EnrichmentService, _get_mysql_session_factory
from src.services.rule_engine_client import RuleEngineClient
from src.utils import (
    get_logger,
    log_telemetry_error,
    log_telemetry_processed,
    TelemetryValidator,
)

logger = get_logger(__name__)
TENANT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
QUEUE_OVERFLOW_COUNTER: Dict[str, int] = defaultdict(int)
QUEUE_OVERFLOW_TOTAL = Counter(
    "queue_overflow_total",
    "Total telemetry sync queue overflow events",
    ["queue_name", "device_id"],
)
QUEUE_DEPTH = Gauge(
    "queue_depth",
    "Current telemetry sync queue depth",
    ["queue_name"],
)


class TelemetryServiceError(Exception):
    """Raised when telemetry processing fails."""
    pass


class TelemetryService:
    """
    Main service for processing telemetry data.

    Orchestrates:
    - Validation
    - Metadata enrichment
    - Rule engine calls
    - InfluxDB persistence
    - WebSocket broadcasting
    - DLQ handling for failures
    """

    def __init__(
        self,
        influx_repository: Optional[InfluxDBRepository] = None,
        dlq_repository: Optional[DLQRepository] = None,
        outbox_repository: Optional[OutboxRepository] = None,
        enrichment_service: Optional[EnrichmentService] = None,
        rule_engine_client: Optional[RuleEngineClient] = None,
        device_projection_client: Optional[DeviceProjectionClient] = None,
    ):
        self.influx_repository = influx_repository or InfluxDBRepository()
        self.dlq_repository = dlq_repository or DLQRepository()
        self.outbox_repository = outbox_repository or OutboxRepository()
        self.enrichment_service = enrichment_service or EnrichmentService()
        self.rule_engine_client = rule_engine_client or RuleEngineClient(
            dlq_repository=self.dlq_repository,
        )
        self.device_projection_client = device_projection_client or DeviceProjectionClient()

        self._queue_name = "telemetry_sync_queue"
        self._processing_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(
            maxsize=settings.device_sync_queue_maxsize
        )
        self._worker_task: Optional[asyncio.Task] = None
        self._queue_monitor_task: Optional[asyncio.Task] = None
        self._update_queue_depth_metric()

        logger.info("TelemetryService initialized")

    async def start(self) -> None:
        """Start background worker for async processing."""
        await self.outbox_repository.ensure_schema()
        self._worker_task = asyncio.create_task(self._processing_worker())
        self._queue_monitor_task = asyncio.create_task(self._queue_depth_monitor())
        logger.info("TelemetryService background worker started")

    async def stop(self) -> None:
        """Stop background worker."""
        drain_timeout = max(0, settings.queue_drain_timeout_sec)
        if self._worker_task is not None:
            try:
                await asyncio.wait_for(self._processing_queue.join(), timeout=drain_timeout)
            except asyncio.TimeoutError:
                logger.warning(
                    "Telemetry shutdown forced before queue drained",
                    queue=self._queue_name,
                    remaining_items=self._processing_queue.qsize(),
                    drain_timeout_sec=drain_timeout,
                )

        for task in (self._worker_task, self._queue_monitor_task):
            if task is not None and not task.done():
                task.cancel()
        for task in (self._worker_task, self._queue_monitor_task):
            if task is not None:
                with suppress(asyncio.CancelledError):
                    await task
        self._worker_task = None
        self._queue_monitor_task = None
        await self.device_projection_client.close()
        logger.info("TelemetryService background worker stopped")

    async def process_telemetry_message(
        self,
        raw_payload: Dict[str, Any],
        correlation_id: Optional[str] = None,
    ) -> bool:
        """Process incoming telemetry message."""
        correlation_id = correlation_id or str(uuid.uuid4())

        try:
            is_valid, error_type, error_message = TelemetryValidator.validate_payload(
                raw_payload
            )

            if not is_valid:
                await asyncio.to_thread(
                    self.dlq_repository.send,
                    original_payload=raw_payload,
                    error_type=error_type or "validation_error",
                    error_message=error_message or "Validation failed",
                )
                log_telemetry_error(
                    logger=logger,
                    device_id=raw_payload.get("device_id", "unknown"),
                    correlation_id=correlation_id,
                    error_type=error_type or "validation_error",
                    error_message=error_message or "Validation failed",
                    payload=raw_payload,
                )
                return False

            try:
                payload = TelemetryPayload(**raw_payload)
            except Exception as e:
                await asyncio.to_thread(
                    self.dlq_repository.send,
                    original_payload=raw_payload,
                    error_type="parse_error",
                    error_message=str(e),
                )
                log_telemetry_error(
                    logger=logger,
                    device_id=raw_payload.get("device_id", "unknown"),
                    correlation_id=correlation_id,
                    error_type="parse_error",
                    error_message=str(e),
                    payload=raw_payload,
                )
                return False

            queue_item = {
                "payload": payload,
                "correlation_id": correlation_id,
                "raw_payload": raw_payload,
            }
            try:
                self._processing_queue.put_nowait(queue_item)
                self._update_queue_depth_metric()
            except asyncio.QueueFull:
                await self._handle_queue_overflow(
                    queue_name=self._queue_name,
                    device_id=payload.device_id,
                    correlation_id=correlation_id,
                    raw_payload=raw_payload,
                )
                return False

            logger.debug(
                "Telemetry queued for processing",
                device_id=payload.device_id,
                correlation_id=correlation_id,
            )
            return True

        except Exception as e:
            logger.error(
                "Unexpected error processing telemetry message",
                error=str(e),
                correlation_id=correlation_id,
            )
            await asyncio.to_thread(
                self.dlq_repository.send,
                original_payload=raw_payload,
                error_type="unexpected_error",
                error_message=str(e),
            )
            return False

    async def _processing_worker(self) -> None:
        """Background worker to process queued telemetry."""
        logger.info("Processing worker started")

        while True:
            try:
                item = await self._processing_queue.get()

                try:
                    await self._process_telemetry_async(
                        payload=item["payload"],
                        correlation_id=item["correlation_id"],
                        raw_payload=item["raw_payload"],
                    )
                except Exception as e:
                    logger.error(
                        "Error in processing worker",
                        error=str(e),
                    )
                finally:
                    self._processing_queue.task_done()
                    self._update_queue_depth_metric()

            except asyncio.CancelledError:
                logger.info("Processing worker cancelled")
                break
            except Exception as e:
                logger.error(
                    "Unexpected error in processing worker",
                    error=str(e),
                )

    async def _process_telemetry_async(
        self,
        payload: TelemetryPayload,
        correlation_id: str,
        raw_payload: Dict[str, Any],
    ) -> None:
        """Process telemetry asynchronously."""
        try:
            payload = await self.enrichment_service.enrich_telemetry(payload)
            if not await self._validate_ingest_ownership(
                payload=payload,
                correlation_id=correlation_id,
                raw_payload=raw_payload,
            ):
                return

            write_success = await asyncio.to_thread(self.influx_repository.write_telemetry, payload)

            if not write_success:
                await asyncio.to_thread(
                    self.dlq_repository.send,
                    original_payload=raw_payload,
                    error_type="influxdb_write_error",
                    error_message="Failed to write to InfluxDB",
                )
                log_telemetry_error(
                    logger=logger,
                    device_id=payload.device_id,
                    correlation_id=correlation_id,
                    error_type="influxdb_write_error",
                    error_message="Failed to write to InfluxDB",
                    payload=raw_payload,
                )
                return

            projection_state = None
            projection_synced = False
            try:
                projection_state = await self.device_projection_client.sync_projection(payload)
                projection_synced = True
            except DeviceProjectionSyncError as sync_error:
                logger.error(
                    "Failed to sync device projection before rule evaluation",
                    device_id=payload.device_id,
                    correlation_id=correlation_id,
                    error=str(sync_error),
                    retryable=sync_error.retryable,
                )
            except Exception as sync_error:
                logger.error(
                    "Unexpected device projection sync failure",
                    device_id=payload.device_id,
                    correlation_id=correlation_id,
                    error=str(sync_error),
                )

            if projection_synced:
                asyncio.create_task(
                    self.rule_engine_client.evaluate_rules(payload, projection_state=projection_state)
                )
            else:
                logger.warning(
                    "Skipping rule evaluation because device projection is stale for current sample",
                    device_id=payload.device_id,
                    correlation_id=correlation_id,
                )

            dynamic_fields = payload.get_dynamic_fields()
            
            try:
                from src.api.websocket import broadcast_telemetry
                await broadcast_telemetry(
                    device_id=payload.device_id,
                    telemetry_data=dynamic_fields,
                )
            except Exception as e:
                logger.warning(
                    "Failed to broadcast telemetry via WebSocket",
                    device_id=payload.device_id,
                    error=str(e),
                )

            outbox_payload = jsonable_encoder(payload.model_dump(mode="json"))
            targets = self._outbox_targets(include_device_service=not projection_synced)
            if targets:
                try:
                    await self.outbox_repository.enqueue_telemetry(
                        device_id=payload.device_id,
                        telemetry_payload=outbox_payload,
                        targets=targets,
                        max_retries=settings.outbox_max_retries,
                    )
                except Exception as enqueue_error:
                    logger.critical(
                        "Telemetry written to InfluxDB but failed to enqueue outbox rows",
                        device_id=payload.device_id,
                        correlation_id=correlation_id,
                        error=str(enqueue_error),
                    )
                    await asyncio.to_thread(
                        self.dlq_repository.send,
                        original_payload=outbox_payload,
                        error_type="outbox_enqueue_error",
                        error_message=str(enqueue_error),
                    )
                    return

            log_telemetry_processed(
                logger=logger,
                device_id=payload.device_id,
                correlation_id=correlation_id,
                enrichment_status=payload.enrichment_status.value,
            )

        except Exception as e:
            logger.error(
                "Error in async processing",
                device_id=payload.device_id,
                correlation_id=correlation_id,
                error=str(e),
            )
            await asyncio.to_thread(
                self.dlq_repository.send,
                original_payload=raw_payload,
                error_type="processing_error",
                error_message=str(e),
            )
            log_telemetry_error(
                logger=logger,
                device_id=payload.device_id,
                correlation_id=correlation_id,
                error_type="processing_error",
                error_message=str(e),
                payload=raw_payload,
            )

    async def _queue_depth_monitor(self) -> None:
        """Periodically report queue depth and saturation."""
        logger.info("Queue depth monitor started", queue=self._queue_name)
        try:
            while True:
                self._emit_queue_depth_log()
                await asyncio.sleep(max(1, settings.queue_depth_check_interval_sec))
        except asyncio.CancelledError:
            logger.info("Queue depth monitor cancelled", queue=self._queue_name)
            raise

    def _outbox_targets(self, *, include_device_service: bool) -> list[OutboxTarget]:
        targets: list[OutboxTarget] = []
        if include_device_service and settings.device_sync_enabled:
            targets.append(OutboxTarget.DEVICE_SERVICE)
        if settings.energy_sync_enabled:
            targets.append(OutboxTarget.ENERGY_SERVICE)
        return targets

    def _update_queue_depth_metric(self) -> None:
        QUEUE_DEPTH.labels(queue_name=self._queue_name).set(self._processing_queue.qsize())

    def _emit_queue_depth_log(self) -> None:
        queue_size = self._processing_queue.qsize()
        maxsize = self._processing_queue.maxsize or settings.device_sync_queue_maxsize
        depth_ratio = (queue_size / maxsize) if maxsize else 0.0
        self._update_queue_depth_metric()
        logger.debug(
            "Telemetry queue depth",
            queue=self._queue_name,
            queue_size=queue_size,
            maxsize=maxsize,
            depth_ratio=depth_ratio,
        )
        if maxsize and queue_size >= maxsize:
            logger.critical(
                "Telemetry queue saturated",
                queue=self._queue_name,
                queue_size=queue_size,
                maxsize=maxsize,
                depth_ratio=depth_ratio,
            )
        elif maxsize and queue_size >= int(maxsize * 0.8):
            logger.warning(
                "Telemetry queue above 80 percent capacity",
                queue=self._queue_name,
                queue_size=queue_size,
                maxsize=maxsize,
                depth_ratio=depth_ratio,
            )

    async def _handle_queue_overflow(
        self,
        *,
        queue_name: str,
        device_id: str,
        correlation_id: str,
        raw_payload: Dict[str, Any],
    ) -> None:
        overflow_count = QUEUE_OVERFLOW_COUNTER[queue_name] + 1
        QUEUE_OVERFLOW_COUNTER[queue_name] = overflow_count
        queue_size = self._processing_queue.qsize()
        QUEUE_OVERFLOW_TOTAL.labels(queue_name=queue_name, device_id=device_id).inc()
        self._update_queue_depth_metric()

        overflow_level = getattr(logger, settings.queue_overflow_log_level.lower(), logger.warning)
        overflow_level(
            "sync_queue_overflow",
            queue=queue_name,
            device_id=device_id,
            correlation_id=correlation_id,
            queue_size=queue_size,
            overflow_count=overflow_count,
        )
        await asyncio.to_thread(
            self.dlq_repository.send,
            original_payload=raw_payload,
            error_type="QUEUE_OVERFLOW",
            error_message=f"{queue_name} queue full at size {queue_size}",
        )

    async def _validate_ingest_ownership(
        self,
        *,
        payload: TelemetryPayload,
        correlation_id: str,
        raw_payload: Dict[str, Any],
    ) -> bool:
        payload_tenant_id = self._normalize_optional_string(payload.tenant_id)
        metadata_tenant_id = self._normalize_optional_string(
            None if payload.device_metadata is None else payload.device_metadata.tenant_id
        )

        if payload_tenant_id and metadata_tenant_id and payload_tenant_id != metadata_tenant_id:
            await self._reject_ingest_ownership(
                payload=payload,
                correlation_id=correlation_id,
                raw_payload=raw_payload,
                error_type="device_ownership_error",
                error_message="Telemetry tenant scope does not match device metadata tenant.",
            )
            return False

        tenant_id = payload_tenant_id or metadata_tenant_id
        if not tenant_id:
            await self._reject_ingest_ownership(
                payload=payload,
                correlation_id=correlation_id,
                raw_payload=raw_payload,
                error_type="tenant_scope_required",
                error_message="Telemetry tenant scope is required for ingestion.",
            )
            return False

        try:
            owned_devices = await self._fetch_tenant_owned_device_ids(
                tenant_id=tenant_id,
                device_ids=[payload.device_id],
            )
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            await self._reject_ingest_ownership(
                payload=payload,
                correlation_id=correlation_id,
                raw_payload=raw_payload,
                error_type=str(detail.get("code") or "tenant_scope_invalid").lower(),
                error_message=str(detail.get("message") or "Telemetry tenant scope is invalid."),
            )
            return False

        if payload.device_id not in owned_devices:
            await self._reject_ingest_ownership(
                payload=payload,
                correlation_id=correlation_id,
                raw_payload=raw_payload,
                error_type="device_ownership_error",
                error_message="Telemetry device was not found in tenant scope.",
            )
            return False

        payload.tenant_id = tenant_id
        if payload.device_metadata is not None and not metadata_tenant_id:
            payload.device_metadata.tenant_id = tenant_id
        return True

    async def _reject_ingest_ownership(
        self,
        *,
        payload: TelemetryPayload,
        correlation_id: str,
        raw_payload: Dict[str, Any],
        error_type: str,
        error_message: str,
    ) -> None:
        await asyncio.to_thread(
            self.dlq_repository.send,
            original_payload=raw_payload,
            error_type=error_type,
            error_message=error_message,
        )
        log_telemetry_error(
            logger=logger,
            device_id=payload.device_id,
            correlation_id=correlation_id,
            error_type=error_type,
            error_message=error_message,
            payload=raw_payload,
        )

    @staticmethod
    def _normalize_optional_string(value: object | None) -> Optional[str]:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    async def query_telemetry(
        self,
        tenant_id: str,
        device_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
    ):
        await self._assert_device_owned_by_tenant(tenant_id=tenant_id, device_id=device_id)
        return self.influx_repository.query_telemetry(
            tenant_id=tenant_id,
            device_id=device_id,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )

    async def get_telemetry(
        self,
        tenant_id: str,
        device_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        fields: Optional[list[str]] = None,
        aggregate: Optional[str] = None,
        interval: Optional[str] = None,
        limit: int = 1000,
        accessible_plant_ids: Optional[list[str]] = None,
    ) -> list:
        await self._assert_device_owned_by_tenant(
            tenant_id=tenant_id,
            device_id=device_id,
            accessible_plant_ids=accessible_plant_ids,
        )
        return self.influx_repository.query_telemetry(
            tenant_id=tenant_id,
            device_id=device_id,
            start_time=start_time,
            end_time=end_time,
            fields=fields,
            aggregate=aggregate,
            interval=interval,
            limit=limit,
        )

    async def get_latest(
        self,
        tenant_id: str,
        device_id: str,
        accessible_plant_ids: Optional[list[str]] = None,
    ) -> Optional[Any]:
        await self._assert_device_owned_by_tenant(
            tenant_id=tenant_id,
            device_id=device_id,
            accessible_plant_ids=accessible_plant_ids,
        )
        return self.influx_repository.get_latest_telemetry(
            tenant_id=tenant_id,
            device_id=device_id,
        )

    async def get_earliest(
        self,
        tenant_id: str,
        device_id: str,
        start_time: Optional[datetime] = None,
        accessible_plant_ids: Optional[list[str]] = None,
    ) -> Optional[Any]:
        await self._assert_device_owned_by_tenant(
            tenant_id=tenant_id,
            device_id=device_id,
            accessible_plant_ids=accessible_plant_ids,
        )
        return self.influx_repository.get_earliest_telemetry(
            tenant_id=tenant_id,
            device_id=device_id,
            start_time=start_time,
        )

    async def get_latest_batch(
        self,
        tenant_id: str,
        device_ids: list[str],
        accessible_plant_ids: Optional[list[str]] = None,
    ) -> Dict[str, Optional[Any]]:
        await self._assert_devices_owned_by_tenant(
            tenant_id=tenant_id,
            device_ids=device_ids,
            accessible_plant_ids=accessible_plant_ids,
        )
        return self.influx_repository.get_latest_telemetry_batch(
            tenant_id=tenant_id,
            device_ids=device_ids,
        )

    async def get_stats(
        self,
        tenant_id: str,
        device_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        accessible_plant_ids: Optional[list[str]] = None,
    ) -> Optional[Any]:
        await self._assert_device_owned_by_tenant(
            tenant_id=tenant_id,
            device_id=device_id,
            accessible_plant_ids=accessible_plant_ids,
        )
        return self.influx_repository.get_stats(
            tenant_id=tenant_id,
            device_id=device_id,
            start_time=start_time,
            end_time=end_time,
        )

    async def _assert_device_owned_by_tenant(
        self,
        *,
        tenant_id: str,
        device_id: str,
        accessible_plant_ids: Optional[list[str]] = None,
    ) -> None:
        owned_devices = await self._fetch_tenant_owned_device_ids(
            tenant_id=tenant_id,
            device_ids=[device_id],
            accessible_plant_ids=accessible_plant_ids,
        )
        if device_id not in owned_devices:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "DEVICE_NOT_FOUND",
                    "message": f"Device {device_id} was not found in tenant scope.",
                },
            )

    async def _assert_devices_owned_by_tenant(
        self,
        *,
        tenant_id: str,
        device_ids: list[str],
        accessible_plant_ids: Optional[list[str]] = None,
    ) -> None:
        requested_device_ids = [device_id for device_id in dict.fromkeys(device_ids) if device_id]
        if not requested_device_ids:
            return

        owned_devices = await self._fetch_tenant_owned_device_ids(
            tenant_id=tenant_id,
            device_ids=requested_device_ids,
            accessible_plant_ids=accessible_plant_ids,
        )
        missing_device_ids = [device_id for device_id in requested_device_ids if device_id not in owned_devices]
        if missing_device_ids:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "DEVICE_NOT_FOUND",
                    "message": "One or more devices were not found in tenant scope.",
                    "device_ids": missing_device_ids,
                },
            )

    async def _fetch_tenant_owned_device_ids(
        self,
        *,
        tenant_id: str,
        device_ids: list[str],
        accessible_plant_ids: Optional[list[str]] = None,
    ) -> set[str]:
        if not tenant_id or not TENANT_ID_PATTERN.fullmatch(tenant_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "TENANT_SCOPE_INVALID",
                    "message": "Tenant scope is invalid.",
                },
            )

        requested_device_ids = [device_id for device_id in dict.fromkeys(device_ids) if device_id]
        if not requested_device_ids:
            return set()

        scoped_plant_ids: Optional[list[str]] = None
        if accessible_plant_ids is not None:
            scoped_plant_ids = [plant_id for plant_id in dict.fromkeys(accessible_plant_ids) if plant_id]
            if not scoped_plant_ids:
                return set()

        session_factory = _get_mysql_session_factory()
        async with session_factory() as session:
            query = """
                SELECT DISTINCT device_id
                FROM devices
                WHERE tenant_id = :tenant_id
                  AND device_id IN :device_ids
                  AND deleted_at IS NULL
            """
            params: dict[str, object] = {
                "tenant_id": tenant_id,
                "device_ids": requested_device_ids,
            }
            bind_params = [bindparam("device_ids", expanding=True)]
            if scoped_plant_ids is not None:
                query += "\n  AND plant_id IN :plant_ids"
                params["plant_ids"] = scoped_plant_ids
                bind_params.append(bindparam("plant_ids", expanding=True))
            result = await session.execute(
                text(query).bindparams(*bind_params),
                params,
            )
            return {
                str(row[0]).strip()
                for row in result.all()
                if row[0] is not None and str(row[0]).strip()
            }

    async def close(self) -> None:
        """Close all service connections."""
        await self.stop()
        try:
            logger.info("DLQ operational stats", **self.dlq_repository.get_operational_stats())
        except Exception as exc:
            logger.warning("Failed to fetch DLQ operational stats", error=str(exc))
        self.influx_repository.close()
        await self.outbox_repository.close()
        self.dlq_repository.close()
        await self.enrichment_service.close()
        await self.rule_engine_client.close()
        logger.info("TelemetryService closed")
