"""Device API endpoints."""

from datetime import datetime, timezone
from time import perf_counter
from typing import Optional

import asyncio
import json
import httpx

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status, Header
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import false, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, get_db
from app.config import settings
from app.models.device import Device
from app.schemas.device import (
    DeviceCreate,
    DeviceUpdate,
    DeviceResponse,
    DeviceListResponse,
    DeviceSingleResponse,
    ErrorResponse,
    ShiftCreate,
    ShiftUpdate,
    ShiftResponse,
    ShiftListResponse,
    ShiftSingleResponse,
    ShiftDeleteResponse,
    UptimeResponse,
    ParameterHealthConfigCreate,
    ParameterHealthConfigUpdate,
    ParameterHealthConfigResponse,
    ParameterHealthConfigListResponse,
    ParameterHealthConfigSingleResponse,
    WeightValidationResponse,
    TelemetryValues,
    HealthScoreResponse,
    PerformanceTrendResponse,
    DashboardSummaryResponse,
    FleetSnapshotResponse,
    DeviceDashboardBootstrapResponse,
    TodayLossBreakdownResponse,
    MonthlyEnergyCalendarResponse,
    FleetStreamEvent,
    DashboardWidgetConfigUpdateRequest,
    DashboardWidgetConfigResponse,
    DeviceStateIntervalListResponse,
    HardwareUnitCreate,
    HardwareUnitUpdate,
    HardwareUnitListResponse,
    HardwareUnitSingleResponse,
    DeviceHardwareInstallationCreate,
    DeviceHardwareInstallationDecommission,
    DeviceHardwareInstallationSingleResponse,
    DeviceHardwareInstallationHistoryResponse,
    DeviceHardwareMappingListResponse,
    DeviceHardwareMappingResponse,
)
from app.repositories.device_state_intervals import DeviceStateIntervalRepository
from app.services.device import DeviceService
from app.services.device_errors import (
    DeviceAlreadyExistsError,
    DeviceIdAllocationError,
    DevicePlantRequiredError,
    HardwareInstallationConflictError,
    HardwareInstallationCompatibilityError,
    HardwareInstallationNotFoundError,
    HardwarePlantMismatchError,
    HardwareStatusError,
    HardwareTenantMismatchError,
    HardwareUnitAlreadyExistsError,
    HardwareUnitIdAllocationError,
    HardwareUnitNotFoundError,
    InvalidDeviceMetadataError,
)
from app.services.hardware_inventory import HardwareInventoryService
from app.monitoring import fleet_stream_broadcaster
from app.monitoring import (
    DEVICE_LIVE_UPDATE_BATCH_DURATION_SECONDS,
    DEVICE_LIVE_UPDATE_BATCH_ITEMS_TOTAL,
    DEVICE_LIVE_UPDATE_BATCH_ROWS,
)
from shared.auth_middleware import get_auth_state
from services.shared.tenant_context import TenantContext, require_tenant
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

HARDWARE_TYPE_LABELS = {
    "energy_meter": "Energy Meter",
    "ct_sensor": "CT Sensor",
    "esp32": "ESP32",
    "oil_sensor": "Oil Sensor",
    "temperature_sensor": "Temperature Sensor",
    "vibration_sensor": "Vibration Sensor",
    "motor_sensor": "Motor Sensor",
}

INSTALLATION_ROLE_LABELS = {
    "main_meter": "Main Meter",
    "ct1": "CT1",
    "ct2": "CT2",
    "ct3": "CT3",
    "ct4": "CT4",
    "controller": "Controller",
    "oil_sensor": "Oil Sensor",
    "temperature_sensor": "Temperature Sensor",
    "vibration_sensor": "Vibration Sensor",
    "motor_sensor": "Motor Sensor",
}


def get_tenant_id(request: Request) -> str | None:
    """
    Resolves the effective tenant/org scope for this request.
    """
    return require_tenant(request)


class IdleConfigRequest(BaseModel):
    full_load_current_a: Optional[float] = Field(default=None, gt=0)
    idle_threshold_pct_of_fla: Optional[float] = Field(default=None, gt=0, lt=1)
    idle_current_threshold: Optional[float] = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_payload(self) -> "IdleConfigRequest":
        if (
            self.full_load_current_a is None
            and self.idle_threshold_pct_of_fla is None
            and self.idle_current_threshold is None
        ):
            raise ValueError(
                "One of full_load_current_a, idle_threshold_pct_of_fla, or deprecated idle_current_threshold is required."
            )
        return self


class DeviceWasteConfigRequest(BaseModel):
    full_load_current_a: Optional[float] = Field(default=None, gt=0)
    overconsumption_current_threshold_a: Optional[float] = Field(default=None, gt=0)
    unoccupied_weekday_start_time: Optional[str] = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    unoccupied_weekday_end_time: Optional[str] = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    unoccupied_weekend_start_time: Optional[str] = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    unoccupied_weekend_end_time: Optional[str] = Field(default=None, pattern=r"^\d{2}:\d{2}$")


class DeviceLiveUpdateRequest(BaseModel):
    telemetry: dict
    dynamic_fields: Optional[dict] = None
    normalized_fields: Optional[dict] = None
    tenant_id: Optional[str] = None


class DeviceLiveUpdateBatchItem(BaseModel):
    device_id: str
    telemetry: dict
    dynamic_fields: Optional[dict] = None
    normalized_fields: Optional[dict] = None


class DeviceLiveUpdateBatchRequest(BaseModel):
    tenant_id: Optional[str] = None
    updates: list[DeviceLiveUpdateBatchItem] = Field(default_factory=list, min_length=1)


def get_required_tenant_id(request: Request) -> str:
    return get_tenant_id(request)


def _normalize_device_phase_type(device: Device) -> None:
    raw_phase_type = getattr(device, "phase_type", None)
    if raw_phase_type is None:
        return
    normalized = str(raw_phase_type).strip().lower()
    if normalized in ("single", "three"):
        device.phase_type = normalized
        return
    if normalized in {"single_phase", "single-phase"}:
        device.phase_type = "single"
        return
    if normalized in {"three_phase", "three-phase"}:
        device.phase_type = "three"
        return
    raise InvalidDeviceMetadataError(
        device_id=str(getattr(device, "device_id", "unknown")),
        field_name="phase_type",
        message="phase_type must be 'single', 'three', or null",
    )


def _serialize_device_response(device: Device) -> DeviceSingleResponse:
    try:
        _normalize_device_phase_type(device)
        return DeviceSingleResponse(data=device)
    except InvalidDeviceMetadataError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_DEVICE_METADATA",
                "message": exc.message,
                "device_id": exc.device_id,
                "field": exc.field_name,
            },
        ) from exc
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_DEVICE_METADATA",
                "message": "Stored device metadata violates the device response contract.",
                "device_id": str(getattr(device, "device_id", "unknown")),
                "details": exc.errors(),
            },
        ) from exc


def _serialize_device_list_rows(devices: list[Device]) -> list[DeviceResponse]:
    serialized: list[DeviceResponse] = []
    for device in devices:
        try:
            _normalize_device_phase_type(device)
            serialized.append(DeviceResponse.model_validate(device, from_attributes=True))
        except InvalidDeviceMetadataError:
            logger.warning(
                "Coercing invalid persisted device metadata in list response",
                extra={
                    "device_id": str(getattr(device, "device_id", "unknown")),
                    "tenant_id": str(getattr(device, "tenant_id", "unknown")),
                    "field": "phase_type",
                    "route": "list_devices",
                },
            )
            device.phase_type = None
            serialized.append(DeviceResponse.model_validate(device, from_attributes=True))
        except ValidationError as exc:
            logger.warning(
                "Skipping invalid device row in list response",
                extra={
                    "device_id": str(getattr(device, "device_id", "unknown")),
                    "tenant_id": str(getattr(device, "tenant_id", "unknown")),
                    "route": "list_devices",
                    "errors": exc.errors(),
                },
            )
    return serialized


def _resolve_accessible_plant_ids(
    request: Request,
    *,
    plant_id: Optional[str] = None,
) -> list[str] | None:
    auth = get_auth_state(request)
    if auth["role"] not in ("plant_manager", "operator", "viewer"):
        return [plant_id] if plant_id else None
    if plant_id and plant_id not in auth["plant_ids"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "PLANT_ACCESS_DENIED",
                "message": "You do not have access to this plant.",
            },
        )
    return [plant_id] if plant_id else list(auth["plant_ids"])


def _ensure_hardware_write_access(request: Request) -> None:
    auth = get_auth_state(request)
    if auth["role"] in ("viewer", "operator"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FORBIDDEN",
                "message": f"Role '{auth['role']}' is not permitted for this action.",
            },
        )


def _ensure_device_write_access(request: Request) -> None:
    auth = get_auth_state(request)
    if auth["role"] in ("viewer", "operator"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FORBIDDEN",
                "message": f"Role '{auth['role']}' is not permitted for this action.",
            },
        )


def _ensure_entity_plant_access(request: Request, plant_id: str | None) -> None:
    auth = get_auth_state(request)
    if auth["role"] not in ("plant_manager", "operator", "viewer"):
        return
    if plant_id is None or plant_id not in auth["plant_ids"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "PLANT_ACCESS_DENIED",
                "message": "You do not have access to this plant.",
            },
        )


def _plant_name_by_id(plants: list[dict]) -> dict[str, str]:
    return {
        str(plant["id"]): str(plant.get("name") or plant["id"])
        for plant in plants
        if isinstance(plant, dict) and plant.get("id")
    }


def _hardware_type_label(unit_type: str) -> str:
    return HARDWARE_TYPE_LABELS.get(unit_type, unit_type.replace("_", " ").title())


def _installation_role_label(installation_role: str) -> str:
    return INSTALLATION_ROLE_LABELS.get(installation_role, installation_role.replace("_", " ").title())


def _raise_hardware_http_error(exc: Exception) -> None:
    if isinstance(exc, HardwareUnitAlreadyExistsError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "HARDWARE_UNIT_ALREADY_EXISTS", "message": str(exc)},
        ) from exc
    if isinstance(exc, HardwareUnitIdAllocationError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "HARDWARE_UNIT_ID_ALLOCATION_FAILED", "message": str(exc)},
        ) from exc
    if isinstance(exc, HardwareUnitNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "HARDWARE_UNIT_NOT_FOUND", "message": str(exc)},
        ) from exc
    if isinstance(exc, HardwareInstallationNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "HARDWARE_INSTALLATION_NOT_FOUND", "message": str(exc)},
        ) from exc
    if isinstance(exc, HardwareInstallationConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "HARDWARE_INSTALLATION_CONFLICT", "message": str(exc)},
        ) from exc
    if isinstance(exc, HardwareInstallationCompatibilityError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "HARDWARE_INSTALLATION_COMPATIBILITY_INVALID", "message": str(exc)},
        ) from exc
    if isinstance(exc, HardwareTenantMismatchError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "HARDWARE_TENANT_MISMATCH", "message": str(exc)},
        ) from exc
    if isinstance(exc, HardwarePlantMismatchError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "HARDWARE_PLANT_MISMATCH", "message": str(exc)},
        ) from exc
    if isinstance(exc, HardwareStatusError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "HARDWARE_STATUS_INVALID", "message": str(exc)},
        ) from exc


