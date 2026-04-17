from __future__ import annotations

import os
import sys
import asyncio
from datetime import date, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.requests import Request

sys.path.insert(0, "/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/reporting-service")
sys.path.insert(1, "/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services")

os.environ.setdefault("DEVICE_SERVICE_URL", "http://device-service:8001")
os.environ.setdefault("ENERGY_SERVICE_URL", "http://energy-service:8002")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from src.handlers import energy_reports as energy_reports_module
from src.models.energy_reports import Base as EnergyBase, EnergyReport, ReportStatus, ReportType
from src.queue.report_queue import InMemoryReportQueue, ReportJob
from src.repositories.report_repository import ReportRepository
from src.schemas.requests import ConsumptionReportRequest
from src.workers import report_worker as report_worker_module
from src.workers.report_worker import ReportWorker
from services.shared.tenant_context import TenantContext


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(EnergyBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield factory
    finally:
        await engine.dispose()


def _request(tenant_id: str = "SH00000001") -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/reports/energy/consumption",
        "headers": [(b"x-tenant-id", tenant_id.encode("utf-8"))],
        "query_string": b"",
    }
    request = Request(scope)
    request.state.tenant_context = TenantContext(
        tenant_id=tenant_id,
        user_id="user-1",
        role="org_admin",
        plant_ids=[],
        is_super_admin=False,
    )
    request.state.role = "org_admin"
    return request


@pytest.mark.asyncio
async def test_submit_api_enqueues_without_inline_execution(session_factory, monkeypatch):
    queue = InMemoryReportQueue()

    async def _fake_validate(device_id: str, ctx):
        return {"device_id": device_id}

    monkeypatch.setattr(energy_reports_module, "get_report_queue", lambda: queue)
    monkeypatch.setattr(energy_reports_module, "validate_device_for_reporting", _fake_validate)
    monkeypatch.setattr(energy_reports_module, "resolve_all_devices", lambda ctx: ["DEVICE-1"])

    async with session_factory() as session:
        response = await energy_reports_module.create_energy_consumption_report(
            request=ConsumptionReportRequest(
                start_date=date(2026, 4, 1),
                end_date=date(2026, 4, 2),
                device_id="DEVICE-1",
                tenant_id="SH00000001",
            ),
            app_request=_request(),
            db=session,
        )
        repo = ReportRepository(session)
        report = await repo.load_report_for_worker(response.report_id, tenant_id="SH00000001")

    job = await queue.get_job()

    assert response.status == "processing"
    assert job is not None
    assert job.report_id == response.report_id
    assert report is not None
    assert report.status == ReportStatus.pending


@pytest.mark.asyncio
async def test_duplicate_submit_reuses_existing_active_report(session_factory, monkeypatch):
    queue = InMemoryReportQueue()

    async def _fake_validate(device_id: str, ctx):
        return {"device_id": device_id}

    monkeypatch.setattr(energy_reports_module, "get_report_queue", lambda: queue)
    monkeypatch.setattr(energy_reports_module, "validate_device_for_reporting", _fake_validate)

    async with session_factory() as session:
        request = ConsumptionReportRequest(
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 2),
            device_id="DEVICE-1",
            tenant_id="SH00000001",
        )
        first = await energy_reports_module.create_energy_consumption_report(request, _request(), session)
        second = await energy_reports_module.create_energy_consumption_report(request, _request(), session)
        repo = ReportRepository(session)
        reports = await repo.list_reports(tenant_id="SH00000001", limit=10, offset=0)

    assert first.report_id == second.report_id
    assert len(reports) == 1


