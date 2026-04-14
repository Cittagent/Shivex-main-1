from datetime import datetime
from typing import Optional
from sqlalchemy import select

from src.models import TenantTariff
from services.shared.scoped_repository import TenantScopedRepository
from services.shared.tenant_context import TenantContext


class TariffRepository(TenantScopedRepository[TenantTariff]):
    model = TenantTariff

    def __init__(self, db, ctx: TenantContext | None = None, allow_cross_tenant: bool = False):
        effective_ctx = ctx or TenantContext.system("svc:reporting-service")
        super().__init__(db, effective_ctx, allow_cross_tenant=allow_cross_tenant or ctx is None)
        self.db = db

    def _effective_tenant_id(self, tenant_id: str | None = None) -> str | None:
        if tenant_id is not None:
            tenant_id = tenant_id.strip() or None
        else:
            tenant_id = self._tenant_id
        return tenant_id

    def _scope_select(self, statement, tenant_id: str | None = None):
        effective_tenant_id = self._effective_tenant_id(tenant_id)
        if effective_tenant_id is not None and self._has_tenant_column():
            statement = statement.where(getattr(self.model, "tenant_id") == effective_tenant_id)
        return statement
    
    async def get_tariff(self, tenant_id: str | None = None, *_: object, **__: object) -> Optional[TenantTariff]:
        result = await self.db.execute(self._scope_select(select(TenantTariff), tenant_id=tenant_id))
        return result.scalar_one_or_none()
    
    async def upsert_tariff(
        self,
        data: dict,
        tenant_id: str | None = None,
        **_: object,
    ) -> TenantTariff:
        effective_tenant_id = self._effective_tenant_id(tenant_id or data.get("tenant_id"))
        if effective_tenant_id is None:
            raise ValueError("Tenant scope is required to upsert a tariff")

        existing = await self.get_tariff(effective_tenant_id)

        if existing:
            if "energy_rate_per_kwh" in data:
                existing.energy_rate_per_kwh = float(data["energy_rate_per_kwh"])
            if "demand_charge_per_kw" in data:
                existing.demand_charge_per_kw = float(data["demand_charge_per_kw"])
            if "reactive_penalty_rate" in data:
                existing.reactive_penalty_rate = float(data["reactive_penalty_rate"])
            if "fixed_monthly_charge" in data:
                existing.fixed_monthly_charge = float(data["fixed_monthly_charge"])
            if "power_factor_threshold" in data:
                existing.power_factor_threshold = float(data["power_factor_threshold"])
            if "currency" in data:
                existing.currency = str(data["currency"])
            existing.updated_at = datetime.utcnow()
            await self.db.commit()
            await self.db.refresh(existing)
            return existing
        else:
            tariff = TenantTariff(
                tenant_id=effective_tenant_id,
                energy_rate_per_kwh=float(data.get("energy_rate_per_kwh", 0)),
                demand_charge_per_kw=float(data.get("demand_charge_per_kw", 0)),
                reactive_penalty_rate=float(data.get("reactive_penalty_rate", 0)),
                fixed_monthly_charge=float(data.get("fixed_monthly_charge", 0)),
                power_factor_threshold=float(data.get("power_factor_threshold", 0.90)),
                currency=data.get("currency", "INR"),
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            tariff = await self.create(tariff)
            await self.db.commit()
            return tariff
