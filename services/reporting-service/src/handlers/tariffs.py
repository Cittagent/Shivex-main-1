from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.schemas.requests import TariffRequest
from src.schemas.responses import TariffResponse
from src.repositories.tariff_repository import TariffRepository
from src.services.tenant_scope import build_service_tenant_context
from services.shared.tenant_context import resolve_request_tenant_id

router = APIRouter(tags=["tariffs"])


def _resolve_tariff_tenant_id(request: Request, explicit_tenant_id: str | None = None) -> str:
    tenant_id = resolve_request_tenant_id(request, explicit_tenant_id=explicit_tenant_id, required=True)
    return str(tenant_id)


@router.post("/", response_model=TariffResponse)
async def create_or_update_tariff(
    request: TariffRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db)
):
    tenant_id = _resolve_tariff_tenant_id(http_request, request.tenant_id)
    repo = TariffRepository(db, build_service_tenant_context(tenant_id))
    
    tariff = await repo.upsert_tariff(
        tenant_id=tenant_id,
        data={**request.model_dump(), "tenant_id": tenant_id}
    )
    
    return TariffResponse(
        tenant_id=tariff.tenant_id,
        energy_rate_per_kwh=float(tariff.energy_rate_per_kwh),
        demand_charge_per_kw=float(tariff.demand_charge_per_kw),
        reactive_penalty_rate=float(tariff.reactive_penalty_rate),
        fixed_monthly_charge=float(tariff.fixed_monthly_charge),
        power_factor_threshold=float(tariff.power_factor_threshold),
        currency=str(tariff.currency)
    )


@router.get("/{tenant_id}", response_model=TariffResponse)
async def get_tariff(
    tenant_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    resolved_tenant_id = _resolve_tariff_tenant_id(request, tenant_id)
    repo = TariffRepository(db, build_service_tenant_context(resolved_tenant_id))
    tariff = await repo.get_tariff(resolved_tenant_id)
    
    if not tariff:
        raise HTTPException(status_code=404, detail="Tariff not found for tenant")
    
    return TariffResponse(
        tenant_id=tariff.tenant_id,
        energy_rate_per_kwh=float(tariff.energy_rate_per_kwh),
        demand_charge_per_kw=float(tariff.demand_charge_per_kw),
        reactive_penalty_rate=float(tariff.reactive_penalty_rate),
        fixed_monthly_charge=float(tariff.fixed_monthly_charge),
        power_factor_threshold=float(tariff.power_factor_threshold),
        currency=str(tariff.currency)
    )
