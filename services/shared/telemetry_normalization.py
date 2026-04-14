from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

try:
    from services.shared.telemetry_contract import is_phase_diagnostic_field
except ModuleNotFoundError:  # pragma: no cover - service-local test path fallback
    from shared.telemetry_contract import is_phase_diagnostic_field  # type: ignore

NORMALIZATION_VERSION = "signed-power-v1"
DEFAULT_ENERGY_FLOW_MODE = "consumption_only"
DEFAULT_POLARITY_MODE = "normal"
ACTIVE_POWER_CONFLICT_TOLERANCE_W = 1.0
DEFAULT_FALLBACK_PF = 0.85

UTC = ZoneInfo("UTC")


@dataclass(frozen=True)
class DevicePowerConfig:
    energy_flow_mode: str = DEFAULT_ENERGY_FLOW_MODE
    polarity_mode: str = DEFAULT_POLARITY_MODE


@dataclass(frozen=True)
class NormalizedTelemetrySample:
    timestamp: datetime
    raw_power_w: Optional[float]
    raw_active_power_w: Optional[float]
    raw_power_factor: Optional[float]
    raw_current_a: Optional[float]
    raw_voltage_v: Optional[float]
    raw_energy_kwh: Optional[float]
    raw_source_power_field: Optional[str]
    raw_source_pf_field: Optional[str]
    raw_source_energy_field: Optional[str]
    net_power_w: Optional[float]
    import_power_w: float
    export_power_w: float
    business_power_w: float
    pf_signed: Optional[float]
    pf_business: Optional[float]
    current_a: Optional[float]
    voltage_v: Optional[float]
    energy_counter_kwh: Optional[float]
    power_direction: str
    quality_flags: tuple[str, ...]
    normalization_version: str = NORMALIZATION_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "raw_power_w": self.raw_power_w,
            "raw_active_power_w": self.raw_active_power_w,
            "raw_power_factor": self.raw_power_factor,
            "raw_current_a": self.raw_current_a,
            "raw_voltage_v": self.raw_voltage_v,
            "raw_energy_kwh": self.raw_energy_kwh,
            "raw_source_power_field": self.raw_source_power_field,
            "raw_source_pf_field": self.raw_source_pf_field,
            "raw_source_energy_field": self.raw_source_energy_field,
            "net_power_w": self.net_power_w,
            "import_power_w": self.import_power_w,
            "export_power_w": self.export_power_w,
            "business_power_w": self.business_power_w,
            "pf_signed": self.pf_signed,
            "pf_business": self.pf_business,
            "current_a": self.current_a,
            "voltage_v": self.voltage_v,
            "energy_counter_kwh": self.energy_counter_kwh,
            "power_direction": self.power_direction,
            "quality_flags": list(self.quality_flags),
            "normalization_version": self.normalization_version,
        }


@dataclass(frozen=True)
class NormalizedIntervalEnergy:
    business_energy_delta_kwh: float
    import_energy_delta_kwh: float
    export_energy_delta_kwh: float
    counter_delta_kwh: Optional[float]
    energy_delta_method: str
    quality_flags: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "business_energy_delta_kwh": self.business_energy_delta_kwh,
            "import_energy_delta_kwh": self.import_energy_delta_kwh,
            "export_energy_delta_kwh": self.export_energy_delta_kwh,
            "counter_delta_kwh": self.counter_delta_kwh,
            "energy_delta_method": self.energy_delta_method,
            "quality_flags": list(self.quality_flags),
        }


def effective_business_power_w(
    sample: NormalizedTelemetrySample,
    *,
    fallback_pf: float = DEFAULT_FALLBACK_PF,
) -> float:
    """Return the canonical business power sample used for business KPIs.

    Explicit active-power aliases remain authoritative. When active power is not
    present, derive a business-compatible import power from normalized current,
    voltage, and business PF so KPI series stay aligned with interval-energy
    fallback behavior.
    """

    if sample.raw_source_power_field is not None:
        return max(float(sample.business_power_w or 0.0), 0.0)

    if sample.current_a is None or sample.voltage_v is None:
        return max(float(sample.business_power_w or 0.0), 0.0)

    pf = sample.pf_business if sample.pf_business is not None else fallback_pf
    return max(float(sample.current_a) * float(sample.voltage_v) * float(pf), 0.0)


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def build_device_power_config(source: Any) -> DevicePowerConfig:
    if isinstance(source, DevicePowerConfig):
        return source
    if isinstance(source, dict):
        energy_flow_mode = str(
            source.get("energy_flow_mode") or DEFAULT_ENERGY_FLOW_MODE
        ).strip() or DEFAULT_ENERGY_FLOW_MODE
        polarity_mode = str(
            source.get("polarity_mode") or DEFAULT_POLARITY_MODE
        ).strip() or DEFAULT_POLARITY_MODE
        return DevicePowerConfig(
            energy_flow_mode=energy_flow_mode,
            polarity_mode=polarity_mode,
        )
    return DevicePowerConfig(
        energy_flow_mode=str(getattr(source, "energy_flow_mode", DEFAULT_ENERGY_FLOW_MODE) or DEFAULT_ENERGY_FLOW_MODE),
        polarity_mode=str(getattr(source, "polarity_mode", DEFAULT_POLARITY_MODE) or DEFAULT_POLARITY_MODE),
    )


