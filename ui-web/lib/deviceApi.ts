import { DEVICE_SERVICE_BASE, fetchWithBackendSession } from "./api";
import { apiFetch } from "./apiFetch";
import { authApi } from "./authApi";
import { createFleetStreamConnector as createReconnectableFleetStream } from "./fleetStreamReconnect";
import { readResponseError } from "./responseError";
import { mapBackendDeviceShape, type BackendDeviceShape, type DeviceShape } from "./deviceMapping.ts";

const DASHBOARD_REQUEST_TIMEOUT_MS = 5_000;

/**
 * Raw backend shape
 */
interface BackendDevice extends BackendDeviceShape {}

/**
 * UI shape - uses runtime_status for dynamic device state
 */
export interface Device extends DeviceShape {}

export type DeviceLoadState = "running" | "idle" | "unloaded" | "unknown";

export interface IdleConfig {
  device_id: string;
  idle_current_threshold: number | null;
  configured: boolean;
}

export interface DeviceWasteConfig {
  device_id: string;
  overconsumption_current_threshold_a: number | null;
  unoccupied_weekday_start_time: string | null;
  unoccupied_weekday_end_time: string | null;
  unoccupied_weekend_start_time: string | null;
  unoccupied_weekend_end_time: string | null;
  has_device_override: boolean;
}

export interface CurrentState {
  device_id: string;
  state: DeviceLoadState;
  current: number | null;
  voltage: number | null;
  threshold: number | null;
  timestamp: string | null;
  current_field: string | null;
  voltage_field: string | null;
}

export interface IdlePeriodStats {
  idle_duration_minutes: number;
  idle_duration_label: string;
  idle_energy_kwh: number;
  idle_cost: number | null;
  currency: string;
}

export interface IdleStats {
  device_id: string;
  today: IdlePeriodStats | null;
  month: IdlePeriodStats | null;
  tariff_configured: boolean;
  pf_estimated: boolean;
  threshold_configured: boolean;
  idle_current_threshold: number | null;
  data_source_type: "metered" | "sensor" | string;
  tariff_cache?: string;
  tariff_stale?: boolean;
}

export interface DeviceLossStats {
  device_id: string;
  day_bucket: string;
  last_telemetry_ts: string | null;
  updated_at: string | null;
  tariff_configured: boolean;
  currency: string;
  today: {
    idle_kwh: number;
    idle_cost_inr: number | null;
    off_hours_kwh: number;
    off_hours_cost_inr: number | null;
    overconsumption_kwh: number;
    overconsumption_cost_inr: number | null;
    total_loss_kwh: number;
    total_loss_cost_inr: number | null;
    today_energy_kwh: number;
    today_energy_cost_inr: number | null;
  };
}

type FleetStreamParams = {
  pageSize?: number;
  runtimeStatus?: "running" | "stopped";
  lastEventId?: string;
  inactivityTimeoutMs?: number;
  onEvent: (payload: FleetStreamEventData) => void;
  onError?: (error: unknown, retryCount: number) => void;
  onOpen?: () => void;
  onReconnectStart?: (reason: "stream_closed" | "stream_error", retryCount: number) => void;
};

export interface DashboardWidgetConfig {
  device_id: string;
  available_fields: string[];
  selected_fields: string[];
  effective_fields: string[];
  default_applied: boolean;
}

interface DeviceApiResponse<T> {
  success: boolean;
  data: T;
}

async function readApiError(res: Response): Promise<string> {
  return readResponseError(res);
}

async function fetchWithBackendSessionTimeout(
  input: string,
  init: RequestInit = {},
  timeoutMs = DASHBOARD_REQUEST_TIMEOUT_MS,
): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(new Error("Request timed out")), timeoutMs);
  try {
    return await fetchWithBackendSession(input, {
      ...init,
      signal: controller.signal,
    });
  } finally {
    window.clearTimeout(timeoutId);
  }
}

/* ----------------------- */
/* Mapping (single place) */
/* ----------------------- */

export function mapBackendDevice(d: BackendDevice): Device {
  return mapBackendDeviceShape(d);
}

/* ----------------------- */

