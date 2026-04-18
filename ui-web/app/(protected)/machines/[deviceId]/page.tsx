"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";

import {
  getDeviceById,
  getDashboardBootstrap,
  Device,
  getIdleConfig,
  saveIdleConfig,
  getCurrentState,
  getDeviceLossStats,
  CurrentState,
  DeviceLossStats,
  getShifts,
  createShift,
  deleteShift,
  Shift,
  ShiftCreate,
  getUptime,
  UptimeData,
  getHealthConfigs,
  createHealthConfig,
  deleteHealthConfig,
  updateHealthConfig,
  HealthConfig,
  HealthConfigCreate,
  calculateHealthScore,
  HealthScore,
  ParameterScore,
  TelemetryValues,
  validateHealthWeights,
  WeightValidation,
  getPerformanceTrends,
  PerformanceTrendData,
  PerformanceTrendRange,
  PerformanceTrendMetric,
  DashboardWidgetConfig,
  getDashboardWidgetConfig,
  saveDashboardWidgetConfig,
} from "@/lib/deviceApi";
import {
  TelemetryPoint,
  getActivityEvents,
  getActivityUnreadCount,
  markAllActivityRead,
  clearActivityHistory,
  ActivityEvent,
} from "@/lib/dataApi";
import { DATA_SERVICE_BASE } from "@/lib/api";
import { buildPerformanceTrendDisplayModel } from "@/lib/performanceTrendDisplay";
import {
  findHealthConfigForMetric,
  findMatchingHealthConfigsForMetric,
  findParameterScoreForMetric,
  matchesHealthParameterKey,
} from "@/lib/healthScoring";
import { formatCurrencyValue, formatEnergyKwh } from "@/lib/presentation";
import {
  EXCLUSIVE_LOSS_BUCKET_HELP,
  OVERCONSUMPTION_THRESHOLD_HELP,
  deriveThresholdsFromFla,
  formatIdleThresholdPctLabel,
  getEngineeringSaveBlockReason,
  hasUnsavedEngineeringDraft,
  getOutsideShiftFinancialBucketMessage,
  parseEngineeringNumberDraft,
} from "@/lib/wasteSemantics";
import { getVisibleDeviceDetailTabs } from "@/lib/deviceDetailTabs";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { TimeSeriesChart } from "@/components/charts/telemetry-charts";
import { isPhaseDiagnosticField } from "@/lib/telemetryContract";
import { MachineRulesView } from "@/app/(protected)/machines/[deviceId]/rules/machine-rules-view";
import { formatIST, getRelativeTime } from "@/lib/utils";
import { ActivationTimestampField } from "@/components/devices/ActivationTimestampField";
import {
  getOperationalStatusMeta,
  mergeCurrentStateWithStability,
  resolveOperationalStatus,
  type DeviceLoadState,
  type DeviceOperationalStatus,
} from "@/lib/deviceStatus";
import { useAdaptivePolling } from "@/lib/useAdaptivePolling";
import { usePermissions } from "@/hooks/usePermissions";
import { ReadOnlyBanner } from "@/components/auth/ReadOnlyBanner";

const METRIC_LABELS: Record<string, string> = {
  power: "Power", voltage: "Voltage (Avg)", current: "Current (Avg)", temperature: "Temperature",
  current_l1: "Current L1", current_l2: "Current L2", current_l3: "Current L3",
  voltage_l1: "Voltage L1", voltage_l2: "Voltage L2", voltage_l3: "Voltage L3",
  pressure: "Pressure", humidity: "Humidity", vibration: "Vibration", frequency: "Frequency",
  power_factor: "Power Factor", speed: "Speed", torque: "Torque", oil_pressure: "Oil Pressure",
};

const METRIC_UNITS: Record<string, string> = {
  power: " W", voltage: " V", current: " A", temperature: " °C",
  pressure: " bar", humidity: " %", vibration: " mm/s", frequency: " Hz",
  power_factor: "", speed: " RPM", torque: " Nm", oil_pressure: " bar",
};

const METRIC_COLORS: Record<string, string> = {
  power: "#2563eb", voltage: "#d97706", current: "#7c3aed", temperature: "#dc2626",
  pressure: "#059669", humidity: "#0891b2", vibration: "#ea580c", frequency: "#4f46e5",
  power_factor: "#8b5cf6", speed: "#0d9488", torque: "#be185d", oil_pressure: "#65a30d",
};

const METRIC_RANGES: Record<string, [number, number]> = {
  power: [0, 500], voltage: [200, 250], current: [0, 20], temperature: [0, 120],
  pressure: [0, 10], humidity: [0, 100], vibration: [0, 10], frequency: [45, 55],
  power_factor: [0.8, 1.0], speed: [1000, 2000], torque: [0, 500], oil_pressure: [0, 5],
};

const DAYS_OF_WEEK = [
  { value: null, label: "All Days" },
  { value: 0, label: "Monday" }, { value: 1, label: "Tuesday" },
  { value: 2, label: "Wednesday" }, { value: 3, label: "Thursday" },
  { value: 4, label: "Friday" }, { value: 5, label: "Saturday" }, { value: 6, label: "Sunday" },
];

const TREND_RANGE_OPTIONS: { label: string; value: PerformanceTrendRange }[] = [
  { label: "30m", value: "30m" },
  { label: "1h", value: "1h" },
  { label: "6h", value: "6h" },
  { label: "24h", value: "24h" },
  { label: "7d", value: "7d" },
  { label: "30d", value: "30d" },
];

const RECENT_TELEMETRY_BUFFER_SIZE = 200;
const RECENT_TELEMETRY_PAGE_SIZE = 10;

type DevicePageTab = "overview" | "telemetry" | "parameters" | "rules";

type ShiftSegment = {
  day: number;
  start: number;
  end: number;
};

function toMinutes(timeValue: string): number | null {
  const parts = timeValue.split(":");
  if (parts.length < 2) return null;
  const hour = Number(parts[0]);
  const minute = Number(parts[1]);
  if (!Number.isFinite(hour) || !Number.isFinite(minute)) return null;
  if (hour < 0 || hour > 23 || minute < 0 || minute > 59) return null;
  return hour * 60 + minute;
}

function toDisplayTime(timeValue: string): string {
  const parts = timeValue.split(":");
  if (parts.length < 2) return timeValue;
  const hh = parts[0].padStart(2, "0");
  const mm = parts[1].padStart(2, "0");
  return `${hh}:${mm}`;
}

function isOvernightRange(startTime: string, endTime: string): boolean {
  const start = toMinutes(startTime);
  const end = toMinutes(endTime);
  if (start === null || end === null) return false;
  return end <= start;
}

function formatShiftRange(startTime: string, endTime: string): string {
  const overnight = isOvernightRange(startTime, endTime);
  return `${toDisplayTime(startTime)} - ${toDisplayTime(endTime)}${overnight ? " (+1 day)" : ""}`;
}

function buildShiftSegments(startTime: string, endTime: string, dayOfWeek: number | null): ShiftSegment[] {
  const start = toMinutes(startTime);
  const end = toMinutes(endTime);
  if (start === null || end === null || start === end) return [];

  const days = dayOfWeek === null ? [0, 1, 2, 3, 4, 5, 6] : [dayOfWeek];
  const segments: ShiftSegment[] = [];
  for (const day of days) {
    if (end > start) {
      segments.push({ day, start, end });
      continue;
    }
    segments.push({ day, start, end: 24 * 60 });
    segments.push({ day: (day + 1) % 7, start: 0, end });
  }
  return segments;
}

function hasSegmentOverlap(a: ShiftSegment, b: ShiftSegment): boolean {
  if (a.day !== b.day) return false;
  return a.start < b.end && b.start < a.end;
}

function findOverlapConflicts(candidate: ShiftCreate, existingShifts: Shift[]): Shift[] {
  const candidateSegments = buildShiftSegments(candidate.shift_start, candidate.shift_end, candidate.day_of_week ?? null);
  if (candidateSegments.length === 0) return [];

  return existingShifts.filter((shift) => {
    const shiftSegments = buildShiftSegments(shift.shift_start, shift.shift_end, shift.day_of_week);
    return candidateSegments.some((cand) => shiftSegments.some((seg) => hasSegmentOverlap(cand, seg)));
  });
}

function getDynamicMetrics(telemetry: TelemetryPoint[]): string[] {
  const latest = telemetry.at(-1);
  if (!latest) return [];
  const metrics = new Set<string>();
  for (const [key, value] of Object.entries(latest)) {
    if (key !== 'timestamp' && key !== 'device_id' && key !== 'schema_version' && 
        key !== 'enrichment_status' && key !== 'table' && typeof value === 'number') {
      metrics.add(key);
    }
  }
  return Array.from(metrics);
}

function getMetricData(telemetry: TelemetryPoint[], metric: string) {
  return telemetry
    .map((t) => {
      const value = t[metric];
      return typeof value === "number" ? { timestamp: t.timestamp, value } : null;
    })
    .filter((item): item is { timestamp: string; value: number } => item !== null);
}