async def _list_tenant_plants(request: Request, tenant_id: str) -> list[dict]:
    base_url = (settings.AUTH_SERVICE_BASE_URL or "").rstrip("/")
    if not base_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "PLANT_VALIDATION_UNAVAILABLE",
                "message": "Plant validation service is not configured.",
            },
        )

    authorization = request.headers.get("Authorization")
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "MISSING_AUTH_TOKEN",
                "message": "Authorization header required for plant validation.",
            },
        )

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"{base_url}/api/v1/tenants/{tenant_id}/plants",
                headers={"Authorization": authorization},
            )
    except httpx.TimeoutException as exc:
        logger.error("plant_validation_timeout", extra={"tenant_id": tenant_id, "error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "PLANT_VALIDATION_UNAVAILABLE",
                "message": "Unable to validate plant right now. Please try again.",
            },
        ) from exc
    except httpx.HTTPError as exc:
        logger.error("plant_validation_request_failed", extra={"tenant_id": tenant_id, "error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "PLANT_VALIDATION_UNAVAILABLE",
                "message": "Unable to validate plant right now. Please try again.",
            },
        ) from exc

    if response.status_code == status.HTTP_404_NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "ORG_NOT_FOUND",
                "message": "Organization not found while validating plant.",
            },
        )
    if response.status_code in {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN}:
        raise HTTPException(
            status_code=response.status_code,
            detail={
                "code": "PLANT_ACCESS_DENIED",
                "message": "You do not have access to validate plants for this tenant.",
            },
        )
    if response.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "PLANT_VALIDATION_UNAVAILABLE",
                "message": "Unable to validate plant right now. Please try again.",
            },
        )

    payload = response.json()
    if not isinstance(payload, list):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "PLANT_VALIDATION_UNAVAILABLE",
                "message": "Plant validation returned an unexpected response.",
            },
        )
    return payload


async def _refresh_loss_views_after_waste_config_change(
    db: AsyncSession,
    *,
    tenant_id: str,
    device_id: str,
) -> None:
    from app.services.dashboard import DashboardService
    from app.services.live_projection import LiveProjectionService

    await LiveProjectionService(db).recompute_today_loss_projection(device_id, tenant_id)
    dashboard = DashboardService(
        db,
        TenantContext(
            tenant_id=tenant_id,
            user_id="waste-config-refresh",
            role="system",
            plant_ids=[],
            is_super_admin=False,
        ),
    )
    await dashboard.materialize_energy_and_loss_snapshots()
    await dashboard.materialize_dashboard_summary_snapshot()


async def _validate_org_plant_access(
    request: Request,
    *,
    tenant_id: str,
    plant_id: str,
) -> None:
    plants = await _list_tenant_plants(request, tenant_id)
    valid_plant_ids = {str(plant.get("id")) for plant in plants if isinstance(plant, dict) and plant.get("id")}
    if plant_id not in valid_plant_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "PLANT_NOT_FOUND",
                "message": "Selected plant does not exist in this organization.",
            },
        )


# =====================================================
# Device Properties Endpoints (Dynamic Schema)
# Must come BEFORE /{device_id} routes
# =====================================================

@router.get(
    "/properties",
    response_model=dict,
)
async def get_all_devices_properties(
    request: Request,
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of devices to include"),
    offset: int = Query(0, ge=0, description="Number of devices to skip"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get properties for all devices."""
    from app.services.device_property import DevicePropertyService

    tenant_id = get_tenant_id(request)
    accessible_plant_ids = _resolve_accessible_plant_ids(request)
    service = DevicePropertyService(db)
    properties = await service.get_all_devices_properties(
        tenant_id=tenant_id,
        accessible_plant_ids=accessible_plant_ids,
        limit=limit,
        offset=offset,
    )
    
    all_props = set()
    for props in properties.values():
        all_props.update(props)
    
    return {
        "success": True,
        "devices": properties,
        "all_properties": sorted(list(all_props))
    }


@router.post(
    "/properties/common",
    response_model=dict,
)
async def get_common_properties(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get common properties across selected devices."""
    from app.services.device_property import DevicePropertyService
    
    body = await request.json()
    device_ids = body.get("device_ids", [])
    tenant_id = get_tenant_id(request)
    accessible_plant_ids = _resolve_accessible_plant_ids(request)

    if accessible_plant_ids is not None and device_ids:
        accessible_device_query = select(Device.device_id).where(
            Device.tenant_id == tenant_id,
            Device.deleted_at.is_(None),
        )
        if accessible_plant_ids:
            accessible_device_query = accessible_device_query.where(Device.plant_id.in_(accessible_plant_ids))
        else:
            accessible_device_query = accessible_device_query.where(false())
        device_rows = await db.execute(accessible_device_query)
        accessible_device_ids = {row[0] for row in device_rows.all()}
        if any(str(device_id) not in accessible_device_ids for device_id in device_ids):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "DEVICE_ACCESS_DENIED",
                    "message": "You do not have access to one or more selected devices.",
                },
            )
    
    service = DevicePropertyService(db)
    common = await service.get_common_properties(device_ids, tenant_id=tenant_id)
    
    return {
        "success": True,
        "properties": common,
        "device_count": len(device_ids),
    }


@router.get(
    "/dashboard/summary",
    response_model=DashboardSummaryResponse,
)
async def get_dashboard_summary(
    request: Request,
    response: Response,
    plant_id: Optional[str] = Query(None, description="Optional plant filter for dashboard summary"),
    db: AsyncSession = Depends(get_db),
) -> DashboardSummaryResponse:
    """Get home dashboard aggregates across all devices."""
    from app.services.live_dashboard import LiveDashboardService

    effective_plant_ids = _resolve_accessible_plant_ids(request, plant_id=plant_id)

    service = LiveDashboardService(db, TenantContext.from_request(request))
    summary = await service.get_dashboard_summary(
        tenant_id=get_tenant_id(request),
        plant_id=plant_id,
        accessible_plant_ids=effective_plant_ids,
    )
    response.headers["Cache-Control"] = "no-store"
    return DashboardSummaryResponse(**summary)


@router.get(
    "/dashboard/fleet-snapshot",
    response_model=FleetSnapshotResponse,
)
async def get_fleet_snapshot(
    request: Request,
    response: Response,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    sort: str = Query(default="device_name", pattern="^(device_name|last_seen)$"),
    runtime_filter: Optional[str] = Query(default=None, pattern="^(running|stopped)$"),
    runtime_status: Optional[str] = Query(None, pattern="^(running|stopped)$"),
    db: AsyncSession = Depends(get_db),
) -> FleetSnapshotResponse:
    from app.services.live_dashboard import LiveDashboardService

    effective_plant_ids = _resolve_accessible_plant_ids(request)
    service = LiveDashboardService(db)
    payload = await service.get_fleet_snapshot(
        page=page,
        page_size=page_size,
        sort=sort,
        tenant_id=get_tenant_id(request),
        runtime_filter=runtime_filter or runtime_status,
        accessible_plant_ids=effective_plant_ids,
    )
    response.headers["Cache-Control"] = "no-store"
    return FleetSnapshotResponse(**payload)


@router.get("/internal/active-tenant-ids")
async def get_active_tenant_ids(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, list[str]]:
    if getattr(request.state, "role", "") != "internal_service":
        raise HTTPException(
            status_code=403,
            detail={
                "code": "INTERNAL_SERVICE_REQUIRED",
                "message": "Internal service authentication is required for this endpoint.",
            },
        )

    result = await db.execute(
        select(Device.tenant_id)
        .where(Device.deleted_at.is_(None), Device.tenant_id.is_not(None))
        .distinct()
        .order_by(Device.tenant_id.asc())
    )
    tenant_ids = [row[0] for row in result.all() if row[0] is not None]
    return {"tenant_ids": tenant_ids}


