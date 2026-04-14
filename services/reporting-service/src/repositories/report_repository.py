from datetime import datetime
from typing import Optional
from sqlalchemy import select, update

from src.models import EnergyReport, ReportType, ReportStatus
from src.services.report_scope import report_visible_to_scope
from services.shared.scoped_repository import TenantScopedRepository
from services.shared.tenant_context import TenantContext


class ReportRepository(TenantScopedRepository[EnergyReport]):
    model = EnergyReport

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

    def _scope_dml(self, statement, tenant_id: str | None = None):
        effective_tenant_id = self._effective_tenant_id(tenant_id)
        if effective_tenant_id is not None and self._has_tenant_column():
            statement = statement.where(getattr(self.model, "tenant_id") == effective_tenant_id)
        return statement
    
    async def create_report(
        self,
        report_id: str,
        report_type: str,
        params: dict,
        tenant_id: str | None = None,
        **_: object,
    ) -> EnergyReport:
        effective_tenant_id = self._effective_tenant_id(tenant_id)
        if effective_tenant_id is None:
            raise ValueError("Tenant scope is required to create a report")

        report = EnergyReport(
            report_id=report_id,
            tenant_id=effective_tenant_id,
            report_type=ReportType(report_type),
            status="pending",
            params=params,
            created_at=datetime.utcnow()
        )
        report = await self.create(report)
        await self.db.commit()
        return report
    
    async def get_report(
        self,
        report_id: str,
        tenant_id: str | None = None,
        accessible_device_ids: list[str] | None = None,
        *_: object,
        **__: object,
    ) -> Optional[EnergyReport]:
        effective_tenant_id = self._effective_tenant_id(tenant_id)
        filters = []
        if effective_tenant_id is not None:
            filters.append(EnergyReport.tenant_id == effective_tenant_id)
        report = await self.get_by_id(report_id, id_field="report_id", extra_filters=filters)
        if report is None or not report_visible_to_scope(report.params, accessible_device_ids):
            return None
        return report
    
    async def update_report(
        self,
        report_id: str,
        tenant_id: str | None = None,
        **kwargs
    ) -> None:
        update_values = {k: v for k, v in kwargs.items() if v is not None}
        # report_id is globally unique, so updating by report_id alone avoids
        # taking an additional tenant secondary-index lock. That secondary lock
        # caused deadlocks when multiple reports for the same tenant advanced
        # progress concurrently.
        statement = update(EnergyReport).where(EnergyReport.report_id == report_id).values(**update_values)
        await self.db.execute(statement)
        await self.db.commit()
    
    async def list_reports(
        self,
        tenant_id: str | None = None,
        limit: int = 20,
        offset: int = 0,
        report_type: Optional[str] = None,
        accessible_device_ids: list[str] | None = None,
        *args: object,
        **__: object,
    ) -> list[EnergyReport]:
        if args:
            # Backward-compatible positional pattern: (tenant_id, limit, offset, report_type)
            if len(args) > 0 and tenant_id is None and isinstance(args[0], str):
                tenant_id = args[0]
            if len(args) > 1 and isinstance(args[1], int):
                limit = args[1]
            if len(args) > 2 and isinstance(args[2], int):
                offset = args[2]
            if len(args) > 3 and isinstance(args[3], str):
                report_type = args[3]
        query = self._scope_select(select(EnergyReport), tenant_id=tenant_id)
        
        if report_type:
            query = query.where(EnergyReport.report_type == ReportType(report_type))
        
        query = query.order_by(EnergyReport.created_at.desc())
        
        result = await self.db.execute(query)
        reports = [
            report
            for report in result.scalars().all()
            if report_visible_to_scope(report.params, accessible_device_ids)
        ]
        return reports[offset : offset + limit]

    async def find_active_duplicate(
        self,
        report_type: str,
        dedup_signature: str,
        tenant_id: str | None = None,
        limit: int = 50,
        **_: object,
    ) -> Optional[EnergyReport]:
        query = self._scope_select(
            select(EnergyReport)
            .where(EnergyReport.report_type == ReportType(report_type))
            .where(EnergyReport.status.in_([ReportStatus.pending, ReportStatus.processing]))
            .order_by(EnergyReport.created_at.desc())
            .limit(limit),
            tenant_id=tenant_id,
        )
        result = await self.db.execute(query)
        for report in result.scalars().all():
            params = report.params or {}
            if params.get("dedup_signature") == dedup_signature:
                return report
        return None