@pytest.mark.asyncio
async def test_worker_processes_queued_job_and_marks_completed(session_factory, monkeypatch):
    queue = InMemoryReportQueue()
    worker = ReportWorker(queue=queue, concurrency=1)

    async def _fake_execute(report_id: str, report_type: str, params: dict) -> None:
        async with report_worker_module.AsyncSessionLocal() as session:
            repo = ReportRepository(session)
            await repo.update_report(
                report_id,
                status="completed",
                progress=100,
                result_json={"ok": True},
                completed_at=datetime.utcnow(),
            )

    monkeypatch.setattr(report_worker_module, "execute_report", _fake_execute)

    async with session_factory() as session:
        report = EnergyReport(
            report_id="report-queued",
            tenant_id="SH00000001",
            report_type=ReportType.consumption,
            status=ReportStatus.pending,
            params={"tenant_id": "SH00000001"},
            created_at=datetime.utcnow(),
            enqueued_at=datetime.utcnow(),
        )
        session.add(report)
        await session.commit()

    monkeypatch.setattr(report_worker_module, "AsyncSessionLocal", session_factory)
    await queue.enqueue(ReportJob(report_id="report-queued", tenant_id="SH00000001", report_type="consumption"))
    job = await queue.get_job()
    assert job is not None

    await worker._process_job(job, slot=0)

    async with session_factory() as session:
        repo = ReportRepository(session)
        refreshed = await repo.load_report_for_worker("report-queued", tenant_id="SH00000001")

    assert refreshed is not None
    assert refreshed.status == ReportStatus.completed
    assert refreshed.worker_id is None
    assert refreshed.processing_started_at is None


@pytest.mark.asyncio
async def test_worker_timeout_marks_failed_after_retry_budget_exhausted(session_factory, monkeypatch):
    queue = InMemoryReportQueue()
    worker = ReportWorker(queue=queue, concurrency=1)

    async def _slow_execute(report_id: str, report_type: str, params: dict) -> None:
        await asyncio.sleep(1.1)

    monkeypatch.setattr(report_worker_module, "execute_report", _slow_execute)
    monkeypatch.setattr(report_worker_module, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(report_worker_module.settings, "REPORT_JOB_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(report_worker_module.settings, "REPORT_JOB_MAX_RETRIES", 1)

    async with session_factory() as session:
        session.add(
            EnergyReport(
                report_id="report-timeout",
                tenant_id="SH00000001",
                report_type=ReportType.consumption,
                status=ReportStatus.pending,
                params={"tenant_id": "SH00000001"},
                created_at=datetime.utcnow(),
                enqueued_at=datetime.utcnow(),
            )
        )
        await session.commit()

    await queue.enqueue(ReportJob(report_id="report-timeout", tenant_id="SH00000001", report_type="consumption"))
    job = await queue.get_job()
    assert job is not None

    await worker._process_job(job, slot=0)

    async with session_factory() as session:
        repo = ReportRepository(session)
        refreshed = await repo.load_report_for_worker("report-timeout", tenant_id="SH00000001")

    assert refreshed is not None
    assert refreshed.status == ReportStatus.failed
    assert refreshed.error_code == "JOB_TIMEOUT"
    assert refreshed.timeout_count == 1


@pytest.mark.asyncio
async def test_stale_processing_report_can_be_reclaimed_by_worker(session_factory, monkeypatch):
    queue = InMemoryReportQueue()
    worker = ReportWorker(queue=queue, concurrency=1)

    async def _fake_execute(report_id: str, report_type: str, params: dict) -> None:
        async with report_worker_module.AsyncSessionLocal() as session:
            repo = ReportRepository(session)
            await repo.update_report(
                report_id,
                status="completed",
                progress=100,
                completed_at=datetime.utcnow(),
            )

    monkeypatch.setattr(report_worker_module, "execute_report", _fake_execute)
    monkeypatch.setattr(report_worker_module, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(report_worker_module.settings, "REPORT_JOB_TIMEOUT_SECONDS", 5)

    async with session_factory() as session:
        session.add(
            EnergyReport(
                report_id="report-stale",
                tenant_id="SH00000001",
                report_type=ReportType.consumption,
                status=ReportStatus.processing,
                params={"tenant_id": "SH00000001"},
                created_at=datetime.utcnow() - timedelta(minutes=10),
                enqueued_at=datetime.utcnow() - timedelta(minutes=10),
                processing_started_at=datetime.utcnow() - timedelta(minutes=10),
                worker_id="dead-worker",
            )
        )
        await session.commit()

    await worker._process_job(
        ReportJob(report_id="report-stale", tenant_id="SH00000001", report_type="consumption"),
        slot=0,
    )

    async with session_factory() as session:
        repo = ReportRepository(session)
        refreshed = await repo.load_report_for_worker("report-stale", tenant_id="SH00000001")

    assert refreshed is not None
    assert refreshed.status == ReportStatus.completed
