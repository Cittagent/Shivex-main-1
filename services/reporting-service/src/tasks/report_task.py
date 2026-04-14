import logging
import traceback
import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from src.config import settings
from src.database import AsyncSessionLocal
from src.repositories.report_repository import ReportRepository
from src.services.influx_reader import influx_reader
from src.services.overtime_engine import compute_overtime_breakdown
from src.services.report_engine import compute_device_report
from src.services.insights_engine import generate_report_insights
from src.services.tariff_resolver import resolve_tariff
from src.services.tenant_scope import build_service_tenant_context
from src.services import (
    calculate_energy,
    calculate_demand,
)
from src.pdf.builder import generate_consumption_pdf, generate_comparison_pdf
from src.storage.minio_client import minio_client
from src.utils.serialization import clean_for_json, extract_engine_data
from services.shared.telemetry_normalization import NORMALIZATION_VERSION


logger = logging.getLogger(__name__)
INTERNAL_HEADERS = {"X-Internal-Service": "reporting-service"}
REPORT_KPI_DURATION_BASIS = "report_window_hours"
KPI_BASIS_NORMALIZED_TELEMETRY = "normalized_telemetry"
KPI_BASIS_CANONICAL_ENERGY = "canonical_energy_overlay"
KPI_BASIS_MIXED = "mixed_device_bases"
AGGREGATE_DEMAND_BASIS_COMPLETE = "complete"
AGGREGATE_DEMAND_BASIS_INCOMPLETE = "incomplete"
INTERNAL_WARNING_MARKERS = {"canonical_energy_projection_applied"}


@dataclass(frozen=True)
class PersistedKpiBlock:
    basis: str
    duration_basis: str
    total_kwh: float | None
    peak_demand_kw: float | None
    peak_timestamp: str | None
    average_load_kw: float | None
    load_factor_pct: float | None
    load_factor_band: str | None


def is_error(result: dict) -> bool:
    return isinstance(result, dict) and result.get("success") is False


def _warning_is_internal(warning: str) -> bool:
    if not isinstance(warning, str):
        return False
    normalized = warning.strip()
    if not normalized:
        return False
    if normalized.startswith("PHASE-TESTING:"):
        normalized = normalized.split(":", 1)[1].strip()
    if ":" in normalized:
        normalized = normalized.split(":", 1)[-1].strip()
    return normalized in INTERNAL_WARNING_MARKERS


def _public_warnings(warnings: list[str]) -> list[str]:
    return [warning for warning in warnings if not _warning_is_internal(warning)]


def _public_device_payload(device: dict[str, Any]) -> dict[str, Any]:
    public_device = dict(device)
    public_device["warnings"] = _public_warnings(list(device.get("warnings", [])))
    return public_device