@router.get(
    "/dashboard/fleet-stream",
)
async def fleet_snapshot_stream(
    request: Request,
    page_size: int = Query(200, ge=1, le=500),
    runtime_status: Optional[str] = Query(None, pattern="^(running|stopped)$"),
    last_event_id_query: Optional[str] = Query(default=None, alias="last_event_id"),
    last_event_id: Optional[str] = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    from app.services.live_dashboard import LiveDashboardService

    tenant_id = get_required_tenant_id(request)
    accessible_plant_ids = _resolve_accessible_plant_ids(request)
    last_seen_int = None
    last_event_id_raw = last_event_id if last_event_id is not None else last_event_id_query
    try:
        last_seen_int = int(last_event_id_raw) if last_event_id_raw is not None else None
    except ValueError:
        last_seen_int = None

    async def event_generator():
        heartbeat_interval = max(1, settings.DASHBOARD_STREAM_HEARTBEAT_SECONDS)
        send_timeout = max(1, settings.DASHBOARD_STREAM_SEND_TIMEOUT_SECONDS)
        subscriber_id, queue = await fleet_stream_broadcaster.subscribe(tenant_id)
        last_delivered_id = last_seen_int
        try:
            async with AsyncSessionLocal() as session:
                snapshot = await LiveDashboardService(session).get_fleet_snapshot(
                    page=1,
                    page_size=page_size,
                    sort="device_name",
                    tenant_id=tenant_id,
                    runtime_filter=runtime_status,
                    accessible_plant_ids=accessible_plant_ids,
                )
            event = FleetStreamEvent(
                id=fleet_stream_broadcaster.latest_event_id(tenant_id),
                event="fleet_update",
                generated_at=snapshot.get("generated_at"),
                freshness_ts=snapshot.get("generated_at"),
                stale=bool(snapshot.get("stale", False)),
                warnings=snapshot.get("warnings", []),
                devices=snapshot.get("devices", []),
                partial=False,
                version=max((int(d.get("version", 0)) for d in snapshot.get("devices", [])), default=0),
            )
            payload = event.model_dump(mode="json")
            try:
                last_delivered_id = int(payload.get("id")) if payload.get("id") is not None else last_delivered_id
            except (TypeError, ValueError):
                pass
            yield (
                f"id: {payload['id']}\n"
                f"event: {payload['event']}\n"
                f"data: {json.dumps(payload)}\n\n"
            )

            while True:
                if await request.is_disconnected():
                    await fleet_stream_broadcaster.unsubscribe(tenant_id, subscriber_id, reason="client_disconnect")
                    break

                try:
                    message = await asyncio.wait_for(queue.get(), timeout=heartbeat_interval)
                    LiveDashboardService.observe_stream_emit_lag(message.created_at)
                    message_id_int = int(message.id)
                    if last_delivered_id is not None and message_id_int <= last_delivered_id:
                        continue
                    created_at = message.created_at
                    if created_at.tzinfo is None:
                        created_at = created_at.replace(tzinfo=timezone.utc)
                    age_sec = (datetime.now(timezone.utc) - created_at).total_seconds()
                    if age_sec > send_timeout:
                        await fleet_stream_broadcaster.unsubscribe(tenant_id, subscriber_id, reason="send_timeout")
                        break
                    event_payload = FleetStreamEvent(
                        id=message.id,
                        event=message.event,
                        generated_at=message.data.get("generated_at"),
                        freshness_ts=message.data.get("generated_at"),
                        stale=bool(message.data.get("stale", False)),
                        warnings=message.data.get("warnings", []),
                        devices=[
                            device
                            for device in message.data.get("devices", [])
                            if accessible_plant_ids is None or device.get("plant_id") in accessible_plant_ids
                        ],
                        partial=bool(message.data.get("partial", False)),
                        version=int(message.data.get("version", 0)),
                    ).model_dump(mode="json")
                    last_delivered_id = message_id_int
                    yield (
                        f"id: {event_payload['id']}\n"
                        f"event: {event_payload['event']}\n"
                        f"data: {json.dumps(event_payload)}\n\n"
                    )
                except asyncio.TimeoutError:
                    heartbeat_payload = FleetStreamEvent(
                        id=fleet_stream_broadcaster.latest_event_id(tenant_id),
                        event="heartbeat",
                        generated_at=datetime.now(timezone.utc),
                        freshness_ts=datetime.now(timezone.utc),
                        stale=False,
                        warnings=[],
                        devices=[],
                        partial=False,
                        version=0,
                    ).model_dump(mode="json")
                    yield (
                        f"id: {heartbeat_payload['id']}\n"
                        f"event: heartbeat\n"
                        f"data: {json.dumps(heartbeat_payload)}\n\n"
                    )
        finally:
            await fleet_stream_broadcaster.unsubscribe(tenant_id, subscriber_id, reason="stream_closed")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store"},
    )