def _resolve_active_power_w(payload: dict[str, Any]) -> tuple[Optional[float], Optional[str], list[str]]:
    flags: list[str] = []
    resolved_value: Optional[float] = None
    resolved_field: Optional[str] = None
    candidates: list[tuple[str, float]] = []
    precedence = ("active_power_kw", "power_kw", "active_power", "power")
    for field in precedence:
        raw_value = _safe_float(payload.get(field))
        if raw_value is None:
            continue
        watts = raw_value * 1000.0 if field.endswith("_kw") or field == "power_kw" else raw_value
        candidates.append((field, watts))
        if resolved_field is None:
            resolved_field = field
            resolved_value = watts

    if len(candidates) > 1:
        flags.append("active_power_alias_used")
        baseline = candidates[0][1]
        if any(abs(value - baseline) > ACTIVE_POWER_CONFLICT_TOLERANCE_W for _, value in candidates[1:]):
            flags.append("active_power_conflict")

    raw_power_w = _safe_float(payload.get("power"))
    return resolved_value if resolved_value is not None else raw_power_w, resolved_field, flags


def _resolve_pf(payload: dict[str, Any]) -> tuple[Optional[float], Optional[str]]:
    for field in ("power_factor", "pf", "cos_phi", "powerfactor"):
        value = _safe_float(payload.get(field))
        if value is not None:
            return value, field
    return None, None


def _resolve_current(payload: dict[str, Any]) -> Optional[float]:
    for field in ("current", "phase_current"):
        value = _safe_float(payload.get(field))
        if value is not None:
            return value
    return None


def _resolve_voltage(payload: dict[str, Any]) -> Optional[float]:
    for field in ("voltage",):
        value = _safe_float(payload.get(field))
        if value is not None:
            return value
    return None


def _resolve_energy_counter(payload: dict[str, Any]) -> tuple[Optional[float], Optional[str]]:
    for field in ("energy_kwh", "kwh", "energy"):
        value = _safe_float(payload.get(field))
        if value is not None:
            return value, field
    return None, None


def normalize_telemetry_sample(
    payload: dict[str, Any],
    config_source: Any,
) -> NormalizedTelemetrySample:
    config = build_device_power_config(config_source)
    flags: list[str] = []

    timestamp = parse_timestamp(payload.get("timestamp") or datetime.now(UTC).isoformat())
    raw_power_w = _safe_float(payload.get("power"))
    raw_active_power_w, raw_source_power_field, alias_flags = _resolve_active_power_w(payload)
    flags.extend(alias_flags)

    raw_power_factor, raw_source_pf_field = _resolve_pf(payload)
    raw_current_a = _resolve_current(payload)
    raw_voltage_v = _resolve_voltage(payload)
    raw_energy_kwh, raw_source_energy_field = _resolve_energy_counter(payload)

    if any(is_phase_diagnostic_field(field) and _safe_float(value) is not None for field, value in payload.items()):
        flags.append("phase_diagnostics_present")

    if raw_active_power_w is None and raw_power_w is None:
        flags.append("power_missing")

    polarity_sign = -1.0 if config.polarity_mode == "inverted" else 1.0
    if config.polarity_mode == "inverted":
        flags.append("polarity_inverted_applied")

    net_power_w = None if raw_active_power_w is None else (polarity_sign * raw_active_power_w)
    if net_power_w is not None and net_power_w < 0:
        flags.append("signed_power_seen")

    import_power_w = max(net_power_w or 0.0, 0.0)
    export_power_w = max(-(net_power_w or 0.0), 0.0) if config.energy_flow_mode == "bidirectional" else 0.0
    if export_power_w > 0:
        flags.append("export_seen")

    business_power_w = import_power_w
    power_direction = "unknown"
    if net_power_w is not None:
        if net_power_w > 0:
            power_direction = "import"
        elif net_power_w < 0:
            power_direction = "export"
        else:
            power_direction = "zero"

    pf_signed = None if raw_power_factor is None else (polarity_sign * raw_power_factor)
    if pf_signed is not None and pf_signed < 0:
        flags.append("signed_pf_seen")
    pf_business = None
    if pf_signed is not None:
        magnitude = abs(pf_signed)
        if 0 < magnitude <= 1:
            pf_business = magnitude
        else:
            flags.append("pf_untrusted")

    current_a = abs(raw_current_a) if raw_current_a is not None else None
    voltage_v = abs(raw_voltage_v) if raw_voltage_v is not None else None
    if raw_current_a is not None and raw_current_a < 0:
        flags.append("raw_current_negative_seen")
    if raw_voltage_v is not None and raw_voltage_v < 0:
        flags.append("raw_voltage_negative_seen")

    return NormalizedTelemetrySample(
        timestamp=timestamp,
        raw_power_w=raw_power_w,
        raw_active_power_w=raw_active_power_w,
        raw_power_factor=raw_power_factor,
        raw_current_a=raw_current_a,
        raw_voltage_v=raw_voltage_v,
        raw_energy_kwh=raw_energy_kwh,
        raw_source_power_field=raw_source_power_field,
        raw_source_pf_field=raw_source_pf_field,
        raw_source_energy_field=raw_source_energy_field,
        net_power_w=net_power_w,
        import_power_w=import_power_w,
        export_power_w=export_power_w,
        business_power_w=business_power_w,
        pf_signed=pf_signed,
        pf_business=pf_business,
        current_a=current_a,
        voltage_v=voltage_v,
        energy_counter_kwh=raw_energy_kwh,
        power_direction=power_direction,
        quality_flags=tuple(sorted(set(flags))),
    )