async def _fetch_canonical_energy_range(
    client: httpx.AsyncClient,
    device_id: str,
    start_date,
    end_date,
    tenant_id: str | None,
) -> dict | None:
    try:
        headers = {**INTERNAL_HEADERS, **({"X-Tenant-Id": tenant_id} if tenant_id else {})}
        resp = await client.get(
            f"{settings.ENERGY_SERVICE_URL}/api/v1/energy/device/{device_id}/range",
            params={"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
            headers=headers,
        )
        if resp.status_code != 200:
            return None
        payload = resp.json()
        if not isinstance(payload, dict) or not payload.get("success"):
            return None
        return payload
    except Exception:
        return None


def _overlay_canonical_energy_totals(
    energy_result: dict[str, Any],
    canonical_range: dict[str, Any] | None,
) -> dict[str, Any]:
    if (
        not canonical_range
        or not isinstance(canonical_range, dict)
        or not canonical_range.get("success")
        or not isinstance(energy_result.get("data"), dict)
    ):
        return energy_result

    totals = canonical_range.get("totals") or {}
    days = canonical_range.get("days") or []
    total_kwh = totals.get("energy_kwh")
    if not isinstance(total_kwh, (int, float)):
        return energy_result

    data = dict(energy_result["data"])
    data["total_kwh"] = round(float(total_kwh), 4)
    data["total_wh"] = round(float(total_kwh) * 1000.0, 2)
    daily_kwh: dict[str, float] = {}
    if isinstance(days, list):
        for row in days:
            if not isinstance(row, dict):
                continue
            day = row.get("date")
            day_energy = row.get("energy_kwh")
            if isinstance(day, str) and isinstance(day_energy, (int, float)):
                daily_kwh[day] = round(float(day_energy), 4)
    if daily_kwh:
        data["daily_kwh"] = daily_kwh

    updated = dict(energy_result)
    updated["data"] = data
    return updated


def _load_factor_band(load_factor_pct: float | None) -> str | None:
    if load_factor_pct is None:
        return None
    if load_factor_pct < 30:
        return "poor"
    if load_factor_pct <= 70:
        return "moderate"
    return "good"


def _report_window_hours(start_dt: datetime, end_dt: datetime) -> float:
    return float(max((end_dt - start_dt).total_seconds() / 3600.0, 0.0))


def _canonical_peak_snapshot(canonical_range: dict[str, Any] | None) -> tuple[float | None, str | None]:
    if not canonical_range or not isinstance(canonical_range, dict) or not canonical_range.get("success"):
        return None, None
    totals = canonical_range.get("totals") or {}
    peak_demand_kw = totals.get("peak_demand_kw")
    peak_timestamp = totals.get("peak_demand_timestamp")
    if not isinstance(peak_demand_kw, (int, float)) or float(peak_demand_kw) <= 0.0:
        return None, None
    return float(peak_demand_kw), peak_timestamp if isinstance(peak_timestamp, str) and peak_timestamp else None


def _build_persisted_kpi_block(
    *,
    basis: str,
    total_kwh: float | None,
    duration_hours: float,
    peak_demand_kw: float | None,
    peak_timestamp: str | None = None,
) -> PersistedKpiBlock:
    normalized_total = round(float(total_kwh), 4) if isinstance(total_kwh, (int, float)) else None
    normalized_peak = (
        round(float(peak_demand_kw), 4)
        if isinstance(peak_demand_kw, (int, float)) and float(peak_demand_kw) > 0.0
        else None
    )
    normalized_peak_timestamp = peak_timestamp if normalized_peak is not None else None

    if normalized_total is None:
        return PersistedKpiBlock(
            basis=basis,
            duration_basis=REPORT_KPI_DURATION_BASIS,
            total_kwh=None,
            peak_demand_kw=normalized_peak,
            peak_timestamp=normalized_peak_timestamp,
            average_load_kw=None,
            load_factor_pct=None,
            load_factor_band=None,
        )

    # A persisted demand/load-factor block is only valid when energy and demand
    # are sourced from the same basis and the report-window duration is known.
    if normalized_peak is None or duration_hours <= 0.0:
        return PersistedKpiBlock(
            basis=basis,
            duration_basis=REPORT_KPI_DURATION_BASIS,
            total_kwh=normalized_total,
            peak_demand_kw=normalized_peak,
            peak_timestamp=normalized_peak_timestamp,
            average_load_kw=None,
            load_factor_pct=None,
            load_factor_band=None,
        )

    average_load_kw = round(normalized_total / duration_hours, 4)
    load_factor_pct = round((average_load_kw / normalized_peak) * 100.0, 2)
    return PersistedKpiBlock(
        basis=basis,
        duration_basis=REPORT_KPI_DURATION_BASIS,
        total_kwh=normalized_total,
        peak_demand_kw=normalized_peak,
        peak_timestamp=normalized_peak_timestamp,
        average_load_kw=average_load_kw,
        load_factor_pct=load_factor_pct,
        load_factor_band=_load_factor_band(load_factor_pct),
    )


def _merge_overlay_kpi_blocks(
    *,
    telemetry_kpi: PersistedKpiBlock,
    canonical_range: dict[str, Any] | None,
    duration_hours: float,
) -> PersistedKpiBlock:
    if not _canonical_energy_basis_is_trustworthy(canonical_range):
        return telemetry_kpi

    canonical_total = _canonical_total_kwh(canonical_range)
    if canonical_total is None:
        return telemetry_kpi

    canonical_peak_kw, canonical_peak_timestamp = _canonical_peak_snapshot(canonical_range)
    if canonical_peak_kw is not None:
        return _build_persisted_kpi_block(
            basis=KPI_BASIS_CANONICAL_ENERGY,
            total_kwh=canonical_total,
            duration_hours=duration_hours,
            peak_demand_kw=canonical_peak_kw,
            peak_timestamp=canonical_peak_timestamp,
        )

    if telemetry_kpi.peak_demand_kw is not None:
        return _build_persisted_kpi_block(
            basis=KPI_BASIS_MIXED,
            total_kwh=canonical_total,
            duration_hours=duration_hours,
            peak_demand_kw=telemetry_kpi.peak_demand_kw,
            peak_timestamp=telemetry_kpi.peak_timestamp,
        )

    return _build_persisted_kpi_block(
        basis=KPI_BASIS_CANONICAL_ENERGY,
        total_kwh=canonical_total,
        duration_hours=duration_hours,
        peak_demand_kw=None,
        peak_timestamp=None,
    )


def _resolve_summary_kpi_basis(per_device: list[dict[str, Any]]) -> str:
    bases = {
        str(device.get("kpi_basis") or KPI_BASIS_NORMALIZED_TELEMETRY)
        for device in per_device
        if device.get("total_kwh") is not None
    }
    if not bases:
        return KPI_BASIS_NORMALIZED_TELEMETRY
    if len(bases) == 1:
        return next(iter(bases))
    return KPI_BASIS_MIXED


def _build_summary_kpi_block(
    *,
    per_device: list[dict[str, Any]],
    total_kwh: float,
    duration_hours: float,
) -> PersistedKpiBlock:
    basis = _resolve_summary_kpi_basis(per_device)
    contributing_devices = [
        device
        for device in per_device
        if isinstance(device.get("total_kwh"), (int, float)) and float(device.get("total_kwh") or 0.0) > 0.0
    ]
    if any(
        not isinstance(device.get("peak_demand_kw"), (int, float)) or float(device.get("peak_demand_kw") or 0.0) <= 0.0
        for device in contributing_devices
    ):
        return _build_persisted_kpi_block(
            basis=basis,
            total_kwh=total_kwh,
            duration_hours=duration_hours,
            peak_demand_kw=None,
            peak_timestamp=None,
        )

    peak_candidates = [
        d
        for d in per_device
        if isinstance(d.get("peak_demand_kw"), (int, float))
        and float(d.get("peak_demand_kw") or 0.0) > 0.0
    ]
    peak_demand_kw = None
    peak_timestamp = None
    if peak_candidates:
        peak_row = max(peak_candidates, key=lambda d: float(d.get("peak_demand_kw") or 0.0))
        peak_demand_kw = peak_row.get("peak_demand_kw")
        peak_timestamp = peak_row.get("peak_timestamp")

    return _build_persisted_kpi_block(
        basis=basis,
        total_kwh=total_kwh,
        duration_hours=duration_hours,
        peak_demand_kw=peak_demand_kw,
        peak_timestamp=peak_timestamp,
    )


def _summary_aggregate_demand_basis(per_device: list[dict[str, Any]]) -> str:
    contributing_devices = [
        device
        for device in per_device
        if isinstance(device.get("total_kwh"), (int, float)) and float(device.get("total_kwh") or 0.0) > 0.0
    ]
    if any(
        not isinstance(device.get("peak_demand_kw"), (int, float)) or float(device.get("peak_demand_kw") or 0.0) <= 0.0
        for device in contributing_devices
    ):
        return AGGREGATE_DEMAND_BASIS_INCOMPLETE
    return AGGREGATE_DEMAND_BASIS_COMPLETE


def _canonical_total_kwh(canonical_range: dict[str, Any] | None) -> float | None:
    if not canonical_range or not isinstance(canonical_range, dict) or not canonical_range.get("success"):
        return None
    totals = canonical_range.get("totals") or {}
    total_kwh = totals.get("energy_kwh")
    if not isinstance(total_kwh, (int, float)):
        return None
    return float(total_kwh)


def _canonical_energy_basis_is_trustworthy(canonical_range: dict[str, Any] | None) -> bool:
    if not canonical_range or not isinstance(canonical_range, dict) or not canonical_range.get("success"):
        return False

    totals = canonical_range.get("totals") or {}
    for key in ("energy_kwh", "loss_kwh", "idle_kwh", "offhours_kwh", "overconsumption_kwh"):
        value = totals.get(key)
        if isinstance(value, (int, float)) and float(value) > 0.0:
            return True

    peak_kw, _ = _canonical_peak_snapshot(canonical_range)
    if peak_kw is not None:
        return True

    for day in canonical_range.get("days") or []:
        if not isinstance(day, dict):
            continue
        if int(day.get("version") or 0) > 0:
            return True
        for key in ("energy_kwh", "loss_kwh", "idle_kwh", "offhours_kwh", "overconsumption_kwh"):
            value = day.get(key)
            if isinstance(value, (int, float)) and float(value) > 0.0:
                return True

    return False


def _overlay_comparison_energy_metrics(
    comparison_result: dict[str, Any],
    canonical_range_a: dict[str, Any] | None,
    canonical_range_b: dict[str, Any] | None,
    device_name_a: str,
    device_name_b: str,
) -> dict[str, Any]:
    if not comparison_result.get("success"):
        return comparison_result

    kwh_a = _canonical_total_kwh(canonical_range_a)
    kwh_b = _canonical_total_kwh(canonical_range_b)
    if kwh_a is None or kwh_b is None:
        return comparison_result

    diff_kwh = kwh_a - kwh_b
    pct_diff = (diff_kwh / kwh_b * 100.0) if kwh_b > 0 else 0.0
    higher_consumer = device_name_a if diff_kwh > 0 else device_name_b

    updated = dict(comparison_result)
    data = dict(updated.get("data") or {})
    metrics = dict(data.get("metrics") or {})
    metrics["energy_comparison"] = {
        "device_a_kwh": round(kwh_a, 2),
        "device_b_kwh": round(kwh_b, 2),
        "difference_kwh": round(diff_kwh, 2),
        "difference_percent": round(pct_diff, 2),
        "higher_consumer": higher_consumer,
    }

    insights: list[str] = []
    existing = data.get("insights")
    if isinstance(existing, list):
        insights = [item for item in existing if isinstance(item, str)]
    if insights:
        if diff_kwh > 0:
            insights[0] = f"{device_name_a} consumed {abs(diff_kwh):.1f} kWh more than {device_name_b}"
        elif diff_kwh < 0:
            insights[0] = f"{device_name_b} consumed {abs(diff_kwh):.1f} kWh more than {device_name_a}"
        else:
            insights[0] = f"{device_name_a} and {device_name_b} consumed equal energy"

    data["metrics"] = metrics
    data["insights"] = insights
    updated["data"] = data
    return updated


async def _fetch_shift_config(
    client: httpx.AsyncClient,
    device_id: str,
    tenant_id: str | None,
) -> list[dict[str, Any]]:
    try:
        headers = {**INTERNAL_HEADERS, **({"X-Tenant-Id": tenant_id} if tenant_id else {})}
        resp = await client.get(
            f"{settings.DEVICE_SERVICE_URL}/api/v1/devices/{device_id}/shifts",
            headers=headers,
        )
        if resp.status_code != 200:
            return []
        payload = resp.json()
        if isinstance(payload, dict):
            data = payload.get("data", [])
            return data if isinstance(data, list) else []
        return payload if isinstance(payload, list) else []
    except Exception:
        return []


def _apply_canonical_offhours(
    overtime_dict: dict[str, Any],
    canonical: dict[str, Any],
    tariff_rate: float | None,
    currency: str,
) -> dict[str, Any]:
    totals = canonical.get("totals") or {}
    days = canonical.get("days") or []

    offhours_total = totals.get("offhours_kwh")
    if isinstance(offhours_total, (int, float)):
        overtime_dict["total_overtime_kwh"] = round(float(offhours_total), 4)
        overtime_dict["total_overtime_cost"] = (
            round(float(offhours_total) * tariff_rate, 2) if tariff_rate is not None else None
        )

    minute_map = {
        str(row.get("date") or ""): {
            "minutes": float(row.get("overtime_minutes") or 0.0),
            "hours": float(row.get("overtime_hours") or 0.0),
        }
        for row in overtime_dict.get("daily_breakdown", []) or []
    }
    windows_by_day: dict[str, list[dict[str, Any]]] = {}
    for row in overtime_dict.get("window_breakdown", []) or []:
        day_key = str(row.get("date") or "")
        if not day_key:
            continue
        windows_by_day.setdefault(day_key, []).append(row)

    merged_breakdown: list[dict[str, Any]] = []
    seen_dates: set[str] = set()
    for item in days:
        day_key = str(item.get("date") or "")
        if not day_key:
            continue
        offhours_kwh = item.get("offhours_kwh")
        if not isinstance(offhours_kwh, (int, float)):
            continue
        metrics = minute_map.get(day_key, {"minutes": 0.0, "hours": 0.0})
        merged_breakdown.append(
            {
                "date": day_key,
                "overtime_minutes": round(metrics["minutes"], 2),
                "overtime_hours": round(metrics["hours"], 4),
                "overtime_kwh": round(float(offhours_kwh), 4),
                "overtime_cost": round(float(offhours_kwh) * tariff_rate, 2) if tariff_rate is not None else None,
            }
        )
        seen_dates.add(day_key)

    for row in overtime_dict.get("daily_breakdown", []) or []:
        day_key = str(row.get("date") or "")
        if not day_key or day_key in seen_dates:
            continue
        merged_breakdown.append(
            {
                "date": day_key,
                "overtime_minutes": round(float(row.get("overtime_minutes") or 0.0), 2),
                "overtime_hours": round(float(row.get("overtime_hours") or 0.0), 4),
                "overtime_kwh": 0.0,
                "overtime_cost": 0.0 if tariff_rate is not None else None,
            }
        )

    canonical_day_kwh = {
        str(item.get("date") or ""): float(item.get("offhours_kwh") or 0.0)
        for item in days
        if str(item.get("date") or "")
    }
    merged_windows: list[dict[str, Any]] = []
    for day_key in sorted(windows_by_day.keys()):
        day_windows = windows_by_day[day_key]
        canonical_kwh = canonical_day_kwh.get(day_key, 0.0)
        measured_kwh = sum(float(row.get("overtime_kwh") or 0.0) for row in day_windows)
        total_minutes = sum(float(row.get("overtime_minutes") or 0.0) for row in day_windows)
        assigned_kwh = 0.0

        for index, row in enumerate(day_windows):
            is_last = index == len(day_windows) - 1
            row_minutes = float(row.get("overtime_minutes") or 0.0)
            row_measured_kwh = float(row.get("overtime_kwh") or 0.0)

            if canonical_kwh <= 0.0:
                window_kwh = 0.0
            elif is_last:
                window_kwh = max(0.0, canonical_kwh - assigned_kwh)
            elif measured_kwh > 0.0:
                window_kwh = canonical_kwh * (row_measured_kwh / measured_kwh)
            elif total_minutes > 0.0:
                window_kwh = canonical_kwh * (row_minutes / total_minutes)
            else:
                window_kwh = 0.0

            assigned_kwh += window_kwh
            merged_windows.append(
                {
                    **row,
                    "overtime_kwh": round(window_kwh, 4),
                    "overtime_cost": round(window_kwh * tariff_rate, 2) if tariff_rate is not None else None,
                    "shift_status": row.get("shift_status") or "Overtime",
                }
            )

    overtime_dict["daily_breakdown"] = sorted(merged_breakdown, key=lambda row: str(row.get("date") or ""))
    overtime_dict["window_breakdown"] = merged_windows
    overtime_dict["currency"] = currency
    overtime_dict["tariff_rate_used"] = tariff_rate
    return overtime_dict


async def run_consumption_report(report_id: str, params: dict) -> None:
    async with AsyncSessionLocal() as db:
        tenant_id = params.get("tenant_id")
        if not tenant_id:
            repo = ReportRepository(db)
            await repo.update_report(
                report_id,
                status="failed",
                error_code="MISSING_TENANT_ID",
                error_message="Tenant scope is required",
            )
            return

        tenant_ctx = build_service_tenant_context(tenant_id)
        repo = ReportRepository(db, ctx=tenant_ctx)
        
        try:
            await repo.update_report(report_id, status="processing", progress=5)
            start_date_str = params.get("start_date")
            end_date_str = params.get("end_date")
            request_device_id = params.get("device_id")
            resolved_device_ids = params.get("resolved_device_ids", [])

            if isinstance(start_date_str, str):
                start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            else:
                start_date = start_date_str

            if isinstance(end_date_str, str):
                end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
            else:
                end_date = end_date_str

            if not start_date or not end_date:
                await repo.update_report(
                    report_id,
                    status="failed",
                    error_code="INVALID_PARAMS",
                    error_message="Missing required start_date/end_date"
                )
                return

            async with httpx.AsyncClient(timeout=30.0) as client:
                headers = {**INTERNAL_HEADERS, **({"X-Tenant-Id": tenant_id} if tenant_id else {})}
                if resolved_device_ids:
                    device_ids = [str(x) for x in resolved_device_ids]
                elif isinstance(request_device_id, str) and request_device_id.upper() == "ALL":
                    resp = await client.get(
                        f"{settings.DEVICE_SERVICE_URL}/api/v1/devices",
                        headers=headers,
                    )
                    payload = resp.json() if resp.status_code == 200 else {}
                    items = payload if isinstance(payload, list) else payload.get("data", [])
                    device_ids = [d.get("device_id") for d in items if d.get("device_id")]
                elif isinstance(request_device_id, str) and request_device_id.strip():
                    device_ids = [request_device_id.strip()]
                else:
                    # Scheduler/backward internal params support
                    device_ids = [d for d in params.get("device_ids", []) if d]

                if not device_ids:
                    await repo.update_report(
                        report_id,
                        status="failed",
                        error_code="NO_VALID_DEVICES",
                        error_message="No devices available for report generation",
                    )
                    return

                await repo.update_report(report_id, progress=15)

                start_dt = datetime.combine(start_date, datetime.min.time())
                end_dt = datetime.combine(end_date, datetime.max.time())

                await repo.update_report(report_id, progress=20)

                all_warnings: list[str] = []
                report_window_hours = _report_window_hours(start_dt, end_dt)

                resolved_tariff = await resolve_tariff(db, tenant_id)
                tariff_rate_used = resolved_tariff.rate
                tariff_currency = resolved_tariff.currency
                tariff_fetched_at = resolved_tariff.fetched_at

                if tariff_rate_used is None:
                    all_warnings.append("Tariff not configured — cost calculations skipped")

                fields = [
                    "energy_kwh",
                    "active_power",
                    "power",
                    "current",
                    "voltage",
                    "power_factor",
                    "frequency",
                    "kvar",
                    "reactive_power",
                    "run_hours",
                ]

                per_device: list[dict[str, Any]] = []

                for idx, device_id in enumerate(device_ids):
                    device_resp = await client.get(
                        f"{settings.DEVICE_SERVICE_URL}/api/v1/devices/{device_id}",
                        headers=headers,
                    )
                    if device_resp.status_code != 200:
                        per_device.append(
                            {
                                "device_id": device_id,
                                "device_name": device_id,
                                "data_source_type": "metered",
                                "quality": "insufficient",
                                "method": "device_not_found",
                                "error": f"Device lookup failed: {device_id}",
                                "warnings": [],
                                "total_kwh": None,
                                "peak_demand_kw": None,
                                "peak_timestamp": None,
                                "average_load_kw": None,
                                "load_factor_pct": None,
                                "load_factor_band": None,
                                "total_hours": 0.0,
                                "daily_breakdown": [],
                                "availability": {},
                                "power_factor": None,
                                "reactive": None,
                            }
                        )
                        continue

                    device_payload = device_resp.json()
                    device_data = device_payload.get("data", {}) if isinstance(device_payload, dict) else {}
                    device_name = device_data.get("device_name", device_id)
                    data_source_type = str(device_data.get("data_source_type") or "metered")
                    device_power_config = {
                        "energy_flow_mode": device_data.get("energy_flow_mode") or "consumption_only",
                        "polarity_mode": device_data.get("polarity_mode") or "normal",
                    }
                    shift_config = await _fetch_shift_config(client, device_id, tenant_id)

                    rows = await influx_reader.query_telemetry(
                        device_id=device_id,
                        start_dt=start_dt,
                        end_dt=end_dt,
                        fields=fields,
                    )
                    device_result = compute_device_report(
                        rows=rows,
                        device_id=device_id,
                        device_name=device_name,
                        data_source_type=data_source_type,
                        device_power_config=device_power_config,
                    )
                    device_dict = clean_for_json(device_result.__dict__)
                    telemetry_kpi = _build_persisted_kpi_block(
                        basis=KPI_BASIS_NORMALIZED_TELEMETRY,
                        total_kwh=device_dict.get("total_kwh"),
                        duration_hours=report_window_hours,
                        peak_demand_kw=device_dict.get("peak_demand_kw"),
                        peak_timestamp=device_dict.get("peak_timestamp"),
                    )
                    overtime_result = compute_overtime_breakdown(
                        rows=rows,
                        shifts=shift_config,
                        tariff_rate=tariff_rate_used,
                        currency=tariff_currency,
                    )
                    overtime_dict = clean_for_json(overtime_result.__dict__)

                    canonical = await _fetch_canonical_energy_range(
                        client=client,
                        device_id=device_id,
                        start_date=start_date,
                        end_date=end_date,
                        tenant_id=tenant_id,
                    )
                    persisted_kpi = _merge_overlay_kpi_blocks(
                        telemetry_kpi=telemetry_kpi,
                        canonical_range=canonical,
                        duration_hours=report_window_hours,
                    )
                    if canonical:
                        day_cost_map: dict[str, float] = {}
                        day_kwh_map: dict[str, float] = {}
                        for item in canonical.get("days") or []:
                            day_key = str(item.get("date") or "")
                            if not day_key:
                                continue
                            kwh_val = item.get("energy_kwh")
                            cost_val = item.get("energy_cost_inr")
                            if isinstance(kwh_val, (int, float)):
                                day_kwh_map[day_key] = float(kwh_val)
                            if isinstance(cost_val, (int, float)):
                                day_cost_map[day_key] = float(cost_val)

                        merged_days = []
                        for day in device_dict.get("daily_breakdown", []) or []:
                            day_key = str(day.get("date") or "")
                            if day_key in day_kwh_map:
                                day["energy_kwh"] = round(day_kwh_map[day_key], 4)
                            if day_key in day_cost_map:
                                day["cost"] = round(day_cost_map[day_key], 2)
                            merged_days.append(day)
                        device_dict["daily_breakdown"] = merged_days

                        overtime_dict = _apply_canonical_offhours(
                            overtime_dict=overtime_dict,
                            canonical=canonical,
                            tariff_rate=tariff_rate_used,
                            currency=tariff_currency,
                        )
                        # Canonical energy overlay is internal reporting metadata only.
                        # It should not be promoted into customer-facing warnings.

                    device_dict["kpi_basis"] = persisted_kpi.basis
                    device_dict["average_load_duration_basis"] = persisted_kpi.duration_basis
                    device_dict["total_kwh"] = persisted_kpi.total_kwh
                    device_dict["peak_demand_kw"] = persisted_kpi.peak_demand_kw
                    device_dict["peak_timestamp"] = persisted_kpi.peak_timestamp
                    device_dict["average_load_kw"] = persisted_kpi.average_load_kw
                    device_dict["load_factor_pct"] = persisted_kpi.load_factor_pct
                    device_dict["load_factor_band"] = persisted_kpi.load_factor_band

                    device_dict["overtime_breakdown"] = overtime_dict.get("daily_breakdown", [])
                    device_dict["overtime_summary"] = overtime_dict
                    device_dict["overtime"] = overtime_dict
                    for w in device_result.warnings:
                        all_warnings.append(f"{device_name}: {w}")
                    if device_result.error:
                        all_warnings.append(f"{device_name}: {device_result.error}")
                    for w in overtime_result.warnings:
                        all_warnings.append(f"{device_name}: {w}")
                    per_device.append(device_dict)

                    progress = 15 + int(((idx + 1) / max(len(device_ids), 1)) * 45)
                    await repo.update_report(report_id, progress=min(progress, 60))

                total_kwh = round(
                    sum(float(d.get("total_kwh") or 0.0) for d in per_device if d.get("total_kwh") is not None),
                    4,
                )

                summary_kpi = _build_summary_kpi_block(
                    per_device=per_device,
                    total_kwh=total_kwh,
                    duration_hours=report_window_hours,
                )
                aggregate_demand_basis = _summary_aggregate_demand_basis(per_device)
                peak_demand_kw = summary_kpi.peak_demand_kw
                peak_timestamp = summary_kpi.peak_timestamp
                average_load_kw = summary_kpi.average_load_kw
                load_factor_pct = summary_kpi.load_factor_pct
                load_factor_band = summary_kpi.load_factor_band
                if aggregate_demand_basis == AGGREGATE_DEMAND_BASIS_INCOMPLETE:
                    all_warnings.append(
                        "aggregate_demand_not_comparable: one or more energy-contributing devices lack a valid demand basis"
                    )

                await repo.update_report(report_id, progress=70)

                total_cost = None
                if tariff_rate_used is not None:
                    total_cost = round(total_kwh * tariff_rate_used, 2)

                # Add cost into per-day rows
                for device in per_device:
                    for day in device.get("daily_breakdown", []) or []:
                        e = day.get("energy_kwh")
                        if tariff_rate_used is not None and isinstance(e, (int, float)):
                            day["cost"] = round(float(e) * tariff_rate_used, 2)
                        else:
                            day["cost"] = None

                overtime_rows: list[dict[str, Any]] = []
                overtime_device_summary: list[dict[str, Any]] = []
                overtime_total_minutes = 0.0
                overtime_total_hours = 0.0
                overtime_total_kwh = 0.0
                overtime_device_count = 0
                devices_without_shift = 0
                for device in per_device:
                    overtime = device.get("overtime") or {}
                    if overtime.get("configured"):
                        overtime_device_count += 1
                    else:
                        devices_without_shift += 1

                    overtime_total_minutes += float(overtime.get("total_overtime_minutes") or 0.0)
                    overtime_total_hours += float(overtime.get("total_overtime_hours") or 0.0)
                    overtime_total_kwh += float(overtime.get("total_overtime_kwh") or 0.0)
                    overtime_device_summary.append(
                        {
                            "device_id": device.get("device_id"),
                            "device_name": device.get("device_name"),
                            "configured": bool(overtime.get("configured")),
                            "shift_count": overtime.get("shift_count", 0),
                            "total_overtime_minutes": overtime.get("total_overtime_minutes", 0.0),
                            "total_overtime_hours": overtime.get("total_overtime_hours", 0.0),
                            "total_overtime_kwh": overtime.get("total_overtime_kwh", 0.0),
                            "total_overtime_cost": overtime.get("total_overtime_cost"),
                            "currency": overtime.get("currency", tariff_currency),
                        }
                    )
                    for row in overtime.get("window_breakdown", []) or []:
                        overtime_rows.append(
                            {
                                "device_id": device.get("device_id"),
                                "device_name": device.get("device_name"),
                                **row,
                            }
                        )

                if devices_without_shift > 0:
                    all_warnings.append(
                        f"{devices_without_shift} device(s) had no active shift configuration and were excluded from overtime charging"
                    )

                overtime_total_cost = (
                    round(
                        sum(float(row.get("overtime_cost") or 0.0) for row in overtime_rows),
                        2,
                    )
                    if tariff_rate_used is not None
                    else None
                )
                overtime_summary = {
                    "configured_devices": overtime_device_count,
                    "devices_without_shift": devices_without_shift,
                    "total_minutes": round(overtime_total_minutes, 2),
                    "total_hours": round(overtime_total_hours, 4),
                    "total_kwh": round(overtime_total_kwh, 4),
                    "total_cost": overtime_total_cost,
                    "currency": tariff_currency,
                    "tariff_rate_used": tariff_rate_used,
                    "device_count": len(per_device),
                    "rows": overtime_rows,
                    "device_summary": overtime_device_summary,
                }

                overall_quality = "high"
                quality_rank = {"high": 0, "medium": 1, "low": 2, "insufficient": 3}
                for d in per_device:
                    q = d.get("quality", "insufficient")
                    if quality_rank.get(q, 3) > quality_rank.get(overall_quality, 0):
                        overall_quality = q

                public_per_device = [_public_device_payload(device) for device in per_device]
                public_warnings = _public_warnings(all_warnings)
                insights = generate_report_insights(
                    per_device=public_per_device,
                    overall_total_kwh=total_kwh,
                    currency=tariff_currency,
                    overtime_summary=overtime_summary,
                )

                await repo.update_report(report_id, progress=85)

                # Flatten day-wise total across devices for chart
                by_day: dict[str, float] = {}
                for d in per_device:
                    for row in d.get("daily_breakdown", []) or []:
                        date_key = str(row.get("date"))
                        if isinstance(row.get("energy_kwh"), (int, float)):
                            by_day[date_key] = by_day.get(date_key, 0.0) + float(row["energy_kwh"])
                daily_series = [{"date": k, "kwh": round(v, 4)} for k, v in sorted(by_day.items())]

                pdf_payload = {
                    "report_id": report_id,
                    "device_label": "All Machines" if len(device_ids) > 1 else per_device[0].get("device_name", device_ids[0]),
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "total_kwh": total_kwh,
                    "peak_demand_kw": peak_demand_kw,
                    "peak_timestamp": peak_timestamp,
                    "average_load_kw": average_load_kw,
                    "load_factor_pct": load_factor_pct,
                    "load_factor_band": load_factor_band,
                    "total_cost": total_cost,
                    "currency": tariff_currency,
                    "tariff_rate_used": tariff_rate_used,
                    "daily_series": daily_series,
                    "per_device": per_device,
                    "overtime_summary": overtime_summary,
                    "overtime_rows": overtime_rows,
                    "overtime_device_summary": overtime_device_summary,
                    "insights": insights,
                    "warnings": public_warnings,
                    "overall_quality": overall_quality,
                    "tariff_fetched_at": tariff_fetched_at,
                    "generated_at": datetime.utcnow().isoformat(),
                }

                pdf_bytes = generate_consumption_pdf(clean_for_json(pdf_payload))
                await repo.update_report(report_id, progress=95)

                s3_key = f"reports/{tenant_id}/{report_id}.pdf"
                minio_client.upload_pdf(pdf_bytes, s3_key)

                result_json = {
                    "schema_version": "3.0",
                    "normalization_version": NORMALIZATION_VERSION,
                    "power_model": "canonical-normalized-business-power",
                    "report_id": report_id,
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "device_scope": "ALL" if len(device_ids) > 1 else device_ids[0],
                    "summary": {
                        "total_kwh": total_kwh,
                        "peak_demand_kw": peak_demand_kw,
                        "peak_timestamp": peak_timestamp,
                        "average_load_kw": average_load_kw,
                        "load_factor_pct": load_factor_pct,
                        "load_factor_band": load_factor_band,
                        "kpi_basis": summary_kpi.basis,
                        "average_load_duration_basis": summary_kpi.duration_basis,
                        "aggregate_demand_basis": aggregate_demand_basis,
                        "total_cost": total_cost,
                        "currency": tariff_currency,
                        "overtime_minutes": overtime_summary["total_minutes"],
                        "overtime_hours": overtime_summary["total_hours"],
                        "overtime_kwh": overtime_summary["total_kwh"],
                        "overtime_cost": overtime_summary["total_cost"],
                    },
                    "data_quality": {
                        "overall": overall_quality,
                        "per_device": {
                            d["device_id"]: {
                                "quality": d.get("quality"),
                                "method": d.get("method"),
                                "warnings": d.get("warnings", []),
                                "error": d.get("error"),
                            }
                            for d in public_per_device
                        },
                    },
                    "warnings": public_warnings,
                    "insights": insights,
                    "daily_series": daily_series,
                    "devices": public_per_device,
                    "overtime": overtime_summary,
                    "tariff_rate_used": tariff_rate_used,
                    "tariff_currency": tariff_currency,
                    "tariff_fetched_at": tariff_fetched_at,
                    "tariff_source": resolved_tariff.source,
                }

                await repo.update_report(
                    report_id,
                    status="completed",
                    progress=100,
                    result_json=clean_for_json(result_json),
                    s3_key=s3_key,
                    completed_at=datetime.utcnow(),
                )
            
        except Exception as e:
            logger.error(f"Report {report_id} failed: {traceback.format_exc()}")
            await repo.update_report(
                report_id,
                status="failed",
                error_code="INTERNAL_ERROR",
                error_message=str(e)
            )


async def run_comparison_report(report_id: str, params: dict) -> None:
    from src.services.comparison_engine import calculate_comparison
    
    async with AsyncSessionLocal() as db:
        tenant_id = params.get("tenant_id")
        if not tenant_id:
            repo = ReportRepository(db)
            await repo.update_report(
                report_id,
                status="failed",
                error_code="MISSING_TENANT_ID",
                error_message="Tenant scope is required",
            )
            return

        tenant_ctx = build_service_tenant_context(tenant_id)
        repo = ReportRepository(db, ctx=tenant_ctx)
        
        try:
            await repo.update_report(report_id, status="processing", progress=10)
            
            comparison_type = params.get("comparison_type")
            
            if comparison_type == "machine_vs_machine":
                device_a = params.get("machine_a_id")
                device_b = params.get("machine_b_id")
                start_date_str = params.get("start_date")
                end_date_str = params.get("end_date")
                
                start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
                end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
                
                await repo.update_report(report_id, progress=20)
                
                async with httpx.AsyncClient() as client:
                    headers = {**INTERNAL_HEADERS, **({"X-Tenant-Id": tenant_id} if tenant_id else {})}
                    resp_a = await client.get(
                        f"{settings.DEVICE_SERVICE_URL}/api/v1/devices/{device_a}",
                        headers=headers,
                    )
                    resp_b = await client.get(
                        f"{settings.DEVICE_SERVICE_URL}/api/v1/devices/{device_b}",
                        headers=headers,
                    )
                    
                    device_a_data = resp_a.json()
                    device_b_data = resp_b.json()
                    
                    if isinstance(device_a_data, dict) and "data" in device_a_data:
                        device_a_data = device_a_data["data"]
                    if isinstance(device_b_data, dict) and "data" in device_b_data:
                        device_b_data = device_b_data["data"]
                
                await repo.update_report(report_id, progress=30)
                
                start_dt = datetime.combine(start_date, datetime.min.time())
                end_dt = datetime.combine(end_date, datetime.max.time())
                
                fields = ["power", "voltage", "current", "power_factor"]
                fields = ["active_power", *fields]
                
                rows_a = await influx_reader.query_telemetry(
                    device_id=device_a, start_dt=start_dt, end_dt=end_dt, fields=fields
                )
                rows_b = await influx_reader.query_telemetry(
                    device_id=device_b, start_dt=start_dt, end_dt=end_dt, fields=fields
                )
                
                if not rows_a or not rows_b:
                    await repo.update_report(
                        report_id,
                        status="failed",
                        error_code="NO_TELEMETRY_DATA",
                        error_message="Comparative analysis cannot be generated. No telemetry data available for one or both devices in the selected period. Please try again later."
                    )
                    return
                
                await repo.update_report(report_id, progress=40)
                
                phase_type_a = device_a_data.get("phase_type", "single")
                phase_type_b = device_b_data.get("phase_type", "single")
                device_power_config_a = {
                    "energy_flow_mode": device_a_data.get("energy_flow_mode") or "consumption_only",
                    "polarity_mode": device_a_data.get("polarity_mode") or "normal",
                }
                device_power_config_b = {
                    "energy_flow_mode": device_b_data.get("energy_flow_mode") or "consumption_only",
                    "polarity_mode": device_b_data.get("polarity_mode") or "normal",
                }
                
                energy_a = calculate_energy(rows_a, phase_type_a, device_power_config=device_power_config_a)
                energy_b = calculate_energy(rows_b, phase_type_b, device_power_config=device_power_config_b)

                if is_error(energy_a) or is_error(energy_b):
                    await repo.update_report(
                        report_id,
                        status="failed",
                        error_code="ENERGY_CALCULATION_ERROR",
                        error_message="Failed to calculate energy for one or both devices"
                    )
                    return

                async with httpx.AsyncClient() as canonical_client:
                    canonical_range_a, canonical_range_b = await asyncio.gather(
                        _fetch_canonical_energy_range(canonical_client, device_a, start_date, end_date, tenant_id),
                        _fetch_canonical_energy_range(canonical_client, device_b, start_date, end_date, tenant_id),
                    )
                energy_a = _overlay_canonical_energy_totals(energy_a, canonical_range_a)
                energy_b = _overlay_canonical_energy_totals(energy_b, canonical_range_b)

                await repo.update_report(report_id, progress=60)
                
                energy_data_a = extract_engine_data(energy_a)
                energy_data_b = extract_engine_data(energy_b)
                power_series_a = energy_data_a.get("power_series", [])
                power_series_b = energy_data_b.get("power_series", [])
                
                demand_a = calculate_demand(power_series_a, settings.DEMAND_WINDOW_MINUTES)
                demand_b = calculate_demand(power_series_b, settings.DEMAND_WINDOW_MINUTES)
                
                await repo.update_report(report_id, progress=70)
                
                comparison_result = calculate_comparison(
                    energy_a, energy_b, demand_a, demand_b,
                    device_a_data.get("device_name", device_a),
                    device_b_data.get("device_name", device_b)
                )
                comparison_result = _overlay_comparison_energy_metrics(
                    comparison_result,
                    canonical_range_a,
                    canonical_range_b,
                    device_a_data.get("device_name", device_a),
                    device_b_data.get("device_name", device_b),
                )
                
                if is_error(comparison_result):
                    await repo.update_report(
                        report_id,
                        status="failed",
                        error_code=comparison_result.get("error_code", "COMPARISON_ERROR"),
                        error_message=comparison_result.get("error_message", "Comparison calculation failed")
                    )
                    return
                
                await repo.update_report(report_id, progress=80)
                
                resolved_tariff = await resolve_tariff(db, tenant_id)
                tariff_dict = {
                    "energy_rate_per_kwh": resolved_tariff.rate,
                    "currency": resolved_tariff.currency,
                }
                
                await repo.update_report(report_id, progress=90)
                
                pdf_data = {
                    "report_id": report_id,
                    "device_a_name": device_a_data.get("device_name", device_a),
                    "device_b_name": device_b_data.get("device_name", device_b),
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "comparison": comparison_result.get("data", {}).get("metrics", {}),
                    "winner": comparison_result.get("data", {}).get("winner"),
                    "insights": comparison_result.get("data", {}).get("insights", []),
                    "currency": tariff_dict.get("currency", "INR")
                }
                
                pdf_bytes = generate_comparison_pdf(clean_for_json(pdf_data))
                
                s3_key = f"reports/{tenant_id}/{report_id}.pdf"
                minio_client.upload_pdf(pdf_bytes, s3_key)
                
                await repo.update_report(
                    report_id,
                    status="completed",
                    progress=100,
                    result_json=clean_for_json(comparison_result),
                    s3_key=s3_key,
                    completed_at=datetime.utcnow()
                )
                
            else:
                await repo.update_report(
                    report_id,
                    status="failed",
                    error_code="NOT_IMPLEMENTED",
                    error_message="Period vs Period comparison not yet implemented"
                )
                
        except Exception as e:
            logger.error(f"Comparison report {report_id} failed: {traceback.format_exc()}")
            await repo.update_report(
                report_id,
                status="failed",
                error_code="INTERNAL_ERROR",
                error_message=str(e)
            )