@router.get(
    "/{device_id}/dashboard-bootstrap",
    response_model=DeviceDashboardBootstrapResponse,
)
async def get_device_dashboard_bootstrap(
    device_id: str,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> DeviceDashboardBootstrapResponse:
    from app.services.live_dashboard import LiveDashboardService
    from app.services.dashboard import DashboardDeviceNotFoundError

    if await _resolve_scoped_device(request, db, device_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "success": False,
                "error": {
                    "code": "DEVICE_NOT_FOUND",
                    "message": f"Device '{device_id}' not found",
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

    service = LiveDashboardService(db)
    try:
        payload = await service.get_dashboard_bootstrap(
            device_id=device_id,
            tenant_id=get_required_tenant_id(request),
        )
    except DashboardDeviceNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "success": False,
                "error": {
                    "code": "DEVICE_NOT_FOUND",
                    "message": f"Device '{device_id}' not found",
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    response.headers["Cache-Control"] = "no-store"
    return DeviceDashboardBootstrapResponse(**payload)


@router.get(
    "/dashboard/today-loss-breakdown",
    response_model=TodayLossBreakdownResponse,
)
async def get_today_loss_breakdown(
    request: Request,
    response: Response,
    plant_id: Optional[str] = Query(None, description="Optional plant filter for today loss breakdown"),
    db: AsyncSession = Depends(get_db),
) -> TodayLossBreakdownResponse:
    """Get all-device today's loss split by category and device."""
    from app.services.live_dashboard import LiveDashboardService

    effective_plant_ids = _resolve_accessible_plant_ids(request, plant_id=plant_id)

    service = LiveDashboardService(db, TenantContext.from_request(request))
    payload = await service.get_today_loss_breakdown(
        tenant_id=get_tenant_id(request),
        plant_id=plant_id,
        accessible_plant_ids=effective_plant_ids,
    )
    response.headers["Cache-Control"] = "no-store"
    return TodayLossBreakdownResponse(**payload)


@router.get(
    "/calendar/monthly-energy",
    response_model=MonthlyEnergyCalendarResponse,
)
async def get_monthly_energy_calendar(
    request: Request,
    response: Response,
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    db: AsyncSession = Depends(get_db),
) -> MonthlyEnergyCalendarResponse:
    """Get all-device month energy totals and per-day list."""
    from app.services.live_dashboard import LiveDashboardService

    service = LiveDashboardService(db)
    payload = await service.get_monthly_energy_calendar(
        year=year,
        month=month,
        tenant_id=get_tenant_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return MonthlyEnergyCalendarResponse(**payload)


@router.get(
    "/hardware-mappings",
    response_model=DeviceHardwareMappingListResponse,
)
async def list_current_hardware_mappings(
    request: Request,
    plant_id: Optional[str] = Query(None),
    device_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> DeviceHardwareMappingListResponse:
    accessible_plant_ids = _resolve_accessible_plant_ids(request, plant_id=plant_id)
    service = HardwareInventoryService(db, TenantContext.from_request(request))
    try:
        mappings = await service.list_current_device_mappings(
            plant_id=plant_id,
            device_id=device_id,
        )
    except Exception as exc:
        _raise_hardware_http_error(exc)
        raise

    if accessible_plant_ids is not None:
        mappings = [row for row in mappings if row.plant_id in accessible_plant_ids]

    plants = await _list_tenant_plants(request, get_required_tenant_id(request))
    plant_names = _plant_name_by_id(plants)
    payload = [
        DeviceHardwareMappingResponse(
            device_id=row.device_id,
            plant_id=row.plant_id,
            plant_name=plant_names.get(row.plant_id, row.plant_id),
            installation_role=row.installation_role,
            installation_role_label=_installation_role_label(row.installation_role),
            hardware_unit_id=row.hardware_unit_id,
            hardware_type=row.hardware_type,
            hardware_type_label=_hardware_type_label(row.hardware_type),
            hardware_name=row.hardware_name,
            manufacturer=row.manufacturer,
            model=row.model,
            serial_number=row.serial_number,
            status="Active" if row.is_active else "Decommissioned",
            is_active=row.is_active,
        )
        for row in mappings
    ]
    return DeviceHardwareMappingListResponse(data=payload, total=len(payload))


@router.get(
    "/{device_id}",
    response_model=DeviceSingleResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Device not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def get_device(
    device_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> DeviceSingleResponse:
    """Get a device by ID.
    
    - **device_id**: Unique device identifier
    - **tenant_id**: Derived from JWT or tenant_id query param for backward compatibility
    """
    service = DeviceService(db, TenantContext.from_request(request))
    tenant_id = get_required_tenant_id(request)
    device = await service.get_device(device_id, tenant_id)
    
    if not device:
        logger.warning("Device not found", extra={"device_id": device_id})
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "success": False,
                "error": {
                    "code": "DEVICE_NOT_FOUND",
                    "message": f"Device with ID '{device_id}' not found",
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

    auth = get_auth_state(request)
    if auth["role"] in ("plant_manager", "operator", "viewer"):
        if device.plant_id and device.plant_id not in auth["plant_ids"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "PLANT_ACCESS_DENIED",
                "message": "You do not have access to this device's plant.",
            },
        )

    return _serialize_device_response(device)


async def _resolve_scoped_device(
    request: Request,
    db: AsyncSession,
    device_id: str,
):
    tenant_id = get_required_tenant_id(request)
    device = await DeviceService(db, TenantContext.from_request(request)).get_device(device_id, tenant_id)
    if device is None:
        return None
    _ensure_entity_plant_access(request, device.plant_id)
    return device


@router.get(
    "",
    response_model=DeviceListResponse,
    responses={
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def list_devices(
    request: Request,
    plant_id: Optional[str] = Query(None, description="Filter by plant"),
    device_type: Optional[str] = Query(None, description="Filter by device type"),
    status: Optional[str] = Query(None, description="Filter by device status"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
) -> DeviceListResponse:
    """List all devices with optional filtering and pagination.
    
    - **plant_id**: Optional plant filter
    - **device_type**: Filter by device type (e.g., 'bulb', 'compressor')
    - **status**: Filter by status ('active', 'inactive', 'maintenance', 'error')
    - **page**: Page number (1-based)
    - **page_size**: Number of items per page (max 100)
    """
    tenant_id = get_tenant_id(request)
    auth = get_auth_state(request)
    effective_plant_ids: list[str] | None = None
    if auth["role"] in ("plant_manager", "operator", "viewer"):
        if plant_id and plant_id not in auth["plant_ids"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "PLANT_ACCESS_DENIED",
                    "message": "You do not have access to this plant.",
                },
            )
        effective_plant_ids = [plant_id] if plant_id else auth["plant_ids"]
    service = DeviceService(db, TenantContext.from_request(request))
    devices, total = await service.list_devices(
        tenant_id=tenant_id,
        plant_id=plant_id,
        accessible_plant_ids=effective_plant_ids,
        device_type=device_type,
        status=status,
        page=page,
        page_size=page_size,
    )
    
    total_pages = (total + page_size - 1) // page_size
    
    return DeviceListResponse(
        data=_serialize_device_list_rows(devices),
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.post(
    "",
    response_model=DeviceSingleResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse, "description": "Validation error"},
        409: {"model": ErrorResponse, "description": "Device already exists"},
        503: {"model": ErrorResponse, "description": "Device ID allocation failed"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def create_device(
    device_data: DeviceCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> DeviceSingleResponse:
    """Create a new device.
    
    - **device_id**: Optional caller-supplied identifier. If omitted, the platform generates one.
    - **device_name**: Human-readable name (required)
    - **device_type**: Device category (required)
    - **device_id_class**: ID allocation class for the generated prefix (`active`, `test`, or `virtual`)
    - **manufacturer**: Device manufacturer (optional)
    - **model**: Device model (optional)
    - **location**: Physical location (optional)
    - **status**: Device status (default: 'active')
    """
    auth = get_auth_state(request)
    tenant_id = get_required_tenant_id(request)
    if auth["role"] == "viewer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FORBIDDEN",
                "message": "Role 'viewer' is not permitted for this action.",
            },
        )

    if not device_data.plant_id or not device_data.plant_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "PLANT_REQUIRED",
                "message": "Plant ID is required. Create or choose a plant before adding a device.",
            },
        )

    device_data.plant_id = device_data.plant_id.strip()

    device_data.tenant_id = tenant_id

    if auth["role"] in ("plant_manager", "operator") and device_data.plant_id not in auth["plant_ids"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "PLANT_ACCESS_DENIED",
                "message": "You do not have access to this plant.",
            },
        )

    await _validate_org_plant_access(request, tenant_id=tenant_id, plant_id=device_data.plant_id)

    service = DeviceService(db, TenantContext.from_request(request))
    
    try:
        device = await service.create_device(device_data)
        return _serialize_device_response(device)
    except DevicePlantRequiredError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "PLANT_REQUIRED",
                "message": str(e),
            },
        ) from e
    except DeviceAlreadyExistsError as e:
        logger.warning(
            "Device creation conflict",
            extra={
                "tenant_id": tenant_id,
                "error": str(e),
            }
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "success": False,
                "error": {
                    "code": "DEVICE_ALREADY_EXISTS",
                    "message": str(e),
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    except DeviceIdAllocationError as e:
        logger.error(
            "Device ID allocation failed during device creation",
            extra={
                "tenant_id": tenant_id,
                "error": str(e),
            }
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "success": False,
                "error": {
                    "code": "DEVICE_ID_ALLOCATION_FAILED",
                    "message": str(e),
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        )


@router.post(
    "/hardware-units",
    response_model=HardwareUnitSingleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_hardware_unit(
    payload: HardwareUnitCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HardwareUnitSingleResponse:
    _ensure_hardware_write_access(request)
    payload.tenant_id = get_required_tenant_id(request)
    _ensure_entity_plant_access(request, payload.plant_id)
    await _validate_org_plant_access(request, tenant_id=payload.tenant_id, plant_id=payload.plant_id)

    service = HardwareInventoryService(db, TenantContext.from_request(request))
    try:
        hardware_unit = await service.create_hardware_unit(payload)
    except Exception as exc:
        _raise_hardware_http_error(exc)
        raise
    return HardwareUnitSingleResponse(data=hardware_unit)


@router.get(
    "/hardware-units/list",
    response_model=HardwareUnitListResponse,
)
async def list_hardware_units(
    request: Request,
    plant_id: Optional[str] = Query(None),
    unit_type: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
) -> HardwareUnitListResponse:
    accessible_plant_ids = _resolve_accessible_plant_ids(request, plant_id=plant_id)
    service = HardwareInventoryService(db, TenantContext.from_request(request))
    units, _total = await service.list_hardware_units(
        plant_id=plant_id,
        unit_type=unit_type,
        status=status_filter,
    )
    if accessible_plant_ids is not None:
        units = [unit for unit in units if unit.plant_id in accessible_plant_ids]
    return HardwareUnitListResponse(data=units, total=len(units))


@router.put(
    "/hardware-units/{hardware_unit_id}",
    response_model=HardwareUnitSingleResponse,
)
async def update_hardware_unit(
    hardware_unit_id: str,
    payload: HardwareUnitUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HardwareUnitSingleResponse:
    _ensure_hardware_write_access(request)
    service = HardwareInventoryService(db, TenantContext.from_request(request))
    try:
        current = await service.get_hardware_unit(hardware_unit_id)
        _ensure_entity_plant_access(request, current.plant_id)
        next_plant_id = payload.plant_id if payload.plant_id is not None else current.plant_id
        await _validate_org_plant_access(
            request,
            tenant_id=get_required_tenant_id(request),
            plant_id=next_plant_id,
        )
        updated = await service.update_hardware_unit(hardware_unit_id, payload)
    except Exception as exc:
        _raise_hardware_http_error(exc)
        raise
    return HardwareUnitSingleResponse(data=updated)


@router.post(
    "/{device_id}/hardware-installations",
    response_model=DeviceHardwareInstallationSingleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def install_hardware_on_device(
    device_id: str,
    payload: DeviceHardwareInstallationCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> DeviceHardwareInstallationSingleResponse:
    _ensure_hardware_write_access(request)
    device_service = DeviceService(db, TenantContext.from_request(request))
    device = await device_service.get_device(device_id, get_required_tenant_id(request))
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "DEVICE_NOT_FOUND", "message": f"Device '{device_id}' not found."},
        )
    _ensure_entity_plant_access(request, device.plant_id)

    service = HardwareInventoryService(db, TenantContext.from_request(request))
    try:
        installation = await service.install_hardware(device_id, payload)
    except Exception as exc:
        _raise_hardware_http_error(exc)
        raise
    return DeviceHardwareInstallationSingleResponse(data=installation)


@router.post(
    "/hardware-installations/{installation_id}/decommission",
    response_model=DeviceHardwareInstallationSingleResponse,
)
async def decommission_hardware_installation(
    installation_id: int,
    payload: DeviceHardwareInstallationDecommission,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> DeviceHardwareInstallationSingleResponse:
    _ensure_hardware_write_access(request)
    service = HardwareInventoryService(db, TenantContext.from_request(request))
    try:
        current = await service.get_installation(installation_id)
        _ensure_entity_plant_access(request, current.plant_id)
        installation = await service.decommission_installation(installation_id, payload)
    except Exception as exc:
        _raise_hardware_http_error(exc)
        raise
    return DeviceHardwareInstallationSingleResponse(data=installation)


@router.get(
    "/{device_id}/hardware-installations/current",
    response_model=DeviceHardwareInstallationHistoryResponse,
)
async def list_current_device_hardware_installations(
    device_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> DeviceHardwareInstallationHistoryResponse:
    device_service = DeviceService(db, TenantContext.from_request(request))
    device = await device_service.get_device(device_id, get_required_tenant_id(request))
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "DEVICE_NOT_FOUND", "message": f"Device '{device_id}' not found."},
        )
    _ensure_entity_plant_access(request, device.plant_id)

    service = HardwareInventoryService(db, TenantContext.from_request(request))
    try:
        installations = await service.list_current_device_installations(device_id)
    except Exception as exc:
        _raise_hardware_http_error(exc)
        raise
    return DeviceHardwareInstallationHistoryResponse(data=installations, total=len(installations))


@router.get(
    "/{device_id}/hardware-installations/history",
    response_model=DeviceHardwareInstallationHistoryResponse,
)
async def get_device_hardware_installation_history(
    device_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> DeviceHardwareInstallationHistoryResponse:
    device_service = DeviceService(db, TenantContext.from_request(request))
    device = await device_service.get_device(device_id, get_required_tenant_id(request))
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "DEVICE_NOT_FOUND", "message": f"Device '{device_id}' not found."},
        )
    _ensure_entity_plant_access(request, device.plant_id)

    service = HardwareInventoryService(db, TenantContext.from_request(request))
    try:
        history = await service.get_device_installation_history(device_id)
    except Exception as exc:
        _raise_hardware_http_error(exc)
        raise
    return DeviceHardwareInstallationHistoryResponse(data=history, total=len(history))


@router.get(
    "/hardware-installations/history",
    response_model=DeviceHardwareInstallationHistoryResponse,
)
async def list_org_hardware_installation_history(
    request: Request,
    plant_id: Optional[str] = Query(None),
    device_id: Optional[str] = Query(None),
    hardware_unit_id: Optional[str] = Query(None),
    state: Optional[str] = Query(None, pattern="^(active|decommissioned)$"),
    db: AsyncSession = Depends(get_db),
) -> DeviceHardwareInstallationHistoryResponse:
    accessible_plant_ids = _resolve_accessible_plant_ids(request, plant_id=plant_id)
    if device_id is not None:
        device_service = DeviceService(db, TenantContext.from_request(request))
        device = await device_service.get_device(device_id, get_required_tenant_id(request))
        if device is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "DEVICE_NOT_FOUND", "message": f"Device '{device_id}' not found."},
            )
        _ensure_entity_plant_access(request, device.plant_id)

    service = HardwareInventoryService(db, TenantContext.from_request(request))
    active_only = None if state is None else state == "active"
    try:
        history = await service.list_installation_history(
            plant_id=plant_id,
            device_id=device_id,
            hardware_unit_id=hardware_unit_id,
            active_only=active_only,
        )
    except Exception as exc:
        _raise_hardware_http_error(exc)
        raise
    if accessible_plant_ids is not None:
        history = [row for row in history if row.plant_id in accessible_plant_ids]
    return DeviceHardwareInstallationHistoryResponse(data=history, total=len(history))


@router.put(
    "/{device_id}",
    response_model=DeviceSingleResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Validation error"},
        404: {"model": ErrorResponse, "description": "Device not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def update_device(
    device_id: str,
    device_data: DeviceUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> DeviceSingleResponse:
    """Update an existing device.
    
    Only provided fields will be updated. All fields are optional.
    
    - **device_id**: Device identifier in path
    - **device_name**: Updated name (optional)
    - **device_type**: Updated type (optional)
    - **manufacturer**: Updated manufacturer (optional)
    - **model**: Updated model (optional)
    - **location**: Updated location (optional)
    - **status**: Updated status (optional)
    """
    service = DeviceService(db, TenantContext.from_request(request))
    tenant_id = get_tenant_id(request)
    auth = get_auth_state(request)
    existing_device = await service.get_device(device_id, tenant_id)
    if not existing_device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "success": False,
                "error": {
                    "code": "DEVICE_NOT_FOUND",
                    "message": f"Device with ID '{device_id}' not found",
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    if auth["role"] in ("plant_manager", "operator", "viewer"):
        if existing_device.plant_id and existing_device.plant_id not in auth["plant_ids"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "PLANT_ACCESS_DENIED",
                    "message": "You do not have access to this device's plant.",
                },
            )
    next_plant_id = existing_device.plant_id
    if "plant_id" in device_data.model_fields_set:
        if device_data.plant_id is None or not device_data.plant_id.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "PLANT_REQUIRED",
                    "message": "Plant ID is required. Devices cannot exist without a plant assignment.",
                },
            )
        next_plant_id = device_data.plant_id.strip()
        device_data.plant_id = next_plant_id

    if auth["role"] in ("plant_manager", "operator", "viewer") and next_plant_id not in auth["plant_ids"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "PLANT_ACCESS_DENIED",
                "message": "You do not have access to this plant.",
            },
        )

    await _validate_org_plant_access(request, tenant_id=tenant_id, plant_id=next_plant_id)

    try:
        device = await service.update_device(device_id, device_data, tenant_id)
    except DevicePlantRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "PLANT_REQUIRED",
                "message": str(exc),
            },
        ) from exc
    
    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "success": False,
                "error": {
                    "code": "DEVICE_NOT_FOUND",
                    "message": f"Device with ID '{device_id}' not found",
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    
    return _serialize_device_response(device)


@router.delete(
    "/{device_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        404: {"model": ErrorResponse, "description": "Device not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def delete_device(
    device_id: str,
    request: Request,
    soft: bool = Query(True, description="Perform soft delete"),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a device.
    
    - **device_id**: Device identifier
    - **tenant_id**: Derived from JWT or tenant_id query param for backward compatibility
    - **soft**: If True, marks device as deleted; if False, permanently removes
    """
    service = DeviceService(db, TenantContext.from_request(request))
    tenant_id = get_tenant_id(request)
    auth = get_auth_state(request)
    existing_device = await service.get_device(device_id, tenant_id)
    if not existing_device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "success": False,
                "error": {
                    "code": "DEVICE_NOT_FOUND",
                    "message": f"Device with ID '{device_id}' not found",
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    if auth["role"] in ("plant_manager", "operator", "viewer"):
        if existing_device.plant_id and existing_device.plant_id not in auth["plant_ids"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "PLANT_ACCESS_DENIED",
                    "message": "You do not have access to this device's plant.",
                },
            )
    deleted = await service.delete_device(device_id, tenant_id, soft=soft)
    
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "success": False,
                "error": {
                    "code": "DEVICE_NOT_FOUND",
                    "message": f"Device with ID '{device_id}' not found",
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    from app.services.live_projection import LiveProjectionService
    from app.services.live_dashboard import LiveDashboardService
    await LiveProjectionService(db).remove_device_projection(device_id, tenant_id)
    fleet_payload = await LiveDashboardService(db).get_fleet_snapshot(
        page=1,
        page_size=5000,
        sort="device_name",
        tenant_id=tenant_id,
    )
    await fleet_stream_broadcaster.publish(
        tenant_id,
        "fleet_update",
        {
            "generated_at": fleet_payload.get("generated_at"),
            "stale": bool(fleet_payload.get("stale", False)),
            "warnings": fleet_payload.get("warnings", []),
            "devices": fleet_payload.get("devices", []),
            "partial": False,
            "version": max((int(d.get("version", 0)) for d in fleet_payload.get("devices", [])), default=0),
        },
    )
    return None


# =====================================================
# Shift Configuration Endpoints
# =====================================================

@router.post(
    "/{device_id}/shifts",
    response_model=ShiftSingleResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse, "description": "Validation error"},
        409: {"model": ErrorResponse, "description": "Shift overlap conflict"},
        404: {"model": ErrorResponse, "description": "Device not found"},
    },
)
async def create_shift(
    device_id: str,
    shift_data: ShiftCreate,
    request: Request,
    tenant_id: Optional[str] = Query(None, description="Tenant ID for multi-tenancy"),
    db: AsyncSession = Depends(get_db),
) -> ShiftSingleResponse:
    """Create a new shift for a device."""
    from app.services.shift import ShiftService, ShiftOverlapError

    _ensure_device_write_access(request)
    if await _resolve_scoped_device(request, db, device_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "success": False,
                "error": {
                    "code": "DEVICE_NOT_FOUND",
                    "message": f"Device with ID '{device_id}' not found",
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    shift_dict = shift_data.model_dump()
    shift_dict["device_id"] = device_id
    shift_dict["tenant_id"] = get_tenant_id(request)
    
    shift_create = ShiftCreate(**shift_dict)
    
    service = ShiftService(db)
    try:
        shift = await service.create_shift(shift_create)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "message": str(exc), "code": "SHIFT_VALIDATION_ERROR"},
        )
    except ShiftOverlapError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "success": False,
                "message": str(exc),
                "code": "SHIFT_OVERLAP_CONFLICT",
                "conflicts": exc.conflicts,
            },
        )
    from app.services.live_projection import LiveProjectionService
    from app.services.live_dashboard import LiveDashboardService
    await LiveProjectionService(db).recompute_after_configuration_change(
        device_id,
        get_tenant_id(request),
    )
    dashboard = LiveDashboardService(db)
    await fleet_stream_broadcaster.publish(
        get_tenant_id(request),
        "fleet_update",
        await dashboard.publish_device_update(
            device_id=device_id,
            tenant_id=get_tenant_id(request),
            partial=True,
        ),
    )
    return ShiftSingleResponse(data=shift)


@router.get(
    "/{device_id}/shifts",
    response_model=ShiftListResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Device not found"},
    },
)
async def list_shifts(
    device_id: str,
    request: Request,
    response: Response,
    tenant_id: Optional[str] = Query(None, description="Tenant ID for multi-tenancy"),
    db: AsyncSession = Depends(get_db),
) -> ShiftListResponse:
    """List all shifts for a device."""
    from app.services.shift import ShiftService

    if await _resolve_scoped_device(request, db, device_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "success": False,
                "error": {
                    "code": "DEVICE_NOT_FOUND",
                    "message": f"Device with ID '{device_id}' not found",
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    
    service = ShiftService(db)
    shifts = await service.get_shifts_by_device(device_id, get_tenant_id(request))
    response.headers["Cache-Control"] = "no-store"
    return ShiftListResponse(data=shifts, total=len(shifts))


@router.get(
    "/{device_id}/shifts/{shift_id}",
    response_model=ShiftSingleResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Shift not found"},
    },
)
async def get_shift(
    device_id: str,
    shift_id: int,
    request: Request,
    tenant_id: Optional[str] = Query(None, description="Tenant ID for multi-tenancy"),
    db: AsyncSession = Depends(get_db),
) -> ShiftSingleResponse:
    """Get a specific shift by ID."""
    from app.services.shift import ShiftService

    if await _resolve_scoped_device(request, db, device_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "success": False,
                "error": {
                    "code": "DEVICE_NOT_FOUND",
                    "message": f"Device with ID '{device_id}' not found",
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    
    service = ShiftService(db)
    shift = await service.get_shift(shift_id, device_id, get_tenant_id(request))
    
    if not shift:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "success": False,
                "error": {
                    "code": "SHIFT_NOT_FOUND",
                    "message": f"Shift with ID '{shift_id}' not found for device '{device_id}'",
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    
    return ShiftSingleResponse(data=shift)


@router.put(
    "/{device_id}/shifts/{shift_id}",
    response_model=ShiftSingleResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Validation error"},
        409: {"model": ErrorResponse, "description": "Shift overlap conflict"},
        404: {"model": ErrorResponse, "description": "Shift not found"},
    },
)
async def update_shift(
    device_id: str,
    shift_id: int,
    shift_data: ShiftUpdate,
    request: Request,
    tenant_id: Optional[str] = Query(None, description="Tenant ID for multi-tenancy"),
    db: AsyncSession = Depends(get_db),
) -> ShiftSingleResponse:
    """Update an existing shift."""
    from app.services.shift import ShiftService, ShiftOverlapError

    _ensure_device_write_access(request)
    if await _resolve_scoped_device(request, db, device_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "success": False,
                "error": {
                    "code": "DEVICE_NOT_FOUND",
                    "message": f"Device with ID '{device_id}' not found",
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    service = ShiftService(db)
    try:
        shift = await service.update_shift(shift_id, device_id, get_tenant_id(request), shift_data)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "message": str(exc), "code": "SHIFT_VALIDATION_ERROR"},
        )
    except ShiftOverlapError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "success": False,
                "message": str(exc),
                "code": "SHIFT_OVERLAP_CONFLICT",
                "conflicts": exc.conflicts,
            },
        )
    
    if not shift:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "success": False,
                "error": {
                    "code": "SHIFT_NOT_FOUND",
                    "message": f"Shift with ID '{shift_id}' not found for device '{device_id}'",
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    from app.services.live_projection import LiveProjectionService
    from app.services.live_dashboard import LiveDashboardService
    await LiveProjectionService(db).recompute_after_configuration_change(
        device_id,
        get_tenant_id(request),
    )
    dashboard = LiveDashboardService(db)
    await fleet_stream_broadcaster.publish(
        get_tenant_id(request),
        "fleet_update",
        await dashboard.publish_device_update(
            device_id=device_id,
            tenant_id=get_tenant_id(request),
            partial=True,
        ),
    )
    return ShiftSingleResponse(data=shift)


@router.delete(
    "/{device_id}/shifts/{shift_id}",
    response_model=ShiftDeleteResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Shift not found"},
    },
)
async def delete_shift(
    device_id: str,
    shift_id: int,
    request: Request,
    tenant_id: Optional[str] = Query(None, description="Tenant ID for multi-tenancy"),
    db: AsyncSession = Depends(get_db),
) -> ShiftDeleteResponse:
    """Delete a shift."""
    from app.services.shift import ShiftService

    _ensure_device_write_access(request)
    if await _resolve_scoped_device(request, db, device_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "success": False,
                "error": {
                    "code": "DEVICE_NOT_FOUND",
                    "message": f"Device with ID '{device_id}' not found",
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    service = ShiftService(db)
    success = await service.delete_shift(shift_id, device_id, get_tenant_id(request))
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "success": False,
                "error": {
                    "code": "SHIFT_NOT_FOUND",
                    "message": f"Shift with ID '{shift_id}' not found for device '{device_id}'",
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    from app.services.live_projection import LiveProjectionService
    from app.services.live_dashboard import LiveDashboardService
    await LiveProjectionService(db).recompute_after_configuration_change(
        device_id,
        get_tenant_id(request),
    )
    dashboard = LiveDashboardService(db)
    await fleet_stream_broadcaster.publish(
        get_tenant_id(request),
        "fleet_update",
        await dashboard.publish_device_update(
            device_id=device_id,
            tenant_id=get_tenant_id(request),
            partial=True,
        ),
    )
    return ShiftDeleteResponse(
        success=True,
        message=f"Shift {shift_id} deleted successfully",
        shift_id=shift_id
    )


@router.get(
    "/{device_id}/uptime",
    response_model=UptimeResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Device not found"},
    },
)
async def get_uptime(
    device_id: str,
    request: Request,
    response: Response,
    tenant_id: Optional[str] = Query(None, description="Tenant ID for multi-tenancy"),
    db: AsyncSession = Depends(get_db),
) -> UptimeResponse:
    """Calculate uptime for a device based on configured shifts."""
    from app.services.shift import ShiftService

    if await _resolve_scoped_device(request, db, device_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "success": False,
                "error": {
                    "code": "DEVICE_NOT_FOUND",
                    "message": f"Device with ID '{device_id}' not found",
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    
    service = ShiftService(db)
    uptime = await service.calculate_uptime(device_id, get_tenant_id(request))
    response.headers["Cache-Control"] = "no-store"
    return UptimeResponse(**uptime)


@router.get(
    "/{device_id}/performance-trends",
    response_model=PerformanceTrendResponse,
)
async def get_performance_trends(
    device_id: str,
    request: Request,
    response: Response,
    metric: str = Query("health", pattern="^(health|uptime)$"),
    range: str = Query("24h", pattern="^(30m|1h|6h|24h|7d|30d)$"),
    db: AsyncSession = Depends(get_db),
) -> PerformanceTrendResponse:
    """Get materialized performance trends for a device."""
    from app.services.performance_trends import PerformanceTrendService

    tenant_id = get_required_tenant_id(request)
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "MISSING_TENANT_SCOPE",
                "message": "Tenant scope is required to load performance trends.",
            },
        )

    device = await _resolve_scoped_device(request, db, device_id)
    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "success": False,
                "error": {
                    "code": "DEVICE_NOT_FOUND",
                    "message": f"Device with ID '{device_id}' not found",
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

    service = PerformanceTrendService(db)
    result = await service.get_trends(device_id=device_id, tenant_id=tenant_id, metric=metric, range_key=range)
    response.headers["Cache-Control"] = "no-store"
    return PerformanceTrendResponse(**result)


# =====================================================
# Health Configuration Endpoints
# =====================================================

@router.post(
    "/{device_id}/health-config",
    response_model=ParameterHealthConfigSingleResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse, "description": "Validation error"},
        404: {"model": ErrorResponse, "description": "Device not found"},
    },
)
async def create_health_config(
    device_id: str,
    config_data: ParameterHealthConfigCreate,
    request: Request,
    tenant_id: Optional[str] = Query(None, description="Tenant ID for multi-tenancy"),
    db: AsyncSession = Depends(get_db),
) -> ParameterHealthConfigSingleResponse:
    """Create a new health configuration for a device parameter."""
    from app.services.health_config import DuplicateHealthConfigError, HealthConfigService

    _ensure_device_write_access(request)
    if await _resolve_scoped_device(request, db, device_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "success": False,
                "error": {
                    "code": "DEVICE_NOT_FOUND",
                    "message": f"Device with ID '{device_id}' not found",
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    config_dict = config_data.model_dump()
    config_dict["device_id"] = device_id
    config_dict["tenant_id"] = get_tenant_id(request)
    
    config_create = ParameterHealthConfigCreate(**config_dict)
    
    service = HealthConfigService(db)
    try:
        config = await service.create_health_config(config_create)
    except DuplicateHealthConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "success": False,
                "error": {
                    "code": "HEALTH_CONFIG_DUPLICATE_PARAMETER",
                    "message": str(exc),
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        ) from exc
    from app.services.live_projection import LiveProjectionService
    from app.services.live_dashboard import LiveDashboardService
    from app.services.performance_trends import PerformanceTrendService
    await LiveProjectionService(db).recompute_after_configuration_change(
        device_id,
        get_tenant_id(request),
    )
    trend_service = PerformanceTrendService(db)
    await trend_service.repair_recent_health_window(
        device_id=device_id,
        tenant_id=get_tenant_id(request),
        rewrite_existing_health=True,
    )
    dashboard = LiveDashboardService(db)
    await fleet_stream_broadcaster.publish(
        get_tenant_id(request),
        "fleet_update",
        await dashboard.publish_device_update(
            device_id=device_id,
            tenant_id=get_tenant_id(request),
            partial=True,
        ),
    )
    return ParameterHealthConfigSingleResponse(data=config)


@router.get(
    "/{device_id}/health-config",
    response_model=ParameterHealthConfigListResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Device not found"},
    },
)
async def list_health_configs(
    device_id: str,
    request: Request,
    response: Response,
    tenant_id: Optional[str] = Query(None, description="Tenant ID for multi-tenancy"),
    db: AsyncSession = Depends(get_db),
) -> ParameterHealthConfigListResponse:
    """List all health configurations for a device."""
    from app.services.health_config import HealthConfigService

    if await _resolve_scoped_device(request, db, device_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "success": False,
                "error": {
                    "code": "DEVICE_NOT_FOUND",
                    "message": f"Device with ID '{device_id}' not found",
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    
    service = HealthConfigService(db)
    configs = await service.get_health_configs_by_device(device_id, get_tenant_id(request))
    response.headers["Cache-Control"] = "no-store"
    return ParameterHealthConfigListResponse(data=configs, total=len(configs))


@router.get(
    "/{device_id}/health-config/validate-weights",
    response_model=WeightValidationResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Device not found"},
    },
)
async def validate_health_weights(
    device_id: str,
    request: Request,
    tenant_id: Optional[str] = Query(None, description="Tenant ID for multi-tenancy"),
    db: AsyncSession = Depends(get_db),
) -> WeightValidationResponse:
    """Validate that all health parameter weights sum to 100%."""
    from app.services.health_config import HealthConfigService

    if await _resolve_scoped_device(request, db, device_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "success": False,
                "error": {
                    "code": "DEVICE_NOT_FOUND",
                    "message": f"Device with ID '{device_id}' not found",
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

    service = HealthConfigService(db)
    validation = await service.validate_weights(device_id, get_tenant_id(request))

    return WeightValidationResponse(**validation)


@router.get(
    "/{device_id}/health-config/{config_id}",
    response_model=ParameterHealthConfigSingleResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Configuration not found"},
    },
)
async def get_health_config(
    device_id: str,
    config_id: int,
    request: Request,
    tenant_id: Optional[str] = Query(None, description="Tenant ID for multi-tenancy"),
    db: AsyncSession = Depends(get_db),
) -> ParameterHealthConfigSingleResponse:
    """Get a specific health configuration by ID."""
    from app.services.health_config import HealthConfigService

    if await _resolve_scoped_device(request, db, device_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "success": False,
                "error": {
                    "code": "DEVICE_NOT_FOUND",
                    "message": f"Device with ID '{device_id}' not found",
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    
    service = HealthConfigService(db)
    config = await service.get_health_config(config_id, device_id, get_tenant_id(request))
    
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "success": False,
                "error": {
                    "code": "HEALTH_CONFIG_NOT_FOUND",
                    "message": f"Health configuration with ID '{config_id}' not found for device '{device_id}'",
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    
    return ParameterHealthConfigSingleResponse(data=config)


@router.put(
    "/{device_id}/health-config/{config_id}",
    response_model=ParameterHealthConfigSingleResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Configuration not found"},
    },
)
async def update_health_config(
    device_id: str,
    config_id: int,
    config_data: ParameterHealthConfigUpdate,
    request: Request,
    tenant_id: Optional[str] = Query(None, description="Tenant ID for multi-tenancy"),
    db: AsyncSession = Depends(get_db),
) -> ParameterHealthConfigSingleResponse:
    """Update an existing health configuration."""
    from app.services.health_config import DuplicateHealthConfigError, HealthConfigService

    _ensure_device_write_access(request)
    if await _resolve_scoped_device(request, db, device_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "success": False,
                "error": {
                    "code": "DEVICE_NOT_FOUND",
                    "message": f"Device with ID '{device_id}' not found",
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    service = HealthConfigService(db)
    try:
        config = await service.update_health_config(config_id, device_id, get_tenant_id(request), config_data)
    except DuplicateHealthConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "success": False,
                "error": {
                    "code": "HEALTH_CONFIG_DUPLICATE_PARAMETER",
                    "message": str(exc),
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        ) from exc
    
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "success": False,
                "error": {
                    "code": "HEALTH_CONFIG_NOT_FOUND",
                    "message": f"Health configuration with ID '{config_id}' not found for device '{device_id}'",
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    from app.services.live_projection import LiveProjectionService
    from app.services.live_dashboard import LiveDashboardService
    from app.services.performance_trends import PerformanceTrendService
    await LiveProjectionService(db).recompute_after_configuration_change(
        device_id,
        get_tenant_id(request),
    )
    trend_service = PerformanceTrendService(db)
    await trend_service.repair_recent_health_window(
        device_id=device_id,
        tenant_id=get_tenant_id(request),
        rewrite_existing_health=True,
    )
    dashboard = LiveDashboardService(db)
    await fleet_stream_broadcaster.publish(
        get_tenant_id(request),
        "fleet_update",
        await dashboard.publish_device_update(
            device_id=device_id,
            tenant_id=get_tenant_id(request),
            partial=True,
        ),
    )
    return ParameterHealthConfigSingleResponse(data=config)


@router.delete(
    "/{device_id}/health-config/{config_id}",
    response_model=dict,
)
async def delete_health_config(
    device_id: str,
    config_id: int,
    request: Request,
    tenant_id: Optional[str] = Query(None, description="Tenant ID for multi-tenancy"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a health configuration (idempotent)."""
    from app.services.health_config import HealthConfigService

    _ensure_device_write_access(request)
    if await _resolve_scoped_device(request, db, device_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "success": False,
                "error": {
                    "code": "DEVICE_NOT_FOUND",
                    "message": f"Device with ID '{device_id}' not found",
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    service = HealthConfigService(db)
    success = await service.delete_health_config(config_id, device_id, get_tenant_id(request))
    from app.services.live_projection import LiveProjectionService
    from app.services.live_dashboard import LiveDashboardService
    from app.services.performance_trends import PerformanceTrendService
    await LiveProjectionService(db).recompute_after_configuration_change(
        device_id,
        get_tenant_id(request),
    )
    trend_service = PerformanceTrendService(db)
    await trend_service.repair_recent_health_window(
        device_id=device_id,
        tenant_id=get_tenant_id(request),
        rewrite_existing_health=True,
    )
    dashboard = LiveDashboardService(db)
    await fleet_stream_broadcaster.publish(
        get_tenant_id(request),
        "fleet_update",
        await dashboard.publish_device_update(
            device_id=device_id,
            tenant_id=get_tenant_id(request),
            partial=True,
        ),
    )
    return {
        "success": True,
        "message": (
            f"Health configuration {config_id} deleted successfully"
            if success
            else f"Health configuration {config_id} already deleted"
        ),
        "config_id": config_id,
        "deleted": bool(success),
    }


@router.post(
    "/{device_id}/health-config/bulk",
    response_model=ParameterHealthConfigListResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse, "description": "Validation error"},
        404: {"model": ErrorResponse, "description": "Device not found"},
    },
)
async def bulk_create_health_configs(
    device_id: str,
    configs: list[ParameterHealthConfigCreate],
    request: Request,
    tenant_id: Optional[str] = Query(None, description="Tenant ID for multi-tenancy"),
    db: AsyncSession = Depends(get_db),
) -> ParameterHealthConfigListResponse:
    """Bulk create or update health configurations for a device."""
    from app.services.health_config import DuplicateHealthConfigError, HealthConfigService

    _ensure_device_write_access(request)
    if await _resolve_scoped_device(request, db, device_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "success": False,
                "error": {
                    "code": "DEVICE_NOT_FOUND",
                    "message": f"Device with ID '{device_id}' not found",
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    tenant_scope = get_tenant_id(request)
    config_dicts = [c.model_dump() for c in configs]
    for config_dict in config_dicts:
        config_dict["device_id"] = device_id
        config_dict["tenant_id"] = tenant_scope
    
    service = HealthConfigService(db)
    try:
        result = await service.bulk_create_or_update(device_id, tenant_scope, config_dicts)
    except DuplicateHealthConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "success": False,
                "error": {
                    "code": "HEALTH_CONFIG_DUPLICATE_PARAMETER",
                    "message": str(exc),
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        ) from exc
    from app.services.live_projection import LiveProjectionService
    from app.services.live_dashboard import LiveDashboardService
    from app.services.performance_trends import PerformanceTrendService
    await LiveProjectionService(db).recompute_after_configuration_change(device_id, tenant_scope)
    trend_service = PerformanceTrendService(db)
    await trend_service.repair_recent_health_window(
        device_id=device_id,
        tenant_id=tenant_scope,
        rewrite_existing_health=True,
    )
    dashboard = LiveDashboardService(db)
    await fleet_stream_broadcaster.publish(
        tenant_scope,
        "fleet_update",
        await dashboard.publish_device_update(device_id=device_id, tenant_id=tenant_scope, partial=True),
    )
    return ParameterHealthConfigListResponse(data=result, total=len(result))


# =====================================================
# Health Score Endpoints
# =====================================================

@router.post(
    "/{device_id}/health-score",
    response_model=HealthScoreResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Device not found"},
    },
)
async def calculate_health_score(
    device_id: str,
    telemetry: TelemetryValues,
    request: Request,
    tenant_id: Optional[str] = Query(None, description="Tenant ID for multi-tenancy"),
    db: AsyncSession = Depends(get_db),
) -> HealthScoreResponse:
    """Calculate device health score based on current telemetry values.
    
    The machine_state field determines if health scoring is active:
    - RUNNING, IDLE, UNLOAD: Full health calculation
    - OFF, POWER CUT: Returns standby status
    """
    from app.services.health_config import HealthConfigService
    
    service = HealthConfigService(db)
    result = await service.calculate_health_score(
        device_id,
        telemetry.values,
        telemetry.machine_state or "RUNNING",
        get_tenant_id(request)
    )
    
    return HealthScoreResponse(**result)


# =====================================================
# Device-Specific Property Endpoints
# =====================================================

@router.get(
    "/{device_id}/properties",
    response_model=list,
)
async def get_device_properties(
    device_id: str,
    request: Request,
    numeric_only: bool = Query(True, description="Only return numeric properties"),
    db: AsyncSession = Depends(get_db),
) -> list:
    """Get all properties for a specific device."""
    from app.services.device_property import DevicePropertyService
    from app.schemas.device import DevicePropertyResponse
    
    tenant_id = get_required_tenant_id(request)
    accessible_plant_ids = _resolve_accessible_plant_ids(request)
    if accessible_plant_ids is not None:
        device = (
            await db.execute(
                select(Device.plant_id).where(
                    Device.device_id == device_id,
                    Device.tenant_id == tenant_id,
                    Device.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if device is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "DEVICE_NOT_FOUND",
                    "message": f"Device '{device_id}' not found",
                },
            )
        if device not in accessible_plant_ids:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "DEVICE_NOT_FOUND",
                    "message": f"Device '{device_id}' not found",
                },
            )

    service = DevicePropertyService(db)
    properties = await service.get_device_properties(device_id, numeric_only, tenant_id)
    
    return [DevicePropertyResponse.model_validate(p) for p in properties]


@router.post(
    "/{device_id}/properties/sync",
    response_model=dict,
)
async def sync_device_properties(
    device_id: str,
    request: Request,
    telemetry: dict,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Sync properties from incoming telemetry data.
    
    This endpoint is called when telemetry data is received for a device.
    It updates both the device properties and the last_seen_timestamp
    to track device runtime status.
    """
    from app.services.device_property import DevicePropertyService
    from app.services.device import DeviceService

    # Prevent noisy 500s for unknown/legacy publisher IDs.
    tenant_id = get_required_tenant_id(request)
    device_service = DeviceService(db, TenantContext.from_request(request))
    device = await device_service.get_device(device_id, tenant_id)
    if not device:
        logger.warning(
            "Ignoring property sync for unknown device",
            extra={"device_id": device_id},
        )
        return {
            "success": False,
            "skipped": True,
            "error": f"Device {device_id} not found",
            "properties_discovered": 0,
            "property_names": [],
        }

    # Sync properties
    property_service = DevicePropertyService(db)
    properties = await property_service.sync_from_telemetry(device_id, telemetry, tenant_id)

    # Update last_seen_timestamp for runtime status tracking
    await device_service.update_last_seen(device_id, tenant_id)

    return {
        "success": True,
        "properties_discovered": len(properties),
        "property_names": [p.property_name for p in properties]
    }


@router.post(
    "/{device_id}/live-update",
    response_model=dict,
)
async def live_device_update(
    device_id: str,
    request: Request,
    payload: DeviceLiveUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Atomic low-latency state update from telemetry ingestion path."""
    from app.services.device_property import DevicePropertyService
    from app.services.live_projection import LiveProjectionService
    from app.services.live_dashboard import LiveDashboardService

    tenant_id = payload.tenant_id or get_tenant_id(request)
    device_exists = await db.scalar(
        select(Device.device_id)
        .where(Device.device_id == device_id, Device.tenant_id == tenant_id, Device.deleted_at.is_(None))
        .with_for_update(read=True)
    )
    if device_exists is None:
        logger.warning("live-update rejected: unknown device %s", device_id)
        return Response(
            content=json.dumps({"error": "DEVICE_NOT_FOUND", "device_id": device_id}),
            media_type="application/json",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    property_service = DevicePropertyService(db)
    dynamic_fields = payload.dynamic_fields or {}
    if dynamic_fields:
        await property_service.sync_from_telemetry(device_id, dynamic_fields, tenant_id)

    projection = LiveProjectionService(db)
    try:
        item = await projection.apply_live_update(
            device_id=device_id,
            tenant_id=tenant_id,
            telemetry_payload=payload.telemetry,
            dynamic_fields=dynamic_fields,
            normalized_fields=payload.normalized_fields,
        )
    except ValueError:
        return {"success": False, "skipped": True, "error": f"Device {device_id} not found"}
    dashboard = LiveDashboardService(db)
    await fleet_stream_broadcaster.publish(
        tenant_id,
        "fleet_update",
        await dashboard.publish_device_update(device_id=device_id, tenant_id=tenant_id, partial=True),
    )
    return {"success": True, "device": item}


@router.post(
    "/live-update/batch",
    response_model=dict,
)
async def live_device_update_batch(
    request: Request,
    payload: DeviceLiveUpdateBatchRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Batch live-state update path for telemetry workers."""
    from app.services.device_property import DevicePropertyService
    from app.services.live_projection import LiveProjectionService

    tenant_id = payload.tenant_id or get_tenant_id(request)
    property_service = DevicePropertyService(db)
    projection = LiveProjectionService(db)
    DEVICE_LIVE_UPDATE_BATCH_ROWS.observe(len(payload.updates))
    started_at = perf_counter()
    batch_updates: list[dict] = []
    pre_batch_results: list[dict] = []
    property_updates_by_device: dict[str, dict] = {}
    for update in payload.updates:
        dynamic_fields = update.dynamic_fields or {}
        if dynamic_fields:
            merged_fields = property_updates_by_device.setdefault(update.device_id, {})
            merged_fields.update(dynamic_fields)
        batch_updates.append(
            {
                "device_id": update.device_id,
                "telemetry": update.telemetry,
                "dynamic_fields": dynamic_fields,
                "normalized_fields": update.normalized_fields,
            }
        )

    if property_updates_by_device:
        try:
            await property_service.sync_from_telemetry_batch(
                tenant_id=tenant_id,
                telemetry_by_device=property_updates_by_device,
            )
        except Exception as exc:
            DEVICE_LIVE_UPDATE_BATCH_DURATION_SECONDS.labels("failure").observe(max(perf_counter() - started_at, 0.0))
            return {
                "success": True,
                "results": [
                    {
                        "device_id": update["device_id"],
                        "success": False,
                        "error": str(exc),
                        "error_code": "PROPERTY_SYNC_ERROR",
                        "retryable": True,
                    }
                    for update in batch_updates
                ],
            }

    try:
        results, published_items = await projection.apply_live_updates_batch(
            tenant_id=tenant_id,
            updates=batch_updates,
        )
        results = [*pre_batch_results, *results]
        outcome = "success"
    except Exception:
        DEVICE_LIVE_UPDATE_BATCH_DURATION_SECONDS.labels("failure").observe(max(perf_counter() - started_at, 0.0))
        raise

    if published_items:
        await fleet_stream_broadcaster.publish(
            tenant_id,
            "fleet_update",
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "stale": False,
                "warnings": [],
                "devices": published_items,
                "partial": True,
                "version": max(int(item.get("version") or 0) for item in published_items),
            },
        )

    success_count = 0
    invalid_count = 0
    retryable_failure_count = 0
    for item in results:
        if item.get("success"):
            success_count += 1
            DEVICE_LIVE_UPDATE_BATCH_ITEMS_TOTAL.labels("success").inc()
            continue
        error_code = str(item.get("error_code") or "")
        if error_code == "INVALID_DEVICE_METADATA":
            invalid_count += 1
            DEVICE_LIVE_UPDATE_BATCH_ITEMS_TOTAL.labels("invalid_metadata").inc()
        elif bool(item.get("retryable")):
            retryable_failure_count += 1
            DEVICE_LIVE_UPDATE_BATCH_ITEMS_TOTAL.labels("retryable_failure").inc()
        else:
            DEVICE_LIVE_UPDATE_BATCH_ITEMS_TOTAL.labels("nonretryable_failure").inc()

    DEVICE_LIVE_UPDATE_BATCH_DURATION_SECONDS.labels(outcome).observe(max(perf_counter() - started_at, 0.0))
    logger.info(
        "Device live-update batch processed",
        extra={
            "tenant_id": tenant_id,
            "batch_size": len(payload.updates),
            "successful_items": success_count,
            "invalid_items": invalid_count,
            "retryable_failures": retryable_failure_count,
        },
    )
    return {"success": True, "results": results}


@router.get(
    "/{device_id}/dashboard-widgets",
    response_model=DashboardWidgetConfigResponse,
    responses={404: {"model": ErrorResponse, "description": "Device not found"}},
)
async def get_dashboard_widgets(
    device_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> DashboardWidgetConfigResponse:
    """Get dashboard widget visibility configuration for a device."""
    from app.services.device_property import DevicePropertyService

    if await _resolve_scoped_device(request, db, device_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"success": False, "message": f"Device '{device_id}' not found"},
        )
    service = DevicePropertyService(db)
    try:
        data = await service.get_dashboard_widget_config(device_id, get_required_tenant_id(request))
        logger.info(
            "Dashboard widget config fetched",
            extra={
                "device_id": device_id,
                "available_count": len(data.get("available_fields", [])),
                "selected_count": len(data.get("selected_fields", [])),
                "default_applied": data.get("default_applied", True),
            },
        )
        return DashboardWidgetConfigResponse(success=True, **data)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"success": False, "message": f"Device '{device_id}' not found"},
        )


@router.put(
    "/{device_id}/dashboard-widgets",
    response_model=DashboardWidgetConfigResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Device not found"},
        422: {"model": ErrorResponse, "description": "Invalid or unavailable fields"},
    },
)
async def update_dashboard_widgets(
    device_id: str,
    request: Request,
    payload: DashboardWidgetConfigUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> DashboardWidgetConfigResponse:
    """Replace dashboard widget visibility configuration for a device."""
    from app.services.device_property import DevicePropertyService

    _ensure_device_write_access(request)
    if await _resolve_scoped_device(request, db, device_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"success": False, "message": f"Device '{device_id}' not found"},
        )
    service = DevicePropertyService(db)
    try:
        data = await service.replace_dashboard_widget_config(
            device_id=device_id,
            tenant_id=get_required_tenant_id(request),
            selected_fields=payload.selected_fields,
        )
        logger.info(
            "Dashboard widget config updated",
            extra={
                "device_id": device_id,
                "selected_count": len(data.get("selected_fields", [])),
            },
        )
        return DashboardWidgetConfigResponse(success=True, **data)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"success": False, "message": f"Device '{device_id}' not found"},
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"success": False, "message": str(exc)},
        )


@router.post(
    "/{device_id}/heartbeat",
    response_model=dict,
)
async def device_heartbeat(
    device_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update device last_seen_timestamp to mark device as alive.
    
    This lightweight endpoint is called periodically by devices or the
    telemetry service to indicate the device is still active.
    """
    from app.services.device import DeviceService
    
    device_service = DeviceService(db, TenantContext.from_request(request))
    device = await device_service.update_last_seen(device_id, get_required_tenant_id(request))
    
    if not device:
        return {
            "success": False,
            "error": f"Device {device_id} not found"
        }
    
    return {
        "success": True,
        "device_id": device_id,
        "first_telemetry_timestamp": (
            device.first_telemetry_timestamp.astimezone(timezone.utc).isoformat()
            if device.first_telemetry_timestamp and device.first_telemetry_timestamp.tzinfo
            else (
                device.first_telemetry_timestamp.replace(tzinfo=timezone.utc).isoformat()
                if device.first_telemetry_timestamp
                else None
            )
        ),
        "last_seen_timestamp": device.last_seen_timestamp.isoformat() if device.last_seen_timestamp else None,
        "runtime_status": device.get_runtime_status()
    }


# =====================================================
# Idle Running Endpoints
# =====================================================

@router.get(
    "/{device_id}/state-intervals",
    response_model=DeviceStateIntervalListResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid filter range"},
        404: {"model": ErrorResponse, "description": "Device not found"},
    },
)
async def get_device_state_intervals(
    device_id: str,
    request: Request,
    start_time: Optional[datetime] = Query(default=None, description="Inclusive range start timestamp"),
    end_time: Optional[datetime] = Query(default=None, description="Inclusive range end timestamp"),
    state_type: Optional[str] = Query(default=None, pattern="^(idle|overconsumption|runtime_on)$"),
    is_open: Optional[bool] = Query(default=None, description="Filter by open/closed interval state"),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> DeviceStateIntervalListResponse:
    if start_time is not None and end_time is not None and start_time > end_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "message": "start_time must be less than or equal to end_time"},
        )
    if await _resolve_scoped_device(request, db, device_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"success": False, "message": f"Device '{device_id}' not found"},
        )

    tenant_id = get_required_tenant_id(request)
    repository = DeviceStateIntervalRepository(db)
    rows, total = await repository.list_device_intervals(
        tenant_id=tenant_id,
        device_id=device_id,
        start_time=start_time,
        end_time=end_time,
        state_type=state_type,
        is_open=is_open,
        limit=limit,
        offset=offset,
    )
    return DeviceStateIntervalListResponse(
        success=True,
        data=rows,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{device_id}/idle-config",
    response_model=dict,
    responses={404: {"model": ErrorResponse, "description": "Device not found"}},
)
async def get_idle_config(
    device_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.services.idle_running import IdleRunningService

    if await _resolve_scoped_device(request, db, device_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"success": False, "message": f"Device '{device_id}' not found"},
        )
    service = IdleRunningService(db, TenantContext.from_request(request))
    try:
        data = await service.get_idle_config(device_id, get_required_tenant_id(request))
        return {"success": True, **data}
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"success": False, "message": f"Device '{device_id}' not found"},
        )


@router.post(
    "/{device_id}/idle-config",
    response_model=dict,
    responses={
        400: {"model": ErrorResponse, "description": "Validation error"},
        404: {"model": ErrorResponse, "description": "Device not found"},
    },
)
async def set_idle_config(
    device_id: str,
    request: Request,
    payload: IdleConfigRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.services.idle_running import IdleRunningService, ThresholdConfigurationError

    _ensure_device_write_access(request)
    if await _resolve_scoped_device(request, db, device_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"success": False, "message": f"Device '{device_id}' not found"},
        )
    service = IdleRunningService(db, TenantContext.from_request(request))
    try:
        data = await service.set_idle_config(
            device_id,
            get_required_tenant_id(request),
            full_load_current_a=payload.full_load_current_a,
            idle_threshold_pct_of_fla=payload.idle_threshold_pct_of_fla,
            idle_current_threshold=payload.idle_current_threshold,
        )
        return {"success": True, **data}
    except ThresholdConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "message": str(exc)},
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"success": False, "message": f"Device '{device_id}' not found"},
        )


@router.get(
    "/{device_id}/current-state",
    response_model=dict,
    responses={404: {"model": ErrorResponse, "description": "Device not found"}},
)
async def get_current_state(
    device_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.services.idle_running import IdleRunningService

    if await _resolve_scoped_device(request, db, device_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"success": False, "message": f"Device '{device_id}' not found"},
        )
    service = IdleRunningService(db, TenantContext.from_request(request))
    try:
        data = await service.get_current_state(device_id, get_required_tenant_id(request))
        return {"success": True, **data}
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"success": False, "message": f"Device '{device_id}' not found"},
        )


@router.get(
    "/{device_id}/waste-config",
    response_model=dict,
    responses={404: {"model": ErrorResponse, "description": "Device not found"}},
)
async def get_waste_config(
    device_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.services.idle_running import IdleRunningService

    if await _resolve_scoped_device(request, db, device_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"success": False, "message": f"Device '{device_id}' not found"},
        )
    service = IdleRunningService(db, TenantContext.from_request(request))
    try:
        data = await service.get_waste_config(device_id, get_required_tenant_id(request))
        return {"success": True, **data}
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"success": False, "message": f"Device '{device_id}' not found"},
        )


