from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from services.shared.telemetry_normalization import (
    effective_business_power_w,
    normalize_telemetry_sample,
)


@dataclass
class DeviceComputationResult:
    device_id: str
    device_name: str
    data_source_type: str
    availability: dict[str, bool]
    method: str
    quality: str
    warnings: list[str]
    error: str | None
    total_kwh: float | None
    peak_demand_kw: float | None
    peak_timestamp: str | None
    average_load_kw: float | None
    load_factor_pct: float | None
    load_factor_band: str | None
    total_hours: float
    daily_breakdown: list[dict[str, Any]]
    overtime_breakdown: list[dict[str, Any]]
    overtime_summary: dict[str, Any] | None
    power_factor: dict[str, Any] | None
    reactive: dict[str, Any] | None
    power_unit_input: str
    power_unit_normalized_to: str
    normalization_applied: bool


def _to_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).copy()
    if "timestamp" not in df.columns:
        return pd.DataFrame()

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp")

    numeric_candidates = [
        "energy_kwh",
        "power",
        "current",
        "voltage",
        "power_factor",
        "frequency",
        "kvar",
        "reactive_power",
        "run_hours",
    ]
    for col in numeric_candidates:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df.reset_index(drop=True)


def _normalize_rows(rows: list[dict[str, Any]], config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        sample = normalize_telemetry_sample(row, config or {})
        effective_power_w = effective_business_power_w(sample)
        quality_flags = set(sample.quality_flags)
        if sample.raw_source_power_field is None and effective_power_w > 0:
            quality_flags.add("power_derived_from_vi_pf")
            if sample.pf_business is None:
                quality_flags.add("pf_untrusted")
        normalized_row = dict(row)
        normalized_row.update(
            {
                "timestamp": sample.timestamp,
                "energy_kwh": sample.energy_counter_kwh,
                "power": effective_power_w,
                "active_power": sample.raw_active_power_w,
                "net_power_w": sample.net_power_w,
                "import_power_w": sample.import_power_w,
                "export_power_w": sample.export_power_w,
                "current": sample.current_a,
                "voltage": sample.voltage_v,
                "power_factor": sample.pf_business,
                "pf_signed": sample.pf_signed,
                "quality_flags": list(sorted(quality_flags)),
                "raw_source_power_field": sample.raw_source_power_field,
            }
        )
        normalized_rows.append(normalized_row)
    return normalized_rows


def _sample_from_normalized_row(row: dict[str, Any]):
    return {
        "timestamp": row.get("timestamp"),
        "energy_counter_kwh": row.get("energy_kwh"),
        "business_power_w": float(row.get("power") or 0.0),
        "export_power_w": float(row.get("export_power_w") or 0.0),
        "current_a": row.get("current"),
        "voltage_v": row.get("voltage"),
        "pf_business": row.get("power_factor"),
    }


def _availability(df: pd.DataFrame) -> dict[str, bool]:
    fields = [
        "energy_kwh",
        "power",
        "current",
        "voltage",
        "power_factor",
        "frequency",
        "kvar",
        "reactive_power",
        "run_hours",
    ]
    return {f: (f in df.columns and df[f].notna().sum() > 0) for f in fields}


def _series_with_time(df: pd.DataFrame, col: str) -> tuple[np.ndarray, np.ndarray]:
    sub = df[["timestamp", col]].dropna()
    if sub.empty:
        return np.array([]), np.array([])
    # timestamp() keeps epoch seconds precision across datetime backends.
    ts = sub["timestamp"].map(lambda x: x.timestamp()).to_numpy(dtype=float)
    vals = sub[col].to_numpy(dtype=float)
    return ts, vals


def _integrate_kwh(ts_sec: np.ndarray, power_kw: np.ndarray) -> tuple[float | None, float, list[str]]:
    if len(ts_sec) < 2 or len(power_kw) < 2:
        return None, 0.0, []

    warnings: list[str] = []
    total_kwh = 0.0
    total_hours = 0.0
    saw_zero_gap = False
    saw_negative_gap = False

    for idx in range(1, len(ts_sec)):
        dt_sec = float(ts_sec[idx] - ts_sec[idx - 1])
        if dt_sec < 0:
            saw_negative_gap = True
            continue
        if dt_sec == 0:
            saw_zero_gap = True
            continue
        dt_hours = dt_sec / 3600.0
        total_hours += dt_hours
        total_kwh += ((float(power_kw[idx - 1]) + float(power_kw[idx])) / 2.0) * dt_hours

    if saw_negative_gap:
        warnings.append("NON_MONOTONIC_TIMESTAMPS: non-monotonic samples skipped during integration")
    if saw_zero_gap:
        warnings.append("TIMESTAMP_GAP_SKIPPED: duplicate timestamp samples skipped during integration")
    if total_hours <= 0:
        return None, 0.0, warnings
    return max(total_kwh, 0.0), max(total_hours, 0.0), warnings


def _canonicalize_df(df: pd.DataFrame, device_power_config: dict[str, Any] | None = None) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    canonical_rows = _normalize_rows(df.to_dict(orient="records"), device_power_config)
    return _to_df(canonical_rows)


def _load_factor_band(load_factor_pct: float | None) -> str | None:
    if load_factor_pct is None:
        return None
    if load_factor_pct < 30:
        return "poor"
    if load_factor_pct <= 70:
        return "moderate"
    return "good"


def _dedupe_warnings(values: list[str]) -> list[str]:
    seen = set()
    out: list[str] = []
    for item in values:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _compute_from_df(
    df: pd.DataFrame,
    device_id: str,
    device_name: str,
    data_source_type: str,
    device_power_config: dict[str, Any] | None = None,
    include_daily: bool = True,
    rows_are_normalized: bool = False,
) -> DeviceComputationResult:
    working_df = df.copy() if rows_are_normalized else _canonicalize_df(df, device_power_config)
    avail = _availability(working_df)
    warnings: list[str] = []
    error: str | None = None

    method = "insufficient"
    quality = "insufficient"
    total_kwh: float | None = None
    total_hours = 0.0
    power_unit_input = "unknown"
    power_unit_normalized_to = "kW"
    normalization_applied = False

    normalized_rows = working_df.to_dict(orient="records")
    if normalized_rows:
        total_energy = 0.0
        total_hours = 0.0
        for idx in range(1, len(normalized_rows)):
            prev = _sample_from_normalized_row(normalized_rows[idx - 1])
            curr = _sample_from_normalized_row(normalized_rows[idx])
            dt_hours = max(
                (pd.to_datetime(curr["timestamp"], utc=True) - pd.to_datetime(prev["timestamp"], utc=True)).total_seconds(),
                0.0,
            ) / 3600.0
            total_energy += max((float(prev["business_power_w"] or 0.0) + float(curr["business_power_w"] or 0.0)) / 2.0, 0.0) * dt_hours / 1000.0
            total_hours += dt_hours
        if total_hours > 0:
            total_kwh = round(max(total_energy, 0.0), 4)
            method = "normalized_business_power"
            quality = "high"

    # Priority 5: insufficient
    if total_kwh is None and avail["current"] and not avail["voltage"]:
        method = "insufficient_current_only"
        quality = "insufficient"
        error = "Insufficient telemetry — voltage required for energy calculation"

    if total_kwh is None and error is None:
        method = "insufficient_missing_fields"
        quality = "insufficient"
        error = "Insufficient telemetry — need one of: energy_kwh, power, or (current + voltage)"

    # Peak demand
    peak_demand_kw: float | None = None
    peak_timestamp: str | None = None
    if avail["power"]:
        sub = working_df[["timestamp", "power"]].copy()
        sub["power"] = pd.to_numeric(sub["power"], errors="coerce")
        sub = sub.dropna(subset=["power"])
        sub = sub[sub["power"] > 0.0]
        if not sub.empty:
            idx = sub["power"].astype(float).idxmax()
            peak_demand_kw = round(float(sub.loc[idx, "power"]) / 1000.0, 4)
            peak_timestamp = sub.loc[idx, "timestamp"].isoformat()
            power_unit_input = "W"
            power_unit_normalized_to = "kW"
            normalization_applied = True

    average_load_kw: float | None = None
    load_factor_pct: float | None = None
    load_factor_band: str | None = None
    if total_kwh is not None and total_hours > 0:
        average_load_kw = round(total_kwh / total_hours, 4)
    if average_load_kw is not None and peak_demand_kw and peak_demand_kw > 0:
        load_factor_pct = round(max(0.0, min(100.0, (average_load_kw / peak_demand_kw) * 100.0)), 2)
        load_factor_band = _load_factor_band(load_factor_pct)

    # Daily breakdown (uses same priority logic per day)
    daily_breakdown: list[dict[str, Any]] = []
    if include_daily and not working_df.empty:
        day_groups = working_df.groupby(working_df["timestamp"].dt.date)
        for day, day_df in day_groups:
            day_result = _compute_from_df(
                day_df.reset_index(drop=True),
                device_id=device_id,
                device_name=device_name,
                data_source_type=data_source_type,
                device_power_config=device_power_config,
                include_daily=False,
                rows_are_normalized=True,
            )
            daily_breakdown.append(
                {
                    "date": str(day),
                    "energy_kwh": day_result.total_kwh,
                    "peak_demand_kw": day_result.peak_demand_kw,
                    "average_load_kw": day_result.average_load_kw,
                    "quality": day_result.quality,
                    "method": day_result.method,
                    "warnings": day_result.warnings,
                }
            )

    power_factor = None
    if avail["power_factor"]:
        pf = pd.to_numeric(working_df["power_factor"], errors="coerce").dropna()
        if not pf.empty:
            avg_pf = float(pf.mean())
            min_pf = float(pf.min())
            if avg_pf < 0.85:
                status = "poor"
                recommendation = "Install capacitor banks to improve power factor above 0.95"
            elif avg_pf < 0.92:
                status = "moderate"
                recommendation = "Consider power factor correction"
            else:
                status = "good"
                recommendation = None
            power_factor = {
                "average": round(avg_pf, 4),
                "min": round(min_pf, 4),
                "status": status,
                "recommendation": recommendation,
            }

    reactive = None
    reactive_field = "kvar" if avail["kvar"] else "reactive_power" if avail["reactive_power"] else None
    if reactive_field:
        ts_sec, kvar_vals = _series_with_time(working_df, reactive_field)
        total_kvarh, _, _ = _integrate_kwh(ts_sec, kvar_vals)
        if total_kvarh is not None:
            ratio = None
            if total_kwh and total_kwh > 0:
                ratio = round(float(total_kvarh / total_kwh), 4)
            reactive = {
                "total_kvarh": round(float(total_kvarh), 4),
                "reactive_ratio": ratio,
                "field_used": reactive_field,
            }

    return DeviceComputationResult(
        device_id=device_id,
        device_name=device_name,
        data_source_type=data_source_type,
        availability=avail,
        method=method,
        quality=quality,
        warnings=_dedupe_warnings(warnings),
        error=error,
        total_kwh=total_kwh,
        peak_demand_kw=peak_demand_kw,
        peak_timestamp=peak_timestamp,
        average_load_kw=average_load_kw,
        load_factor_pct=load_factor_pct,
        load_factor_band=load_factor_band,
        total_hours=round(total_hours, 4),
        daily_breakdown=daily_breakdown,
        overtime_breakdown=[],
        overtime_summary=None,
        power_factor=power_factor,
        reactive=reactive,
        power_unit_input=power_unit_input,
        power_unit_normalized_to=power_unit_normalized_to,
        normalization_applied=normalization_applied,
    )


def compute_device_report(
    rows: list[dict[str, Any]],
    device_id: str,
    device_name: str,
    data_source_type: str,
    device_power_config: dict[str, Any] | None = None,
) -> DeviceComputationResult:
    df = _to_df(rows)
    if df.empty:
        return DeviceComputationResult(
            device_id=device_id,
            device_name=device_name,
            data_source_type=data_source_type,
            availability={},
            method="no_data",
            quality="insufficient",
            warnings=[],
            error="No telemetry data available for selected period",
            total_kwh=None,
            peak_demand_kw=None,
            peak_timestamp=None,
            average_load_kw=None,
            load_factor_pct=None,
            load_factor_band=None,
            total_hours=0.0,
            daily_breakdown=[],
            overtime_breakdown=[],
            overtime_summary=None,
            power_factor=None,
            reactive=None,
            power_unit_input="unknown",
            power_unit_normalized_to="kW",
            normalization_applied=False,
        )
    return _compute_from_df(df, device_id, device_name, data_source_type, device_power_config=device_power_config)
