"""Low-latency dashboard read service backed by live projection rows."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.device import Device, DeviceLiveState, DeviceShift, RuntimeStatus, TELEMETRY_TIMEOUT_SECONDS
from app.services.idle_running import TariffCache
from app.services.load_thresholds import classify_current_band, resolve_device_thresholds
from app.services.live_projection import LiveProjectionService
from app.services.runtime_state import load_state_sql, runtime_status_sql
from services.shared.tenant_context import TenantContext, build_internal_headers


def _get_platform_tz() -> ZoneInfo:
    return ZoneInfo(settings.PLATFORM_TIMEZONE)


class LiveDashboardService:
    def __init__(self, session: AsyncSession, ctx: TenantContext | None = None):
        self._session = session
        self._projection = LiveProjectionService(session)
        self._ctx = ctx

    @staticmethod
    def _normalize_tariff(tariff: Optional[dict]) -> dict:
        if not isinstance(tariff, dict):
            return {"configured": False, "rate": 0.0, "currency": "INR", "cache": "empty"}
        normalized = dict(tariff)
        normalized.setdefault("configured", False)
        normalized.setdefault("rate", 0.0)
        normalized.setdefault("currency", "INR")
        return normalized

    @staticmethod
    def _tenant_context(tenant_id: Optional[str]) -> Optional[TenantContext]:
        if tenant_id is None:
            return None
        return TenantContext(
            tenant_id=tenant_id,
            user_id="system",
            role="system",
            plant_ids=[],
            is_super_admin=False,
        )

    def _resolve_plant_scope(
        self,
        plant_id: Optional[str] = None,
        accessible_plant_ids: Optional[list[str]] = None,
    ) -> Optional[list[str]]:
        if accessible_plant_ids is not None:
            if plant_id:
                return [plant_id] if plant_id in accessible_plant_ids else []
            return list(accessible_plant_ids)
        if plant_id:
            return [plant_id]
        if self._ctx is None:
            return None
        if self._ctx.role in {"plant_manager", "operator", "viewer"}:
            return list(self._ctx.plant_ids)
        return None

    @staticmethod
    def _apply_plant_scope(query, plant_ids: Optional[list[str]]):
        if plant_ids is None:
            return query
        if not plant_ids:
            return query.where(False)
        return query.where(Device.plant_id.in_(plant_ids))

    @staticmethod
    def _iso_utc(value: Optional[datetime]) -> Optional[str]:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()

    async def _fetch_energy_json(self, path: str, params: Optional[dict] = None) -> Optional[dict]:
        base = (settings.ENERGY_SERVICE_BASE_URL or "").rstrip("/")
        if not base:
            return None
        try:
            async with httpx.AsyncClient(timeout=max(0.5, settings.ENERGY_SERVICE_TIMEOUT_SECONDS)) as client:
                resp = await client.get(
                    f"{base}{path}",
                    params=params,
                    headers=build_internal_headers(
                        "device-service",
                        params.get("tenant_id") if isinstance(params, dict) else None,
                    ),
                )
                if resp.status_code != 200:
                    return None
                payload = resp.json()
                if not isinstance(payload, dict) or not payload.get("success"):
                    return None
                return payload
        except Exception:
            return None

    async def _build_current_day_loss_view(
        self,
        tenant_id: Optional[str],
        *,
        tariff_rate: float,
        currency: str,
        plant_id: Optional[str] = None,
        accessible_plant_ids: Optional[list[str]] = None,
    ) -> dict:
        local_day = datetime.now(timezone.utc).astimezone(_get_platform_tz()).date()
        plant_scope = self._resolve_plant_scope(plant_id, accessible_plant_ids)
        rows_query = (
            select(Device, DeviceLiveState)
            .outerjoin(
                DeviceLiveState,
                (DeviceLiveState.device_id == Device.device_id)
                & (DeviceLiveState.tenant_id == Device.tenant_id),
            )
            .where(Device.deleted_at.is_(None))
        )
        if tenant_id:
            rows_query = rows_query.where(Device.tenant_id == tenant_id)
        rows_query = self._apply_plant_scope(rows_query, plant_scope)
        rows = (await self._session.execute(rows_query)).all()

        table_rows: list[dict] = []
        totals = {
            "idle_kwh": 0.0,
            "off_hours_kwh": 0.0,
            "overconsumption_kwh": 0.0,
            "total_loss_kwh": 0.0,
            "today_energy_kwh": 0.0,
        }

        for device, state in rows:
            day_matches = state is not None and state.day_bucket == local_day
            idle = float(state.today_idle_kwh or 0.0) if day_matches and state else 0.0
            off_hours = float(state.today_offhours_kwh or 0.0) if day_matches and state else 0.0
            over = float(state.today_overconsumption_kwh or 0.0) if day_matches and state else 0.0
            total_loss = float(state.today_loss_kwh or 0.0) if day_matches and state else 0.0
            today_energy = float(state.today_energy_kwh or 0.0) if day_matches and state else 0.0

            totals["idle_kwh"] += idle
            totals["off_hours_kwh"] += off_hours
            totals["overconsumption_kwh"] += over
            totals["total_loss_kwh"] += total_loss
            totals["today_energy_kwh"] += today_energy

            table_rows.append(
                {
                    "device_id": device.device_id,
                    "device_name": device.device_name,
                    "idle_kwh": round(idle, 4),
                    "idle_cost_inr": round(idle * tariff_rate, 4),
                    "off_hours_kwh": round(off_hours, 4),
                    "off_hours_cost_inr": round(off_hours * tariff_rate, 4),
                    "overconsumption_kwh": round(over, 4),
                    "overconsumption_cost_inr": round(over * tariff_rate, 4),
                    "total_loss_kwh": round(total_loss, 4),
                    "total_loss_cost_inr": round(total_loss * tariff_rate, 4),
                    "status": "computed",
                    "reason": None,
                }
            )

        table_rows.sort(key=lambda row: row["total_loss_cost_inr"], reverse=True)
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "currency": currency,
            "totals": {
                "idle_kwh": round(totals["idle_kwh"], 4),
                "idle_cost_inr": round(totals["idle_kwh"] * tariff_rate, 4),
                "off_hours_kwh": round(totals["off_hours_kwh"], 4),
                "off_hours_cost_inr": round(totals["off_hours_kwh"] * tariff_rate, 4),
                "overconsumption_kwh": round(totals["overconsumption_kwh"], 4),
                "overconsumption_cost_inr": round(totals["overconsumption_kwh"] * tariff_rate, 4),
                "total_loss_kwh": round(totals["total_loss_kwh"], 4),
                "total_loss_cost_inr": round(totals["total_loss_kwh"] * tariff_rate, 4),
                "today_energy_kwh": round(totals["today_energy_kwh"], 4),
                "today_energy_cost_inr": round(totals["today_energy_kwh"] * tariff_rate, 4),
            },
            "rows": table_rows,
        }

    async def get_fleet_snapshot(
        self,
        page: int = 1,
        page_size: int = 50,
        sort: str = "device_name",
        tenant_id: Optional[str] = None,
        runtime_filter: Optional[str] = None,
        accessible_plant_ids: Optional[list[str]] = None,
    ) -> dict:
        now_utc = datetime.now(timezone.utc)
        derived_last_seen = func.coalesce(DeviceLiveState.last_telemetry_ts, Device.last_seen_timestamp)
        derived_runtime_status = runtime_status_sql(derived_last_seen, now_utc=now_utc)
        derived_load_state = load_state_sql(DeviceLiveState.load_state, derived_last_seen, now_utc=now_utc)

        count_query = (
            select(func.count())
            .select_from(Device)
            .outerjoin(
                DeviceLiveState,
                (DeviceLiveState.device_id == Device.device_id)
                & (DeviceLiveState.tenant_id == Device.tenant_id),
            )
            .where(Device.deleted_at.is_(None))
        )
        page_query = (
            select(
                Device,
                DeviceLiveState,
                Device.first_telemetry_timestamp,
                derived_runtime_status.label("resolved_runtime_status"),
                derived_load_state.label("resolved_load_state"),
                derived_last_seen.label("resolved_last_seen"),
            )
            .outerjoin(
                DeviceLiveState,
                (DeviceLiveState.device_id == Device.device_id)
                & (DeviceLiveState.tenant_id == Device.tenant_id),
            )
            .where(Device.deleted_at.is_(None))
        )

        if tenant_id:
            count_query = count_query.where(Device.tenant_id == tenant_id)
            page_query = page_query.where(Device.tenant_id == tenant_id)

        if accessible_plant_ids is not None:
            if accessible_plant_ids:
                count_query = count_query.where(Device.plant_id.in_(accessible_plant_ids))
                page_query = page_query.where(Device.plant_id.in_(accessible_plant_ids))
            else:
                count_query = count_query.where(False)
                page_query = page_query.where(False)

        if runtime_filter:
            count_query = count_query.where(derived_runtime_status == runtime_filter)
            page_query = page_query.where(derived_runtime_status == runtime_filter)

        last_seen_nulls_last = case((derived_last_seen.is_(None), 1), else_=0)
        if sort == "last_seen":
            page_query = page_query.order_by(last_seen_nulls_last.asc(), derived_last_seen.desc(), func.lower(Device.device_name).asc())
        else:
            page_query = page_query.order_by(func.lower(Device.device_name).asc(), last_seen_nulls_last.asc(), derived_last_seen.desc())

        total = int((await self._session.execute(count_query)).scalar() or 0)
        total_pages = max(1, (total + page_size - 1) // page_size)
        safe_page = max(1, min(page, total_pages))
        offset = (safe_page - 1) * page_size

        rows = (
            await self._session.execute(
                page_query.offset(offset).limit(page_size)
            )
        ).all()

        page_items: list[dict] = []
        device_ids: list[str] = []
        for device, state, first_telemetry_ts, runtime_status, load_state, last_seen_ts in rows:
            device_ids.append(device.device_id)
            thresholds = resolve_device_thresholds(device)
            current_band = (
                classify_current_band(
                    float(state.last_current_a) if state and state.last_current_a is not None else None,
                    float(state.last_voltage_v) if state and state.last_voltage_v is not None else None,
                    thresholds,
                )
                if runtime_status == RuntimeStatus.RUNNING.value
                else "unknown"
            )
            page_items.append(
                {
                    "device_id": device.device_id,
                    "device_name": device.device_name,
                    "device_type": device.device_type,
                    "plant_id": device.plant_id,
                    "runtime_status": runtime_status,
                    "load_state": load_state or "unknown",
                    "current_band": current_band,
                    "location": device.location,
                    "first_telemetry_timestamp": self._iso_utc(first_telemetry_ts),
                    "last_seen_timestamp": last_seen_ts.isoformat() if last_seen_ts is not None else None,
                    "health_score": round(float(state.health_score), 2) if state and state.health_score is not None else None,
                    "uptime_percentage": round(float(state.uptime_percentage), 2) if state and state.uptime_percentage is not None else None,
                    "has_uptime_config": False,
                    "data_freshness_ts": now_utc.isoformat(),
                    "version": int(state.version) if state else 0,
                }
            )

        shift_map: dict[str, int] = {}
        if device_ids:
            active_shift_counts = (
                await self._session.execute(
                    select(DeviceShift.device_id, func.count(DeviceShift.id))
                    .where(DeviceShift.is_active.is_(True), DeviceShift.device_id.in_(device_ids))
                    .group_by(DeviceShift.device_id)
                )
            ).all()
            shift_map = {row[0]: int(row[1]) for row in active_shift_counts}
        for item in page_items:
            item["has_uptime_config"] = shift_map.get(item["device_id"], 0) > 0

        return {
            "success": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "stale": False,
            "warnings": [],
            "degraded_services": [],
            "total": total,
            "page": safe_page,
            "page_size": page_size,
            "total_pages": total_pages,
            "devices": page_items,
        }

    async def get_dashboard_summary(
        self,
        tenant_id: Optional[str] = None,
        plant_id: Optional[str] = None,
        accessible_plant_ids: Optional[list[str]] = None,
    ) -> dict:
        now_utc = datetime.now(timezone.utc)
        plant_scope = self._resolve_plant_scope(plant_id, accessible_plant_ids)
        authoritative_last_seen = func.coalesce(DeviceLiveState.last_telemetry_ts, Device.last_seen_timestamp)
        derived_runtime_status = runtime_status_sql(authoritative_last_seen, now_utc=now_utc)

        summary_query = (
            select(
                func.count(Device.device_id),
                func.sum(case((derived_runtime_status == RuntimeStatus.RUNNING.value, 1), else_=0)),
                func.count(DeviceLiveState.health_score),
                func.avg(DeviceLiveState.health_score),
                func.avg(DeviceLiveState.uptime_percentage),
            )
            .select_from(Device)
            .outerjoin(
                DeviceLiveState,
                (DeviceLiveState.device_id == Device.device_id)
                & (DeviceLiveState.tenant_id == Device.tenant_id),
            )
            .where(Device.deleted_at.is_(None))
        )
        if tenant_id:
            summary_query = summary_query.where(Device.tenant_id == tenant_id)
        summary_query = self._apply_plant_scope(summary_query, plant_scope)

        total, running, devices_with_health_data, avg_health, avg_uptime = (
            await self._session.execute(summary_query)
        ).one()

        uptime_query = (
            select(func.count(func.distinct(DeviceShift.device_id)))
            .select_from(DeviceShift)
            .join(
                Device,
                (Device.device_id == DeviceShift.device_id)
                & (Device.tenant_id == DeviceShift.tenant_id),
            )
            .where(
                Device.deleted_at.is_(None),
                DeviceShift.is_active.is_(True),
            )
        )
        if tenant_id:
            uptime_query = uptime_query.where(DeviceShift.tenant_id == tenant_id)
        uptime_query = self._apply_plant_scope(uptime_query, plant_scope)
        uptime_configured = int((await self._session.execute(uptime_query)).scalar() or 0)

        total = int(total or 0)
        running = int(running or 0)
        devices_with_health_data = int(devices_with_health_data or 0)

        tariff = self._normalize_tariff(await TariffCache.get(tenant_id))
        rate = float(tariff.get("rate") or 0.0)
        live_loss_view = await self._build_current_day_loss_view(
            tenant_id,
            tariff_rate=rate,
            currency=str(tariff.get("currency") or "INR"),
            plant_id=plant_id,
            accessible_plant_ids=accessible_plant_ids,
        )
        currency = str(tariff.get("currency") or "INR")
        totals_query = (
            select(
                func.sum(DeviceLiveState.month_energy_kwh),
                func.sum(DeviceLiveState.today_energy_kwh),
            )
            .select_from(Device)
            .outerjoin(
                DeviceLiveState,
                (DeviceLiveState.device_id == Device.device_id)
                & (DeviceLiveState.tenant_id == Device.tenant_id),
            )
            .where(Device.deleted_at.is_(None))
        )
        if tenant_id:
            totals_query = totals_query.where(Device.tenant_id == tenant_id)
        totals_query = self._apply_plant_scope(totals_query, plant_scope)
        totals = (await self._session.execute(totals_query)).first()
        month_energy = float(totals[0] or 0.0)
        today_energy = float(totals[1] or 0.0)
        month_cost = month_energy * rate
        today_cost = today_energy * rate
        live_totals = live_loss_view["totals"]
        today_loss = float(live_totals["total_loss_kwh"] or 0.0)
        today_loss_cost = float(live_totals["total_loss_cost_inr"] or 0.0)

        return {
            "success": True,
            "generated_at": now_utc.isoformat(),
            "stale": False,
            "warnings": [],
            "degraded_services": [],
            "summary": {
                "total_devices": total,
                "running_devices": running,
                "stopped_devices": max(0, total - running),
                "devices_with_health_data": devices_with_health_data,
                "devices_with_uptime_configured": uptime_configured,
                "devices_missing_uptime_config": max(0, total - uptime_configured),
                "system_health": round(float(avg_health), 2) if avg_health is not None else None,
                "average_efficiency": round(float(avg_uptime), 2) if avg_uptime is not None else None,
            },
            "alerts": {
                "active_alerts": 0,
                "alerts_triggered": 0,
                "alerts_cleared": 0,
                "rules_created": 0,
            },
            "devices": [],
            "energy_widgets": {
                "month_energy_kwh": round(month_energy, 4),
                "month_energy_cost_inr": round(month_cost, 4),
                "today_energy_kwh": round(today_energy, 4),
                "today_energy_cost_inr": round(today_cost, 4),
                "today_loss_kwh": round(today_loss, 4),
                "today_loss_cost_inr": round(today_loss_cost, 4),
                "generated_at": now_utc.isoformat(),
                "currency": currency,
                "data_quality": "ok",
                "invariant_checks": {},
                "reconciliation_warning": None,
                "no_nan_inf": True,
            },
            "cost_data_state": "fresh",
            "cost_data_reasons": [],
            "cost_generated_at": now_utc.isoformat(),
        }

    async def get_today_loss_breakdown(
        self,
        tenant_id: Optional[str] = None,
        plant_id: Optional[str] = None,
        accessible_plant_ids: Optional[list[str]] = None,
    ) -> dict:
        tariff = self._normalize_tariff(await TariffCache.get(tenant_id))
        rate = float(tariff.get("rate") or 0.0)
        live_loss_view = await self._build_current_day_loss_view(
            tenant_id,
            tariff_rate=rate,
            currency=str(tariff.get("currency") or "INR"),
            plant_id=plant_id,
            accessible_plant_ids=accessible_plant_ids,
        )

        return {
            "success": True,
            "generated_at": live_loss_view["generated_at"],
            "stale": False,
            "currency": live_loss_view["currency"],
            "totals": live_loss_view["totals"],
            "rows": live_loss_view["rows"],
            "data_quality": "ok",
            "invariant_checks": {},
            "no_nan_inf": True,
            "warnings": [],
            "cost_data_state": "fresh",
            "cost_data_reasons": [],
            "cost_generated_at": live_loss_view["generated_at"],
        }

    async def get_monthly_energy_calendar(self, year: int, month: int, tenant_id: Optional[str] = None) -> dict:
        energy_payload = await self._fetch_energy_json(
            "/api/v1/energy/calendar/monthly",
            params={"year": year, "month": month, **({"tenant_id": tenant_id} if tenant_id else {})},
        )
        if energy_payload:
            payload = dict(energy_payload)
            payload.setdefault("stale", False)
            payload.setdefault("warnings", [])
            payload.setdefault("data_quality", "ok")
            payload.setdefault("no_nan_inf", True)
            payload.setdefault("cost_data_state", "fresh")
            payload.setdefault("cost_data_reasons", [])
            payload.setdefault("cost_generated_at", payload.get("generated_at"))
            return payload

        from app.services.dashboard import DashboardService

        svc = DashboardService(self._session, self._tenant_context(tenant_id))
        return await svc.get_monthly_energy(year=year, month=month)

    async def get_dashboard_bootstrap(self, device_id: str, tenant_id: str) -> dict:
        # Delegate to existing dashboard service for full payload; no in-memory cache at this layer.
        from app.services.dashboard import DashboardService

        svc = DashboardService(self._session, self._tenant_context(tenant_id))
        return await svc.get_dashboard_bootstrap(device_id=device_id, tenant_id=tenant_id)

    async def publish_device_update(self, device_id: str, tenant_id: str, *, partial: bool = True) -> dict:
        item = await self._projection.get_device_snapshot_item(device_id, tenant_id)
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "stale": False,
            "warnings": [],
            "devices": [item],
            "partial": partial,
            "version": int(item.get("version") or 0),
        }

    @staticmethod
    def observe_stream_emit_lag(created_at: datetime) -> None:
        from app.services.dashboard import DashboardService

        DashboardService.observe_stream_emit_lag(created_at)

    @staticmethod
    def record_stream_disconnect(reason: str) -> None:
        from app.services.dashboard import DashboardService

        DashboardService.record_stream_disconnect(reason)