def compute_interval_energy_delta(
    previous: Optional[NormalizedTelemetrySample],
    current: NormalizedTelemetrySample,
    *,
    max_fallback_gap_seconds: float = 120.0,
    fallback_pf: float = DEFAULT_FALLBACK_PF,
) -> NormalizedIntervalEnergy:
    flags = set(current.quality_flags)
    if previous is None:
        flags.add("first_sample")
        return NormalizedIntervalEnergy(0.0, 0.0, 0.0, None, "none", tuple(sorted(flags)))

    dt_sec = (current.timestamp - previous.timestamp).total_seconds()
    if dt_sec <= 0:
        flags.add("duplicate_or_out_of_order")
        return NormalizedIntervalEnergy(0.0, 0.0, 0.0, None, "none", tuple(sorted(flags)))

    counter_delta: Optional[float] = None
    if current.energy_counter_kwh is not None and previous.energy_counter_kwh is not None:
        counter_delta = current.energy_counter_kwh - previous.energy_counter_kwh
        if counter_delta < 0:
            flags.add("counter_reverse_seen")
            counter_delta = None
        elif counter_delta == 0:
            return NormalizedIntervalEnergy(0.0, 0.0, 0.0, 0.0, "counter", tuple(sorted(flags)))
        else:
            return NormalizedIntervalEnergy(
                business_energy_delta_kwh=counter_delta,
                import_energy_delta_kwh=counter_delta,
                export_energy_delta_kwh=0.0,
                counter_delta_kwh=counter_delta,
                energy_delta_method="counter",
                quality_flags=tuple(sorted(flags)),
            )
    else:
        flags.add("counter_missing")

    if dt_sec > max_fallback_gap_seconds:
        flags.add("long_gap_fallback_blocked")
        return NormalizedIntervalEnergy(0.0, 0.0, 0.0, counter_delta, "none", tuple(sorted(flags)))

    dt_hours = dt_sec / 3600.0
    if current.business_power_w > 0 or previous.business_power_w > 0:
        avg_import_w = (previous.business_power_w + current.business_power_w) / 2.0
        business_kwh = max(avg_import_w, 0.0) * dt_hours / 1000.0
        avg_export_w = (previous.export_power_w + current.export_power_w) / 2.0
        export_kwh = max(avg_export_w, 0.0) * dt_hours / 1000.0
        flags.add("fallback_integration")
        return NormalizedIntervalEnergy(
            business_energy_delta_kwh=business_kwh,
            import_energy_delta_kwh=business_kwh,
            export_energy_delta_kwh=export_kwh,
            counter_delta_kwh=counter_delta,
            energy_delta_method="power_integration",
            quality_flags=tuple(sorted(flags)),
        )

    if (
        current.current_a is not None
        and current.voltage_v is not None
        and previous.current_a is not None
        and previous.voltage_v is not None
    ):
        current_pf = current.pf_business if current.pf_business is not None else fallback_pf
        previous_pf = previous.pf_business if previous.pf_business is not None else fallback_pf
        current_w = current.current_a * current.voltage_v * current_pf
        previous_w = previous.current_a * previous.voltage_v * previous_pf
        business_kwh = max((current_w + previous_w) / 2.0, 0.0) * dt_hours / 1000.0
        flags.add("power_derived_from_vi_pf")
        if current.pf_business is None or previous.pf_business is None:
            flags.add("pf_untrusted")
        return NormalizedIntervalEnergy(
            business_energy_delta_kwh=business_kwh,
            import_energy_delta_kwh=business_kwh,
            export_energy_delta_kwh=0.0,
            counter_delta_kwh=counter_delta,
            energy_delta_method="derived_vi_pf",
            quality_flags=tuple(sorted(flags)),
        )

    return NormalizedIntervalEnergy(0.0, 0.0, 0.0, counter_delta, "none", tuple(sorted(flags | {"insufficient_power_for_fallback"})))
