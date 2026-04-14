from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.tariff_repository import TariffRepository
from src.services.tenant_scope import build_service_tenant_context


@dataclass
class ResolvedTariff:
    rate: float | None
    currency: str
    fetched_at: str
    source: str


async def resolve_tariff(session: AsyncSession, tenant_id: str | None) -> ResolvedTariff:
    if tenant_id is None:
        raise ValueError("Tenant scope is required to resolve tariff settings")

    tenant_ctx = build_service_tenant_context(tenant_id)
    tenant_repo = TariffRepository(session, tenant_ctx)

    tenant_tariff = await tenant_repo.get_tariff(tenant_id)
    if tenant_tariff:
        return ResolvedTariff(
            rate=float(tenant_tariff.energy_rate_per_kwh),
            currency=str(tenant_tariff.currency or "INR").upper(),
            fetched_at=(tenant_tariff.updated_at or datetime.utcnow()).isoformat(),
            source="tenant_tariffs",
        )

    return ResolvedTariff(
        rate=None,
        currency="INR",
        fetched_at=datetime.utcnow().isoformat(),
        source="default_unconfigured",
    )
