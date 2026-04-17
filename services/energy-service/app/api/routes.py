from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas import DeviceLifecycleRequest, LiveUpdateBatchRequest, LiveUpdateRequest
from app.services.broadcaster import energy_broadcaster
from app.services.energy_engine import EnergyEngine
from shared.feature_entitlements import require_feature
from shared.tenant_context import resolve_request_tenant_id

router = APIRouter(prefix="/api/v1/energy")


def get_tenant_id(request: Request) -> str | None:
    return resolve_request_tenant_id(request)


@router.get("/health")
async def health() -> dict:
    return {"status": "healthy", "service": "energy-service"}


@router.post("/live-update")
async def live_update(request: Request, payload: LiveUpdateRequest, db: AsyncSession = Depends(get_db)) -> dict:
    telemetry = payload.telemetry or {}
    device_id = str(telemetry.get("device_id") or "").strip()
    if not device_id:
        return {"success": False, "error": "device_id required"}

    engine = EnergyEngine(db)
    tenant_id = resolve_request_tenant_id(request, explicit_tenant_id=payload.tenant_id)
    result = await engine.apply_live_update(
        device_id=device_id,
        telemetry=telemetry,
        dynamic_fields=payload.dynamic_fields,
        normalized_fields=payload.normalized_fields,
        tenant_id=tenant_id,
    )
    await energy_broadcaster.publish("energy_update", result)
    return {"success": True, "data": result}


@router.post("/live-update/batch")
async def live_update_batch(request: Request, payload: LiveUpdateBatchRequest, db: AsyncSession = Depends(get_db)) -> dict:
    tenant_id = resolve_request_tenant_id(request, explicit_tenant_id=payload.tenant_id)
    engine = EnergyEngine(db)
    results = await engine.apply_live_updates_batch(
        tenant_id=tenant_id,
        updates=[
            {
                "telemetry": update.telemetry,
                "dynamic_fields": update.dynamic_fields,
                "normalized_fields": update.normalized_fields,
            }
            for update in payload.updates
        ],
    )
    success_payloads = [
        item["data"]
        for item in results
        if item.get("success") and isinstance(item.get("data"), dict)
    ]
    if success_payloads:
        await energy_broadcaster.publish_many("energy_update", success_payloads)
    return {"success": True, "results": results}


@router.post("/device-lifecycle/{device_id}")
async def device_lifecycle(device_id: str, payload: DeviceLifecycleRequest, db: AsyncSession = Depends(get_db)) -> dict:
    engine = EnergyEngine(db)
    result = await engine.apply_device_lifecycle(device_id=device_id, status=payload.status, at=payload.at)
    await energy_broadcaster.publish("energy_update", {"device_id": device_id, "version": result.get("version"), "freshness_ts": payload.at.isoformat() if payload.at else None})
    return {"success": True, "data": result}


@router.get("/summary")
async def summary(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    payload = await EnergyEngine(db).get_summary(tenant_id=get_tenant_id(request))
    return {"success": True, **payload}


@router.get("/today-loss-breakdown")
async def today_loss_breakdown(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    payload = await EnergyEngine(db).get_today_loss_breakdown(tenant_id=get_tenant_id(request))
    return {"success": True, **payload}


@router.get("/calendar/monthly", dependencies=[Depends(require_feature("calendar"))])
async def calendar_monthly(
    request: Request,
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    db: AsyncSession = Depends(get_db),
) -> dict:
    payload = await EnergyEngine(db).get_monthly_calendar(year=year, month=month, tenant_id=get_tenant_id(request))
    return {"success": True, **payload}


@router.get("/device/{device_id}/range")
async def device_range(
    request: Request,
    device_id: str,
    start_date: date = Query(...),
    end_date: date = Query(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    payload = await EnergyEngine(db).get_device_range(
        device_id=device_id,
        start=start_date,
        end=end_date,
        tenant_id=get_tenant_id(request),
    )
    return {"success": True, **payload}
