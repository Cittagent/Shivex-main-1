"""SQLAlchemy models for Device Service."""

from datetime import datetime, time, timezone, timedelta, date
from enum import Enum
from typing import Optional

from sqlalchemy import String, DateTime, Text, Integer, ForeignKey, ForeignKeyConstraint, Time, Float, Boolean, UniqueConstraint, Numeric, BigInteger, Index, Date, Enum as SAEnum, event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# Configurable timeout threshold for telemetry (in seconds)
TELEMETRY_TIMEOUT_SECONDS = 60  # Device considered STOPPED if no telemetry for 60 seconds
TENANT_ID_LENGTH = 10


class DeviceStatus(str, Enum):
    """Device status enumeration (LEGACY - for backward compatibility only)."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    MAINTENANCE = "maintenance"
    ERROR = "error"


class RuntimeStatus(str, Enum):
    """Runtime status derived from telemetry activity."""
    RUNNING = "running"
    STOPPED = "stopped"


class PhaseType(str, Enum):
    """Electrical phase type for devices.
    
    Used for energy reporting to distinguish between:
    - single: Single-phase equipment
    - three: Three-phase equipment
    """
    SINGLE = "single"
    THREE = "three"


class DataSourceType(str, Enum):
    """Data source type used by reporting calculations."""
    METERED = "metered"
    SENSOR = "sensor"


class EnergyFlowMode(str, Enum):
    CONSUMPTION_ONLY = "consumption_only"
    BIDIRECTIONAL = "bidirectional"


class PolarityMode(str, Enum):
    NORMAL = "normal"
    INVERTED = "inverted"


class DeviceIdClass(str, Enum):
    """Classification used to allocate generated device identifiers."""

    ACTIVE = "active"
    TEST = "test"
    VIRTUAL = "virtual"


class DeviceIdSequence(Base):
    """Persistent per-prefix allocator state for generated device IDs."""

    __tablename__ = "device_id_sequences"

    prefix: Mapped[str] = mapped_column(String(2), primary_key=True)
    next_value: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class HardwareUnitSequence(Base):
    """Persistent allocator state for generated hardware unit IDs."""

    __tablename__ = "hardware_unit_sequences"

    prefix: Mapped[str] = mapped_column(String(3), primary_key=True)
    next_value: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class Device(Base):
    """Device model representing IoT devices in the system.
    
    This model is designed to be multi-tenant ready. The tenant_id field
    is included for future multi-tenancy support but is nullable for Phase-1.
    
    Runtime status is computed dynamically based on last_seen_timestamp:
    - RUNNING: telemetry received within TELEMETRY_TIMEOUT_SECONDS
    - STOPPED: no telemetry received within TELEMETRY_TIMEOUT_SECONDS or never received
    """
    
    __tablename__ = "devices"
    __table_args__ = (
        UniqueConstraint("device_id", name="uq_devices_device_id"),
    )
    
    # Primary key - using business key for device_id
    device_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    
    # Multi-tenant support
    tenant_id: Mapped[str] = mapped_column(String(TENANT_ID_LENGTH), primary_key=True, nullable=False, index=True)
    plant_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        nullable=True,
        index=True,
        comment="Soft ref to plants.id in auth-service",
    )
    
    # Device metadata
    device_name: Mapped[str] = mapped_column(String(255), nullable=False)
    device_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    device_id_class: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    manufacturer: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    # Phase type - electrical configuration for energy reporting
    # This is static metadata, not telemetry-derived
    phase_type: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        index=True
    )

    # Report source type metadata
    data_source_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=DataSourceType.METERED.value,
        index=True,
    )
    energy_flow_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=EnergyFlowMode.CONSUMPTION_ONLY.value,
        index=True,
    )
    polarity_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=PolarityMode.NORMAL.value,
        index=True,
    )

    # Idle detection threshold in amperes (per-device configuration)
    idle_current_threshold: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 4),
        nullable=True,
    )
    overconsumption_current_threshold_a: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 4),
        nullable=True,
    )
    unoccupied_weekday_start_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    unoccupied_weekday_end_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    unoccupied_weekend_start_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    unoccupied_weekend_end_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    
    # Legacy status field - DEPRECATED
    # This field is kept for backward compatibility only.
    # Do NOT use for runtime display - use get_runtime_status() instead.
    legacy_status: Mapped[str] = mapped_column(
        String(50),
        default="active",
        nullable=False,
        index=True
    )
    
    # Last seen timestamp - tracks when telemetry was last received
    # This is the source of truth for runtime status
    last_seen_timestamp: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True
    )

    # Immutable activation timestamp derived from the first telemetry sample
    # ever observed after onboarding. This is written once and never mutated.
    first_telemetry_timestamp: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    
    # Extended metadata as JSON (for future extensibility)
    metadata_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )
    
    # Soft delete support (for future)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    shifts: Mapped[list["DeviceShift"]] = relationship(
        "DeviceShift", 
        back_populates="device", 
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    health_configs: Mapped[list["ParameterHealthConfig"]] = relationship(
        "ParameterHealthConfig",
        back_populates="device",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    hardware_installations: Mapped[list["DeviceHardwareInstallation"]] = relationship(
        "DeviceHardwareInstallation",
        back_populates="device",
        cascade="all, delete-orphan",
        lazy="selectin",
        overlaps="hardware_unit,installations",
    )
    
    def __repr__(self) -> str:
        return f"<Device(device_id={self.device_id}, name={self.device_name}, type={self.device_type})>"
    
    @property
    def status(self) -> str:
        """Legacy status property for backward compatibility.
        
        DEPRECATED: Use get_runtime_status() instead.
        """
        return self.legacy_status
    
    @property
    def runtime_status(self) -> str:
        """Computed runtime status property for API responses.
        
        This is a computed property that returns the runtime status
        based on last_seen_timestamp. It is used by the ORM when
        serializing to JSON.
        """
        return self.get_runtime_status()
    
    def get_runtime_status(self) -> str:
        """Compute runtime status based on telemetry activity.
        
        Returns:
            'running' - if telemetry received within TELEMETRY_TIMEOUT_SECONDS
            'stopped' - if no telemetry received within TELEMETRY_TIMEOUT_SECONDS or never received
        """
        if self.last_seen_timestamp is None:
            return RuntimeStatus.STOPPED.value
        
        now = datetime.now(timezone.utc)
        
        # Handle naive datetime from database
        last_seen = self.last_seen_timestamp
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        
        time_diff = (now - last_seen).total_seconds()
        
        if time_diff <= TELEMETRY_TIMEOUT_SECONDS:
            return RuntimeStatus.RUNNING.value
        else:
            return RuntimeStatus.STOPPED.value
    
    def is_running(self) -> bool:
        """Check if device is currently running (receiving telemetry)."""
        return self.get_runtime_status() == RuntimeStatus.RUNNING.value
    
    def is_stopped(self) -> bool:
        """Check if device is currently stopped (not receiving telemetry)."""
        return self.get_runtime_status() == RuntimeStatus.STOPPED.value
    
    def update_last_seen(self) -> None:
        """Update last_seen_timestamp to current time.
        
        Called when telemetry is received for this device.
        """
        self.last_seen_timestamp = datetime.now(timezone.utc)


class DeviceShift(Base):
    """Shift configuration for device uptime calculation.
    
    Supports multiple shifts per day per device.
    Each shift has planned start/end times and optional maintenance break.
    """
    
    __tablename__ = "device_shifts"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # Foreign key to device
    device_id: Mapped[str] = mapped_column(
        String(50), 
        ForeignKey("devices.device_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    
    # Tenant for multi-tenancy
    tenant_id: Mapped[Optional[str]] = mapped_column(String(TENANT_ID_LENGTH), nullable=True, index=True)
    
    # Shift identification
    shift_name: Mapped[str] = mapped_column(String(100), nullable=False)
    
    # Planned times (stored as time for date-agnostic scheduling)
    shift_start: Mapped[time] = mapped_column(Time, nullable=False)
    shift_end: Mapped[time] = mapped_column(Time, nullable=False)
    
    # Maintenance break duration in minutes
    maintenance_break_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    # Day of week (0=Monday, 6=Sunday). Null means all days.
    day_of_week: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    # Active flag
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )
    
    # Relationship
    device: Mapped["Device"] = relationship("Device", back_populates="shifts")
    
    def __repr__(self) -> str:
        return f"<DeviceShift(id={self.id}, device_id={self.device_id}, shift_name={self.shift_name})>"
    
    @property
    def planned_duration_minutes(self) -> int:
        """Calculate total planned shift duration in minutes."""
        start_minutes = self.shift_start.hour * 60 + self.shift_start.minute
        end_minutes = self.shift_end.hour * 60 + self.shift_end.minute
        
        if end_minutes <= start_minutes:
            # Shift crosses midnight
            end_minutes += 24 * 60
            
        return end_minutes - start_minutes
    
    @property
    def effective_runtime_minutes(self) -> int:
        """Calculate effective runtime after maintenance break."""
        return self.planned_duration_minutes - self.maintenance_break_minutes


class ParameterHealthConfig(Base):
    """Parameter health configuration for device health scoring.
    
    Each parameter can have configurable ranges and weights for health calculation.
    """
    
    __tablename__ = "parameter_health_config"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    device_id: Mapped[str] = mapped_column(
        String(50), 
        ForeignKey("devices.device_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    
    tenant_id: Mapped[Optional[str]] = mapped_column(String(TENANT_ID_LENGTH), nullable=True, index=True)
    
    parameter_name: Mapped[str] = mapped_column(String(100), nullable=False)
    canonical_parameter_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    
    normal_min: Mapped[Optional[float]] = mapped_column(nullable=True)
    normal_max: Mapped[Optional[float]] = mapped_column(nullable=True)
    
    weight: Mapped[float] = mapped_column(default=0.0, nullable=False)
    
    ignore_zero_value: Mapped[bool] = mapped_column(default=False, nullable=False)
    
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )
    
    device: Mapped["Device"] = relationship("Device", back_populates="health_configs")
    
    def __repr__(self) -> str:
        return f"<ParameterHealthConfig(id={self.id}, device_id={self.device_id}, parameter={self.parameter_name})>"


_HEALTH_PARAMETER_ALIASES: dict[str, tuple[str, ...]] = {
    "current": ("current_a", "phase_current"),
    "power": ("active_power", "active_power_kw", "business_power_w", "power_kw", "kw"),
    "power_factor": ("pf", "cos_phi", "powerfactor", "pf_business", "raw_power_factor"),
    "voltage": ("voltage_v",),
}
_HEALTH_ALIASES_TO_CANONICAL = {
    alias.casefold(): canonical
    for canonical, aliases in _HEALTH_PARAMETER_ALIASES.items()
    for alias in aliases
}


def canonicalize_health_parameter_name(parameter_name: Optional[str]) -> str:
    normalized = str(parameter_name or "").strip().casefold()
    return _HEALTH_ALIASES_TO_CANONICAL.get(normalized, normalized)


@event.listens_for(ParameterHealthConfig, "before_insert")
@event.listens_for(ParameterHealthConfig, "before_update")
def _sync_parameter_health_canonical_name(_mapper, _connection, target: ParameterHealthConfig) -> None:
    target.canonical_parameter_name = canonicalize_health_parameter_name(target.parameter_name)


class DevicePerformanceTrend(Base):
    """Materialized trend snapshots for device performance charts."""

    __tablename__ = "device_performance_trends"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    device_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("devices.device_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[str] = mapped_column(String(TENANT_ID_LENGTH), nullable=False, index=True)

    bucket_start_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    bucket_end_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    bucket_timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata", nullable=False)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=5, nullable=False)

    health_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    uptime_percentage: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    planned_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    effective_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    break_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    points_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    is_valid: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
        index=True,
    )

    __table_args__ = (
        UniqueConstraint("device_id", "tenant_id", "bucket_start_utc", name="uq_perf_trend_device_bucket"),
    )

    def __repr__(self) -> str:
        return f"<DevicePerformanceTrend(device_id={self.device_id}, bucket={self.bucket_start_utc})>"


class DeviceProperty(Base):
    """Dynamic device properties discovered from telemetry.
    
    This table stores the properties (fields) discovered from each device's
    telemetry data. Used for dynamic rule property selection.
    """
    
    __tablename__ = "device_properties"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    device_id: Mapped[str] = mapped_column(
        String(50), 
        ForeignKey("devices.device_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(TENANT_ID_LENGTH), nullable=False, index=True)
    
    property_name: Mapped[str] = mapped_column(String(100), nullable=False)
    
    data_type: Mapped[str] = mapped_column(String(20), default="float", nullable=False)
    
    is_numeric: Mapped[bool] = mapped_column(default=True, nullable=False)
    
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False
    )
    
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )
    
    __table_args__ = (
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )
    
    def __repr__(self) -> str:
        return f"<DeviceProperty(device_id={self.device_id}, property={self.property_name})>"


class DeviceDashboardWidget(Base):
    """Per-device dashboard widget visibility configuration."""

    __tablename__ = "device_dashboard_widgets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("devices.device_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[str] = mapped_column(String(TENANT_ID_LENGTH), nullable=False, index=True)
    field_name: Mapped[str] = mapped_column(String(100), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("device_id", "tenant_id", "field_name", name="uq_device_dashboard_widget"),
        Index("ix_device_dashboard_widgets_device_order", "device_id", "tenant_id", "display_order"),
    )

    def __repr__(self) -> str:
        return f"<DeviceDashboardWidget(device_id={self.device_id}, field_name={self.field_name})>"


class DeviceDashboardWidgetSetting(Base):
    """Per-device widget config state to distinguish default/fallback vs explicit empty."""

    __tablename__ = "device_dashboard_widget_settings"

    device_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("devices.device_id", ondelete="CASCADE"),
        primary_key=True,
    )
    tenant_id: Mapped[str] = mapped_column(String(TENANT_ID_LENGTH), primary_key=True, nullable=False)
    is_configured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<DeviceDashboardWidgetSetting(device_id={self.device_id}, "
            f"is_configured={self.is_configured})>"
        )


class IdleRunningLog(Base):
    """Daily aggregate idle-running consumption log per device."""

    __tablename__ = "idle_running_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("devices.device_id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_id: Mapped[str] = mapped_column(String(TENANT_ID_LENGTH), nullable=False, index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idle_duration_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    idle_energy_kwh: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False, default=0)
    idle_cost: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="INR")
    tariff_rate_used: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False, default=0)
    pf_estimated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("device_id", "tenant_id", "period_start", name="uq_idle_log_device_day"),
        Index("idx_idle_log_device_period", "device_id", "tenant_id", "period_start"),
    )

    def __repr__(self) -> str:
        return f"<IdleRunningLog(device_id={self.device_id}, period_start={self.period_start})>"


class DeviceLiveState(Base):
    """Per-device real-time projection for low-latency dashboard reads."""

    __tablename__ = "device_live_state"

    device_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("devices.device_id", ondelete="CASCADE"),
        primary_key=True,
    )
    tenant_id: Mapped[str] = mapped_column(String(TENANT_ID_LENGTH), primary_key=True, nullable=False)
    last_telemetry_ts: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sample_ts: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    runtime_status: Mapped[str] = mapped_column(String(32), nullable=False, default=RuntimeStatus.STOPPED.value, index=True)
    load_state: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    health_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    uptime_percentage: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    today_energy_kwh: Mapped[float] = mapped_column(Numeric(14, 6), nullable=False, default=0)
    today_idle_kwh: Mapped[float] = mapped_column(Numeric(14, 6), nullable=False, default=0)
    today_offhours_kwh: Mapped[float] = mapped_column(Numeric(14, 6), nullable=False, default=0)
    today_overconsumption_kwh: Mapped[float] = mapped_column(Numeric(14, 6), nullable=False, default=0)
    today_loss_kwh: Mapped[float] = mapped_column(Numeric(14, 6), nullable=False, default=0)
    today_loss_cost_inr: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)

    month_energy_kwh: Mapped[float] = mapped_column(Numeric(14, 6), nullable=False, default=0)
    month_energy_cost_inr: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)

    today_running_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    today_effective_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    day_bucket: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    month_bucket: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)

    last_energy_kwh: Mapped[Optional[float]] = mapped_column(Numeric(14, 6), nullable=True)
    last_power_kw: Mapped[Optional[float]] = mapped_column(Numeric(14, 6), nullable=True)
    last_current_a: Mapped[Optional[float]] = mapped_column(Numeric(14, 6), nullable=True)
    last_voltage_v: Mapped[Optional[float]] = mapped_column(Numeric(14, 6), nullable=True)
    idle_streak_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    idle_streak_duration_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
        index=True,
    )

    def __repr__(self) -> str:
        return f"<DeviceLiveState(device_id={self.device_id}, version={self.version})>"


class WasteSiteConfig(Base):
    """Factory/site-level defaults for waste analysis windows."""

    __tablename__ = "waste_site_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[Optional[str]] = mapped_column(String(TENANT_ID_LENGTH), nullable=True, index=True)
    default_unoccupied_weekday_start_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    default_unoccupied_weekday_end_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    default_unoccupied_weekend_start_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    default_unoccupied_weekend_end_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    timezone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    updated_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_waste_site_config_tenant"),
    )


class DashboardSnapshot(Base):
    """Persisted dashboard snapshot payload for low-latency reads."""

    __tablename__ = "dashboard_snapshots"

    tenant_id: Mapped[str] = mapped_column(String(TENANT_ID_LENGTH), primary_key=True)
    snapshot_key: Mapped[str] = mapped_column(String(120), primary_key=True)
    payload_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    s3_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    storage_backend: Mapped[str] = mapped_column(
        SAEnum("mysql", "minio", name="dashboard_snapshot_storage_backend"),
        nullable=False,
        default="mysql",
    )
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        Index("ix_dashboard_snapshots_tenant_id", "tenant_id"),
        Index("ix_dashboard_snapshots_generated_at", "generated_at"),
        Index("ix_dashboard_snapshots_expires_at", "expires_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<DashboardSnapshot(tenant_id={self.tenant_id}, "
            f"key={self.snapshot_key}, generated_at={self.generated_at})>"
        )


class HardwareUnitStatus(str, Enum):
    """Lifecycle status for a physical hardware unit."""

    AVAILABLE = "available"
    RETIRED = "retired"


class HardwareUnit(Base):
    """Physical hardware inventory tracked per tenant and plant."""

    __tablename__ = "hardware_units"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hardware_unit_id: Mapped[str] = mapped_column(String(100), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(TENANT_ID_LENGTH), nullable=False, index=True)
    plant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    unit_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    unit_name: Mapped[str] = mapped_column(String(255), nullable=False)
    manufacturer: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    serial_number: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=HardwareUnitStatus.AVAILABLE.value,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    installations: Mapped[list["DeviceHardwareInstallation"]] = relationship(
        "DeviceHardwareInstallation",
        back_populates="hardware_unit",
        cascade="all, delete-orphan",
        lazy="selectin",
        overlaps="device,hardware_installations",
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "hardware_unit_id", name="uq_hardware_units_tenant_unit_id"),
        Index("ix_hardware_units_tenant_plant_type", "tenant_id", "plant_id", "unit_type"),
    )


class DeviceHardwareInstallation(Base):
    """Historical hardware installation events for a device."""

    __tablename__ = "device_hardware_installations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(TENANT_ID_LENGTH), nullable=False, index=True)
    plant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    hardware_unit_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    installation_role: Mapped[str] = mapped_column(String(100), nullable=False)
    commissioned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )
    decommissioned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    active_hardware_unit_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    active_device_role_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    hardware_unit: Mapped["HardwareUnit"] = relationship(
        "HardwareUnit",
        back_populates="installations",
        lazy="selectin",
        overlaps="device,hardware_installations",
    )
    device: Mapped["Device"] = relationship(
        "Device",
        lazy="selectin",
        overlaps="hardware_unit,installations,hardware_installations",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["device_id", "tenant_id"],
            ["devices.device_id", "devices.tenant_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "hardware_unit_id"],
            ["hardware_units.tenant_id", "hardware_units.hardware_unit_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id",
            "active_hardware_unit_key",
            name="uq_device_hardware_installations_active_unit",
        ),
        UniqueConstraint(
            "tenant_id",
            "active_device_role_key",
            name="uq_device_hardware_installations_active_role",
        ),
        Index(
            "ix_device_hardware_installations_device_history",
            "tenant_id",
            "device_id",
            "commissioned_at",
        ),
        Index(
            "ix_device_hardware_installations_hardware_history",
            "tenant_id",
            "hardware_unit_id",
            "commissioned_at",
        ),
    )

    @property
    def is_active(self) -> bool:
        return self.decommissioned_at is None
