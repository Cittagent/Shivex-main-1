from typing import Any, Literal, Optional
from io import BytesIO

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models import ReportStatus
from src.repositories.report_repository import ReportRepository
from src.repositories.scheduled_repository import ScheduledRepository
from src.services.device_scope import ReportingDeviceScopeService
from src.services.report_scope import normalize_schedule_params_template
from src.services.tenant_scope import build_service_tenant_context, normalize_tenant_id
from src.storage.minio_client import minio_client, StorageError
from services.shared.tenant_context import TenantContext, resolve_request_tenant_id

router = APIRouter(tags=["reports"])


def _external_report_status(status: object) -> str:
    resolved = status.value if hasattr(status, "value") else str(status)
    return "processing" if resolved == "pending" else resolved


class ScheduleCreateRequest(BaseModel):
    report_type: Literal["consumption", "comparison"]
    frequency: Literal["daily", "weekly", "monthly"]
    params_template: dict[str, Any] = Field(default_factory=dict)


def _resolve_request_tenant_id(request: Request, tenant_id: str | None = None) -> str:
    resolved = normalize_tenant_id(resolve_request_tenant_id(request, explicit_tenant_id=tenant_id))
    if resolved is None:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "TENANT_SCOPE_REQUIRED",
                "message": "Tenant scope is required.",
            },
        )
    return resolved


async def _resolve_accessible_device_ids(request: Request) -> list[str] | None:
    ctx = TenantContext.from_request(request)
    try:
        return await ReportingDeviceScopeService(ctx).resolve_accessible_device_ids()
    except HTTPException:
        raise
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "DEVICE_SERVICE_UNAVAILABLE",
                "message": str(exc),
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


@router.get("/history")
async def list_reports(
    request: Request,
    tenant_id: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    report_type: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    tenant_id = _resolve_request_tenant_id(request, tenant_id)
    repo = ReportRepository(db, ctx=build_service_tenant_context(tenant_id))
    accessible_device_ids = await _resolve_accessible_device_ids(request)
    reports = await repo.list_reports(
        tenant_id,
        limit,
        offset,
        report_type,
        accessible_device_ids=accessible_device_ids,
    )
    
    return {
        "reports": [
            {
                "report_id": r.report_id,
                "status": _external_report_status(r.status),
                "report_type": r.report_type.value if hasattr(r.report_type, 'value') else str(r.report_type),
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None
            }
            for r in reports
        ]
    }


@router.post("/schedules")
async def create_schedule(
    data: ScheduleCreateRequest,
    request: Request,
    tenant_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db)
):
    tenant_id = _resolve_request_tenant_id(request, tenant_id)
    accessible_device_ids = await _resolve_accessible_device_ids(request)
    repo = ScheduledRepository(db, ctx=build_service_tenant_context(tenant_id))
    payload = data.model_dump()
    payload["tenant_id"] = tenant_id
    try:
        payload["params_template"] = normalize_schedule_params_template(
            payload.get("params_template", {}),
            accessible_device_ids,
        )
        schedule = await repo.create_schedule(payload)
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "SCHEDULE_SCOPE_FORBIDDEN",
                "message": str(exc),
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "VALIDATION_ERROR",
                "message": str(exc),
            },
        ) from exc
    
    return {
        "schedule_id": schedule.schedule_id,
        "tenant_id": schedule.tenant_id,
        "report_type": schedule.report_type.value if hasattr(schedule.report_type, 'value') else str(schedule.report_type),
        "frequency": schedule.frequency.value if hasattr(schedule.frequency, 'value') else str(schedule.frequency),
        "is_active": schedule.is_active,
        "next_run_at": schedule.next_run_at.isoformat() if schedule.next_run_at else None,
        "created_at": schedule.created_at.isoformat()
    }


@router.get("/schedules")
async def list_schedules(
    request: Request,
    tenant_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db)
):
    tenant_id = _resolve_request_tenant_id(request, tenant_id)
    repo = ScheduledRepository(db, ctx=build_service_tenant_context(tenant_id))
    accessible_device_ids = await _resolve_accessible_device_ids(request)
    schedules = await repo.list_schedules(tenant_id, accessible_device_ids=accessible_device_ids)
    
    return {
        "schedules": [
            {
                "schedule_id": s.schedule_id,
                "tenant_id": s.tenant_id,
                "report_type": s.report_type.value if hasattr(s.report_type, 'value') else str(s.report_type),
                "frequency": s.frequency.value if hasattr(s.frequency, 'value') else str(s.frequency),
                "is_active": s.is_active,
                "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
                "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None,
                "last_status": s.last_status,
                "last_result_url": s.last_result_url,
                "params_template": s.params_template
            }
            for s in schedules
        ]
    }


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(
    schedule_id: str,
    request: Request,
    tenant_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db)
):
    tenant_id = _resolve_request_tenant_id(request, tenant_id)
    repo = ScheduledRepository(db, ctx=build_service_tenant_context(tenant_id))
    accessible_device_ids = await _resolve_accessible_device_ids(request)
    schedule = await repo.get_schedule(schedule_id, accessible_device_ids=accessible_device_ids)
    
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    
    if schedule.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    await repo.update_schedule(schedule_id, is_active=False)
    
    return {"message": "Schedule deactivated"}


@router.get("/{report_id}/status")
async def get_report_status(
    report_id: str,
    request: Request,
    tenant_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db)
):
    tenant_id = _resolve_request_tenant_id(request, tenant_id)
    repo = ReportRepository(db, ctx=build_service_tenant_context(tenant_id))
    accessible_device_ids = await _resolve_accessible_device_ids(request)
    report = await repo.get_report(report_id, tenant_id, accessible_device_ids=accessible_device_ids)
    
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    
    return {
        "report_id": report.report_id,
        "status": _external_report_status(report.status),
        "progress": getattr(report, 'progress', 0),
        "error_code": report.error_code,
        "error_message": report.error_message
    }


@router.get("/{report_id}/result")
async def get_report_result(
    report_id: str,
    request: Request,
    tenant_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db)
):
    tenant_id = _resolve_request_tenant_id(request, tenant_id)
    repo = ReportRepository(db, ctx=build_service_tenant_context(tenant_id))
    accessible_device_ids = await _resolve_accessible_device_ids(request)
    report = await repo.get_report(report_id, tenant_id, accessible_device_ids=accessible_device_ids)
    
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    
    if report.status != ReportStatus.completed:
        raise HTTPException(status_code=404, detail="Report not completed yet")
    
    return report.result_json


@router.get("/{report_id}/download")
async def download_report(
    report_id: str,
    request: Request,
    tenant_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db)
):
    tenant_id = _resolve_request_tenant_id(request, tenant_id)
    repo = ReportRepository(db, ctx=build_service_tenant_context(tenant_id))
    accessible_device_ids = await _resolve_accessible_device_ids(request)
    report = await repo.get_report(report_id, tenant_id, accessible_device_ids=accessible_device_ids)
    
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    
    if not report.s3_key:
        raise HTTPException(status_code=404, detail="PDF not available")
    
    try:
        pdf_bytes = minio_client.download_pdf(report.s3_key)
        return StreamingResponse(
            BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=energy_report_{report_id}.pdf",
                "Content-Length": str(len(pdf_bytes))
            }
        )
    except StorageError:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "PDF_NOT_FOUND",
                "message": "Report file not available",
            },
        )
