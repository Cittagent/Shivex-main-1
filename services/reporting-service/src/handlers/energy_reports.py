from datetime import datetime, date
import hashlib
import json
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.queue import ReportJob, get_report_queue
from src.schemas.requests import ConsumptionReportRequest
from src.schemas.responses import ReportResponse
from src.repositories.report_repository import ReportRepository
from src.services.device_scope import ReportingDeviceScopeService
from src.services.tenant_scope import build_service_tenant_context, normalize_tenant_id
from services.shared.tenant_context import TenantContext, resolve_request_tenant_id

router = APIRouter(tags=["energy-reports"])


def get_tenant_id(request: Request) -> str | None:
    return resolve_request_tenant_id(request)


def resolve_submission_tenant_id(app_request: Request, body_tenant_id: str | None) -> str:
    resolved = normalize_tenant_id(
        resolve_request_tenant_id(app_request, explicit_tenant_id=body_tenant_id)
    )
    if resolved is None:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "TENANT_SCOPE_REQUIRED",
                "message": "Tenant scope is required to submit a report.",
            },
        )
    return resolved


async def resolve_all_devices(ctx: TenantContext) -> list[str]:
    import logging

    logger = logging.getLogger(__name__)
    try:
        device_ids = await ReportingDeviceScopeService(ctx).resolve_accessible_device_ids()
    except httpx.RequestError as exc:
        logger.error("report_device_scope_request_failed", extra={"error": str(exc)})
        raise HTTPException(
            status_code=503,
            detail={
                "error": "DEVICE_SERVICE_UNAVAILABLE",
                "message": f"Cannot connect to device service: {str(exc)}",
            },
        ) from exc
    except httpx.HTTPStatusError as exc:
        logger.error("report_device_scope_http_error", extra={"status_code": exc.response.status_code})
        raise HTTPException(
            status_code=502,
            detail={
                "error": "DEVICE_SERVICE_ERROR",
                "message": f"Device service returned status {exc.response.status_code}",
            },
        ) from exc
    except RuntimeError as exc:
        logger.error("report_device_scope_runtime_error", extra={"error": str(exc)})
        raise HTTPException(
            status_code=503,
            detail={
                "error": "DEVICE_SCOPE_UNAVAILABLE",
                "message": str(exc),
            },
        ) from exc

    logger.info("Resolved %s accessible devices for tenant %s", len(device_ids), ctx.require_tenant())
    return device_ids


def normalize_dates_to_utc(start_date: date, end_date: date) -> tuple[datetime, datetime]:
    """
    Normalize dates to UTC with day-boundary alignment.
    - Floor start to 00:00:00 UTC
    - Ceil end to 23:59:59.999999 UTC
    Returns tuple of (start_datetime, end_datetime)
    """
    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.max.time())
    return start_dt, end_dt


def validate_date_duration_seconds(start_dt: datetime, end_dt: datetime, min_seconds: int = 86400) -> bool:
    """
    Validate duration using seconds instead of days to avoid timezone drift.
    min_seconds defaults to 86400 (24 hours).
    """
    # normalize_dates_to_utc() uses an inclusive end-of-day timestamp
    # (23:59:59.999999). Treat that inclusive window as a full calendar day
    # when enforcing the minimum duration contract.
    duration_seconds = (end_dt - start_dt).total_seconds() + 1e-6
    return duration_seconds >= min_seconds


async def validate_device_for_reporting(device_id: str, ctx: TenantContext) -> dict:
    """
    Validate device exists.
    Returns device data if valid.
    Raises HTTPException if invalid.
    """
    try:
        return await ReportingDeviceScopeService(ctx).validate_accessible_device(device_id)
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "DEVICE_SERVICE_UNAVAILABLE",
                "message": f"Cannot connect to device service: {str(exc)}",
            },
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error": "DEVICE_SERVICE_ERROR",
                "message": f"Device service returned status {exc.response.status_code}",
            },
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "DEVICE_SCOPE_UNAVAILABLE",
                "message": str(exc),
            },
        ) from exc