export async function getDevices(): Promise<Device[]> {
  const res = await apiFetch(`${DEVICE_SERVICE_BASE}/api/v1/devices`);
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }

  const json: DeviceApiResponse<BackendDevice[]> = await res.json();

  return (json.data || []).map(mapBackendDevice);
}

export async function createDevice(data: {
  device_name: string;
  device_type: string;
  device_id_class: "active" | "test" | "virtual";
  phase_type: "single" | "three";
  data_source_type: "metered" | "sensor";
  manufacturer?: string;
  model?: string;
  location?: string;
  plant_id: string;
}): Promise<Device> {
  const res = await apiFetch(`${DEVICE_SERVICE_BASE}/api/v1/devices`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    throw new Error(await readApiError(res));
  }
  const json = await res.json();
  return mapBackendDevice((json.data ?? json) as BackendDevice);
}

export async function getDeviceById(deviceId: string): Promise<Device | null> {
  if (!deviceId) return null;

  const res = await apiFetch(
    `${DEVICE_SERVICE_BASE}/api/v1/devices/${deviceId}`
  );

  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }

  const json: DeviceApiResponse<BackendDevice> = await res.json();

  return json.data ? mapBackendDevice(json.data) : null;
}

export async function deleteDevice(deviceId: string): Promise<void> {
  const res = await apiFetch(
    `${DEVICE_SERVICE_BASE}/api/v1/devices/${encodeURIComponent(deviceId)}`,
    { method: "DELETE" },
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.message ?? err.detail ?? `Failed to delete device: ${res.status}`);
  }
}

export async function getIdleConfig(deviceId: string): Promise<IdleConfig> {
  const res = await apiFetch(`${DEVICE_SERVICE_BASE}/api/v1/devices/${deviceId}/idle-config`);
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  const json = await res.json();
  return {
    device_id: json.device_id,
    idle_current_threshold: json.idle_current_threshold,
    configured: Boolean(json.configured),
  };
}

export async function saveIdleConfig(deviceId: string, idleCurrentThreshold: number): Promise<IdleConfig> {
  const res = await apiFetch(`${DEVICE_SERVICE_BASE}/api/v1/devices/${deviceId}/idle-config`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ idle_current_threshold: idleCurrentThreshold }),
  });
  if (!res.ok) {
    throw new Error(await readApiError(res));
  }
  const json = await res.json();
  return {
    device_id: json.device_id,
    idle_current_threshold: json.idle_current_threshold,
    configured: Boolean(json.configured),
  };
}

export async function getCurrentState(deviceId: string): Promise<CurrentState> {
  const res = await apiFetch(`${DEVICE_SERVICE_BASE}/api/v1/devices/${deviceId}/current-state`);
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  const json = await res.json();
  return {
    device_id: json.device_id,
    state: json.state ?? "unknown",
    current: json.current ?? null,
    voltage: json.voltage ?? null,
    threshold: json.threshold ?? null,
    timestamp: json.timestamp ?? null,
    current_field: json.current_field ?? null,
    voltage_field: json.voltage_field ?? null,
  };
}

export async function getIdleStats(deviceId: string): Promise<IdleStats> {
  const res = await apiFetch(`${DEVICE_SERVICE_BASE}/api/v1/devices/${deviceId}/idle-stats`);
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  const json = await res.json();
  return {
    device_id: json.device_id,
    today: json.today ?? null,
    month: json.month ?? null,
    tariff_configured: Boolean(json.tariff_configured),
    pf_estimated: Boolean(json.pf_estimated),
    threshold_configured: Boolean(json.threshold_configured),
    idle_current_threshold: json.idle_current_threshold ?? null,
    data_source_type: json.data_source_type,
    tariff_cache: json.tariff_cache,
    tariff_stale: json.tariff_stale,
  };
}