@router.put(
    "/{device_id}/waste-config",
    response_model=dict,
    responses={
        400: {"model": ErrorResponse, "description": "Validation error"},
        404: {"model": ErrorResponse, "description": "Device not found"},
    },
)
async def set_waste_config(
    device_id: str,
    request: Request,
    payload: DeviceWasteConfigRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.services.idle_running import IdleRunningService, ThresholdConfigurationError

    _ensure_device_write_access(request)
    if await _resolve_scoped_device(request, db, device_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"success": False, "message": f"Device '{device_id}' not found"},
        )
    service = IdleRunningService(db, TenantContext.from_request(request))
    tenant_id = get_required_tenant_id(request)
    try:
        data = await service.set_waste_config(
            device_id=device_id,
            tenant_id=tenant_id,
            overconsumption_current_threshold_a=payload.overconsumption_current_threshold_a,
            full_load_current_a=payload.full_load_current_a,
            unoccupied_weekday_start_time=payload.unoccupied_weekday_start_time,
            unoccupied_weekday_end_time=payload.unoccupied_weekday_end_time,
            unoccupied_weekend_start_time=payload.unoccupied_weekend_start_time,
            unoccupied_weekend_end_time=payload.unoccupied_weekend_end_time,
        )
        await _refresh_loss_views_after_waste_config_change(
            db,
            tenant_id=tenant_id,
            device_id=device_id,
        )
        return {"success": True, **data}
    except ThresholdConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "message": str(exc)},
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"success": False, "message": f"Device '{device_id}' not found"},
        )