@router.post("/consumption", response_model=ReportResponse)
async def create_energy_consumption_report(
    request: ConsumptionReportRequest,
    app_request: Request,
    db: AsyncSession = Depends(get_db)
):
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info("="*60)
    logger.info("ENERGY REPORT REQUEST RECEIVED")
    logger.info(f"  start_date: {request.start_date}")
    logger.info(f"  end_date: {request.end_date}")
    logger.info(f"  device_id: {request.device_id}")
    logger.info(f"  tenant_id: {request.tenant_id}")
    logger.info("="*60)

    tenant_id = resolve_submission_tenant_id(app_request, request.tenant_id)
    request.tenant_id = tenant_id
    tenant_ctx = build_service_tenant_context(tenant_id)
    request_ctx = TenantContext.from_request(app_request)
    
    request_device_id = (request.device_id or "").strip()
    if not request_device_id:
        raise HTTPException(
            status_code=400,
            detail={"error": "VALIDATION_ERROR", "message": "device_id is required"}
        )

    device_ids: list[str] = []
    if request_device_id.upper() == "ALL":
        logger.info("Received 'all' device selection, resolving to actual device IDs")
        resolved_ids = await resolve_all_devices(request_ctx)
        
        if not resolved_ids:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "NO_VALID_DEVICES",
                    "message": "No energy-capable devices found for this tenant."
                }
            )
        
        device_ids = resolved_ids
        logger.info(f"Resolved device IDs: {device_ids}")
    else:
        await validate_device_for_reporting(request_device_id, request_ctx)
        device_ids = [request_device_id]
    
    start_dt, end_dt = normalize_dates_to_utc(request.start_date, request.end_date)
    duration_seconds = (end_dt - start_dt).total_seconds()
    
    logger.info("="*60)
    logger.info("DATE NORMALIZATION RESULTS")
    logger.info(f"  Original start: {request.start_date}")
    logger.info(f"  Original end: {request.end_date}")
    logger.info(f"  UTC start_dt: {start_dt}")
    logger.info(f"  UTC end_dt: {end_dt}")
    logger.info(f"  Duration seconds: {duration_seconds}")
    logger.info(f"  Duration days: {duration_seconds / 86400}")
    logger.info("="*60)
    
    if not validate_date_duration_seconds(start_dt, end_dt):
        logger.error(f"Date validation FAILED: duration {duration_seconds} seconds < 86400")
        raise HTTPException(
            status_code=400,
            detail={
                "error": "INVALID_DATE_RANGE",
                "message": f"Date range must be at least 24 hours apart. Current: {duration_seconds/86400:.1f} days"
            }
        )
    
    repo = ReportRepository(db, ctx=tenant_ctx)
    dedup_payload = {
        "tenant_id": tenant_id,
        "report_type": "consumption",
        "device_id": request_device_id.upper() if request_device_id.upper() == "ALL" else request_device_id,
        "resolved_device_ids": sorted(device_ids),
        "start_date": str(request.start_date),
        "end_date": str(request.end_date),
        "report_name": request.report_name or "",
    }
    dedup_signature = hashlib.sha256(
        json.dumps(dedup_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    duplicate = await repo.find_active_duplicate(
        tenant_id=tenant_id,
        report_type="consumption",
        dedup_signature=dedup_signature,
    )
    if duplicate:
        dup_status = duplicate.status.value if hasattr(duplicate.status, "value") else str(duplicate.status)
        return ReportResponse(
            report_id=duplicate.report_id,
            status="processing" if dup_status == "pending" else dup_status,
            created_at=duplicate.created_at.isoformat() if duplicate.created_at else datetime.utcnow().isoformat(),
            estimated_completion_seconds=15,
        )
    
    report_id = str(uuid4())
    
    params = request.model_dump()
    params["start_date"] = str(params["start_date"])
    params["end_date"] = str(params["end_date"])
    params["resolved_device_ids"] = device_ids
    params["dedup_signature"] = dedup_signature
    
    await repo.create_report(
        report_id=report_id,
        tenant_id=tenant_id,
        report_type="consumption",
        params=params
    )
    await get_report_queue().enqueue(
        ReportJob(
            report_id=report_id,
            tenant_id=tenant_id,
            report_type="consumption",
        )
    )
    
    return ReportResponse(
        report_id=report_id,
        status="processing",
        created_at=datetime.utcnow().isoformat(),
        estimated_completion_seconds=15,
    )
