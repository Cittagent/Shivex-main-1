from datetime import datetime
from typing import Optional

from sqlalchemy import delete, select, update

from src.models import WasteAnalysisJob, WasteDeviceSummary
from services.shared.tenant_context import TenantContext


class WasteRepository:
    def __init__(self, db, ctx: TenantContext | None = None):
        self.db = db
        self._ctx = ctx or TenantContext.system("svc:waste-analysis-service")
        self._tenant_id = self._ctx.tenant_id

    async def create_job(
        self,
        job_id: str,
        job_name: Optional[str],
        scope: str,
        device_ids: Optional[list[str]],
        start_date,
        end_date,
        granularity: str,
        **_: object,
    ) -> WasteAnalysisJob:
        job = WasteAnalysisJob(
            id=job_id,
            tenant_id=self._require_tenant_id(),
            job_name=job_name,
            scope=scope,
            device_ids=device_ids,
            start_date=start_date,
            end_date=end_date,
            granularity=granularity,
            status="pending",
            progress_pct=0,
            stage="Queued",
            result_json={"tenant_id": self._tenant_id} if self._tenant_id else {},
            created_at=datetime.utcnow(),
        )
        self.db.add(job)
        await self.db.commit()
        await self.db.refresh(job)
        return job

    def _require_tenant_id(self) -> str:
        return self._ctx.require_tenant()

    def _tenant_scoped_job_query(self):
        statement = select(WasteAnalysisJob)
        if self._tenant_id is not None:
            statement = statement.where(WasteAnalysisJob.tenant_id == self._tenant_id)
        return statement

    async def get_job(self, job_id: str, **_: object) -> Optional[WasteAnalysisJob]:
        result = await self.db.execute(
            self._tenant_scoped_job_query().where(WasteAnalysisJob.id == job_id)
        )
        return result.scalar_one_or_none()

    async def list_jobs(self, limit: int = 20, offset: int = 0, **_: object) -> list[WasteAnalysisJob]:
        result = await self.db.execute(
            self._tenant_scoped_job_query()
            .order_by(WasteAnalysisJob.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def update_job(self, job_id: str, **kwargs) -> None:
        payload = {k: v for k, v in kwargs.items() if v is not None}
        if not payload:
            return
        existing = await self.get_job(job_id)
        existing_meta = existing.result_json if existing and isinstance(existing.result_json, dict) else {}
        if "result_json" in payload and isinstance(payload["result_json"], dict) and existing_meta.get("tenant_id"):
            payload["result_json"] = {**payload["result_json"], "tenant_id": existing_meta["tenant_id"]}
        await self.db.execute(update(WasteAnalysisJob).where(WasteAnalysisJob.id == job_id).values(**payload))
        await self.db.commit()

    async def replace_device_summaries(self, job_id: str, summaries: list[dict]) -> None:
        await self.db.execute(delete(WasteDeviceSummary).where(WasteDeviceSummary.job_id == job_id))
        for s in summaries:
            self.db.add(WasteDeviceSummary(job_id=job_id, **s))
        await self.db.commit()

    async def replace_device_summaries_chunked(self, job_id: str, summaries: list[dict], batch_size: int = 500) -> None:
        await self.db.execute(delete(WasteDeviceSummary).where(WasteDeviceSummary.job_id == job_id))
        await self.db.commit()

        size = max(1, int(batch_size))
        for i in range(0, len(summaries), size):
            batch = summaries[i : i + size]
            for s in batch:
                self.db.add(WasteDeviceSummary(job_id=job_id, **s))
            await self.db.commit()

    async def list_device_summaries(self, job_id: str) -> list[WasteDeviceSummary]:
        result = await self.db.execute(
            select(WasteDeviceSummary)
            .where(WasteDeviceSummary.job_id == job_id)
            .order_by(WasteDeviceSummary.id.asc())
        )
        return list(result.scalars().all())

    async def find_active_duplicate(
        self,
        scope: str,
        device_ids: Optional[list[str]],
        start_date,
        end_date,
        granularity: str,
        limit: int = 50,
        **_: object,
    ) -> Optional[WasteAnalysisJob]:
        statement = (
            self._tenant_scoped_job_query()
            .where(WasteAnalysisJob.status.in_(["pending", "running"]))
            .where(WasteAnalysisJob.scope == scope)
            .where(WasteAnalysisJob.start_date == start_date)
            .where(WasteAnalysisJob.end_date == end_date)
            .where(WasteAnalysisJob.granularity == granularity)
            .order_by(WasteAnalysisJob.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(statement)
        requested_ids = sorted(device_ids or [])
        for job in result.scalars().all():
            existing_ids = sorted(job.device_ids or [])
            if existing_ids == requested_ids:
                return job
        return None