@router.get(
    "/{device_id}/loss-stats",
    response_model=dict,
    responses={404: {"model": ErrorResponse, "description": "Device not found"}},
)
async def get_device_loss_stats(
    device_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.services.dashboard import DashboardDeviceNotFoundError, DashboardService

    if await _resolve_scoped_device(request, db, device_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"success": False, "message": f"Device '{device_id}' not found"},
        )
    tenant_id = get_required_tenant_id(request)
    service = DashboardService(db, TenantContext.from_request(request))
    try:
        data = await service.get_device_loss_stats(device_id, tenant_id)
        return {"success": True, **data}
    except DashboardDeviceNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"success": False, "message": f"Device '{device_id}' not found"},
        )


@router.get(
    "/{device_id}/idle-stats",
    response_model=dict,
    responses={404: {"model": ErrorResponse, "description": "Device not found"}},
)
async def get_idle_stats(
    device_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.services.idle_running import IdleRunningService

    if await _resolve_scoped_device(request, db, device_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"success": False, "message": f"Device '{device_id}' not found"},
        )
    service = IdleRunningService(db, TenantContext.from_request(request))
    try:
        data = await service.get_idle_stats(device_id, get_required_tenant_id(request))
        return {"success": True, **data}
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"success": False, "message": f"Device '{device_id}' not found"},
        )
