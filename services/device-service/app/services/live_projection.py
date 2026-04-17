"""Real-time device projection updates for low-latency dashboards."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.device import Device, DeviceLiveState, DeviceShift, DeviceStateIntervalType, RuntimeStatus, TELEMETRY_TIMEOUT_SECONDS
from app.repositories.device import DeviceRepository
from app.repositories.device_state_intervals import DeviceStateIntervalRepository
from app.services.device_state_intervals import DeviceStateIntervalService
from app.services.health_config import HealthConfigService
from app.services.idle_running import IdleRunningService, TariffCache
from app.services.load_thresholds import classify_current_band, resolve_device_thresholds
from app.services.runtime_state import resolve_load_state, resolve_runtime_status, resolve_runtime_timeout_ended_at
from app.services.device_errors import InvalidDeviceMetadataError
from app.services.shift import ShiftService
from app.schemas.device import normalize_phase_type
from services.shared.energy_accounting import aggregate_window, split_loss_components
from services.shared.telemetry_normalization import (
    NormalizedTelemetrySample,
    compute_interval_energy_delta,
    normalize_telemetry_sample,
)
from services.shared.tenant_context import TenantContext, build_internal_headers

logger = logging.getLogger(__name__)


def _get_platform_tz() -> ZoneInfo:
    from app.config import settings

    return ZoneInfo(settings.PLATFORM_TIMEZONE)


def _health_machine_state_from_live_state(load_state: Optional[str], runtime_status: Optional[str] = None) -> str:
    normalized_load = str(load_state or "").strip().lower()
    if normalized_load == "idle":
        return "IDLE"
    if normalized_load == "overconsumption":
        return "RUNNING"
    if normalized_load == "unloaded":
        return "UNLOAD"
    if normalized_load == "running":
        return "RUNNING"
    if str(runtime_status or "").strip().lower() == RuntimeStatus.RUNNING.value:
        return "RUNNING"
    return "OFF"


def _health_machine_state_for_recompute(
    *,
    latest_telemetry: dict[str, Any],
    device: Device,
    persisted_load_state: Optional[str],
    persisted_runtime_status: Optional[str],
) -> str:
    mapped = IdleRunningService.map_telemetry(latest_telemetry)
    derived_load_state = IdleRunningService.detect_device_state_with_thresholds(
        current=mapped.current,
        voltage=mapped.voltage,
        thresholds=resolve_device_thresholds(device),
    )
    if derived_load_state in {"running", "idle", "unloaded", "overconsumption"}:
        return _health_machine_state_from_live_state(derived_load_state, RuntimeStatus.RUNNING.value)

    persisted_machine_state = _health_machine_state_from_live_state(persisted_load_state, persisted_runtime_status)
    if persisted_machine_state != "OFF":
        return persisted_machine_state

    # Recompute runs after config changes against freshly fetched live telemetry.
    # If we have telemetry but not enough fields to classify load/off state, prefer
    # an explicit RUNNING fallback so valid health recomputation is not suppressed.
    return "RUNNING"


async def update_live_state_with_lock(
    session: AsyncSession,
    device_id: str,
    tenant_id: str,
    updates: dict,
    max_retries: int = 3,
    retry_delay_ms: int = 50
) -> bool:
    """
    Returns True if update succeeded, False if all retries exhausted.
    Logs WARNING on retry, ERROR if all retries fail.
    """

    for attempt in range(1, max_retries + 1):
        version_result = await session.execute(
            select(DeviceLiveState.version).where(
                DeviceLiveState.device_id == device_id,
                DeviceLiveState.tenant_id == tenant_id,
            )
        )
        expected_version = version_result.scalar_one_or_none()
        if expected_version is None:
            logger.error(
                "Device live state row missing for optimistic lock update",
                extra={"device_id": device_id, "tenant_id": tenant_id},
            )
            return False

        update_result = await session.execute(
            update(DeviceLiveState)
            .where(
                DeviceLiveState.device_id == device_id,
                DeviceLiveState.tenant_id == tenant_id,
                DeviceLiveState.version == expected_version,
            )
            .values(
                **updates,
                version=DeviceLiveState.version + 1,
                updated_at=datetime.utcnow(),
            )
        )
        if (update_result.rowcount or 0) > 0:
            return True

        await session.rollback()
        if attempt < max_retries:
            logger.warning(
                "Optimistic lock conflict on device_live_state update; retrying",
                extra={
                    "device_id": device_id,
                    "tenant_id": tenant_id,
                    "attempt": attempt,
                    "max_retries": max_retries,
                },
            )
            await asyncio.sleep(retry_delay_ms / 1000.0)

    logger.error(
        "Optimistic lock retries exhausted for device_live_state update",
        extra={"device_id": device_id, "tenant_id": tenant_id, "max_retries": max_retries},
    )
    return False


class LiveProjectionService:
    """Maintains live projection rows and event payloads per device."""

    def __init__(self, session: AsyncSession, ctx: TenantContext | None = None):
        self._session = session
        self._ctx = ctx
        self._devices = DeviceRepository(
            session,
            ctx or TenantContext.system("svc:device-service"),
            allow_cross_tenant=ctx is None,
        )
        self._intervals = DeviceStateIntervalService(session)
        self._interval_repo = DeviceStateIntervalRepository(session)
        self._health = HealthConfigService(session)
        self._shift = ShiftService(session)

    @staticmethod
    def _parse_ts(value: Any) -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if value:
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except Exception:
                pass
        return datetime.now(timezone.utc)

    @staticmethod
    def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _activation_eligible(self, device: Device, telemetry_ts: datetime) -> bool:
        created_at = self._as_utc(device.created_at)
        sample_ts = self._as_utc(telemetry_ts)
        if sample_ts is None:
            return False
        if created_at is not None and sample_ts < created_at:
            return False
        return device.first_telemetry_timestamp is None

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except Exception:
            return None

    @staticmethod
    def _power_kw_from_payload(payload: dict[str, Any], mapped_power: Optional[float]) -> float:
        kw = LiveProjectionService._to_float(payload.get("active_power_kw"))
        if kw is not None:
            return max(kw, 0.0)
        kw = LiveProjectionService._to_float(payload.get("power_kw"))
        if kw is not None:
            return max(kw, 0.0)
        kw = LiveProjectionService._to_float(payload.get("kw"))
        if kw is not None:
            return max(kw, 0.0)
        source = dict(payload)
        if mapped_power is not None and "power" not in source and "active_power" not in source:
            source["power"] = mapped_power
        normalized = normalize_telemetry_sample(source, {})
        return normalized.business_power_w / 1000.0

    @staticmethod
    def _is_inside_shift(local_ts: datetime, shifts: list[DeviceShift]) -> bool:
        if not shifts:
            return False
        now_t = local_ts.time()
        weekday = local_ts.weekday()
        for shift in shifts:
            if not shift.is_active:
                continue
            start = shift.shift_start
            end = shift.shift_end
            day = shift.day_of_week
            if end > start:
                if start <= now_t < end and (day is None or day == weekday):
                    return True
            else:
                if now_t >= start and (day is None or day == weekday):
                    return True
                if now_t < end and (day is None or day == (weekday - 1) % 7):
                    return True
        return False

    async def _get_or_create_state(self, device_id: str, tenant_id: str) -> DeviceLiveState:
        state = await self._session.get(DeviceLiveState, {"device_id": device_id, "tenant_id": tenant_id})
        if state is not None:
            return state
        state = DeviceLiveState(
            device_id=device_id,
            tenant_id=tenant_id,
            runtime_status=RuntimeStatus.STOPPED.value,
            load_state="unknown",
            version=0,
        )
        self._session.add(state)
        await self._session.flush()
        return state

    @staticmethod
    def _resolve_idle_streak(
        *,
        previous_load_state: Optional[str],
        previous_sample_ts: Optional[datetime],
        previous_started_at: Optional[datetime],
        current_load_state: str,
        current_sample_ts: datetime,
    ) -> tuple[Optional[datetime], int]:
        if current_load_state != "idle":
            return None, 0

        continuity_intact = False
        if previous_load_state == "idle" and previous_sample_ts is not None and current_sample_ts >= previous_sample_ts:
            continuity_gap_sec = (current_sample_ts - previous_sample_ts).total_seconds()
            continuity_intact = continuity_gap_sec <= TELEMETRY_TIMEOUT_SECONDS

        if continuity_intact and previous_started_at is not None:
            return previous_started_at, max(int((current_sample_ts - previous_started_at).total_seconds()), 0)

        return current_sample_ts, 0

    @staticmethod
    def _normalize_device_metadata(device: Device) -> Device:
        try:
            device.phase_type = normalize_phase_type(device.phase_type, allow_legacy_aliases=True)
        except ValueError as exc:
            raise InvalidDeviceMetadataError(
                device_id=device.device_id,
                field_name="phase_type",
                message=str(exc),
            ) from exc
        return device

    @staticmethod
    def _normalized_sample_from_payload(
        *,
        telemetry_payload: dict[str, Any],
        dynamic_fields: Optional[dict[str, Any]],
        normalized_fields: Optional[dict[str, Any]],
        device: Device,
    ) -> tuple[dict[str, Any], NormalizedTelemetrySample]:
        source = dict(telemetry_payload)
        if isinstance(dynamic_fields, dict):
            source.update(dynamic_fields)

        normalized = (
            NormalizedTelemetrySample(
                timestamp=LiveProjectionService._parse_ts(normalized_fields.get("timestamp")),
                raw_power_w=normalized_fields.get("raw_power_w"),
                raw_active_power_w=normalized_fields.get("raw_active_power_w"),
                raw_power_factor=normalized_fields.get("raw_power_factor"),
                raw_current_a=normalized_fields.get("raw_current_a"),
                raw_voltage_v=normalized_fields.get("raw_voltage_v"),
                raw_energy_kwh=normalized_fields.get("raw_energy_kwh"),
                raw_source_power_field=normalized_fields.get("raw_source_power_field"),
                raw_source_pf_field=normalized_fields.get("raw_source_pf_field"),
                raw_source_energy_field=normalized_fields.get("raw_source_energy_field"),
                net_power_w=normalized_fields.get("net_power_w"),
                import_power_w=float(normalized_fields.get("import_power_w") or 0.0),
                export_power_w=float(normalized_fields.get("export_power_w") or 0.0),
                business_power_w=float(normalized_fields.get("business_power_w") or 0.0),
                pf_signed=normalized_fields.get("pf_signed"),
                pf_business=normalized_fields.get("pf_business"),
                current_a=normalized_fields.get("current_a"),
                voltage_v=normalized_fields.get("voltage_v"),
                energy_counter_kwh=normalized_fields.get("energy_counter_kwh"),
                power_direction=normalized_fields.get("power_direction") or "unknown",
                quality_flags=tuple(normalized_fields.get("quality_flags") or []),
                normalization_version=normalized_fields.get("normalization_version") or "signed-power-v1",
            )
            if isinstance(normalized_fields, dict)
            else normalize_telemetry_sample(source, device)
        )
        return source, normalized

    def _build_snapshot_item(
        self,
        *,
        device: Device,
        state: DeviceLiveState,
        freshness_ts: Optional[datetime] = None,
    ) -> dict[str, Any]:
        thresholds = resolve_device_thresholds(device)
        authoritative_last_seen = state.last_telemetry_ts if state.last_telemetry_ts is not None else device.last_seen_timestamp
        runtime_status = resolve_runtime_status(authoritative_last_seen)
        load_state = resolve_load_state(state.load_state, authoritative_last_seen)
        current_band = (
            classify_current_band(
                float(state.last_current_a) if state.last_current_a is not None else None,
                float(state.last_voltage_v) if state.last_voltage_v is not None else None,
                thresholds,
            )
            if runtime_status == RuntimeStatus.RUNNING.value
            else "unknown"
        )
        first_activation_ts = self._as_utc(device.first_telemetry_timestamp)
        idle_streak_started_at = self._as_utc(state.idle_streak_started_at)
        generated_at = freshness_ts or datetime.now(timezone.utc)
        return {
            "device_id": device.device_id,
            "device_name": device.device_name,
            "device_type": device.device_type,
            "plant_id": device.plant_id,
            "runtime_status": runtime_status,
            "load_state": load_state,
            "current_band": current_band,
            "full_load_current_a": thresholds.full_load_current_a,
            "idle_threshold_pct_of_fla": thresholds.idle_threshold_pct_of_fla,
            "derived_idle_threshold_a": thresholds.derived_idle_threshold_a,
            "derived_overconsumption_threshold_a": thresholds.derived_overconsumption_threshold_a,
            "idle_streak_started_at": idle_streak_started_at.isoformat() if idle_streak_started_at is not None else None,
            "idle_streak_duration_sec": int(state.idle_streak_duration_sec or 0),
            "location": device.location,
            "first_telemetry_timestamp": first_activation_ts.isoformat() if first_activation_ts is not None else None,
            "last_seen_timestamp": authoritative_last_seen.isoformat() if authoritative_last_seen is not None else None,
            "health_score": round(float(state.health_score), 2) if state.health_score is not None else None,
            "uptime_percentage": round(float(state.uptime_percentage), 2) if state.uptime_percentage is not None else None,
            "has_uptime_config": any(shift.is_active for shift in (device.shifts or [])),
            "data_freshness_ts": generated_at.isoformat(),
            "version": int(state.version or 0),
        }

    async def _apply_live_update_loaded(
        self,
        *,
        device: Device,
        state: DeviceLiveState,
        tenant_id: str,
        telemetry_payload: dict[str, Any],
        dynamic_fields: Optional[dict[str, Any]] = None,
        normalized_fields: Optional[dict[str, Any]] = None,
        persistence_mode: str = "optimistic",
        tariff_rate: Optional[float] = None,
        active_health_configs: Optional[list[Any]] = None,
    ) -> dict[str, Any]:
        self._normalize_device_metadata(device)
        ts = self._parse_ts(telemetry_payload.get("timestamp"))
        activation_should_write = self._activation_eligible(device, ts)
        last_sample_ts = self._as_utc(state.last_sample_ts)
        if last_sample_ts is not None and ts <= last_sample_ts:
            if activation_should_write:
                await self._devices.set_first_telemetry_timestamp_if_missing(
                    device_id=device.device_id,
                    tenant_id=device.tenant_id,
                    timestamp=ts,
                )
                device.first_telemetry_timestamp = device.first_telemetry_timestamp or ts
            return self._build_snapshot_item(device=device, state=state)

        local_tz = _get_platform_tz()
        local_day = ts.astimezone(local_tz).date()
        month_bucket = local_day.replace(day=1)

        if state.day_bucket != local_day:
            state.day_bucket = local_day
            state.today_energy_kwh = 0
            state.today_idle_kwh = 0
            state.today_offhours_kwh = 0
            state.today_overconsumption_kwh = 0
            state.today_loss_kwh = 0
            state.today_loss_cost_inr = 0
            state.today_running_seconds = 0
            state.today_effective_seconds = 0
        if state.month_bucket != month_bucket:
            state.month_bucket = month_bucket
            state.month_energy_kwh = 0
            state.month_energy_cost_inr = 0

        source, normalized = self._normalized_sample_from_payload(
            telemetry_payload=telemetry_payload,
            dynamic_fields=dynamic_fields,
            normalized_fields=normalized_fields,
            device=device,
        )
        telemetry_numeric = HealthConfigService.extract_numeric_telemetry_values(source)

        power_kw = normalized.business_power_w / 1000.0
        current_a = normalized.current_a
        voltage_v = normalized.voltage_v
        thresholds = resolve_device_thresholds(device)
        load_state = IdleRunningService.detect_device_state_with_thresholds(
            current=current_a,
            voltage=voltage_v,
            thresholds=thresholds,
        )
        current_band = classify_current_band(current_a, voltage_v, thresholds)
        previous_load_state = state.load_state
        previous_current_band = classify_current_band(
            float(state.last_current_a) if state.last_current_a is not None else None,
            float(state.last_voltage_v) if state.last_voltage_v is not None else None,
            thresholds,
        )
        previous_idle_streak_started_at = self._as_utc(state.idle_streak_started_at)

        dt_sec = 0.0
        if last_sample_ts and ts > last_sample_ts:
            dt_sec = (ts - last_sample_ts).total_seconds()
            dt_sec = max(0.0, min(dt_sec, 120.0))

        idle_streak_started_at, idle_streak_duration_sec = self._resolve_idle_streak(
            previous_load_state=previous_load_state,
            previous_sample_ts=last_sample_ts,
            previous_started_at=previous_idle_streak_started_at,
            current_load_state=load_state,
            current_sample_ts=ts,
        )

        previous_normalized = None
        if last_sample_ts is not None:
            previous_source = {
                "timestamp": last_sample_ts.isoformat(),
                "energy_kwh": float(state.last_energy_kwh) if state.last_energy_kwh is not None else None,
                "power_kw": float(state.last_power_kw) if state.last_power_kw is not None else None,
                "current": float(state.last_current_a) if state.last_current_a is not None else None,
                "voltage": float(state.last_voltage_v) if state.last_voltage_v is not None else None,
            }
            previous_normalized = normalize_telemetry_sample(previous_source, device)

        energy_resolution = compute_interval_energy_delta(
            previous_normalized,
            normalized,
            max_fallback_gap_seconds=120.0,
        )
        energy_delta = float(energy_resolution.business_energy_delta_kwh)
        sample_energy_kwh = normalized.energy_counter_kwh

        active_shifts = [shift for shift in (device.shifts or []) if shift.is_active]
        inside_shift = self._is_inside_shift(ts.astimezone(local_tz), active_shifts)
        running_signal = power_kw > 0 or (current_a is not None and current_a > 0)
        if dt_sec > 0 and inside_shift:
            state.today_effective_seconds = int(state.today_effective_seconds or 0) + int(dt_sec)
            if running_signal:
                state.today_running_seconds = int(state.today_running_seconds or 0) + int(dt_sec)

        idle_threshold = thresholds.derived_idle_threshold_a
        over_threshold = thresholds.derived_overconsumption_threshold_a
        idle_delta = 0.0
        off_delta = 0.0
        over_delta = 0.0
        if running_signal and energy_delta > 0:
            idle_delta, off_delta, over_delta = split_loss_components(
                duration_sec=dt_sec,
                interval_energy_kwh=energy_delta,
                current_a=current_a,
                voltage_v=voltage_v,
                pf=normalized.pf_business,
                idle_threshold=idle_threshold,
                over_threshold=over_threshold,
                inside_shift=inside_shift,
                power_kw=power_kw if power_kw > 0 else None,
            )

        state.today_energy_kwh = Decimal(str(float(state.today_energy_kwh or 0) + energy_delta))
        state.month_energy_kwh = Decimal(str(float(state.month_energy_kwh or 0) + energy_delta))
        state.today_idle_kwh = Decimal(str(float(state.today_idle_kwh or 0) + idle_delta))
        state.today_offhours_kwh = Decimal(str(float(state.today_offhours_kwh or 0) + off_delta))
        state.today_overconsumption_kwh = Decimal(str(float(state.today_overconsumption_kwh or 0) + over_delta))
        total_loss = float(state.today_idle_kwh or 0) + float(state.today_offhours_kwh or 0) + float(state.today_overconsumption_kwh or 0)
        state.today_loss_kwh = Decimal(str(total_loss))

        if tariff_rate is None:
            tariff = await TariffCache.get(tenant_id) or {}
            if not isinstance(tariff, dict):
                tariff = {}
            tariff_rate = float(tariff.get("rate") or 0.0)
        rate = float(tariff_rate or 0.0)
        state.today_loss_cost_inr = Decimal(str(total_loss * rate))
        state.month_energy_cost_inr = Decimal(str(float(state.month_energy_kwh or 0) * rate))

        if active_health_configs is None:
            health = await self._health.calculate_health_score(
                device_id=device.device_id,
                telemetry_values=telemetry_numeric,
                machine_state=_health_machine_state_from_live_state(load_state, RuntimeStatus.RUNNING.value),
                tenant_id=tenant_id,
            )
        else:
            health = self._health.calculate_health_score_from_configs(
                device_id=device.device_id,
                telemetry_values=telemetry_numeric,
                machine_state=_health_machine_state_from_live_state(load_state, RuntimeStatus.RUNNING.value),
                active_configs=active_health_configs,
            )
        state.health_score = health.get("health_score")
        if state.today_effective_seconds and state.today_effective_seconds > 0:
            state.uptime_percentage = max(
                0.0,
                min(100.0, (float(state.today_running_seconds or 0) / float(state.today_effective_seconds)) * 100.0),
            )

        state.runtime_status = RuntimeStatus.RUNNING.value
        state.load_state = load_state
        state.last_sample_ts = ts
        state.last_telemetry_ts = ts
        state.idle_streak_started_at = idle_streak_started_at
        state.idle_streak_duration_sec = idle_streak_duration_sec
        state.last_energy_kwh = Decimal(str(sample_energy_kwh)) if sample_energy_kwh is not None else state.last_energy_kwh
        updates = {
            "day_bucket": local_day,
            "month_bucket": month_bucket,
            "today_energy_kwh": Decimal(str(float(state.today_energy_kwh or 0))),
            "month_energy_kwh": Decimal(str(float(state.month_energy_kwh or 0))),
            "today_idle_kwh": Decimal(str(float(state.today_idle_kwh or 0))),
            "today_offhours_kwh": Decimal(str(float(state.today_offhours_kwh or 0))),
            "today_overconsumption_kwh": Decimal(str(float(state.today_overconsumption_kwh or 0))),
            "today_loss_kwh": Decimal(str(float(state.today_loss_kwh or 0))),
            "today_loss_cost_inr": Decimal(str(float(state.today_loss_cost_inr or 0))),
            "month_energy_cost_inr": Decimal(str(float(state.month_energy_cost_inr or 0))),
            "today_running_seconds": int(state.today_running_seconds or 0),
            "today_effective_seconds": int(state.today_effective_seconds or 0),
            "health_score": state.health_score,
            "uptime_percentage": state.uptime_percentage,
            "runtime_status": RuntimeStatus.RUNNING.value,
            "load_state": load_state,
            "last_sample_ts": ts,
            "last_telemetry_ts": ts,
            "idle_streak_started_at": idle_streak_started_at,
            "idle_streak_duration_sec": idle_streak_duration_sec,
            "last_energy_kwh": Decimal(str(sample_energy_kwh)) if sample_energy_kwh is not None else state.last_energy_kwh,
            "last_power_kw": Decimal(str(power_kw)),
            "last_current_a": Decimal(str(current_a)) if current_a is not None else None,
            "last_voltage_v": Decimal(str(voltage_v)) if voltage_v is not None else None,
        }

        if persistence_mode == "locked":
            for field, value in updates.items():
                setattr(state, field, value)
            state.version = int(state.version or 0) + 1
            state.updated_at = datetime.utcnow()
            await self._session.flush()
        else:
            success = await update_live_state_with_lock(self._session, device.device_id, tenant_id, updates)
            if not success:
                await self._session.rollback()
                if activation_should_write:
                    await self._devices.set_first_telemetry_timestamp_if_missing(
                        device_id=device.device_id,
                        tenant_id=device.tenant_id,
                        timestamp=ts,
                    )
                    await self._session.commit()
                self._session.expire_all()
                return await self.get_device_snapshot_item(device.device_id, tenant_id)
            for field, value in updates.items():
                setattr(state, field, value)
            state.version = int(state.version or 0) + 1
            state.updated_at = datetime.utcnow()

        if (
            last_sample_ts is None
            or previous_load_state != load_state
            or previous_current_band != current_band
        ):
            await self._sync_state_intervals(
                tenant_id=tenant_id,
                device_id=device.device_id,
                sample_ts=ts,
                load_state=load_state,
                current_band=current_band,
            )
        if activation_should_write:
            updated = await self._devices.set_first_telemetry_timestamp_if_missing(
                device_id=device.device_id,
                tenant_id=device.tenant_id,
                timestamp=ts,
            )
            if updated:
                device.first_telemetry_timestamp = ts
        device.last_seen_timestamp = ts
        return self._build_snapshot_item(device=device, state=state)

    async def apply_live_update(
        self,
        device_id: str,
        tenant_id: str,
        telemetry_payload: dict[str, Any],
        dynamic_fields: Optional[dict[str, Any]] = None,
        normalized_fields: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        query = (
            select(Device)
            .where(Device.device_id == device_id, Device.tenant_id == tenant_id, Device.deleted_at.is_(None))
            .options(selectinload(Device.shifts))
        )
        device = (await self._session.execute(query)).scalar_one_or_none()
        if device is None:
            raise ValueError(f"Device '{device_id}' not found")
        state = await self._get_or_create_state(device_id, tenant_id)
        item = await self._apply_live_update_loaded(
            device=device,
            state=state,
            tenant_id=tenant_id,
            telemetry_payload=telemetry_payload,
            dynamic_fields=dynamic_fields,
            normalized_fields=normalized_fields,
            persistence_mode="optimistic",
        )
        await self._session.commit()
        return item

    async def apply_live_updates_batch(
        self,
        *,
        tenant_id: str,
        updates: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if not updates:
            return [], []

        ordered_device_ids: list[str] = []
        seen: set[str] = set()
        for update in updates:
            device_id = str(update["device_id"])
            if device_id in seen:
                continue
            seen.add(device_id)
            ordered_device_ids.append(device_id)

        device_rows = await self._session.execute(
            select(Device)
            .where(
                Device.tenant_id == tenant_id,
                Device.deleted_at.is_(None),
                Device.device_id.in_(ordered_device_ids),
            )
            .options(selectinload(Device.shifts))
        )
        devices_by_id = {str(device.device_id): device for device in device_rows.scalars().all()}

        state_rows = await self._session.execute(
            select(DeviceLiveState)
            .where(
                DeviceLiveState.tenant_id == tenant_id,
                DeviceLiveState.device_id.in_(ordered_device_ids),
            )
            .with_for_update()
        )
        states_by_id = {str(state.device_id): state for state in state_rows.scalars().all()}

        for device_id in ordered_device_ids:
            if device_id in devices_by_id and device_id not in states_by_id:
                state = DeviceLiveState(
                    device_id=device_id,
                    tenant_id=tenant_id,
                    runtime_status=RuntimeStatus.STOPPED.value,
                    load_state="unknown",
                    version=0,
                )
                self._session.add(state)
                states_by_id[device_id] = state
        await self._session.flush()

        tariff = await TariffCache.get(tenant_id) or {}
        if not isinstance(tariff, dict):
            tariff = {}
        tariff_rate = float(tariff.get("rate") or 0.0)
        health_configs_by_device = await self._health.get_active_health_configs_by_devices(ordered_device_ids, tenant_id)

        results: list[dict[str, Any]] = []
        published_items_by_device: dict[str, dict[str, Any]] = {}
        processable_updates: list[tuple[dict[str, Any], Device, DeviceLiveState]] = []
        for update in updates:
            device_id = str(update["device_id"])
            device = devices_by_id.get(device_id)
            if device is None:
                results.append(
                    {
                        "device_id": device_id,
                        "success": False,
                        "error": f"Device {device_id} not found",
                        "error_code": "DEVICE_NOT_FOUND",
                        "retryable": False,
                    }
                )
                continue
            processable_updates.append((update, device, states_by_id[device_id]))

        async def _apply_single_with_savepoint(
            update: dict[str, Any],
            device: Device,
            state: DeviceLiveState,
        ) -> None:
            device_id = str(update["device_id"])
            try:
                async with self._session.begin_nested():
                    item = await self._apply_live_update_loaded(
                        device=device,
                        state=state,
                        tenant_id=tenant_id,
                        telemetry_payload=update["telemetry"],
                        dynamic_fields=update.get("dynamic_fields"),
                        normalized_fields=update.get("normalized_fields"),
                        persistence_mode="locked",
                        tariff_rate=tariff_rate,
                        active_health_configs=health_configs_by_device.get(device_id, []),
                    )
                published_items_by_device[device_id] = item
                results.append(
                    {
                        "device_id": device_id,
                        "success": True,
                        "device": item,
                        "retryable": False,
                    }
                )
            except InvalidDeviceMetadataError as exc:
                results.append(
                    {
                        "device_id": device_id,
                        "success": False,
                        "error": exc.message,
                        "error_code": "INVALID_DEVICE_METADATA",
                        "retryable": False,
                    }
                )
            except ValidationError as exc:
                results.append(
                    {
                        "device_id": device_id,
                        "success": False,
                        "error": "Stored device metadata violates the device response contract.",
                        "error_code": "INVALID_DEVICE_METADATA",
                        "details": exc.errors(),
                        "retryable": False,
                    }
                )
            except ValueError:
                results.append(
                    {
                        "device_id": device_id,
                        "success": False,
                        "error": f"Device {device_id} not found",
                        "error_code": "DEVICE_NOT_FOUND",
                        "retryable": False,
                    }
                )
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code if exc.response is not None else 503
                results.append(
                    {
                        "device_id": device_id,
                        "success": False,
                        "error": f"Projection dependency returned HTTP {status_code}",
                        "error_code": "PROJECTION_DEPENDENCY_HTTP_ERROR",
                        "retryable": status_code >= 500 or status_code in {408, 429},
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "device_id": device_id,
                        "success": False,
                        "error": str(exc),
                        "error_code": "PROJECTION_INTERNAL_ERROR",
                        "retryable": True,
                    }
                )

        chunk_size = max(1, int(settings.PROJECTION_BATCH_CHUNK_SIZE))
        for start in range(0, len(processable_updates), chunk_size):
            chunk = processable_updates[start:start + chunk_size]
            try:
                chunk_success: list[tuple[str, dict[str, Any]]] = []
                async with self._session.begin_nested():
                    for update, device, state in chunk:
                        item = await self._apply_live_update_loaded(
                            device=device,
                            state=state,
                            tenant_id=tenant_id,
                            telemetry_payload=update["telemetry"],
                            dynamic_fields=update.get("dynamic_fields"),
                            normalized_fields=update.get("normalized_fields"),
                            persistence_mode="locked",
                            tariff_rate=tariff_rate,
                            active_health_configs=health_configs_by_device.get(str(update["device_id"]), []),
                        )
                        chunk_success.append((str(update["device_id"]), item))
                for device_id, item in chunk_success:
                    published_items_by_device[device_id] = item
                    results.append(
                        {
                            "device_id": device_id,
                            "success": True,
                            "device": item,
                            "retryable": False,
                        }
                    )
            except Exception:
                # Fall back to per-item savepoint isolation when any row in the chunk fails.
                for update, device, state in chunk:
                    await _apply_single_with_savepoint(update, device, state)

        await self._session.commit()
        return results, list(published_items_by_device.values())

    async def _sync_state_intervals(
        self,
        *,
        tenant_id: str,
        device_id: str,
        sample_ts: datetime,
        load_state: str,
        current_band: str,
    ) -> None:
        await self._intervals.sync_interval_state(
            tenant_id=tenant_id,
            device_id=device_id,
            state_type=DeviceStateIntervalType.IDLE,
            is_active=load_state == DeviceStateIntervalType.IDLE.value,
            event_ts=sample_ts,
            sample_ts=sample_ts,
            opened_reason="load_state_idle",
            closed_reason="load_state_exit",
            source="live_projection",
        )
        await self._intervals.sync_interval_state(
            tenant_id=tenant_id,
            device_id=device_id,
            state_type=DeviceStateIntervalType.OVERCONSUMPTION,
            is_active=current_band == DeviceStateIntervalType.OVERCONSUMPTION.value,
            event_ts=sample_ts,
            sample_ts=sample_ts,
            opened_reason="current_band_overconsumption",
            closed_reason="current_band_exit",
            source="live_projection",
        )
        await self._intervals.sync_interval_state(
            tenant_id=tenant_id,
            device_id=device_id,
            state_type=DeviceStateIntervalType.RUNTIME_ON,
            is_active=True,
            event_ts=sample_ts,
            sample_ts=sample_ts,
            opened_reason="telemetry_running",
            source="live_projection",
        )

    async def recompute_after_configuration_change(self, device_id: str, tenant_id: str) -> dict[str, Any]:
        device = await self._session.get(Device, {"device_id": device_id, "tenant_id": tenant_id})
        if device is None:
            raise ValueError(f"Device '{device_id}' not found")
        state = await self._get_or_create_state(device_id, tenant_id)
        configs = await self._health.get_health_configs_by_device(device_id, tenant_id)
        active_configs = [cfg for cfg in configs if cfg.is_active]
        if not active_configs:
            # Deterministic clear when config is removed; never keep stale health.
            state.health_score = None
        else:
            latest: dict[str, Any] = {}
            try:
                latest = await self._fetch_latest_telemetry(device_id, tenant_id, timeout_sec=1.5)
            except Exception:
                latest = {}
            telemetry_numeric = HealthConfigService.extract_numeric_telemetry_values(latest)
            if telemetry_numeric:
                machine_state = _health_machine_state_for_recompute(
                    latest_telemetry=latest,
                    device=device,
                    persisted_load_state=state.load_state,
                    persisted_runtime_status=state.runtime_status,
                )
                health = await self._health.calculate_health_score(
                    device_id=device_id,
                    telemetry_values=telemetry_numeric,
                    machine_state=machine_state,
                    tenant_id=tenant_id,
                )
                state.health_score = health.get("health_score")
            else:
                # Avoid serving stale health when telemetry is temporarily unavailable.
                state.health_score = None
        uptime = await self._shift.calculate_uptime(device_id, tenant_id)
        state.uptime_percentage = uptime.get("uptime_percentage")
        success = await update_live_state_with_lock(
            self._session,
            device_id,
            tenant_id,
            {
                "health_score": state.health_score,
                "uptime_percentage": state.uptime_percentage,
            },
        )
        if not success:
            await self._session.rollback()
            self._session.expire_all()
            return await self.get_device_snapshot_item(device_id, tenant_id)
        await self._session.commit()
        self._session.expire_all()
        return await self.get_device_snapshot_item(device_id, tenant_id)

    async def remove_device_projection(self, device_id: str, tenant_id: str) -> None:
        await self._session.execute(
            delete(DeviceLiveState).where(
                DeviceLiveState.device_id == device_id,
                DeviceLiveState.tenant_id == tenant_id,
            )
        )
        await self._session.commit()

    async def reconcile_recent_projections(self, max_devices: int = 500) -> dict[str, Any]:
        """Best-effort drift repair by replaying latest telemetry if projection is behind."""
        query = select(DeviceLiveState).order_by(DeviceLiveState.updated_at.desc()).limit(max(1, max_devices))
        if self._ctx is not None and self._ctx.tenant_id is not None:
            query = query.where(DeviceLiveState.tenant_id == self._ctx.tenant_id)
        rows = (await self._session.execute(query)).scalars().all()

        scanned = 0
        repaired = 0
        repaired_device_ids: list[str] = []
        closed_intervals = 0
        timeout_closed_device_ids: list[str] = []
        for state in rows:
            scanned += 1
            try:
                latest = await self._fetch_latest_telemetry(state.device_id, state.tenant_id)
                if not latest:
                    latest_ts = None
                else:
                    latest_ts = self._parse_ts(latest.get("timestamp"))
                    state_last_sample = self._as_utc(state.last_sample_ts)
                    if state_last_sample is None or latest_ts > state_last_sample:
                        await self.apply_live_update(
                            device_id=state.device_id,
                            tenant_id=state.tenant_id,
                            telemetry_payload=latest,
                            dynamic_fields=latest,
                        )
                        repaired += 1
                        repaired_device_ids.append(state.device_id)
                timeout_summary = await self._reconcile_timed_out_intervals_for_device(
                    tenant_id=state.tenant_id,
                    device_id=state.device_id,
                    authoritative_last_seen=self._as_utc(state.last_telemetry_ts),
                )
                closed_intervals += int(timeout_summary.get("closed_intervals", 0))
                if int(timeout_summary.get("closed_intervals", 0)) > 0:
                    timeout_closed_device_ids.append(state.device_id)
            except Exception:
                continue

        if closed_intervals > 0:
            await self._session.commit()
        elif repaired == 0:
            await self._session.rollback()
        self._session.expire_all()
        return {
            "scanned": scanned,
            "repaired": repaired,
            "repaired_device_ids": repaired_device_ids,
            "closed_intervals": closed_intervals,
            "timeout_closed_device_ids": timeout_closed_device_ids,
        }

    async def reconcile_open_interval_timeouts(self, max_devices: int = 500) -> dict[str, Any]:
        """Close stale open intervals for devices that have timed out."""
        open_intervals = await self._interval_repo.list_open_intervals(
            tenant_id=self._ctx.tenant_id if self._ctx is not None else None,
            state_types=[
                DeviceStateIntervalType.RUNTIME_ON,
                DeviceStateIntervalType.IDLE,
                DeviceStateIntervalType.OVERCONSUMPTION,
            ],
        )

        device_keys: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for row in open_intervals:
            key = (row.tenant_id, row.device_id)
            if key in seen:
                continue
            seen.add(key)
            device_keys.append(key)
            if len(device_keys) >= max(1, max_devices):
                break

        closed_intervals = 0
        closed_device_ids: list[str] = []
        scanned = len(device_keys)
        for tenant_id, device_id in device_keys:
            state = await self._session.get(DeviceLiveState, {"device_id": device_id, "tenant_id": tenant_id})
            authoritative_last_seen = self._as_utc(state.last_telemetry_ts) if state is not None else None
            summary = await self._reconcile_timed_out_intervals_for_device(
                tenant_id=tenant_id,
                device_id=device_id,
                authoritative_last_seen=authoritative_last_seen,
            )
            closed_intervals += int(summary.get("closed_intervals", 0))
            if int(summary.get("closed_intervals", 0)) > 0:
                closed_device_ids.append(device_id)

        if closed_intervals > 0:
            await self._session.commit()
        else:
            await self._session.rollback()
        self._session.expire_all()
        return {
            "scanned": scanned,
            "closed_intervals": closed_intervals,
            "closed_device_ids": closed_device_ids,
        }

    async def _reconcile_timed_out_intervals_for_device(
        self,
        *,
        tenant_id: str,
        device_id: str,
        authoritative_last_seen: Optional[datetime],
        now_utc: Optional[datetime] = None,
    ) -> dict[str, Any]:
        timeout_ended_at = resolve_runtime_timeout_ended_at(authoritative_last_seen)
        if timeout_ended_at is None:
            return {"closed_intervals": 0}

        if resolve_runtime_status(authoritative_last_seen, now_utc=now_utc) != RuntimeStatus.STOPPED.value:
            return {"closed_intervals": 0}

        closed_rows = await self._intervals.reconcile_timeout_closure(
            tenant_id=tenant_id,
            device_id=device_id,
            ended_at=timeout_ended_at,
            sample_ts=timeout_ended_at,
            closed_reason="telemetry_timeout",
            source="timeout_reconciler",
        )
        persisted_state_updated = await self._persist_timed_out_live_state(
            tenant_id=tenant_id,
            device_id=device_id,
        )
        return {
            "closed_intervals": len(closed_rows),
            "persisted_state_updated": persisted_state_updated,
        }

    async def _persist_timed_out_live_state(
        self,
        *,
        tenant_id: str,
        device_id: str,
    ) -> bool:
        state = await self._get_or_create_state(device_id, tenant_id)
        desired_updates = {
            "runtime_status": RuntimeStatus.STOPPED.value,
            "load_state": "unknown",
            "idle_streak_started_at": None,
            "idle_streak_duration_sec": 0,
        }
        if (
            state.runtime_status == desired_updates["runtime_status"]
            and state.load_state == desired_updates["load_state"]
            and state.idle_streak_started_at is None
            and int(state.idle_streak_duration_sec or 0) == desired_updates["idle_streak_duration_sec"]
        ):
            return False

        success = await update_live_state_with_lock(
            self._session,
            device_id,
            tenant_id,
            desired_updates,
        )
        if success:
            state.runtime_status = desired_updates["runtime_status"]
            state.load_state = desired_updates["load_state"]
            state.idle_streak_started_at = desired_updates["idle_streak_started_at"]
            state.idle_streak_duration_sec = desired_updates["idle_streak_duration_sec"]
        return success

    async def backfill_first_telemetry_timestamps(self, max_devices: int = 500) -> dict[str, Any]:
        """Backfill immutable activation timestamps from historical telemetry."""
        query = (
            select(Device)
            .where(
                Device.deleted_at.is_(None),
                Device.first_telemetry_timestamp.is_(None),
            )
            .order_by(Device.created_at.asc(), Device.device_id.asc())
            .limit(max(1, max_devices))
        )
        if self._ctx is not None and self._ctx.tenant_id is not None:
            query = query.where(Device.tenant_id == self._ctx.tenant_id)

        rows = (await self._session.execute(query)).scalars().all()
        scanned = 0
        repaired = 0
        repaired_device_ids: list[str] = []

        for device in rows:
            scanned += 1
            try:
                first_sample = await self._fetch_earliest_telemetry(
                    device_id=device.device_id,
                    tenant_id=device.tenant_id,
                    start_time=self._as_utc(device.created_at) or device.created_at,
                )
                if not first_sample:
                    continue
                ts = self._parse_ts(first_sample.get("timestamp"))
                if ts is None:
                    continue
                if not self._activation_eligible(device, ts):
                    continue
                updated = await self._devices.set_first_telemetry_timestamp_if_missing(
                    device_id=device.device_id,
                    tenant_id=device.tenant_id,
                    timestamp=ts,
                )
                if updated:
                    repaired += 1
                    repaired_device_ids.append(device.device_id)
            except Exception:
                continue

        if repaired > 0:
            await self._session.commit()
        else:
            await self._session.rollback()
        self._session.expire_all()

        return {"scanned": scanned, "repaired": repaired, "repaired_device_ids": repaired_device_ids}

    async def _fetch_latest_telemetry(
        self,
        device_id: str,
        tenant_id: str,
        timeout_sec: float = 5.0,
    ) -> dict[str, Any]:
        url = f"{settings.DATA_SERVICE_BASE_URL}/api/v1/data/telemetry/{device_id}"
        async with httpx.AsyncClient(timeout=max(0.5, timeout_sec)) as client:
            resp = await client.get(
                url,
                params={"limit": "1"},
                headers=build_internal_headers("device-service", tenant_id),
            )
            resp.raise_for_status()
            payload = resp.json()
        items = payload.get("data", {}).get("items", []) if isinstance(payload, dict) else []
        if not items:
            return {}
        return items[0]

    async def _fetch_earliest_telemetry(
        self,
        device_id: str,
        tenant_id: str,
        *,
        start_time: datetime,
        timeout_sec: float = 10.0,
    ) -> dict[str, Any]:
        url = f"{settings.DATA_SERVICE_BASE_URL}/api/v1/data/telemetry/{device_id}/earliest"
        async with httpx.AsyncClient(timeout=max(0.5, timeout_sec)) as client:
            resp = await client.get(
                url,
                params={"start_time": start_time.isoformat()},
                headers=build_internal_headers("device-service", tenant_id),
            )
            resp.raise_for_status()
            payload = resp.json()
        item = payload.get("data", {}).get("item", {}) if isinstance(payload, dict) else {}
        return item if isinstance(item, dict) else {}

    async def _fetch_telemetry_window(
        self,
        device_id: str,
        tenant_id: str,
        *,
        start_time: datetime,
        end_time: datetime,
        limit: int = 10000,
        timeout_sec: float = 10.0,
    ) -> list[dict[str, Any]]:
        url = f"{settings.DATA_SERVICE_BASE_URL}/api/v1/data/telemetry/{device_id}"
        async with httpx.AsyncClient(timeout=max(0.5, timeout_sec)) as client:
            resp = await client.get(
                url,
                params={
                    "start_time": start_time.isoformat(),
                    "end_time": end_time.isoformat(),
                    "limit": str(limit),
                },
                headers=build_internal_headers("device-service", tenant_id),
            )
            resp.raise_for_status()
            payload = resp.json()
        items = payload.get("data", {}).get("items", []) if isinstance(payload, dict) else []
        return items if isinstance(items, list) else []

    async def recompute_today_loss_projection(self, device_id: str, tenant_id: str) -> dict[str, Any]:
        query = (
            select(Device)
            .where(Device.device_id == device_id, Device.tenant_id == tenant_id, Device.deleted_at.is_(None))
            .options(selectinload(Device.shifts))
        )
        device = (await self._session.execute(query)).scalar_one_or_none()
        if device is None:
            raise ValueError(f"Device '{device_id}' not found")

        state = await self._get_or_create_state(device_id, tenant_id)
        now_utc = datetime.now(timezone.utc)
        local_tz = _get_platform_tz()
        local_day = now_utc.astimezone(local_tz).date()
        day_start_local = datetime.combine(local_day, time.min, tzinfo=local_tz)
        day_start_utc = day_start_local.astimezone(timezone.utc)

        rows = await self._fetch_telemetry_window(
            device_id,
            tenant_id,
            start_time=day_start_utc,
            end_time=now_utc,
        )
        accounting = aggregate_window(
            rows,
            platform_tz=local_tz,
            shifts=[shift for shift in (device.shifts or []) if shift.is_active],
            idle_threshold=resolve_device_thresholds(device).derived_idle_threshold_a,
            over_threshold=resolve_device_thresholds(device).derived_overconsumption_threshold_a,
            config_source=device,
        )

        today_energy = float(accounting.total.energy_kwh)
        today_idle = float(accounting.total.idle_kwh)
        today_offhours = float(accounting.total.offhours_kwh)
        today_over = float(accounting.total.overconsumption_kwh)
        today_loss = float(accounting.total.total_loss_kwh)

        tariff = await TariffCache.get(tenant_id) or {}
        if not isinstance(tariff, dict):
            tariff = {}
        rate = float(tariff.get("rate") or 0.0)
        updates = {
            "day_bucket": local_day,
            "today_energy_kwh": Decimal(str(round(today_energy, 6))),
            "today_idle_kwh": Decimal(str(round(today_idle, 6))),
            "today_offhours_kwh": Decimal(str(round(today_offhours, 6))),
            "today_overconsumption_kwh": Decimal(str(round(today_over, 6))),
            "today_loss_kwh": Decimal(str(round(today_loss, 6))),
            "today_loss_cost_inr": Decimal(str(round(today_loss * rate, 4))),
        }
        success = await update_live_state_with_lock(self._session, device_id, tenant_id, updates)
        if not success:
            await self._session.rollback()
            self._session.expire_all()
            return await self.get_device_snapshot_item(device_id, tenant_id)

        await self._session.commit()
        self._session.expire_all()
        return await self.get_device_snapshot_item(device_id, tenant_id)

    async def get_device_snapshot_item(self, device_id: str, tenant_id: str) -> dict[str, Any]:
        row = (
            await self._session.execute(
                select(Device, DeviceLiveState)
                .outerjoin(
                    DeviceLiveState,
                    (DeviceLiveState.device_id == Device.device_id)
                    & (DeviceLiveState.tenant_id == Device.tenant_id),
                )
                .options(selectinload(Device.shifts))
                .where(
                    Device.device_id == device_id,
                    Device.tenant_id == tenant_id,
                    Device.deleted_at.is_(None),
                )
            )
        ).first()
        if row is None:
            raise ValueError(f"Device '{device_id}' not found")
        device, state = row
        self._normalize_device_metadata(device)
        state = state or DeviceLiveState(
            device_id=device.device_id,
            tenant_id=device.tenant_id,
            runtime_status=RuntimeStatus.STOPPED.value,
            load_state="unknown",
            version=0,
        )
        return self._build_snapshot_item(device=device, state=state)