function sortTelemetryAsc(items: TelemetryPoint[]): TelemetryPoint[] {
  return [...items].sort(
    (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
  );
}

function sortTelemetryDesc(items: TelemetryPoint[]): TelemetryPoint[] {
  return [...items].sort(
    (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
  );
}

function formatTimestamp(ts: string): string {
  return formatIST(ts, ts);
}

function formatMinutes(totalMinutes: number | null | undefined): string {
  if (typeof totalMinutes !== "number" || Number.isNaN(totalMinutes) || totalMinutes < 0) {
    return "—";
  }
  const rounded = Math.round(totalMinutes);
  const hrs = Math.floor(rounded / 60);
  const mins = rounded % 60;
  return `${hrs}h ${mins}m`;
}

function formatEventType(eventType: string): string {
  return eventType
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function UptimeCircle({ uptime, onClick }: { uptime: UptimeData | null; onClick: () => void }) {
  const percentage = uptime?.uptime_percentage ?? 0;
  const color = percentage >= 95 ? "#22c55e" : percentage >= 80 ? "#eab308" : "#ef4444";
  
  return (
    <div className="relative cursor-pointer group" onClick={onClick}>
      <div className="w-16 h-16">
        <svg className="w-full h-full transform -rotate-90">
          <circle cx="32" cy="32" r="28" stroke="#e2e8f0" strokeWidth="6" fill="none" />
          <circle cx="32" cy="32" r="28" stroke={color} strokeWidth="6" fill="none"
            strokeDasharray={`${(percentage / 100) * 176} 176`} className="transition-all duration-500" />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-xs font-bold">{percentage.toFixed(0)}%</span>
        </div>
      </div>
      
      <div className="absolute left-full top-1/2 -translate-y-1/2 ml-2 w-48 bg-white shadow-lg rounded-lg border p-3 opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all z-50">
        <p className="text-xs font-semibold text-slate-700 mb-2">Uptime Details</p>
        {uptime ? (
          <>
            <p className="text-xs text-slate-600">Active Shifts: <span className="font-medium">{uptime.shifts_configured}</span></p>
            {uptime.uptime_percentage === null ? (
              <p className="text-xs text-amber-700 mt-2">{uptime.message || "No active shift window right now."}</p>
            ) : (
              <>
                <p className="text-xs text-slate-600">Planned: <span className="font-medium">{formatMinutes(uptime.total_planned_minutes)}</span></p>
                <p className="text-xs text-slate-600">Effective: <span className="font-medium">{formatMinutes(uptime.total_effective_minutes)}</span></p>
                <p className="text-xs text-slate-600">Running: <span className="font-medium">{formatMinutes(uptime.actual_running_minutes)}</span></p>
                <p className="text-xs text-slate-500 mt-2">Uptime = running minutes / effective shift minutes.</p>
              </>
            )}
          </>
        ) : (
          <p className="text-xs text-slate-500">No shifts configured</p>
        )}
      </div>
    </div>
  );
}

function HealthScoreCircle({ healthScore, onClick }: { healthScore: HealthScore | null; onClick: () => void }) {
  const hasScore = typeof healthScore?.health_score === "number";
  const score = hasScore ? (healthScore?.health_score as number) : 0;
  const statusColor = healthScore?.status_color || "⚪";
  
  const colorMap: Record<string, string> = {
    "🟢": "#22c55e", "🟡": "#eab308", "🟠": "#f97316", "🔴": "#ef4444", "⚪": "#94a3b8"
  };
  const color = healthScore ? colorMap[statusColor] || "#94a3b8" : "#94a3b8";
  const isStandby = healthScore?.status === "Standby";
  
  return (
    <div className="relative cursor-pointer group" onClick={onClick}>
      <div className="w-16 h-16">
        <svg className="w-full h-full transform -rotate-90">
          <circle cx="32" cy="32" r="28" stroke="#e2e8f0" strokeWidth="6" fill="none" />
          <circle cx="32" cy="32" r="28" stroke={color} strokeWidth="6" fill="none"
            strokeDasharray={`${(score / 100) * 176} 176`} className="transition-all duration-500" />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-xs font-bold">{isStandby || !hasScore ? "—" : `${score.toFixed(0)}%`}</span>
          <span className="text-[10px]">{isStandby ? "Standby" : statusColor}</span>
        </div>
      </div>
      
      <div className="absolute left-full top-1/2 -translate-y-1/2 ml-2 w-56 bg-white shadow-lg rounded-lg border p-3 opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all z-50">
        <p className="text-xs font-semibold text-slate-700 mb-2">Health Score Details</p>
        {healthScore ? (
          <>
            <p className="text-xs text-slate-600">Status: <span className="font-medium">{healthScore.status} {healthScore.status_color}</span></p>
            <p className="text-xs text-slate-600">Machine State: <span className="font-medium">{healthScore.machine_state}</span></p>
            <p className="text-xs text-slate-600">Parameters: <span className="font-medium">{healthScore.parameters_included} included, {healthScore.parameters_skipped} skipped</span></p>
            <p className="text-xs text-slate-600">Total Weight: <span className="font-medium">{healthScore.total_weight_configured}%</span></p>
            {healthScore.parameter_scores.length > 0 && (
              <div className="mt-2 border-t pt-2">
                <p className="text-xs font-medium text-slate-700">Parameter Scores:</p>
                {healthScore.parameter_scores.slice(0, 5).map((p) => (
                  <p key={p.parameter_name} className="text-xs text-slate-600">
                    {p.parameter_name}: {p.raw_score !== null ? `${p.raw_score}%` : p.status} {p.status_color}
                  </p>
                ))}
              </div>
            )}
          </>
        ) : (
          <p className="text-xs text-slate-500">No health data</p>
        )}
      </div>
    </div>
  );
}

function OperationalStatusBadge({ status }: { status: DeviceOperationalStatus }) {
  const item = getOperationalStatusMeta(status);
  return (
    <span className={`inline-flex max-w-full items-center rounded-full border px-3 py-1 text-center text-xs font-semibold leading-tight [overflow-wrap:anywhere] ${item.className}`}>
      {item.label}
    </span>
  );
}

function getDetailedLoadStateLabel(state: DeviceLoadState | undefined): string {
  if (state === "running") return "In Load";
  if (state === "idle") return "Idle";
  if (state === "overconsumption") return "Overconsumption";
  if (state === "unloaded") return "Unloaded";
  return "Unknown";
}

function getBackendStatusBadge(statusColor: string | null | undefined): { color: string; bgColor: string } {
  if (statusColor === "🟢") return { color: "text-green-700", bgColor: "bg-green-100" };
  if (statusColor === "🟡") return { color: "text-yellow-700", bgColor: "bg-yellow-100" };
  if (statusColor === "🟠") return { color: "text-orange-700", bgColor: "bg-orange-100" };
  if (statusColor === "🔴") return { color: "text-red-700", bgColor: "bg-red-100" };
  return { color: "text-slate-600", bgColor: "bg-slate-100" };
}

function ParameterEfficiencyCard({
  metric, 
  value, 
  healthConfig,
  parameterScore,
  onConfigure 
}: { 
  metric: string; 
  value: number; 
  healthConfig: HealthConfig | null;
  parameterScore: ParameterScore | null;
  onConfigure: () => void;
}) {
  const { canEditDevice } = usePermissions();
  const fallbackRange = METRIC_RANGES[metric] || [0, 100];
  const min = healthConfig?.normal_min ?? fallbackRange[0];
  const max = healthConfig?.normal_max ?? fallbackRange[1];
  const denominator = Math.max(max - min, 1);
  const valuePct = Math.max(0, Math.min(100, ((value - min) / denominator) * 100));

  const normalMin = healthConfig?.normal_min ?? null;
  const normalMax = healthConfig?.normal_max ?? null;
  const hasNormalRange = normalMin !== null && normalMax !== null;
  const normalStartPct = hasNormalRange ? Math.max(0, Math.min(100, ((normalMin - min) / denominator) * 100)) : null;
  const normalEndPct = hasNormalRange ? Math.max(0, Math.min(100, ((normalMax - min) / denominator) * 100)) : null;

  const score = parameterScore?.raw_score ?? null;
  const status = getBackendStatusBadge(parameterScore?.status_color);
  const displayLabel = parameterScore?.status || (healthConfig ? "Awaiting backend score" : "Display only");
  const scoreLabel = score !== null ? `Score ${score.toFixed(0)}% • ${displayLabel}` : displayLabel;
  const telemetryLabel =
    parameterScore?.telemetry_key && !matchesHealthParameterKey(parameterScore.telemetry_key, metric)
      ? `Resolved from ${parameterScore.telemetry_key}`
      : null;

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <p className="text-[11px] uppercase tracking-[0.18em] font-semibold text-slate-500">
            {METRIC_LABELS[metric] || metric}
          </p>
          <p className="text-3xl font-bold text-slate-900 mt-2">
            {value.toFixed(2)}
            <span className="text-lg font-semibold text-slate-500 ml-1">{METRIC_UNITS[metric]?.trim() || ""}</span>
          </p>
        </div>
        {canEditDevice ? (
          <button
            onClick={onConfigure}
            className="text-xs font-medium px-2.5 py-1.5 rounded-md border border-slate-200 text-slate-600 hover:bg-slate-100"
          >
            {healthConfig ? "Edit Range" : "Set Range"}
          </button>
        ) : null}
      </div>

      <div className="relative h-3 rounded-full bg-slate-200 overflow-hidden">
        {hasNormalRange && normalStartPct !== null && normalEndPct !== null && (
          <div
            className="absolute top-0 h-full bg-emerald-100"
            style={{ left: `${Math.min(normalStartPct, normalEndPct)}%`, width: `${Math.abs(normalEndPct - normalStartPct)}%` }}
          />
        )}
        <div
          className="absolute left-0 top-0 h-full rounded-full transition-all duration-500"
          style={{
            width: `${valuePct}%`,
            background: "linear-gradient(90deg, #4f46e5 0%, #6366f1 70%, #818cf8 100%)",
          }}
        />
      </div>

      <div className="mt-3 grid grid-cols-1 gap-2 text-xs text-slate-600 sm:grid-cols-2 lg:grid-cols-3">
        <p>Min: <span className="font-semibold text-slate-800">{min.toFixed(2)}</span></p>
        <p>Max: <span className="font-semibold text-slate-800">{max.toFixed(2)}</span></p>
        <p className="text-right">
          Normal band:{" "}
          <span className="font-semibold text-slate-800">
            {hasNormalRange ? `${(normalMin as number).toFixed(2)}-${(normalMax as number).toFixed(2)}` : "Not set"}
          </span>
        </p>
      </div>

      <div className="mt-3 flex items-center justify-between">
        <div className={`text-xs px-2 py-1 rounded-full font-medium ${status.color} ${status.bgColor}`}>
          {scoreLabel}
        </div>
        <div className="text-xs text-slate-500 text-right">
          {healthConfig ? (
            <div>
              Weight: <span className="font-semibold text-slate-700">{healthConfig.weight}%</span>
            </div>
          ) : (
            <div>Display only</div>
          )}
          {telemetryLabel ? <div>{telemetryLabel}</div> : null}
        </div>
      </div>
    </div>
  );
}

function HealthConfigModal({ 
  isOpen, 
  onClose, 
  deviceId, 
  metric,
  existingConfig,
  allConfigs,
  onSave,
  onDelete 
}: { 
  isOpen: boolean; 
  onClose: () => void; 
  deviceId: string;
  metric: string;
  existingConfig: HealthConfig | null;
  allConfigs: HealthConfig[];
  onSave: (config: HealthConfigCreate) => void;
  onDelete: (configId: number) => Promise<void>;
}) {
  const { canDeleteDevice } = usePermissions();
  const initialFormData = useMemo<HealthConfigCreate>(() => {
    if (existingConfig) {
      return {
        parameter_name: existingConfig.parameter_name,
        normal_min: existingConfig.normal_min ?? undefined,
        normal_max: existingConfig.normal_max ?? undefined,
        weight: existingConfig.weight,
        ignore_zero_value: existingConfig.ignore_zero_value,
        is_active: existingConfig.is_active,
      };
    }

    const defaultRanges: Record<string, [number, number]> = {
      pressure: [2, 6],
      temperature: [20, 60],
      vibration: [0, 3],
      power: [100, 400],
      voltage: [210, 240],
      current: [2, 15],
      frequency: [48, 52],
      power_factor: [0.85, 1.0],
      speed: [1200, 1800],
      torque: [50, 300],
      oil_pressure: [1, 4],
      humidity: [30, 70],
    };
    const defaults = defaultRanges[metric];
    return {
      parameter_name: metric,
      normal_min: defaults?.[0] ?? undefined,
      normal_max: defaults?.[1] ?? undefined,
      weight: 0,
      ignore_zero_value: false,
      is_active: true,
    };
  }, [existingConfig, metric]);

  const [formData, setFormData] = useState<HealthConfigCreate>(initialFormData);
  const [deleteInFlight, setDeleteInFlight] = useState(false);
  
  if (!isOpen) return null;
  
  const totalWeight = allConfigs
    .filter(c => c.is_active && !matchesHealthParameterKey(c.parameter_name, metric))
    .reduce((sum, c) => sum + c.weight, 0) + formData.weight;
  
  const otherWeightsSum = allConfigs
    .filter(c => c.is_active && !matchesHealthParameterKey(c.parameter_name, metric))
    .reduce((sum, c) => sum + c.weight, 0);
  
  const remainingWeight = 100 - otherWeightsSum;
  const currentWeight = existingConfig?.weight || 0;
  const maxAllowedWeight = remainingWeight + currentWeight;
  const isWeightValid = Math.abs(totalWeight - 100) < 0.01;
  
  const handleWeightChange = (value: number) => {
    // Allow any value that's within the allowed range (remaining + current weight)
    // This allows decreasing weight when editing
    if (!isNaN(value) && value >= 0 && value <= maxAllowedWeight) {
      setFormData({ ...formData, weight: value });
    }
  };
  
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 w-full max-w-md max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold">Configure Health: {metric}</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600">✕</button>
        </div>
        
        <div className="space-y-4">
          <div className="p-3 bg-blue-50 rounded text-sm">
            <p className="font-medium text-blue-800 mb-2">Normal Range</p>
            <p className="text-blue-600 text-xs">Values inside this band receive the full 100% parameter score.</p>
          </div>
          
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className="block text-sm font-medium mb-1">Normal Min</label>
              <input type="number" step="0.1" value={formData.normal_min ?? ""} onChange={(e) => setFormData({ ...formData, normal_min: e.target.value ? parseFloat(e.target.value) : undefined })} className="w-full px-3 py-2 border rounded-md" />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Normal Max</label>
              <input type="number" step="0.1" value={formData.normal_max ?? ""} onChange={(e) => setFormData({ ...formData, normal_max: e.target.value ? parseFloat(e.target.value) : undefined })} className="w-full px-3 py-2 border rounded-md" />
            </div>
          </div>
          
            <div className="border-t pt-4">
              <label className="block text-sm font-medium mb-1">
                Weight (%) 
                {existingConfig && <span className="text-xs text-slate-500 font-normal ml-2">(Saved: {currentWeight}%, Max: {maxAllowedWeight}%)</span>}
              </label>
              <input 
                type="number" 
                min="0" 
                max={maxAllowedWeight}
                step="1" 
                value={formData.weight} 
                onChange={(e) => handleWeightChange(parseFloat(e.target.value) || 0)}
                className="w-full px-3 py-2 border rounded-md" 
              />
              <div className={`text-xs mt-2 p-2 rounded ${isWeightValid ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"}`}>
                <p>Total Weight: <strong>{totalWeight.toFixed(1)}%</strong> / 100%</p>
                <p>Remaining: <strong>{remainingWeight.toFixed(1)}%</strong></p>
                {!isWeightValid && <p className="mt-1">⚠️ Total must equal 100% to calculate health score</p>}
                {isWeightValid && <p className="mt-1">✓ Weight configured correctly</p>}
              </div>
            </div>
          
          <div className="flex items-center gap-2">
            <input type="checkbox" id="ignoreZero" checked={formData.ignore_zero_value} onChange={(e) => setFormData({ ...formData, ignore_zero_value: e.target.checked })} className="rounded" />
            <label htmlFor="ignoreZero" className="text-sm">Ignore zero values (exclude from scoring when machine is off)</label>
          </div>
          
          {existingConfig && canDeleteDevice && (
            <Button
              variant="danger"
              className="w-full"
              disabled={deleteInFlight}
              onClick={async () => {
                if (deleteInFlight) return;
                setDeleteInFlight(true);
                try {
                  await onDelete(existingConfig.id);
                } finally {
                  setDeleteInFlight(false);
                }
              }}
            >
              {deleteInFlight ? "Deleting..." : "Delete Configuration"}
            </Button>
          )}
        </div>
        
        <div className="flex gap-2 mt-6">
          <Button variant="outline" onClick={onClose} className="flex-1">Cancel</Button>
          <Button onClick={() => onSave(formData)} className="flex-1">
            {isWeightValid ? "Save" : `Save (${totalWeight.toFixed(0)}%)`}
          </Button>
        </div>
        {!isWeightValid && (
          <p className="text-xs text-center mt-2 text-amber-600">
            ⚠️ Note: Health score will only calculate when total weight = 100%
          </p>
        )}
      </div>
    </div>
  );
}

export default function MachineDashboardPage() {
  const { canEditDevice, canDeleteDevice, canCreateRule, isReadOnly } = usePermissions();
  const params = useParams();
  const deviceId = (params.deviceId as string) || "";

  const [machine, setMachine] = useState<Device | null>(null);
  const [telemetry, setTelemetry] = useState<TelemetryPoint[]>([]);
  const [telemetryStreamRows, setTelemetryStreamRows] = useState<TelemetryPoint[]>([]);
  const [telemetryTablePage, setTelemetryTablePage] = useState(1);
  const [shifts, setShifts] = useState<Shift[]>([]);
  const [uptime, setUptime] = useState<UptimeData | null>(null);
  const [healthConfigs, setHealthConfigs] = useState<HealthConfig[]>([]);
  const [healthScore, setHealthScore] = useState<HealthScore | null>(null);
  const [currentState, setCurrentState] = useState<CurrentState | null>(null);
  const [lossStats, setLossStats] = useState<DeviceLossStats | null>(null);
  const [fullLoadCurrentInput, setFullLoadCurrentInput] = useState<string>("");
  const [persistedFullLoadCurrent, setPersistedFullLoadCurrent] = useState<number | null>(null);
  const [idleThresholdPctInput, setIdleThresholdPctInput] = useState<string>("");
  const [persistedIdleThresholdPct, setPersistedIdleThresholdPct] = useState<number | null>(null);
  const [engineeringSaveMessage, setEngineeringSaveMessage] = useState<string>("");
  const [engineeringSaving, setEngineeringSaving] = useState(false);
  const [widgetConfig, setWidgetConfig] = useState<DashboardWidgetConfig | null>(null);
  const [selectedWidgetFields, setSelectedWidgetFields] = useState<string[]>([]);
  const [widgetSaveMessage, setWidgetSaveMessage] = useState<string>("");
  const [widgetSaving, setWidgetSaving] = useState(false);
  const [widgetDirty, setWidgetDirty] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<DevicePageTab>("overview");
  const [showAddShift, setShowAddShift] = useState(false);
  const [showHealthConfig, setShowHealthConfig] = useState(false);
  const [selectedMetric, setSelectedMetric] = useState<string>("");
  const [showAlertHistory, setShowAlertHistory] = useState(false);
  const [activityEvents, setActivityEvents] = useState<ActivityEvent[]>([]);
  const [unreadEventCount, setUnreadEventCount] = useState(0);
  const [trendMetric, setTrendMetric] = useState<PerformanceTrendMetric>("health");
  const [trendRange, setTrendRange] = useState<PerformanceTrendRange>("1h");
  const [trendLoading, setTrendLoading] = useState(false);
  const [trendError, setTrendError] = useState<string | null>(null);
  const [trendData, setTrendData] = useState<PerformanceTrendData | null>(null);
  const [newShift, setNewShift] = useState<ShiftCreate>({
    shift_name: "", shift_start: "09:00", shift_end: "17:00", maintenance_break_minutes: 0, day_of_week: null, is_active: true,
  });
  const latestTelemetryTimestampRef = useRef<string | null>(null);
  const telemetryWsRef = useRef<WebSocket | null>(null);
  const visibleTabs: ReadonlyArray<{ id: DevicePageTab; label: string }> = getVisibleDeviceDetailTabs({
    isReadOnly,
    canEditDevice,
    canCreateRule,
  });
  const activeTabVisible = visibleTabs.some((tab) => tab.id === activeTab);

  const fetchData = async (isInitial = false) => {
    try {
      const bootstrap = await getDashboardBootstrap(deviceId);
      const machineData = bootstrap.device ?? (await getDeviceById(deviceId));
      const ascTelemetry = sortTelemetryAsc(bootstrap.telemetry ?? []);
      const descTelemetry = sortTelemetryDesc(bootstrap.telemetry ?? []);
      setMachine(machineData);
      setTelemetry(ascTelemetry);
      setTelemetryStreamRows(descTelemetry.slice(0, RECENT_TELEMETRY_BUFFER_SIZE));
      setTelemetryTablePage(1);
      latestTelemetryTimestampRef.current = descTelemetry[0]?.timestamp || null;
      setUptime(bootstrap.uptime);
      setShifts(bootstrap.shifts);
      setHealthConfigs(bootstrap.health_configs);
      setWidgetConfig(bootstrap.widget_config);
      setCurrentState((previous) =>
        mergeCurrentStateWithStability(previous, bootstrap.current_state, {
          runtimeStatus: machineData?.runtime_status,
          source: "bootstrap",
        }) ?? null,
      );
      setLossStats(bootstrap.loss_stats);
      if (isInitial || !widgetDirty) {
        setSelectedWidgetFields(bootstrap.widget_config?.effective_fields || []);
        setWidgetDirty(false);
      }
      setHealthScore(bootstrap.health_score);
      setFullLoadCurrentInput(
        bootstrap.idle_config?.full_load_current_a != null
          ? String(bootstrap.idle_config.full_load_current_a)
          : ""
      );
      setPersistedFullLoadCurrent(
        bootstrap.idle_config?.full_load_current_a != null
          ? Number(bootstrap.idle_config.full_load_current_a)
          : null,
      );
      setIdleThresholdPctInput(
        bootstrap.idle_config?.idle_threshold_pct_of_fla != null
          ? String(bootstrap.idle_config.idle_threshold_pct_of_fla)
          : ""
      );
      setPersistedIdleThresholdPct(
        bootstrap.idle_config?.idle_threshold_pct_of_fla != null
          ? Number(bootstrap.idle_config.idle_threshold_pct_of_fla)
          : null,
      );
      
      setError(null);
    } catch (err) {
      if (isInitial) setError(err instanceof Error ? err.message : "Failed to fetch data");
    } finally {
      if (isInitial) setLoading(false);
    }
  };

  const connectTelemetryStream = () => {
    if (!deviceId || typeof window === "undefined") return;
    if (telemetryWsRef.current) {
      telemetryWsRef.current.close();
      telemetryWsRef.current = null;
    }
    const wsProto = window.location.protocol === "https:" ? "wss" : "ws";
    const wsUrl = `${wsProto}://${window.location.host}${DATA_SERVICE_BASE}/ws/telemetry/${deviceId}`;
    const ws = new WebSocket(wsUrl);
    telemetryWsRef.current = ws;

    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload?.type !== "telemetry" || !payload?.data) return;
        const latest = {
          ...(payload.data || {}),
          timestamp: payload.timestamp || new Date().toISOString(),
        } as TelemetryPoint;
        if (!latest.timestamp || latestTelemetryTimestampRef.current === latest.timestamp) return;
        latestTelemetryTimestampRef.current = latest.timestamp;
        setTelemetryStreamRows((prev) => sortTelemetryDesc([latest, ...prev]).slice(0, RECENT_TELEMETRY_BUFFER_SIZE));
        setTelemetry((prev) => sortTelemetryAsc([...prev, latest]).slice(-100));
      } catch (err) {
        console.error("Telemetry WS parse error:", err);
      }
    };
    ws.onerror = () => {
      ws.close();
    };
  };

  const loadActivityHistory = async () => {
    try {
      const [eventsResult, unreadCount] = await Promise.all([
        getActivityEvents({ deviceId, page: 1, pageSize: 25 }),
        getActivityUnreadCount(deviceId),
      ]);
      setActivityEvents(eventsResult.data);
      setUnreadEventCount(unreadCount);
    } catch (err) {
      console.error("Failed to load activity history:", err);
    }
  };

  const loadPerformanceTrends = async () => {
    try {
      setTrendLoading(true);
      setTrendError(null);
      const data = await getPerformanceTrends(deviceId, trendMetric, trendRange);
      setTrendData(data);
    } catch (err) {
      setTrendError(err instanceof Error ? err.message : "Failed to load performance trends");
    } finally {
      setTrendLoading(false);
    }
  };

  const loadIdleConfig = async () => {
    try {
      const config = await getIdleConfig(deviceId);
      setFullLoadCurrentInput(
        config.full_load_current_a != null
          ? String(config.full_load_current_a)
          : ""
      );
      setPersistedFullLoadCurrent(
        config.full_load_current_a != null
          ? Number(config.full_load_current_a)
          : null,
      );
      setIdleThresholdPctInput(
        config.idle_threshold_pct_of_fla != null
          ? String(config.idle_threshold_pct_of_fla)
          : ""
      );
      setPersistedIdleThresholdPct(
        config.idle_threshold_pct_of_fla != null
          ? Number(config.idle_threshold_pct_of_fla)
          : null,
      );
    } catch (err) {
      console.error("Failed to load idle config:", err);
    }
  };

  const loadCurrentState = async () => {
    try {
      const state = await getCurrentState(deviceId);
      setCurrentState((previous) =>
        mergeCurrentStateWithStability(previous, state, {
          runtimeStatus: machine?.runtime_status,
          source: "current_state_poll",
        }) ?? null,
      );
    } catch (err) {
      console.error("Failed to load current state:", err);
    }
  };

  const loadLossStats = async () => {
    try {
      const stats = await getDeviceLossStats(deviceId);
      setLossStats(stats);
    } catch (err) {
      console.error("Failed to load device loss stats:", err);
    }
  };

  const reconcileAfterCrud = async (options?: { refreshShifts?: boolean; refreshHealthConfigs?: boolean }) => {
    try {
      const tasks: Promise<unknown>[] = [getUptime(deviceId)];
      if (options?.refreshShifts) tasks.push(getShifts(deviceId));
      if (options?.refreshHealthConfigs) tasks.push(getHealthConfigs(deviceId));

      const results = await Promise.all(tasks);
      setUptime(results[0] as UptimeData);
      let nextIndex = 1;
      if (options?.refreshShifts) {
        setShifts(results[nextIndex] as Shift[]);
        nextIndex += 1;
      }
      if (options?.refreshHealthConfigs) {
        setHealthConfigs(results[nextIndex] as HealthConfig[]);
      }
    } catch {
      // Keep optimistic state and let periodic polling reconcile eventually.
    }

    const latest = telemetryStreamRows[0];
    if (latest) {
      const values: Record<string, number> = {};
      for (const [key, value] of Object.entries(latest)) {
        if (typeof value === "number" && Number.isFinite(value)) {
          values[key] = value;
        }
      }
      if (Object.keys(values).length > 0) {
        try {
          const score = await calculateHealthScore(deviceId, { values, machine_state: "RUNNING" } as TelemetryValues);
          setHealthScore(score);
        } catch {
          // Non-blocking reconciliation.
        }
      }
    }
    void loadPerformanceTrends();
  };

  useEffect(() => {
    if (!deviceId) return;
    fetchData(true);
    connectTelemetryStream();
    return () => {
      if (telemetryWsRef.current) {
        telemetryWsRef.current.close();
        telemetryWsRef.current = null;
      }
    };
  }, [deviceId]);

  useAdaptivePolling(
    () => {
      if (!deviceId) return;
      void reconcileAfterCrud({ refreshShifts: true, refreshHealthConfigs: true });
      void loadCurrentState();
    },
    30000,
    90000
  );

  useAdaptivePolling(
    () => {
      if (!deviceId) return;
      void loadLossStats();
    },
    60000,
    180000
  );

  useAdaptivePolling(
    () => {
      if (!deviceId) return;
      void loadActivityHistory();
    },
    6000,
    20000
  );

  useEffect(() => {
    if (!deviceId) return;
    void loadActivityHistory();
  }, [deviceId]);

  useEffect(() => {
    if (!deviceId) return;
    loadPerformanceTrends();
  }, [deviceId, trendMetric, trendRange]);

  useEffect(() => {
    const totalPages = Math.max(1, Math.ceil(telemetryStreamRows.length / RECENT_TELEMETRY_PAGE_SIZE));
    setTelemetryTablePage((current) => Math.min(current, totalPages));
  }, [telemetryStreamRows.length]);

  const handleAddShift = async () => {
    if (newShift.shift_start === newShift.shift_end) {
      alert("Shift start and end times cannot be the same.");
      return;
    }
    if (shiftOverlapConflicts.length > 0) {
      alert("Shift overlaps with existing shifts. Please pick a non-overlapping time.");
      return;
    }
    try {
      const created = await createShift(deviceId, newShift);
      setShifts((prev) => [...prev, created].sort((a, b) => a.shift_start.localeCompare(b.shift_start)));
      setShowAddShift(false);
      setNewShift({ shift_name: "", shift_start: "09:00", shift_end: "17:00", maintenance_break_minutes: 0, day_of_week: null, is_active: true });
      void reconcileAfterCrud({ refreshShifts: true });
    } catch (err) { alert("Failed: " + (err as Error).message); }
  };

  const handleDeleteShift = async (shiftId: number) => {
    if (!confirm("Delete this shift?")) return;
    const previous = shifts;
    setShifts((prev) => prev.filter((shift) => shift.id !== shiftId));
    try {
      await deleteShift(deviceId, shiftId);
      void reconcileAfterCrud({ refreshShifts: true });
    } catch (err) {
      setShifts(previous);
      alert("Failed: " + (err as Error).message);
    }
  };

  const handleSaveHealthConfig = async (config: HealthConfigCreate) => {
    try {
      const existing = findHealthConfigForMetric(config.parameter_name, healthConfigs);
      if (existing) {
        const updated = await updateHealthConfig(deviceId, existing.id, config);
        setHealthConfigs((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
      } else {
        const created = await createHealthConfig(deviceId, config);
        setHealthConfigs((prev) => [...prev.filter((item) => item.id !== created.id), created]);
      }
      setShowHealthConfig(false);
      setSelectedMetric("");
      void reconcileAfterCrud({ refreshHealthConfigs: true });
    } catch (err) { alert("Failed: " + (err as Error).message); }
  };

  const handleDeleteHealthConfig = async (configId: number) => {
    const previous = healthConfigs;
    const previousHealthScore = healthScore;
    setHealthConfigs((prev) => prev.filter((cfg) => cfg.id !== configId));
    setHealthScore(null);
    try {
      await deleteHealthConfig(deviceId, configId);
      setShowHealthConfig(false);
      setSelectedMetric("");
      void reconcileAfterCrud({ refreshHealthConfigs: true });
    } catch (err) {
      setHealthConfigs(previous);
      setHealthScore(previousHealthScore);
      alert("Failed: " + (err as Error).message);
    }
  };

  const handleSaveEngineeringConfig = async () => {
    const fullLoadCurrent = parsedFullLoadCurrentDraft;
    const idleThresholdPct = resolvedIdleThresholdPctDraft;
    if (fullLoadCurrent == null || engineeringSaveBlockReason) {
      return;
    }
    try {
      setEngineeringSaving(true);
      setEngineeringSaveMessage("");
      await saveIdleConfig(deviceId, {
        full_load_current_a: fullLoadCurrent,
        idle_threshold_pct_of_fla: idleThresholdPct,
      });
      await Promise.all([loadIdleConfig(), loadCurrentState(), loadLossStats()]);
      setEngineeringSaveMessage("FLA-based load classification saved.");
    } catch (err) {
      alert("Failed: " + (err as Error).message);
    } finally {
      setEngineeringSaving(false);
    }
  };

  const handleToggleWidgetField = (field: string) => {
    setWidgetSaveMessage("");
    setWidgetDirty(true);
    setSelectedWidgetFields((prev) => {
      if (prev.includes(field)) {
        return prev.filter((f) => f !== field);
      }
      return [...prev, field];
    });
  };

  const handleSaveWidgetConfig = async () => {
    try {
      setWidgetSaving(true);
      setWidgetSaveMessage("");
      const saved = await saveDashboardWidgetConfig(deviceId, selectedWidgetFields);
      setWidgetConfig(saved);
      setSelectedWidgetFields(saved.effective_fields || []);
      setWidgetSaveMessage("Widget configuration saved.");
      setWidgetDirty(false);
    } catch (err) {
      alert("Failed: " + (err as Error).message);
    } finally {
      setWidgetSaving(false);
    }
  };

  const handleMarkAllRead = async () => {
    try {
      await markAllActivityRead(deviceId);
      await loadActivityHistory();
    } catch (err) {
      alert("Failed: " + (err as Error).message);
    }
  };

  const handleClearHistory = async () => {
    if (!confirm("Clear all alert history for this machine?")) return;
    try {
      await clearActivityHistory(deviceId);
      await loadActivityHistory();
    } catch (err) {
      alert("Failed: " + (err as Error).message);
    }
  };

  if (loading) return <div className="p-8"><div className="flex items-center justify-center h-64"><div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div></div></div>;
  if (error || !machine) return <div className="p-8"><div className="bg-red-50 border p-6 rounded"><h2 className="text-red-800 font-semibold">Error</h2><p className="text-red-600">{error || "Not found"}</p><Link href="/machines"><Button className="mt-4">Back</Button></Link></div></div>;

  const latestTelemetry = telemetry.at(-1);
  const dynamicMetrics = getDynamicMetrics(telemetry);
  const telemetryBufferedRowCount = telemetryStreamRows.length;
  const telemetryTableTotalPages = Math.max(1, Math.ceil(telemetryBufferedRowCount / RECENT_TELEMETRY_PAGE_SIZE));
  const telemetryTableCurrentPage = Math.min(telemetryTablePage, telemetryTableTotalPages);
  const telemetryTableStartIndex = (telemetryTableCurrentPage - 1) * RECENT_TELEMETRY_PAGE_SIZE;
  const telemetryTableVisibleRows = telemetryStreamRows.slice(
    telemetryTableStartIndex,
    telemetryTableStartIndex + RECENT_TELEMETRY_PAGE_SIZE,
  );
  const effectiveWidgetFields = widgetConfig?.effective_fields || dynamicMetrics;
  const selectedWidgetFieldSet = new Set(selectedWidgetFields);
  const visibleOverviewMetrics = effectiveWidgetFields.filter((field) => dynamicMetrics.includes(field));
  const healthPercent = typeof healthScore?.health_score === "number" ? healthScore.health_score : null;
  const uptimePercent = typeof uptime?.uptime_percentage === "number" ? uptime.uptime_percentage : null;
  const trendDisplay = buildPerformanceTrendDisplayModel(trendData, trendMetric);
  const effectiveLoadState = (currentState?.state ?? "unknown") as DeviceLoadState;
  const operationalStatus = resolveOperationalStatus({
    runtimeStatus: machine.runtime_status,
    loadState: currentState?.state,
    currentBand: currentState?.current_band,
    hasTelemetry: Boolean(machine.last_seen_timestamp),
  });
  const operationalStatusMeta = getOperationalStatusMeta(operationalStatus);
  const effectiveLoadStateLabel = getDetailedLoadStateLabel(effectiveLoadState);
  const currentBandLabel =
    currentState?.current_band === "in_load"
      ? "In Load"
      : currentState?.current_band === "overconsumption"
        ? "Overconsumption"
        : currentState?.current_band === "idle"
          ? "Idle"
          : currentState?.current_band === "unloaded"
            ? "Unloaded"
            : "Unknown";
  const noActiveShiftWindow = uptime?.uptime_percentage == null;
  const outsideShiftFinancialBucketMessage = noActiveShiftWindow
    ? getOutsideShiftFinancialBucketMessage(effectiveLoadStateLabel)
    : null;
  const parsedFullLoadCurrentDraft = parseEngineeringNumberDraft(fullLoadCurrentInput);
  const parsedIdleThresholdPctDraft = parseEngineeringNumberDraft(idleThresholdPctInput);
  const resolvedIdleThresholdPctDraft =
    idleThresholdPctInput.trim().length > 0
      ? parsedIdleThresholdPctDraft
      : (persistedIdleThresholdPct ?? 0.25);
  const engineeringSaveBlockReason = getEngineeringSaveBlockReason(
    parsedFullLoadCurrentDraft,
    resolvedIdleThresholdPctDraft,
  );
  const fullLoadCurrentDraftDiffersFromSaved = hasUnsavedEngineeringDraft(
    fullLoadCurrentInput,
    persistedFullLoadCurrent,
  );
  const idleThresholdPctDraftDiffersFromSaved = hasUnsavedEngineeringDraft(
    idleThresholdPctInput,
    persistedIdleThresholdPct,
  );
  const thresholdPreview = deriveThresholdsFromFla(
    parsedFullLoadCurrentDraft,
    resolvedIdleThresholdPctDraft,
  );
  const shiftTimeEqual = newShift.shift_start === newShift.shift_end;
  const shiftOverlapConflicts = findOverlapConflicts(newShift, shifts);
  const shiftFormError = shiftTimeEqual
    ? "Start and end cannot be the same."
    : shiftOverlapConflicts.length > 0
      ? `Overlaps with: ${shiftOverlapConflicts
          .map((s) => `${s.shift_name} (${formatShiftRange(s.shift_start, s.shift_end)})`)
          .join(", ")}`
      : "";
  const shiftFormBlocked = !newShift.shift_name || shiftTimeEqual || shiftOverlapConflicts.length > 0;

  return (
    <div className="section-spacing">
      <ReadOnlyBanner />
      <div className="w-full">
        <div className="mb-8">
          <div className="flex items-center gap-2 text-sm text-slate-500 mb-4">
            <Link href="/machines" className="hover:text-slate-900">Machines</Link><span>/</span><span className="text-slate-900">{machine.name}</span>
          </div>
          <div className="relative rounded-3xl border border-slate-200 bg-gradient-to-b from-white to-slate-50/70 p-6 md:p-8 shadow-sm">
            <div className="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-6">
              <div className="min-w-0 flex-1">
                <h1 className="text-4xl font-bold tracking-tight text-slate-900">{machine.name}</h1>
                <p
                  className="mt-1 break-all font-mono text-sm text-slate-500 sm:text-base lg:text-lg"
                  title={machine.id}
                >
                  {machine.id}
                </p>
                <ActivationTimestampField
                  label="Activated"
                  timestamp={machine.first_telemetry_timestamp}
                  emptyText="Not activated yet"
                  className="mt-2 flex items-center gap-2 text-sm text-slate-500"
                  labelClassName="font-medium text-slate-700"
                  valueClassName="text-slate-500"
                />
                {machine.last_seen_timestamp ? (
                  <p className="text-sm text-slate-500 mt-2">
                    Last seen: {formatIST(machine.last_seen_timestamp)}
                  </p>
                ) : (
                  <p className="text-sm text-slate-500 mt-2">Last seen: No data received</p>
                )}
              </div>

              <div className="flex flex-wrap items-center justify-end gap-3 self-start">
                <button
                  type="button"
                  onClick={() => setShowAlertHistory((prev) => !prev)}
                  className="relative inline-flex items-center justify-center w-11 h-11 rounded-xl border border-slate-200 bg-white hover:bg-slate-50"
                  title="Machine alert history"
                >
                  <svg className="w-5 h-5 text-slate-700" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M15 17h5l-1.4-1.4A2 2 0 0 1 18 14.2V11a6 6 0 1 0-12 0v3.2a2 2 0 0 1-.6 1.4L4 17h5" />
                    <path d="M10 17a2 2 0 0 0 4 0" />
                  </svg>
                  {unreadEventCount > 0 && (
                    <span className="absolute -top-1 -right-1 min-w-5 h-5 px-1 rounded-full bg-red-600 text-white text-[10px] leading-5 text-center">
                      {unreadEventCount > 99 ? "99+" : unreadEventCount}
                    </span>
                  )}
                </button>
                <StatusBadge status={machine.runtime_status} />
                <OperationalStatusBadge status={operationalStatus} />
              </div>
            </div>

            <div className="mt-7 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
              <div className="rounded-xl border border-slate-200 bg-white p-4">
                <p className="text-xs uppercase tracking-[0.14em] text-slate-500 font-semibold">Name</p>
                <p className="text-xl font-semibold text-slate-900 mt-2">{machine.name}</p>
              </div>
              <div className="rounded-xl border border-slate-200 bg-white p-4">
                <p className="text-xs uppercase tracking-[0.14em] text-slate-500 font-semibold">Status</p>
                <p
                  className={`mt-2 text-xl font-bold leading-tight [overflow-wrap:anywhere] sm:text-2xl ${
                    operationalStatusMeta.className.split(" ").find((token) => token.startsWith("text-")) || "text-slate-900"
                  }`}
                  title={operationalStatusMeta.label}
                >
                  {operationalStatusMeta.label}
                </p>
              </div>
              <div className="rounded-xl border border-slate-200 bg-white p-4">
                <p className="text-xs uppercase tracking-[0.14em] text-slate-500 font-semibold">ID</p>
                <p
                  className="mt-2 break-all font-mono text-sm font-semibold leading-snug text-slate-800 sm:text-base"
                  title={machine.id}
                >
                  {machine.id}
                </p>
              </div>
              <div className="rounded-xl border border-slate-200 bg-white p-4">
                <p className="text-xs uppercase tracking-[0.14em] text-slate-500 font-semibold">Type</p>
                <p className="text-xl font-semibold text-slate-900 mt-2 capitalize">{machine.type || "—"}</p>
              </div>
              <div className="relative group rounded-xl border border-slate-200 bg-white p-4 cursor-help">
                <p className="text-xs uppercase tracking-[0.14em] text-slate-500 font-semibold">Uptime</p>
                <p className="text-3xl font-bold text-slate-900 mt-2">{uptimePercent !== null ? `${uptimePercent.toFixed(1)}%` : "—"}</p>
                <p className="text-[11px] text-slate-500 mt-1">
                  {uptimePercent !== null ? "Hover for calc details" : (uptime?.message || "No active shift window")}
                </p>
                <div className="pointer-events-none absolute left-1/2 top-full z-30 mt-2 w-72 -translate-x-1/2 rounded-xl border border-slate-200 bg-white p-3 shadow-xl opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all">
                  <p className="text-xs font-semibold text-slate-700 mb-2">Uptime Calculation</p>
                  {uptime ? (
                    <>
                      <p className="text-xs text-slate-600">Active shifts: <span className="font-medium">{uptime.shifts_configured}</span></p>
                      {uptime.uptime_percentage === null ? (
                        <p className="text-xs text-amber-700 mt-1">{uptime.message || "No active shift window right now."}</p>
                      ) : (
                        <>
                          <p className="text-xs text-slate-600">Planned duration: <span className="font-medium">{formatMinutes(uptime.total_planned_minutes)}</span></p>
                          <p className="text-xs text-slate-600">Effective duration: <span className="font-medium">{formatMinutes(uptime.total_effective_minutes)}</span></p>
                          <p className="text-xs text-slate-600">Actual running: <span className="font-medium">{formatMinutes(uptime.actual_running_minutes)}</span></p>
                          {uptime.window_start && uptime.window_end && (
                            <p className="text-xs text-slate-600">
                              Shift window: <span className="font-medium">{formatIST(uptime.window_start, "—")} → {formatIST(uptime.window_end, "—")}</span>
                            </p>
                          )}
                          <p className="text-xs text-slate-500 mt-2">Formula: uptime = running minutes / effective shift minutes.</p>
                        </>
                      )}
                    </>
                  ) : (
                    <p className="text-xs text-slate-500">No shift configuration found.</p>
                  )}
                </div>
              </div>
              <div className="relative group rounded-xl border border-slate-200 bg-white p-4 cursor-help">
                <p className="text-xs uppercase tracking-[0.14em] text-slate-500 font-semibold">Health Score</p>
                <p className={`text-5xl font-extrabold mt-1 ${healthPercent !== null && healthPercent >= 70 ? "text-emerald-400" : healthPercent !== null ? "text-orange-500" : "text-slate-400"}`}>
                  {healthPercent !== null ? `${healthPercent.toFixed(0)}%` : "—"}
                </p>
                <p className="text-[11px] text-slate-500 mt-1">Hover for calc details</p>
                <div className="pointer-events-none absolute right-0 top-full z-30 mt-2 w-80 rounded-xl border border-slate-200 bg-white p-3 shadow-xl opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all">
                  <p className="text-xs font-semibold text-slate-700 mb-2">Health Score Breakdown</p>
                  {healthScore ? (
                    <>
                      <p className="text-xs text-slate-600">Status: <span className="font-medium">{healthScore.status}</span></p>
                      <p className="text-xs text-slate-600">Machine state: <span className="font-medium">{healthScore.machine_state}</span></p>
                      <p className="text-xs text-slate-600">Parameters used: <span className="font-medium">{healthScore.parameters_included}</span>, skipped: <span className="font-medium">{healthScore.parameters_skipped}</span></p>
                      <p className="text-xs text-slate-600">Configured weight total: <span className="font-medium">{healthScore.total_weight_configured}%</span></p>
                      <p className="text-xs text-slate-500 mt-2">Health = sum of each parameter score multiplied by its configured weight.</p>
                      <div className="mt-2 border-t border-slate-100 pt-2 space-y-1">
                        {healthScore.parameter_scores.slice(0, 4).map((p) => (
                          <p key={p.parameter_name} className="text-xs text-slate-600">
                            {p.parameter_name}: {p.raw_score !== null ? `${p.raw_score.toFixed(1)}%` : p.status} ({p.weight}% wt)
                          </p>
                        ))}
                      </div>
                    </>
                  ) : (
                    <p className="text-xs text-slate-500">No health data available.</p>
                  )}
                </div>
              </div>
            </div>

            <div className="mt-4 text-sm text-slate-600">
              <span className="font-medium text-slate-700">Location:</span> {machine.location || "—"}
            </div>
            {outsideShiftFinancialBucketMessage && (
              <div className="mt-4 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                {outsideShiftFinancialBucketMessage}
              </div>
            )}

            <div className="mt-5 rounded-2xl border border-slate-200 bg-white p-4">
              <p className="text-xs uppercase tracking-[0.14em] text-slate-500 font-semibold">Waste & Loss Today</p>
              <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <div className="rounded-xl border border-slate-200 p-3">
                  <p className="text-xs text-slate-500 uppercase tracking-wide">Idle Loss</p>
                  <p className="text-lg font-semibold text-slate-900 mt-1">{formatEnergyKwh(Number(lossStats?.today.idle_kwh || 0))}</p>
                  <p className="text-xs text-slate-500 mt-1">
                    {lossStats?.tariff_configured
                      ? formatCurrencyValue(Number(lossStats?.today.idle_cost_inr || 0), lossStats?.currency || "INR")
                      : "Set tariff in Settings"}
                  </p>
                </div>
                <div className="rounded-xl border border-slate-200 p-3">
                  <p className="text-xs text-slate-500 uppercase tracking-wide">Off-hours Loss</p>
                  <p className="text-lg font-semibold text-slate-900 mt-1">{formatEnergyKwh(Number(lossStats?.today.off_hours_kwh || 0))}</p>
                  <p className="text-xs text-slate-500 mt-1">
                    {lossStats?.tariff_configured
                      ? formatCurrencyValue(Number(lossStats?.today.off_hours_cost_inr || 0), lossStats?.currency || "INR")
                      : "Set tariff in Settings"}
                  </p>
                </div>
                <div className="rounded-xl border border-slate-200 p-3">
                  <p className="text-xs text-slate-500 uppercase tracking-wide">Overconsumption Loss</p>
                  <p className="text-lg font-semibold text-slate-900 mt-1">{formatEnergyKwh(Number(lossStats?.today.overconsumption_kwh || 0))}</p>
                  <p className="text-xs text-slate-500 mt-1">
                    {lossStats?.tariff_configured
                      ? formatCurrencyValue(Number(lossStats?.today.overconsumption_cost_inr || 0), lossStats?.currency || "INR")
                      : "Set tariff in Settings"}
                  </p>
                </div>
                <div className="rounded-xl border border-slate-200 p-3 bg-slate-50">
                  <p className="text-xs text-slate-500 uppercase tracking-wide">Total Loss</p>
                  <p className="text-lg font-semibold text-slate-900 mt-1">{formatEnergyKwh(Number(lossStats?.today.total_loss_kwh || 0))}</p>
                  <p className="text-xs text-slate-500 mt-1">
                    {lossStats?.tariff_configured
                      ? formatCurrencyValue(Number(lossStats?.today.total_loss_cost_inr || 0), lossStats?.currency || "INR")
                      : "Set tariff in Settings"}
                  </p>
                </div>
              </div>
              <p className="text-xs text-slate-500 mt-3">
                Today energy: {formatEnergyKwh(Number(lossStats?.today.today_energy_kwh || 0))}
                {lossStats?.last_telemetry_ts ? ` · Last telemetry ${formatIST(lossStats.last_telemetry_ts)}` : ""}
              </p>
              <p className="text-xs text-slate-500 mt-2">{EXCLUSIVE_LOSS_BUCKET_HELP}</p>
              {outsideShiftFinancialBucketMessage && (
                <p className="text-xs text-amber-700 mt-2">{outsideShiftFinancialBucketMessage}</p>
              )}
            </div>

            {showAlertHistory && (
              <div className="absolute right-3 top-16 z-40 w-[calc(100vw-1.5rem)] max-w-[460px] max-h-[520px] overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xl sm:right-6">
                <div className="px-4 py-3 border-b border-slate-200 flex items-center justify-between">
                  <div>
                    <p className="text-sm font-semibold text-slate-900">Machine Alerts</p>
                    <p className="text-xs text-slate-500">{machine.id}</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setShowAlertHistory(false)}
                    className="text-slate-400 hover:text-slate-700"
                  >
                    ✕
                  </button>
                </div>
                <div className="max-h-[380px] overflow-y-auto p-3 space-y-3">
                  {activityEvents.length === 0 ? (
                    <div className="text-center text-sm text-slate-500 py-8">No alert history</div>
                  ) : (
                    activityEvents.map((event) => (
                      <div key={event.eventId} className={`rounded-lg border p-3 ${event.isRead ? "bg-slate-50 border-slate-200" : "bg-red-50 border-red-200"}`}>
                        <div className="flex items-center justify-between gap-2">
                          <p className="text-sm font-semibold text-slate-900">{event.title}</p>
                          <span className="text-[11px] px-2 py-0.5 rounded bg-slate-100 text-slate-700">
                            {formatEventType(event.eventType)}
                          </span>
                        </div>
                        <p className="text-xs text-slate-600 mt-1">{event.message}</p>
                        <p className="text-[11px] text-slate-500 mt-2">{formatTimestamp(event.createdAt)}</p>
                      </div>
                    ))
                  )}
                </div>
                <div className="px-4 py-3 border-t border-slate-200 flex items-center justify-between gap-2">
                  <Button variant="outline" size="sm" onClick={handleMarkAllRead}>Mark all read</Button>
                  <Button variant="danger" size="sm" onClick={handleClearHistory}>Clear history</Button>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="border-b border-slate-200 mb-6">
          <nav className="flex gap-8">
            {visibleTabs.map((tab) => (
              <button key={tab.id} onClick={() => setActiveTab(tab.id)}
                className={`pb-4 text-sm font-medium border-b-2 ${activeTab === tab.id ? "border-blue-600 text-blue-600" : "border-transparent text-slate-500 hover:text-slate-700"}`}>
                {tab.label}
              </button>
            ))}
          </nav>
        </div>

        {(activeTab === "overview" || !activeTabVisible) && (
          <div className="space-y-6">
            {visibleOverviewMetrics.length > 0 && (
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
                {visibleOverviewMetrics.map((metric) => {
                  const value = latestTelemetry?.[metric];
                  if (typeof value !== 'number') return null;
                  const healthConfigForMetric = findHealthConfigForMetric(metric, healthConfigs);
                  const parameterScoreForMetric = findParameterScoreForMetric(metric, healthScore?.parameter_scores || []);
                  return (
                    <ParameterEfficiencyCard
                      key={metric}
                      metric={metric}
                      value={value}
                      healthConfig={healthConfigForMetric}
                      parameterScore={parameterScoreForMetric}
                      onConfigure={() => { setSelectedMetric(metric); setShowHealthConfig(true); }}
                    />
                  );
                })}
              </div>
            )}

            {telemetry.length > 0 && visibleOverviewMetrics.length > 0 && (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {visibleOverviewMetrics.map((metric) => {
                  const data = getMetricData(telemetry, metric);
                  if (data.length === 0) return null;
                  return <Card key={metric}><CardHeader><CardTitle>{METRIC_LABELS[metric] || metric} Trend</CardTitle></CardHeader><CardContent><TimeSeriesChart data={data} color={METRIC_COLORS[metric] || "#2563eb"} unit={METRIC_UNITS[metric] || ""} /></CardContent></Card>;
                })}
              </div>
            )}

            <Card>
              <CardHeader className="flex flex-row items-center justify-between gap-4">
                <div>
                  <CardTitle>Performance Trends</CardTitle>
                  <p className="text-sm text-slate-500 mt-1">Recent telemetry-derived {trendMetric} trend</p>
                </div>
                <div className="flex items-center gap-2 flex-wrap justify-end">
                  <div className="inline-flex rounded-lg border border-slate-200 p-1">
                    {([
                      { value: "health", label: "Health" },
                      { value: "uptime", label: "Uptime" },
                    ] as { value: PerformanceTrendMetric; label: string }[]).map((item) => (
                      <button
                        key={item.value}
                        type="button"
                        onClick={() => setTrendMetric(item.value)}
                        className={`px-3 py-1.5 text-sm rounded-md ${
                          trendMetric === item.value
                            ? "bg-blue-600 text-white"
                            : "text-slate-600 hover:bg-slate-100"
                        }`}
                      >
                        {item.label}
                      </button>
                    ))}
                  </div>
                  <div className="inline-flex rounded-lg border border-slate-200 p-1">
                    {TREND_RANGE_OPTIONS.map((item) => (
                      <button
                        key={item.value}
                        type="button"
                        onClick={() => setTrendRange(item.value)}
                        className={`px-2.5 py-1.5 text-sm rounded-md ${
                          trendRange === item.value
                            ? "bg-slate-800 text-white"
                            : "text-slate-600 hover:bg-slate-100"
                        }`}
                      >
                        {item.label}
                      </button>
                    ))}
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                {trendLoading ? (
                  <div className="h-64 flex items-center justify-center text-slate-500">Loading trends...</div>
                ) : trendError ? (
                  <div className="h-64 flex items-center justify-center text-red-600">{trendError}</div>
                ) : trendDisplay.empty ? (
                  <div className="h-64 flex flex-col items-center justify-center text-slate-500">
                    <p>No {trendMetric} trend data available.</p>
                    <p className="text-sm mt-1">{trendDisplay.message || "Configure health/shift settings and wait for trend snapshots."}</p>
                  </div>
                ) : (
                  <div className="space-y-3">
                    <TimeSeriesChart
                      data={trendDisplay.hasMeasuredData ? trendDisplay.chartData : trendDisplay.staleChartData}
                      color={trendMetric === "health" ? "#10b981" : "#2563eb"}
                      unit="%"
                      showArea={trendDisplay.hasMeasuredData}
                      strokeDasharray={trendDisplay.hasFallbackOnly ? "8 6" : undefined}
                      lineName={trendDisplay.hasFallbackOnly ? "Last known value" : undefined}
                      title={`${trendMetric === "health" ? "Health Score" : "Uptime"} (${trendRange})`}
                    />
                    {trendDisplay.hasFallbackOnly && (
                      <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                        <p className="font-medium">{trendDisplay.message}</p>
                        {trendDisplay.staleLabel && (
                          <p className="mt-1 text-amber-800">{trendDisplay.staleLabel}</p>
                        )}
                      </div>
                    )}
                    {trendDisplay.hasMeasuredData && trendData?.metric_message && (
                      <p className="text-xs text-slate-500">{trendData.metric_message}</p>
                    )}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        )}

        {activeTabVisible && activeTab === "telemetry" && (
          <div className="space-y-6">
            {telemetryStreamRows.length === 0 ? <Card><CardContent className="py-12 text-center text-slate-500">No data</CardContent></Card> : (
              <Card>
                <CardHeader className="flex flex-row items-center justify-between">
                  <div>
                    <CardTitle>Recent Telemetry</CardTitle>
                    <p className="text-xs text-slate-400 mt-1">
                      Auto-refresh every 1s • {telemetryBufferedRowCount} buffered rows • Page {telemetryTableCurrentPage} of {telemetryTableTotalPages}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={telemetryTableCurrentPage <= 1}
                      onClick={() => setTelemetryTablePage((prev) => Math.max(1, prev - 1))}
                    >
                      Previous
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={telemetryTableCurrentPage >= telemetryTableTotalPages}
                      onClick={() => setTelemetryTablePage((prev) => Math.min(telemetryTableTotalPages, prev + 1))}
                    >
                      Next
                    </Button>
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="overflow-x-auto">
                    <table className="min-w-full divide-y divide-slate-200">
                      <thead className="bg-slate-50"><tr>
                        <th className="px-6 py-3 text-left text-xs font-medium text-slate-500">Timestamp</th>
                        {dynamicMetrics.map((m) => (
                          <th key={m} className="px-6 py-3 text-left text-xs font-medium text-slate-500">
                            {METRIC_LABELS[m] || m}{isPhaseDiagnosticField(m) ? <span className="block text-[10px] font-normal text-slate-400">Diagnostic</span> : null}
                          </th>
                        ))}
                      </tr></thead>
                      <tbody className="bg-white divide-y">
                        {telemetryTableVisibleRows.map((point, i) => (
                          <tr key={i} className={telemetryTableCurrentPage === 1 && i === 0 ? "bg-blue-50" : ""}>
                            <td className="px-6 py-3 text-sm font-mono">{formatTimestamp(point.timestamp)}</td>
                            {dynamicMetrics.map((m) => {
                              const value = point[m];
                              return <td key={m} className="px-6 py-3 text-sm">{typeof value === "number" ? value.toFixed(2) : "—"}</td>;
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div className="mt-4 flex items-center justify-between text-sm text-slate-500">
                    <span>Showing rows {telemetryTableStartIndex + 1}-{Math.min(telemetryTableStartIndex + telemetryTableVisibleRows.length, telemetryBufferedRowCount)} of {telemetryBufferedRowCount}</span>
                    <span>Newest rows continue to stream into the buffer at the top.</span>
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
        )}

        {activeTabVisible && activeTab === "parameters" && (
          <div className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>Telemetry Widgets</CardTitle>
                <p className="text-sm text-slate-600">
                  Select telemetry widgets to show on this machine dashboard.
                </p>
              </CardHeader>
              <CardContent>
                {widgetConfig && widgetConfig.available_fields.length > 0 ? (
                  <>
                    <div className="flex flex-wrap gap-3">
                      {widgetConfig.available_fields.map((field) => {
                        const selected = selectedWidgetFieldSet.has(field);
                        return (
                          <button
                            key={field}
                            type="button"
                            onClick={() => handleToggleWidgetField(field)}
                            className={`inline-flex items-center gap-2 rounded-full border px-4 py-2 text-sm font-medium transition ${
                              selected
                                ? "border-blue-300 bg-blue-50 text-blue-700"
                                : "border-slate-300 bg-white text-slate-600 hover:bg-slate-50"
                            }`}
                          >
                            <span className={`inline-flex h-4 w-4 items-center justify-center rounded border text-xs ${
                              selected ? "border-blue-500 bg-blue-600 text-white" : "border-slate-400 text-transparent"
                            }`}>
                              ✓
                            </span>
                            <span
                              className="h-2.5 w-2.5 rounded-full"
                              style={{ backgroundColor: METRIC_COLORS[field] || "#64748b" }}
                            />
                            {METRIC_LABELS[field] || field}
                          </button>
                        );
                      })}
                    </div>
                    <div className="mt-4 flex items-center gap-3">
                      <Button onClick={handleSaveWidgetConfig} disabled={widgetSaving || !widgetDirty}>
                        {widgetSaving ? "Saving..." : "Save Widgets"}
                      </Button>
                      {widgetDirty && (
                        <p className="text-xs text-amber-700">
                          Unsaved changes
                        </p>
                      )}
                      {widgetConfig.default_applied && (
                        <p className="text-xs text-slate-500">
                          Default mode active: all discovered widgets are shown until you save.
                        </p>
                      )}
                      {widgetSaveMessage && (
                        <p className="text-xs text-emerald-700">{widgetSaveMessage}</p>
                      )}
                    </div>
                  </>
                ) : (
                  <p className="text-sm text-slate-500">
                    No numeric telemetry fields discovered yet. Start telemetry to configure widgets.
                  </p>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex flex-row items-center justify-between">
                <CardTitle>Shift Configuration</CardTitle>
                <Button onClick={() => setShowAddShift(!showAddShift)}>{showAddShift ? "Cancel" : "+ Add Shift"}</Button>
              </CardHeader>
              <CardContent>
                {showAddShift && (
                  <div className="bg-slate-50 p-4 rounded-lg mb-6 space-y-4">
                    <p className="text-xs text-slate-600">
                      Rule: overlaps are not allowed. Touching boundaries are allowed (for example, 09:00-10:00 and 10:00-11:00). Overnight shifts are shown as <span className="font-semibold">(+1 day)</span>.
                    </p>
                    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                      <div><label className="block text-sm font-medium mb-1">Shift Name</label><input type="text" value={newShift.shift_name} onChange={(e) => setNewShift({ ...newShift, shift_name: e.target.value })} placeholder="e.g., Morning Shift" className="w-full px-3 py-2 border rounded-md" /></div>
                      <div><label className="block text-sm font-medium mb-1">Day of Week</label><select value={newShift.day_of_week ?? ""} onChange={(e) => setNewShift({ ...newShift, day_of_week: e.target.value ? parseInt(e.target.value) : null })} className="w-full px-3 py-2 border rounded-md">{DAYS_OF_WEEK.map(d => <option key={d.value ?? "all"} value={d.value ?? ""}>{d.label}</option>)}</select></div>
                      <div><label className="block text-sm font-medium mb-1">Start Time</label><input type="time" value={newShift.shift_start} onChange={(e) => setNewShift({ ...newShift, shift_start: e.target.value })} className="w-full px-3 py-2 border rounded-md" /></div>
                      <div><label className="block text-sm font-medium mb-1">End Time</label><input type="time" value={newShift.shift_end} onChange={(e) => setNewShift({ ...newShift, shift_end: e.target.value })} className="w-full px-3 py-2 border rounded-md" /></div>
                      <div><label className="block text-sm font-medium mb-1">Maintenance Break (min)</label><input type="number" min="0" max="480" value={newShift.maintenance_break_minutes} onChange={(e) => setNewShift({ ...newShift, maintenance_break_minutes: parseInt(e.target.value) || 0 })} className="w-full px-3 py-2 border rounded-md" /></div>
                    </div>
                    {shiftFormError && (
                      <p className="text-sm text-red-600">{shiftFormError}</p>
                    )}
                    <Button onClick={handleAddShift} disabled={shiftFormBlocked}>Save Shift</Button>
                  </div>
                )}
                {shifts.length === 0 ? <div className="text-center py-8 text-slate-500">No shifts configured</div> : (
                  <div className="space-y-4">
                    {shifts.map((shift) => (
                      <div key={shift.id} className={`flex items-center justify-between p-4 rounded-lg border ${shift.is_active ? "bg-white" : "bg-slate-50 opacity-60"}`}>
                        <div>
                          <div className="flex items-center gap-2"><h3 className="font-medium">{shift.shift_name}</h3>{!shift.is_active && <span className="text-xs bg-slate-200 px-2 py-0.5 rounded">Inactive</span>}</div>
                          <p className="text-sm text-slate-500 mt-1">
                            {formatShiftRange(shift.shift_start, shift.shift_end)}
                            {isOvernightRange(shift.shift_start, shift.shift_end) && (
                              <span className="ml-2 inline-flex rounded bg-indigo-100 px-2 py-0.5 text-[11px] font-medium text-indigo-700">Overnight shift</span>
                            )}
                            {shift.maintenance_break_minutes > 0 && <span className="ml-2">(Break: {shift.maintenance_break_minutes} min)</span>}
                          </p>
                          <p className="text-xs text-slate-400 mt-1">{DAYS_OF_WEEK.find(d => d.value === shift.day_of_week)?.label || "All Days"}</p>
                        </div>
                        {canDeleteDevice ? (
                          <Button variant="danger" size="sm" onClick={() => handleDeleteShift(shift.id)}>Delete</Button>
                        ) : null}
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Parameter Health Configuration</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="mb-4 p-4 bg-blue-50 rounded-lg">
                  <p className="text-sm text-blue-800"><strong>Health Score:</strong> Each configured parameter gets a score of 100, 50, or 0 based on whether the value is in range, near range, or outside tolerance. The overall health score is the weighted sum of those parameter scores.</p>
                  <p className="text-sm text-blue-800 mt-1"><strong>Machine State:</strong> Health scoring runs for RUNNING, IDLE, and UNLOAD. For OFF and POWER CUT, the score shows as &quot;Standby&quot;.</p>
                  <p className="text-sm text-blue-800 mt-1"><strong>Weights:</strong> All active parameter weights must sum to 100%.</p>
                </div>
                
                {dynamicMetrics.length > 0 ? (
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {dynamicMetrics.map((metric) => {
                  const config = findHealthConfigForMetric(metric, healthConfigs);
                  const matchingConfigs = findMatchingHealthConfigsForMetric(metric, healthConfigs);
                  return (
                    <div key={metric} className={`p-4 rounded-lg border ${config?.is_active ? "bg-white" : "bg-slate-50 opacity-60"}`}>
                          <div className="flex items-center justify-between mb-2">
                            <h4 className="font-medium">{METRIC_LABELS[metric] || metric}</h4>
                            {matchingConfigs.length > 1 ? (
                              <span className="text-xs bg-amber-100 text-amber-700 px-2 py-0.5 rounded">Duplicate Configs</span>
                            ) : (
                              config && <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded">Configured</span>
                            )}
                          </div>
                          {config ? (
                            <div className="text-sm text-slate-600 space-y-1">
                              <p>Normal: {config.normal_min ?? "—"} - {config.normal_max ?? "—"}</p>
                              <p>Weight: {config.weight}%</p>
                              <p>Ignore Zero: {config.ignore_zero_value ? "Yes" : "No"}</p>
                              {matchingConfigs.length > 1 ? (
                                <p className="text-amber-700">
                                  Backend has {matchingConfigs.length} matching configs for this metric. The newest one is shown here.
                                </p>
                              ) : null}
                            </div>
                          ) : (
                            <p className="text-sm text-slate-500">Not configured</p>
                          )}
                          {canEditDevice ? (
                            <Button size="sm" className="mt-3 w-full" onClick={() => { setSelectedMetric(metric); setShowHealthConfig(true); }}>
                              {config ? "Edit" : "Configure"}
                            </Button>
                          ) : null}
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="text-center py-8 text-slate-500">No telemetry parameters available</div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Load Classification Configuration</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  <p className="text-sm text-slate-600">
                    Full load current (FLA) is the primary engineering input. Idle is derived as a percentage of FLA,
                    and overconsumption starts above FLA. Loss booking still uses measured telemetry energy.
                  </p>
                  <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                    <div>
                      <label className="block text-sm font-medium mb-1">Full Load Current (A)</label>
                      <input
                        type="number"
                        min="0.01"
                        step="0.01"
                        value={fullLoadCurrentInput}
                        onChange={(e) => setFullLoadCurrentInput(e.target.value)}
                        className="w-full px-3 py-2 border rounded-md"
                        placeholder="e.g. 20.00"
                      />
                      <p className="mt-1 text-xs text-slate-500">
                        Saved: {persistedFullLoadCurrent != null ? `${persistedFullLoadCurrent.toFixed(2)} A` : "Not configured"}
                      </p>
                      {fullLoadCurrentDraftDiffersFromSaved && (
                        <p className="mt-1 text-xs text-amber-700">Draft differs from saved value.</p>
                      )}
                    </div>
                    <div>
                      <label className="block text-sm font-medium mb-1">Idle Threshold Percent of FLA</label>
                      <input
                        type="number"
                        min="0.01"
                        max="0.99"
                        step="0.01"
                        value={idleThresholdPctInput}
                        onChange={(e) => setIdleThresholdPctInput(e.target.value)}
                        className="w-full px-3 py-2 border rounded-md"
                        placeholder="Defaults to 0.25"
                      />
                      <p className="mt-1 text-xs text-slate-500">
                        Saved: {persistedIdleThresholdPct != null ? formatIdleThresholdPctLabel(persistedIdleThresholdPct) : "25% of FLA"}
                      </p>
                      {idleThresholdPctDraftDiffersFromSaved && (
                        <p className="mt-1 text-xs text-amber-700">Draft differs from saved value.</p>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <Button
                      onClick={handleSaveEngineeringConfig}
                      disabled={engineeringSaving || Boolean(engineeringSaveBlockReason)}
                    >
                      {engineeringSaving ? "Saving..." : "Save Classification"}
                    </Button>
                    {engineeringSaveMessage && (
                      <span className="text-sm text-emerald-700">{engineeringSaveMessage}</span>
                    )}
                  </div>
                  {engineeringSaveBlockReason && (
                    <p className="text-sm text-amber-700">{engineeringSaveBlockReason}</p>
                  )}

                  <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600 space-y-1">
                    <p>Idle default: 25% of FLA unless you override the idle percentage.</p>
                    <p>
                      Derived idle threshold:{" "}
                      <span className="font-semibold text-slate-800">
                        {thresholdPreview.derivedIdleThreshold != null
                          ? `${thresholdPreview.derivedIdleThreshold.toFixed(2)} A`
                          : "Unavailable until FLA is configured"}
                      </span>
                    </p>
                    <p>
                      Derived overconsumption threshold:{" "}
                      <span className="font-semibold text-slate-800">
                        {thresholdPreview.derivedOverconsumptionThreshold != null
                          ? `${thresholdPreview.derivedOverconsumptionThreshold.toFixed(2)} A`
                          : "Unavailable until FLA is configured"}
                      </span>
                    </p>
                    <p>
                      Current operating band:{" "}
                      <span className="font-semibold text-slate-800">{currentBandLabel}</span>
                    </p>
                    <p>
                      Auto-detected current field:{" "}
                      <span className="font-semibold text-slate-800">
                        {currentState?.current_field || "Not detected"}
                      </span>
                    </p>
                    <p>
                      Device type:{" "}
                      <span className="font-semibold text-slate-800 capitalize">
                        {machine.data_source_type || "metered"}
                      </span>
                    </p>
                    <p>{OVERCONSUMPTION_THRESHOLD_HELP}</p>
                    {!currentState?.current_field && (
                      <p className="text-amber-700">
                        No current parameter found in telemetry. Idle and overconsumption detection will remain unavailable until current data is received.
                      </p>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        )}

        {activeTabVisible && activeTab === "rules" && <MachineRulesView deviceId={deviceId} />}
      </div>
      
      <HealthConfigModal
        key={`${selectedMetric}-${findHealthConfigForMetric(selectedMetric, healthConfigs)?.id ?? "new"}`}
        isOpen={showHealthConfig}
        onClose={() => { setShowHealthConfig(false); setSelectedMetric(""); }}
        deviceId={deviceId}
        metric={selectedMetric}
        existingConfig={findHealthConfigForMetric(selectedMetric, healthConfigs)}
        allConfigs={healthConfigs}
        onSave={handleSaveHealthConfig}
        onDelete={handleDeleteHealthConfig}
      />
    </div>
  );
}