export async function getDeviceWasteConfig(deviceId: string): Promise<DeviceWasteConfig> {
  const res = await apiFetch(`${DEVICE_SERVICE_BASE}/api/v1/devices/${deviceId}/waste-config`, {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(await readApiError(res));
  }
  const json = await res.json();
  return {
    device_id: json.device_id,
    overconsumption_current_threshold_a: json.overconsumption_current_threshold_a ?? null,
    unoccupied_weekday_start_time: json.unoccupied_weekday_start_time ?? null,
    unoccupied_weekday_end_time: json.unoccupied_weekday_end_time ?? null,
    unoccupied_weekend_start_time: json.unoccupied_weekend_start_time ?? null,
    unoccupied_weekend_end_time: json.unoccupied_weekend_end_time ?? null,
    has_device_override: Boolean(json.has_device_override),
  };
}

export async function saveDeviceWasteConfig(
  deviceId: string,
  payload: {
    overconsumption_current_threshold_a: number | null;
    unoccupied_weekday_start_time: string | null;
    unoccupied_weekday_end_time: string | null;
    unoccupied_weekend_start_time: string | null;
    unoccupied_weekend_end_time: string | null;
  }
): Promise<DeviceWasteConfig> {
  const res = await apiFetch(`${DEVICE_SERVICE_BASE}/api/v1/devices/${deviceId}/waste-config`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(await readApiError(res));
  }
  const json = await res.json();
  return {
    device_id: json.device_id,
    overconsumption_current_threshold_a: json.overconsumption_current_threshold_a ?? null,
    unoccupied_weekday_start_time: json.unoccupied_weekday_start_time ?? null,
    unoccupied_weekday_end_time: json.unoccupied_weekday_end_time ?? null,
    unoccupied_weekend_start_time: json.unoccupied_weekend_start_time ?? null,
    unoccupied_weekend_end_time: json.unoccupied_weekend_end_time ?? null,
    has_device_override: Boolean(json.has_device_override),
  };
}

export async function getDashboardWidgetConfig(deviceId: string): Promise<DashboardWidgetConfig> {
  const res = await apiFetch(`${DEVICE_SERVICE_BASE}/api/v1/devices/${deviceId}/dashboard-widgets`, {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  const json = await res.json();
  return {
    device_id: json.device_id,
    available_fields: json.available_fields ?? [],
    selected_fields: json.selected_fields ?? [],
    effective_fields: json.effective_fields ?? [],
    default_applied: Boolean(json.default_applied),
  };
}

export async function saveDashboardWidgetConfig(
  deviceId: string,
  selectedFields: string[]
): Promise<DashboardWidgetConfig> {
  const res = await apiFetch(`${DEVICE_SERVICE_BASE}/api/v1/devices/${deviceId}/dashboard-widgets`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ selected_fields: selectedFields }),
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(body || `HTTP ${res.status}`);
  }
  const json = await res.json();
  return {
    device_id: json.device_id,
    available_fields: json.available_fields ?? [],
    selected_fields: json.selected_fields ?? [],
    effective_fields: json.effective_fields ?? [],
    default_applied: Boolean(json.default_applied),
  };
}


/* =====================================================
 * Shift Configuration API
 * ===================================================== */

export interface Shift {
  id: number;
  device_id: string;
  shift_name: string;
  shift_start: string;  // HH:MM format
  shift_end: string;    // HH:MM format
  maintenance_break_minutes: number;
  day_of_week: number | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ShiftCreate {
  shift_name: string;
  shift_start: string;
  shift_end: string;
  maintenance_break_minutes: number;
  day_of_week?: number | null;
  is_active?: boolean;
}

export interface UptimeData {
  device_id: string;
  uptime_percentage: number | null;
  total_planned_minutes: number;
  total_effective_minutes: number;
  actual_running_minutes?: number;
  shifts_configured: number;
  window_start?: string | null;
  window_end?: string | null;
  window_timezone?: string;
  data_coverage_pct?: number;
  data_quality?: "high" | "medium" | "low" | string;
  calculation_mode?: string;
  message: string;
}

function mapShift(s: Record<string, unknown>): Shift {
  return {
    id: Number(s.id ?? 0),
    device_id: String(s.device_id ?? ""),
    shift_name: String(s.shift_name ?? ""),
    shift_start: String(s.shift_start ?? ""),
    shift_end: String(s.shift_end ?? ""),
    maintenance_break_minutes: Number(s.maintenance_break_minutes ?? 0),
    day_of_week: s.day_of_week == null ? null : Number(s.day_of_week),
    is_active: Boolean(s.is_active),
    created_at: String(s.created_at ?? ""),
    updated_at: String(s.updated_at ?? ""),
  };
}

export async function getShifts(deviceId: string): Promise<Shift[]> {
  const res = await apiFetch(`${DEVICE_SERVICE_BASE}/api/v1/devices/${deviceId}/shifts`, {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  const json = await res.json();
  return (json.data || []).map(mapShift);
}

export async function createShift(deviceId: string, shift: ShiftCreate): Promise<Shift> {
  const res = await apiFetch(`${DEVICE_SERVICE_BASE}/api/v1/devices/${deviceId}/shifts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(shift),
  });
  if (!res.ok) {
    throw new Error(await readApiError(res));
  }
  const json = await res.json();
  return mapShift(json.data);
}

export async function updateShift(
  deviceId: string,
  shiftId: number,
  shift: Partial<ShiftCreate>
): Promise<Shift> {
  const res = await apiFetch(
    `${DEVICE_SERVICE_BASE}/api/v1/devices/${deviceId}/shifts/${shiftId}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(shift),
    }
  );
  if (!res.ok) {
    throw new Error(await readApiError(res));
  }
  const json = await res.json();
  return mapShift(json.data);
}

export async function deleteShift(deviceId: string, shiftId: number): Promise<void> {
  const res = await apiFetch(
    `${DEVICE_SERVICE_BASE}/api/v1/devices/${deviceId}/shifts/${shiftId}`,
    { method: "DELETE" }
  );
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
}

export async function getUptime(deviceId: string): Promise<UptimeData> {
  const res = await apiFetch(`${DEVICE_SERVICE_BASE}/api/v1/devices/${deviceId}/uptime`, {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return res.json();
}


/* =====================================================
 * Health Configuration API
 * ===================================================== */

export interface HealthConfig {
  id: number;
  device_id: string;
  parameter_name: string;
  normal_min: number | null;
  normal_max: number | null;
  weight: number;
  ignore_zero_value: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface HealthConfigCreate {
  parameter_name: string;
  normal_min?: number | null;
  normal_max?: number | null;
  weight: number;
  ignore_zero_value?: boolean;
  is_active?: boolean;
}

export interface WeightValidation {
  is_valid: boolean;
  total_weight: number;
  message: string;
  parameters: Array<{
    parameter_name: string;
    weight: number;
    is_active: boolean;
  }>;
}

export interface ParameterScore {
  parameter_name: string;
  telemetry_key?: string | null;
  value: number | null;
  raw_score: number | null;
  weighted_score: number;
  weight: number;
  status: string;
  status_color: string;
  resolution?: string | null;
  included_in_score?: boolean;
}

export interface HealthScore {
  device_id: string;
  health_score: number | null;
  status: string;
  status_color: string;
  message: string;
  machine_state: string;
  parameter_scores: ParameterScore[];
  total_weight_configured: number;
  parameters_included: number;
  parameters_skipped: number;
}

export type PerformanceTrendMetric = "health" | "uptime";
export type PerformanceTrendRange = "30m" | "1h" | "6h" | "24h" | "7d" | "30d";

export interface PerformanceTrendPoint {
  timestamp: string;
  health_score: number | null;
  uptime_percentage: number | null;
  planned_minutes: number;
  effective_minutes: number;
  break_minutes: number;
}

export interface PerformanceTrendFallbackPoint {
  timestamp: string;
  value: number;
}

export interface PerformanceTrendData {
  device_id: string;
  metric: PerformanceTrendMetric;
  range: PerformanceTrendRange;
  interval_minutes: number;
  timezone: string;
  points: PerformanceTrendPoint[];
  total_points: number;
  sampled_points: number;
  message: string;
  metric_message: string;
  range_start: string;
  range_end: string;
  is_stale: boolean;
  last_actual_timestamp: string | null;
  fallback_point: PerformanceTrendFallbackPoint | null;
}

export interface DashboardDeviceItem {
  device_id: string;
  device_name: string;
  device_type: string;
  plant_id?: string | null;
  runtime_status: string;
  location: string | null;
  first_telemetry_timestamp: string | null;
  last_seen_timestamp: string | null;
  health_score: number | null;
  uptime_percentage: number | null;
}

export interface DashboardSystemSummary {
  total_devices: number;
  running_devices: number;
  stopped_devices: number;
  devices_with_health_data: number;
  devices_with_uptime_configured: number;
  devices_missing_uptime_config: number;
  system_health: number | null;
  average_efficiency: number | null;
}

export interface DashboardAlertsSummary {
  active_alerts: number;
  alerts_triggered: number;
  alerts_cleared: number;
  rules_created: number;
}

export interface DashboardSummaryData {
  generated_at: string;
  service_started_at?: string | null;
  stale?: boolean;
  warnings?: string[];
  summary: DashboardSystemSummary;
  alerts: DashboardAlertsSummary;
  devices: DashboardDeviceItem[];
  cost_data_state?: "fresh" | "stale" | "unavailable";
  cost_data_reasons?: string[];
  cost_generated_at?: string | null;
  energy_widgets?: {
    month_energy_kwh: number;
    month_energy_cost_inr: number;
    today_energy_kwh: number;
    today_energy_cost_inr: number;
    today_loss_kwh: number;
    today_loss_cost_inr: number;
    generated_at: string;
    currency: string;
    data_quality: string;
    invariant_checks?: Record<string, unknown>;
    no_nan_inf?: boolean;
  };
}

export interface FleetSnapshotItem {
  device_id: string;
  device_name: string;
  device_type: string;
  plant_id?: string | null;
  runtime_status: string;
  load_state: DeviceLoadState;
  location: string | null;
  first_telemetry_timestamp: string | null;
  last_seen_timestamp: string | null;
  health_score: number | null;
  has_uptime_config: boolean;
  data_freshness_ts: string | null;
  version?: number;
}

export interface FleetSnapshotData {
  generated_at: string;
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  devices: FleetSnapshotItem[];
}

export interface FleetStreamEventData {
  id: string;
  event: "fleet_update" | "heartbeat";
  generated_at: string;
  freshness_ts: string;
  stale: boolean;
  warnings: string[];
  devices: FleetSnapshotItem[];
  partial?: boolean;
  version?: number;
}

export interface DashboardBootstrapData {
  generated_at: string;
  version: number;
  device: Device | null;
  telemetry: Array<Record<string, number | string | undefined> & { timestamp: string }>;
  uptime: UptimeData;
  shifts: Shift[];
  health_configs: HealthConfig[];
  health_score: HealthScore | null;
  widget_config: DashboardWidgetConfig | null;
  current_state: CurrentState | null;
  idle_stats: IdleStats | null;
  idle_config: IdleConfig | null;
  waste_config: DeviceWasteConfig | null;
  loss_stats: DeviceLossStats | null;
}

export interface TodayLossBreakdownRow {
  device_id: string;
  device_name: string;
  idle_kwh: number;
  idle_cost_inr: number;
  off_hours_kwh: number;
  off_hours_cost_inr: number;
  overconsumption_kwh: number;
  overconsumption_cost_inr: number;
  total_loss_kwh: number;
  total_loss_cost_inr: number;
  status: string;
  reason: string | null;
}

export interface TodayLossBreakdownData {
  generated_at: string;
  stale?: boolean;
  currency: string;
  cost_data_state?: "fresh" | "stale" | "unavailable";
  cost_data_reasons?: string[];
  cost_generated_at?: string | null;
  totals: {
    idle_kwh: number;
    idle_cost_inr: number;
    off_hours_kwh: number;
    off_hours_cost_inr: number;
    overconsumption_kwh: number;
    overconsumption_cost_inr: number;
    total_loss_kwh: number;
    total_loss_cost_inr: number;
    today_energy_kwh: number;
    today_energy_cost_inr: number;
  };
  rows: TodayLossBreakdownRow[];
  data_quality: string;
  warnings: string[];
}

export interface MonthlyEnergyCalendarData {
  year: number;
  month: number;
  currency: string;
  generated_at: string;
  stale?: boolean;
  warnings?: string[];
  cost_data_state?: "fresh" | "stale" | "unavailable";
  cost_data_reasons?: string[];
  cost_generated_at?: string | null;
  summary: {
    total_energy_kwh: number;
    total_energy_cost_inr: number;
  };
  days: Array<{
    date: string;
    energy_kwh: number;
    energy_cost_inr: number;
  }>;
  data_quality: string;
}

export interface TelemetryValues {
  values: Record<string, number>;
  machine_state?: string;
}

function mapHealthConfig(c: Record<string, unknown>): HealthConfig {
  return {
    id: Number(c.id ?? 0),
    device_id: String(c.device_id ?? ""),
    parameter_name: String(c.parameter_name ?? ""),
    normal_min: c.normal_min == null ? null : Number(c.normal_min),
    normal_max: c.normal_max == null ? null : Number(c.normal_max),
    weight: Number(c.weight ?? 0),
    ignore_zero_value: Boolean(c.ignore_zero_value),
    is_active: Boolean(c.is_active),
    created_at: String(c.created_at ?? ""),
    updated_at: String(c.updated_at ?? ""),
  };
}

export async function getHealthConfigs(deviceId: string): Promise<HealthConfig[]> {
  const res = await apiFetch(`${DEVICE_SERVICE_BASE}/api/v1/devices/${deviceId}/health-config`, {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  const json = await res.json();
  return (json.data || []).map(mapHealthConfig);
}

export async function createHealthConfig(
  deviceId: string,
  config: HealthConfigCreate
): Promise<HealthConfig> {
  const res = await apiFetch(
    `${DEVICE_SERVICE_BASE}/api/v1/devices/${deviceId}/health-config`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(config),
    }
  );
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  const json = await res.json();
  return mapHealthConfig(json.data);
}

export async function updateHealthConfig(
  deviceId: string,
  configId: number,
  config: Partial<HealthConfigCreate>
): Promise<HealthConfig> {
  const res = await apiFetch(
    `${DEVICE_SERVICE_BASE}/api/v1/devices/${deviceId}/health-config/${configId}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(config),
    }
  );
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  const json = await res.json();
  return mapHealthConfig(json.data);
}

export async function deleteHealthConfig(
  deviceId: string,
  configId: number
): Promise<void> {
  const res = await apiFetch(
    `${DEVICE_SERVICE_BASE}/api/v1/devices/${deviceId}/health-config/${configId}`,
    { method: "DELETE", cache: "no-store" }
  );
  // Backward-compatible idempotency: treat already-deleted as success.
  if (!res.ok && res.status !== 404) {
    throw new Error(`HTTP ${res.status}`);
  }
}

export async function validateHealthWeights(
  deviceId: string
): Promise<WeightValidation> {
  const res = await apiFetch(
    `${DEVICE_SERVICE_BASE}/api/v1/devices/${deviceId}/health-config/validate-weights`
  );
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return res.json();
}

export async function bulkCreateHealthConfigs(
  deviceId: string,
  configs: HealthConfigCreate[]
): Promise<HealthConfig[]> {
  const res = await apiFetch(
    `${DEVICE_SERVICE_BASE}/api/v1/devices/${deviceId}/health-config/bulk`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(configs),
    }
  );
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  const json = await res.json();
  return (json.data || []).map(mapHealthConfig);
}

export async function calculateHealthScore(
  deviceId: string,
  telemetry: TelemetryValues
): Promise<HealthScore> {
  const res = await apiFetch(
    `${DEVICE_SERVICE_BASE}/api/v1/devices/${deviceId}/health-score`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(telemetry),
    }
  );
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return res.json();
}

export async function getPerformanceTrends(
  deviceId: string,
  metric: PerformanceTrendMetric,
  range: PerformanceTrendRange
): Promise<PerformanceTrendData> {
  const query = new URLSearchParams({
    metric,
    range,
  });
  const res = await apiFetch(
    `${DEVICE_SERVICE_BASE}/api/v1/devices/${deviceId}/performance-trends?${query.toString()}`
  );
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return res.json();
}

export async function getDashboardSummary(plantId?: string | null): Promise<DashboardSummaryData> {
  const query = new URLSearchParams();
  if (plantId) {
    query.set("plant_id", plantId);
  }
  const url = query.size > 0
    ? `${DEVICE_SERVICE_BASE}/api/v1/devices/dashboard/summary?${query.toString()}`
    : `${DEVICE_SERVICE_BASE}/api/v1/devices/dashboard/summary`;
  const res = await fetchWithBackendSessionTimeout(url, {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  const json = await res.json();
  return {
    generated_at: json.generated_at,
    service_started_at: res.headers.get("x-service-started-at"),
    stale: Boolean(json.stale),
    warnings: json.warnings ?? [],
    summary: json.summary,
    alerts: json.alerts,
    devices: json.devices || [],
    cost_data_state: json.cost_data_state ?? "unavailable",
    cost_data_reasons: json.cost_data_reasons ?? [],
    cost_generated_at: json.cost_generated_at ?? null,
    energy_widgets: json.energy_widgets ?? undefined,
  };
}

export async function getFleetSnapshot(
  page: number,
  pageSize: number,
): Promise<FleetSnapshotData> {
  const query = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });
  const res = await fetchWithBackendSessionTimeout(`${DEVICE_SERVICE_BASE}/api/v1/devices/dashboard/fleet-snapshot?${query.toString()}`, {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  const json = await res.json();
  return {
    generated_at: json.generated_at,
    total: json.total ?? 0,
    page: json.page ?? 1,
    page_size: json.page_size ?? 50,
    total_pages: json.total_pages ?? 1,
    devices: json.devices ?? [],
  };
}

function parseFleetStreamChunk(
  chunk: string,
  onEvent: (payload: FleetStreamEventData) => void,
): void {
  const dataLines: string[] = [];

  for (const line of chunk.split("\n")) {
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim());
    }
  }

  if (dataLines.length === 0) {
    return;
  }

  const payload = JSON.parse(dataLines.join("\n")) as FleetStreamEventData;
  onEvent(payload);
}

export function connectFleetStream(params: FleetStreamParams): () => void {
  return createFleetStreamConnector()(params);
}

export function createFleetStreamConnector(
): (params: FleetStreamParams) => () => void {
  const deps = {
    refreshAccessToken: () => authApi.refreshAccessToken(),
    clearSession: () => authApi.clearSession(),
    scheduleReconnect: (callback: () => void, delayMs: number) => window.setTimeout(callback, delayMs),
    clearScheduledReconnect: (handle: unknown) => window.clearTimeout(handle as ReturnType<typeof window.setTimeout>),
    createAbortController: () => new AbortController(),
    createTextDecoder: () => new TextDecoder(),
    parseEventChunk: (chunk: string) => {
      let parsedPayload: FleetStreamEventData | null = null;
      parseFleetStreamChunk(chunk, (payload) => {
        parsedPayload = payload;
      });
      return parsedPayload;
    },
  };

  return (params) => {
    let currentLastEventId = params.lastEventId;

    const buildQuery = () => {
      const query = new URLSearchParams({
        page_size: String(params?.pageSize ?? 200),
      });
      if (params?.runtimeStatus) {
        query.append("runtime_status", params.runtimeStatus);
      }
      if (currentLastEventId) {
        query.append("last_event_id", currentLastEventId);
      }
      return query;
    };

    const reconnectableStream = createReconnectableFleetStream<FleetStreamEventData>({
      ...deps,
      streamFetch: (_input: string, init?: RequestInit) =>
        apiFetch(`${DEVICE_SERVICE_BASE}/api/v1/devices/dashboard/fleet-stream?${buildQuery().toString()}`, init),
      parseEventChunk: (chunk: string) => {
        let parsedPayload: FleetStreamEventData | null = null;
        parseFleetStreamChunk(chunk, (payload) => {
          if (payload?.id) {
            currentLastEventId = payload.id;
          }
          parsedPayload = payload;
        });
        return parsedPayload;
      },
    });

    return reconnectableStream({
      streamUrl: `${DEVICE_SERVICE_BASE}/api/v1/devices/dashboard/fleet-stream`,
      onEvent: params.onEvent,
      onError: params.onError,
      onOpen: params.onOpen,
      onReconnectStart: params.onReconnectStart,
      inactivityTimeoutMs: params.inactivityTimeoutMs,
    });
  };
}

export async function getDashboardBootstrap(deviceId: string): Promise<DashboardBootstrapData> {
  const res = await fetchWithBackendSessionTimeout(`${DEVICE_SERVICE_BASE}/api/v1/devices/${deviceId}/dashboard-bootstrap`, {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  const json = await res.json();
  return {
    generated_at: json.generated_at,
    version: Number(json.version || 0),
    device: json.device ? mapBackendDevice(json.device) : null,
    telemetry: json.telemetry ?? [],
    uptime: json.uptime ?? ({} as UptimeData),
    shifts: json.shifts ?? [],
    health_configs: json.health_configs ?? [],
    health_score: json.health_score ?? null,
    widget_config: json.widget_config ?? null,
    current_state: json.current_state ?? null,
    idle_stats: json.idle_stats ?? null,
    idle_config: json.idle_config ?? null,
    waste_config: json.waste_config ?? null,
    loss_stats: json.loss_stats ?? null,
  };
}

export async function getDeviceLossStats(deviceId: string): Promise<DeviceLossStats> {
  const res = await apiFetch(`${DEVICE_SERVICE_BASE}/api/v1/devices/${deviceId}/loss-stats`, {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  const json = await res.json();
  return {
    device_id: json.device_id,
    day_bucket: json.day_bucket,
    last_telemetry_ts: json.last_telemetry_ts ?? null,
    updated_at: json.updated_at ?? null,
    tariff_configured: Boolean(json.tariff_configured),
    currency: json.currency ?? "INR",
    today: {
      idle_kwh: Number(json.today?.idle_kwh ?? 0),
      idle_cost_inr: json.today?.idle_cost_inr == null ? null : Number(json.today.idle_cost_inr),
      off_hours_kwh: Number(json.today?.off_hours_kwh ?? 0),
      off_hours_cost_inr: json.today?.off_hours_cost_inr == null ? null : Number(json.today.off_hours_cost_inr),
      overconsumption_kwh: Number(json.today?.overconsumption_kwh ?? 0),
      overconsumption_cost_inr: json.today?.overconsumption_cost_inr == null ? null : Number(json.today.overconsumption_cost_inr),
      total_loss_kwh: Number(json.today?.total_loss_kwh ?? 0),
      total_loss_cost_inr: json.today?.total_loss_cost_inr == null ? null : Number(json.today.total_loss_cost_inr),
      today_energy_kwh: Number(json.today?.today_energy_kwh ?? 0),
      today_energy_cost_inr: json.today?.today_energy_cost_inr == null ? null : Number(json.today.today_energy_cost_inr),
    },
  };
}

export async function getTodayLossBreakdown(plantId?: string | null): Promise<TodayLossBreakdownData> {
  const query = new URLSearchParams();
  if (plantId) {
    query.set("plant_id", plantId);
  }
  const url = query.size > 0
    ? `${DEVICE_SERVICE_BASE}/api/v1/devices/dashboard/today-loss-breakdown?${query.toString()}`
    : `${DEVICE_SERVICE_BASE}/api/v1/devices/dashboard/today-loss-breakdown`;
  const res = await apiFetch(url, {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  const json = await res.json();
  return {
    generated_at: json.generated_at,
    stale: Boolean(json.stale),
    currency: json.currency ?? "INR",
    cost_data_state: json.cost_data_state ?? "unavailable",
    cost_data_reasons: json.cost_data_reasons ?? [],
    cost_generated_at: json.cost_generated_at ?? null,
    totals: json.totals,
    rows: json.rows ?? [],
    data_quality: json.data_quality ?? "ok",
    warnings: json.warnings ?? [],
  };
}

export async function getMonthlyEnergyCalendar(year: number, month: number): Promise<MonthlyEnergyCalendarData> {
  const query = new URLSearchParams({
    year: String(year),
    month: String(month),
  });
  const res = await apiFetch(`${DEVICE_SERVICE_BASE}/api/v1/devices/calendar/monthly-energy?${query.toString()}`, {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  const json = await res.json();
  return {
    year: json.year,
    month: json.month,
    currency: json.currency ?? "INR",
    generated_at: json.generated_at,
    stale: Boolean(json.stale),
    warnings: json.warnings ?? [],
    cost_data_state: json.cost_data_state ?? "unavailable",
    cost_data_reasons: json.cost_data_reasons ?? [],
    cost_generated_at: json.cost_generated_at ?? null,
    summary: json.summary,
    days: json.days ?? [],
    data_quality: json.data_quality ?? "ok",
  };
}
