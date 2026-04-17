"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Area, AreaChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { getDevices, Device } from "@/lib/deviceApi";
import { authApi, type PlantProfile } from "@/lib/authApi";
import { useAuth } from "@/lib/authContext";
import { useTenantStore } from "@/lib/tenantStore";
import { resolveScopedTenantId, resolveVisiblePlants } from "@/lib/orgScope";
import { DeviceScopeSelector } from "@/components/reports/DeviceScopeSelector";
import {
  buildDeviceScopeCatalog,
  getDeviceScopeSummary,
  normalizeDeviceScopeSelection,
  resolveDeviceIdsForSelection,
  type DeviceScopeSelection,
} from "@/lib/deviceScopeSelection";
import {
  runAnalytics,
  runFleetAnalytics,
  getAnalyticsStatus,
  getFormattedResults,
  getSupportedModels,
  listAnalyticsJobs,
  AnomalyFormattedResult,
  FailureFormattedResult,
  FleetFormattedResult,
  AnalyticsJobListItem,
  ApiError,
} from "@/lib/analyticsApi";

type Screen = "wizard" | "anomaly" | "failure" | "fleet";
type AnalysisType = "anomaly" | "failure_prediction";
type Preset = "quick" | "recommended" | "deep" | "custom";
type ResultType = AnomalyFormattedResult | FailureFormattedResult | FleetFormattedResult;
type ModelVoteRecord = Record<string, unknown>;
type FleetExecItem = { device_id: string; reason?: string; message?: string };
type FleetExecMeta = {
  devices_skipped?: FleetExecItem[];
  devices_failed?: FleetExecItem[];
  devices_ready?: string[];
  selected_device_count?: number;
  coverage_pct?: number;
};

const COLORS = {
  bg: "#f8fafc",
  panel: "#ffffff",
  panelBorder: "rgba(148, 163, 184, 0.3)",
  text: "#1e293b",
  muted: "rgba(71, 85, 105, 0.8)",
  accent: "#6366f1",
  good: "#22c55e",
  warn: "#f59e0b",
  bad: "#ef4444",
};

const PRESET_LABELS: Record<Preset, string> = {
  quick: "Last 24 Hours",
  recommended: "Last 7 Days",
  deep: "Last 30 Days",
  custom: "Custom",
};

function formatYmd(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function getPresetRange(preset: Preset): { start: string; end: string } {
  const end = new Date();
  const start = new Date();
  if (preset === "quick") start.setDate(end.getDate() - 1);
  else if (preset === "recommended") start.setDate(end.getDate() - 7);
  else if (preset === "deep") start.setDate(end.getDate() - 30);
  return { start: formatYmd(start), end: formatYmd(end) };
}

function formatDaysAnalysed(days: number): string {
  if (!Number.isFinite(days) || days <= 0) return "0 minutes";
  if (days < 1) {
    const hours = Math.max(1, Math.round(days * 24));
    return `${hours} hour${hours === 1 ? "" : "s"}`;
  }
  const wholeDays = Math.max(1, Math.round(days));
  return `${wholeDays} day${wholeDays === 1 ? "" : "s"}`;
}

function badgeColor(level: string): string {
  if (level === "Very High") return "#4f46e5";
  if (level === "High") return "#22c55e";
  if (level === "Moderate") return "#f59e0b";
  return "#ef4444";
}

function getErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error ? error.message : fallback;
}

function formatHistoryDate(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatAnalysisLabel(result: ResultType | null): string {
  if (!result) return "Analysis";
  if (result.analysis_type === "anomaly_detection") return "Anomaly Detection";
  if (result.analysis_type === "failure_prediction") return "Failure Prediction";
  return "Fleet Analytics";
}

function formatSeconds(seconds?: number | null): string {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) return "";
  if (seconds < 60) return `${Math.max(1, Math.round(seconds))}s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  return mins > 0 ? `${hours}h ${mins}m` : `${hours}h`;
}

function formatProgressMessage(status: {
  status: string;
  message?: string | null;
  phase_label?: string | null;
  queue_position?: number | null;
  estimated_wait_seconds?: number | null;
  estimated_completion_seconds?: number | null;
  estimate_quality?: "low" | "medium" | "high" | null;
}): string {
  const phaseText = status.phase_label?.trim() || status.message?.trim() || "Processing";
  const qualitySuffix = status.estimate_quality ? ` (${status.estimate_quality} confidence)` : "";
  if (status.status === "pending") {
    const queue = typeof status.queue_position === "number" ? `Queue #${status.queue_position + 1}` : "Queued";
    const waitText = formatSeconds(status.estimated_wait_seconds);
    return waitText ? `${queue} · wait ~${waitText}${qualitySuffix}` : `${queue}${qualitySuffix}`;
  }
  if (status.status === "running") {
    const completion = formatSeconds(status.estimated_completion_seconds);
    return completion ? `${phaseText} · ETA ~${completion}${qualitySuffix}` : phaseText;
  }
  return phaseText;
}

function ModelVotingPanel({
  ensemble,
}: {
  ensemble?: unknown;
}) {
  if (!ensemble || typeof ensemble !== "object") return null;
  const parsed = ensemble as {
    per_model?: Record<string, unknown>;
    verdict?: string;
    confidence?: string;
    votes?: number;
    vote_count?: number;
  };
  if (!parsed.per_model || typeof parsed.per_model !== "object") return null;
  return (
    <div style={panelStyle()}>
      <h3 style={titleStyle()}>Model Confirmation</h3>
      <div style={{ display: "grid", gap: 6 }}>
        {Object.entries(parsed.per_model).map(([name, model]) => {
          const m = model as ModelVoteRecord;
          const flagged = Boolean((m.voted_high ?? m.flagged) as boolean | undefined);
          const probability = typeof m.probability_pct === "number" ? m.probability_pct : null;
          const score = typeof m.score === "number" ? m.score : null;
          const trendType = typeof m.trend_type === "string" ? m.trend_type : "—";
          const value = probability != null ? `${probability}% probability` : score != null ? `Score: ${(score * 100).toFixed(0)}` : trendType;
          return (
            <div key={name} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, fontSize: 11 }}>
              <span style={{ fontFamily: "monospace", fontSize: 10 }}>{name}</span>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span>{value}</span>
                <span style={{ padding: "2px 6px", borderRadius: 999, fontSize: 10, background: flagged ? "#fee2e2" : "#dcfce7", color: flagged ? "#b91c1c" : "#15803d" }}>
                  {flagged ? "HIGH RISK" : "Normal"}
                </span>
                {m.is_trained === false && (
                  <span style={{ color: COLORS.muted, fontSize: 10 }}>(not trained)</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
      <div style={{ marginTop: 8, paddingTop: 8, borderTop: "1px solid #e2e8f0", fontSize: 11, fontWeight: 600 }}>
        Verdict: {parsed.verdict ?? parsed.confidence ?? "N/A"} · {(parsed.votes ?? parsed.vote_count ?? 0)}/3 models agree
      </div>
    </div>
  );
}

function DataQualityBanner({ flags }: { flags?: Array<Record<string, unknown>> }) {
  if (!flags?.length) return null;
  return (
    <>
      {flags.map((flag, i) => {
        if (flag.type !== "data_confidence") return null;
        const color = flag.color as string | undefined;
        const style =
          color === "red"
            ? { background: "#fef2f2", color: "#b91c1c" }
            : color === "orange"
              ? { background: "#fff7ed", color: "#c2410c" }
              : color === "yellow"
                ? { background: "#fefce8", color: "#a16207" }
                : { background: "#eff6ff", color: "#1d4ed8" };
        return (
          <div key={`dq-${i}`} style={{ ...style, borderRadius: 8, padding: 8, fontSize: 11 }}>
            ℹ Confidence: {String(flag.confidence_level ?? "Unknown")} — {String(flag.message ?? "")}
          </div>
        );
      })}
    </>
  );
}

function StepDots({ step }: { step: number }) {
  return (
    <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
      {[1, 2, 3, 4, 5].map((i) => (
        <div key={i} style={{ width: 20, height: 20, borderRadius: 10, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 9, fontWeight: 600, color: "white", background: step === i ? COLORS.accent : step > i ? COLORS.good : "#cbd5e1" }}>
          {step > i ? "✓" : i}
        </div>
      ))}
    </div>
  );
}

const HISTORY_PAGE_SIZE = 5;

function AnalyticsPageContent() {
  const search = useSearchParams();
  const { me } = useAuth();
  const { selectedTenantId } = useTenantStore();
  const [screen, setScreen] = useState<Screen>("wizard");
  const [step, setStep] = useState(1);

  const [devices, setDevices] = useState<Device[]>([]);
  const [plants, setPlants] = useState<PlantProfile[]>([]);
  const [models, setModels] = useState<{ anomaly_detection: string[]; failure_prediction: string[]; forecasting: string[] } | null>(null);

  const [scopeSelection, setScopeSelection] = useState<DeviceScopeSelection>({
    mode: "all",
    plantId: null,
    deviceIds: [],
  });
  const [preset, setPreset] = useState<Preset>("recommended");
  const [dateRange, setDateRange] = useState(getPresetRange("recommended"));
  const [analysisType, setAnalysisType] = useState<AnalysisType | null>(null);

  const [jobId, setJobId] = useState<string | null>(null);
  const [displayProgress, setDisplayProgress] = useState(0);
  const [progressMsg, setProgressMsg] = useState("Preparing analysis...");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ResultType | null>(null);
  const [historyJobs, setHistoryJobs] = useState<AnalyticsJobListItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [openingJobId, setOpeningJobId] = useState<string | null>(null);
  const [historyPage, setHistoryPage] = useState(0);
  const [hasMoreHistory, setHasMoreHistory] = useState(false);
  const [anomalyPage, setAnomalyPage] = useState(1);
  const [fleetParentResult, setFleetParentResult] = useState<FleetFormattedResult | null>(null);
  const [fleetNotice, setFleetNotice] = useState<string | null>(null);
  const scopedOrgId = resolveScopedTenantId(me, selectedTenantId);
  const visiblePlants = useMemo(() => resolveVisiblePlants(me, plants), [me, plants]);
  const scopeCatalog = useMemo(
    () => buildDeviceScopeCatalog(devices, visiblePlants),
    [devices, visiblePlants],
  );
  const normalizedScopeSelection = useMemo(
    () => normalizeDeviceScopeSelection(scopeSelection, scopeCatalog),
    [scopeCatalog, scopeSelection],
  );
  const selectedDeviceIds = useMemo(
    () => resolveDeviceIdsForSelection(normalizedScopeSelection, scopeCatalog),
    [normalizedScopeSelection, scopeCatalog],
  );
  const selectedScopeSummary = useMemo(
    () => getDeviceScopeSummary(normalizedScopeSelection, scopeCatalog),
    [normalizedScopeSelection, scopeCatalog],
  );

  const loadHistory = useCallback(async (page = 0) => {
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const jobs = await listAnalyticsJobs({
        limit: HISTORY_PAGE_SIZE + 1,
        offset: page * HISTORY_PAGE_SIZE,
      });
      setHistoryPage(page);
      setHasMoreHistory(jobs.length > HISTORY_PAGE_SIZE);
      setHistoryJobs(jobs.slice(0, HISTORY_PAGE_SIZE));
      return jobs;
    } catch (e: unknown) {
      setHistoryError(getErrorMessage(e, "Failed to load analytics history"));
      setHasMoreHistory(false);
      setHistoryJobs([]);
      return [];
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    Promise.all([
      getDevices(),
      getSupportedModels(),
      scopedOrgId ? authApi.listPlants(scopedOrgId) : Promise.resolve([]),
    ])
      .then(([devs, mods, orgPlants]) => {
        setDevices(devs);
        setModels(mods);
        setPlants(orgPlants);
        const qd = search.get("device");
        if (qd && devs.some((device) => device.id === qd)) {
          setScopeSelection({
            mode: "devices",
            plantId: null,
            deviceIds: [qd],
          });
        }
      })
      .catch((e: unknown) => setError(getErrorMessage(e, "Failed to load initial data")));
  }, [scopedOrgId, search]);

  useEffect(() => {
    void loadHistory(0);
  }, [loadHistory]);

  useEffect(() => {
    const selectionChanged =
      normalizedScopeSelection.mode !== scopeSelection.mode ||
      normalizedScopeSelection.plantId !== scopeSelection.plantId ||
      normalizedScopeSelection.deviceIds.length !== scopeSelection.deviceIds.length ||
      normalizedScopeSelection.deviceIds.some((deviceId, index) => deviceId !== scopeSelection.deviceIds[index]);
    if (selectionChanged) {
      setScopeSelection(normalizedScopeSelection);
    }
  }, [normalizedScopeSelection, scopeSelection]);

  const runDays = useMemo(() => {
    const start = new Date(dateRange.start).getTime();
    const end = new Date(dateRange.end).getTime();
    return Math.max(1, Math.round((end - start) / 86400000));
  }, [dateRange]);

  useEffect(() => {
    if (!jobId) return;
    const MAX_POLL_MS = 15 * 60 * 1000;
    const pollStart = Date.now();
    let consecutiveFailures = 0;
    let cancelled = false;

    const poll = async () => {
      while (!cancelled) {
        if (Date.now() - pollStart > MAX_POLL_MS) {
          setError(
            "Analysis is taking too long. It may still be running - check back later."
          );
          setStep(3);
          break;
        }

        await new Promise((resolve) => setTimeout(resolve, 3000));
        if (cancelled) {
          break;
        }

        try {
          const status = await getAnalyticsStatus(jobId);
          const reportedProgress = typeof status.progress === "number" ? status.progress : 0;
          setDisplayProgress(Math.max(0, Math.min(100, reportedProgress)));
          setProgressMsg(formatProgressMessage(status));

          if (status.status === "completed") {
            const results = await getFormattedResults(jobId);
            setDisplayProgress(100);
            setResult(results);
            if (results.analysis_type === "fleet") {
              setFleetParentResult(results);
            } else {
              setFleetParentResult(null);
            }
            setFleetNotice(null);
            setAnomalyPage(1);
            setStep(5);
            void loadHistory(0);
            break;
          }

          if (status.status === "failed") {
            setError(
              status.error_message ?? status.message ?? "Analysis failed."
            );
            setStep(3);
            break;
          }

          consecutiveFailures = 0;
        } catch {
          consecutiveFailures += 1;
          if (consecutiveFailures >= 3) {
            setError(
              "Lost connection. Please refresh and check if results are available."
            );
            setStep(3);
            break;
          }
        }
      }
    };

    void poll();
    return () => {
      cancelled = true;
    };
  }, [jobId, loadHistory]);

  const submit = useCallback(async () => {
    if (!analysisType || !models) return;

    setError(null);
    setDisplayProgress(0);
    setProgressMsg("Preparing analysis...");
    setStep(4);

    try {
      const modelName = analysisType === "anomaly"
        ? (models.anomaly_detection[0] ?? "isolation_forest")
        : (models.failure_prediction[0] ?? "random_forest");

      if (selectedDeviceIds.length !== 1) {
        const resp = await runFleetAnalytics({
          device_ids: selectedDeviceIds,
          analysis_type: analysisType === "anomaly" ? "anomaly" : "prediction",
          model_name: modelName,
          start_time: `${dateRange.start}T00:00:00Z`,
          end_time: `${dateRange.end}T23:59:59Z`,
          parameters: { sensitivity: "medium", lookback_days: runDays },
        });
        setJobId(resp.job_id);
        return;
      }

      const resp = await runAnalytics({
        device_id: selectedDeviceIds[0],
        analysis_type: analysisType === "anomaly" ? "anomaly" : "prediction",
        model_name: modelName,
        start_time: `${dateRange.start}T00:00:00Z`,
        end_time: `${dateRange.end}T23:59:59Z`,
        parameters: { sensitivity: "medium", lookback_days: runDays },
      });
      setJobId(resp.job_id);
    } catch (err: unknown) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "An unexpected error occurred";
      setError(message);
      setStep(3);
    }
  }, [analysisType, models, selectedDeviceIds, dateRange, runDays]);

  const reset = () => {
    setScreen("wizard");
    setStep(1);
    setResult(null);
    setFleetParentResult(null);
    setFleetNotice(null);
    setAnomalyPage(1);
    setJobId(null);
    setError(null);
    setProgressMsg("Preparing analysis...");
    setScopeSelection({
      mode: "all",
      plantId: null,
      deviceIds: [],
    });
  };

  const openStoredJob = useCallback(async (selectedJobId: string) => {
    setOpeningJobId(selectedJobId);
    setHistoryError(null);
    try {
      const storedResult = await getFormattedResults(selectedJobId);
      setJobId(selectedJobId);
      setResult(storedResult);
      setAnomalyPage(1);
      setFleetNotice(null);
      if (storedResult.analysis_type === "fleet") {
        setFleetParentResult(storedResult);
        setScreen("fleet");
      } else if (storedResult.analysis_type === "anomaly_detection") {
        setFleetParentResult(null);
        setScreen("anomaly");
      } else {
        setFleetParentResult(null);
        setScreen("failure");
      }
      setStep(5);
    } catch (e: unknown) {
      setHistoryError(getErrorMessage(e, "Unable to open stored analytics result"));
    } finally {
      setOpeningJobId(null);
    }
  }, []);

  const showHistoryPanel = step === 1;

  const goDashboard = () => {
    if (!result) return;
    if (result.analysis_type === "anomaly_detection") setScreen("anomaly");
    else if (result.analysis_type === "failure_prediction") setScreen("failure");
    else {
      setFleetParentResult(result);
      setFleetNotice(null);
      setScreen("fleet");
    }
  };

  const backToFleetSummary = () => {
    if (!fleetParentResult) return;
    setResult(fleetParentResult);
    setFleetNotice(null);
    setScreen("fleet");
  };

  const openFleetDevice = async (deviceId: string, childJobId?: string) => {
    setFleetNotice(null);
    if (!childJobId) {
      setFleetNotice(`Detailed results are not available yet for ${deviceId}.`);
      return;
    }
    try {
      const childResult = await getFormattedResults(childJobId);
      setResult(childResult);
      if (childResult.analysis_type === "anomaly_detection") {
        setAnomalyPage(1);
        setScreen("anomaly");
        return;
      }
      if (childResult.analysis_type === "failure_prediction") {
        setScreen("failure");
        return;
      }
      setFleetNotice(`Unsupported drilldown result for ${deviceId}.`);
    } catch (err: unknown) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : `Unable to open detailed view for ${deviceId}.`;
      setFleetNotice(message);
    }
  };

  if (screen === "wizard") {
    return (
      <div style={{ minHeight: "100vh", width: "100%", overflowX: "hidden", background: COLORS.bg, color: COLORS.text, fontFamily: "'DM Sans','Segoe UI',sans-serif" }}>
        <div style={{ maxWidth: 700, margin: "0 auto", padding: "16px 16px 24px", boxSizing: "border-box" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 16 }}>
            <div>
              <div style={{ color: COLORS.muted, fontSize: 10, letterSpacing: 1.5, textTransform: "uppercase" }}>Analytics</div>
              <h1 style={{ margin: "4px 0 0", fontSize: 18, color: COLORS.text }}>Run AI-powered analytics on your machine data</h1>
            </div>
            <StepDots step={step} />
          </div>

          <div style={{ background: COLORS.panel, border: `1px solid ${COLORS.panelBorder}`, borderRadius: 10, padding: 14, boxShadow: "0 1px 3px rgba(0,0,0,0.1)" }}>
            {step === 1 && (
              <>
                <h2 style={{ marginTop: 0, marginBottom: 6, fontSize: 14, color: COLORS.text }}>Select Scope</h2>
                <div style={{ color: COLORS.muted, marginBottom: 10, fontSize: 12 }}>Which machines to analyse?</div>

                <DeviceScopeSelector
                  catalog={scopeCatalog}
                  value={normalizedScopeSelection}
                  onChange={setScopeSelection}
                />
                <div style={{ color: COLORS.muted, marginTop: 10, fontSize: 11 }}>{selectedScopeSummary}</div>

                <button
                  onClick={() => setStep(2)}
                  disabled={selectedDeviceIds.length === 0}
                  style={{
                    marginTop: 12,
                    width: "100%",
                    padding: 8,
                    borderRadius: 8,
                    border: "none",
                    background: COLORS.accent,
                    color: "white",
                    fontWeight: 600,
                    fontSize: 13,
                    cursor: selectedDeviceIds.length === 0 ? "not-allowed" : "pointer",
                    opacity: selectedDeviceIds.length === 0 ? 0.55 : 1,
                  }}
                >
                  Continue
                </button>
              </>
            )}

            {step === 2 && (
              <>
                <h2 style={{ marginTop: 0, marginBottom: 6, fontSize: 14, color: COLORS.text }}>Select Date Range</h2>
                <div style={{ color: COLORS.muted, marginBottom: 10, fontSize: 12 }}>How much telemetry data?</div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, marginBottom: 10 }}>
                  {(["quick", "recommended", "deep", "custom"] as Preset[]).map((p) => {
                    const range = p === "custom" ? dateRange : getPresetRange(p);
                    return (
                      <button
                        key={p}
                        onClick={() => {
                          setPreset(p);
                          if (p !== "custom") setDateRange(range);
                        }}
                        style={{ textAlign: "left", background: preset === p ? "rgba(99,102,241,0.1)" : "#f1f5f9", color: COLORS.text, border: `1px solid ${preset === p ? "#6366f1" : COLORS.panelBorder}`, borderRadius: 8, padding: 8, cursor: "pointer" }}
                      >
                        <div style={{ color: COLORS.accent, letterSpacing: 1, textTransform: "uppercase", fontSize: 9, fontWeight: 600 }}>{p}</div>
                        <div style={{ marginTop: 3, fontSize: 12, fontWeight: 600 }}>{PRESET_LABELS[p]}</div>
                        <div style={{ color: COLORS.muted, marginTop: 2, fontSize: 10 }}>{range.start} → {range.end}</div>
                      </button>
                    );
                  })}
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                  <div>
                    <div style={{ fontSize: 10, color: COLORS.muted, letterSpacing: 1 }}>FROM</div>
                    <input type="date" value={dateRange.start} onChange={(e) => { setPreset("custom"); setDateRange((r) => ({ ...r, start: e.target.value })); }} style={{ marginTop: 4, width: "100%", padding: 6, borderRadius: 6, border: `1px solid ${COLORS.panelBorder}`, background: "white", color: COLORS.text, fontSize: 11 }} />
                  </div>
                  <div>
                    <div style={{ fontSize: 10, color: COLORS.muted, letterSpacing: 1 }}>TO</div>
                    <input type="date" value={dateRange.end} onChange={(e) => { setPreset("custom"); setDateRange((r) => ({ ...r, end: e.target.value })); }} style={{ marginTop: 4, width: "100%", padding: 6, borderRadius: 6, border: `1px solid ${COLORS.panelBorder}`, background: "white", color: COLORS.text, fontSize: 11 }} />
                  </div>
                </div>

                <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
                  <button onClick={() => setStep(1)} style={{ padding: "8px 12px", borderRadius: 8, border: `1px solid ${COLORS.panelBorder}`, background: "white", color: COLORS.text, fontWeight: 600, fontSize: 12, cursor: "pointer" }}>Back</button>
                  <button onClick={() => setStep(3)} style={{ flex: 1, padding: "8px 12px", borderRadius: 8, border: "none", background: COLORS.accent, color: "white", fontWeight: 600, fontSize: 12, cursor: "pointer" }}>Continue</button>
                </div>
              </>
            )}

            {step === 3 && (
              <>
                <h2 style={{ marginTop: 0, marginBottom: 6, fontSize: 14, color: COLORS.text }}>Analysis Type</h2>
                <div style={{ color: COLORS.muted, marginBottom: 10, fontSize: 12 }}>What to discover?</div>

                <button onClick={() => setAnalysisType("anomaly")} style={{ width: "100%", textAlign: "left", background: analysisType === "anomaly" ? "rgba(99,102,241,0.1)" : "#f1f5f9", color: COLORS.text, border: `1px solid ${analysisType === "anomaly" ? "#6366f1" : COLORS.panelBorder}`, borderRadius: 8, padding: 10, marginBottom: 6, cursor: "pointer" }}>
                  <div style={{ fontSize: 13, fontWeight: 600 }}>Anomaly Detection</div>
                  <div style={{ color: COLORS.muted, marginTop: 2, fontSize: 11 }}>Find unusual patterns, spikes, drops.</div>
                </button>

                <button onClick={() => setAnalysisType("failure_prediction")} style={{ width: "100%", textAlign: "left", background: analysisType === "failure_prediction" ? "rgba(99,102,241,0.1)" : "#f1f5f9", color: COLORS.text, border: `1px solid ${analysisType === "failure_prediction" ? "#6366f1" : COLORS.panelBorder}`, borderRadius: 8, padding: 10, cursor: "pointer" }}>
                  <div style={{ fontSize: 13, fontWeight: 600 }}>Failure Prediction</div>
                  <div style={{ color: COLORS.muted, marginTop: 2, fontSize: 11 }}>Predict failure probability, remaining life.</div>
                </button>

                {error && <div style={{ marginTop: 8, color: COLORS.bad, fontSize: 11 }}>{error}</div>}

                <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
                  <button onClick={() => setStep(2)} style={{ padding: "8px 12px", borderRadius: 8, border: `1px solid ${COLORS.panelBorder}`, background: "white", color: COLORS.text, fontWeight: 600, fontSize: 12, cursor: "pointer" }}>Back</button>
                  <button onClick={submit} disabled={!analysisType} style={{ flex: 1, padding: "8px 12px", borderRadius: 8, border: "none", background: COLORS.accent, color: "white", fontWeight: 600, fontSize: 12, cursor: !analysisType ? "not-allowed" : "pointer", opacity: analysisType ? 1 : 0.55 }}>Run Analysis</button>
                </div>
              </>
            )}

            {step === 4 && (
              <div style={{ minHeight: 180, display: "flex", alignItems: "center", justifyContent: "center", padding: "10px 0" }}>
                <div style={{ width: "100%", maxWidth: 260, textAlign: "center" }}>
                  <div style={{ color: COLORS.accent, letterSpacing: 1, textTransform: "uppercase", fontWeight: 600, marginBottom: 12, fontSize: 10 }}>
                    Running {analysisType === "anomaly" ? "Anomaly Detection" : "Failure Prediction"}
                  </div>
                  <div style={{ width: 80, height: 80, borderRadius: "50%", border: "5px solid #e2e8f0", margin: "0 auto 12px", position: "relative", boxSizing: "border-box", display: "flex", alignItems: "center", justifyContent: "center" }}>
                    <div style={{ position: "absolute", width: 80, height: 80, borderRadius: "50%", border: "5px solid transparent", borderTopColor: COLORS.accent, animation: "spin 1s linear infinite" }} />
                    <span style={{ fontSize: 16, fontWeight: 700, color: COLORS.text }}>{Math.round(displayProgress)}%</span>
                  </div>
                  <div style={{ fontSize: 11, color: COLORS.muted }}>{progressMsg}</div>
                  <div style={{ marginTop: 6, color: COLORS.muted, fontSize: 10, opacity: 0.7 }}>{selectedScopeSummary} · {dateRange.start} → {dateRange.end}</div>
                </div>
                <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
              </div>
            )}

            {step === 5 && (
              <div style={{ textAlign: "center", padding: "14px 0 6px" }}>
                <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 6, color: COLORS.text }}>Analysis Complete</div>
                <div style={{ color: COLORS.muted, marginBottom: 12, fontSize: 11 }}>
                  {result?.analysis_type === "anomaly_detection" && `${result.summary.total_anomalies} anomalies · ${result.summary.health_impact} impact`}
                  {result?.analysis_type === "failure_prediction" && `${result.summary.failure_probability_pct.toFixed(1)}% failure probability · ${result.summary.failure_risk} risk`}
                  {result?.analysis_type === "fleet" && `${result.device_summaries.length} devices analysed`}
                </div>
                <button onClick={goDashboard} style={{ width: "100%", padding: 8, borderRadius: 8, border: "none", background: COLORS.accent, color: "white", fontWeight: 600, fontSize: 13, cursor: "pointer", marginBottom: 6 }}>View Dashboard</button>
                <button onClick={reset} style={{ width: "100%", padding: 8, borderRadius: 8, border: `1px solid ${COLORS.panelBorder}`, background: "white", color: COLORS.text, fontWeight: 600, fontSize: 13, cursor: "pointer" }}>Run Another Analysis</button>
              </div>
            )}
          </div>

          {showHistoryPanel && (
            <div style={{ ...panelStyle(), marginTop: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
                <div>
                  <h2 style={{ margin: 0, fontSize: 14, color: COLORS.text }}>Analysis History</h2>
                  <div style={{ color: COLORS.muted, fontSize: 11, marginTop: 2 }}>
                    Reopen completed analytics results saved by the platform
                  </div>
                </div>
                <button
                  onClick={() => void loadHistory(historyPage)}
                  disabled={historyLoading}
                  style={{
                    padding: "6px 10px",
                    borderRadius: 8,
                    border: `1px solid ${COLORS.panelBorder}`,
                    background: "white",
                    color: COLORS.text,
                    fontWeight: 600,
                    fontSize: 11,
                    cursor: historyLoading ? "not-allowed" : "pointer",
                    opacity: historyLoading ? 0.65 : 1,
                  }}
                >
                  Refresh
                </button>
              </div>

              {historyError && (
                <div style={{ color: COLORS.bad, fontSize: 11, marginBottom: 8 }}>{historyError}</div>
              )}

              {historyLoading && historyJobs.length === 0 ? (
                <div style={{ color: COLORS.muted, fontSize: 11 }}>Loading analytics history...</div>
              ) : historyJobs.length === 0 ? (
                <div style={{ color: COLORS.muted, fontSize: 11 }}>No analytics jobs found yet.</div>
              ) : (
                <>
                  <div style={{ overflowX: "auto" }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
                      <thead>
                        <tr style={{ textAlign: "left", color: COLORS.muted }}>
                          <th style={{ padding: "8px 6px" }}>Job ID</th>
                          <th style={{ padding: "8px 6px" }}>Status</th>
                          <th style={{ padding: "8px 6px" }}>Created</th>
                          <th style={{ padding: "8px 6px" }}>Completed</th>
                          <th style={{ padding: "8px 6px" }}>Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {historyJobs.map((job) => {
                          const isCompleted = job.status === "completed";
                          const isOpening = openingJobId === job.job_id;
                          return (
                            <tr key={job.job_id} style={{ borderTop: "1px solid #e2e8f0" }}>
                              <td style={{ padding: "8px 6px", fontFamily: "monospace", fontSize: 10 }}>{job.job_id}</td>
                              <td style={{ padding: "8px 6px" }}>
                                <span
                                  style={{
                                    display: "inline-flex",
                                    alignItems: "center",
                                    borderRadius: 999,
                                    padding: "2px 8px",
                                    background:
                                      job.status === "completed"
                                        ? "#dcfce7"
                                        : job.status === "failed"
                                          ? "#fee2e2"
                                          : "#e0e7ff",
                                    color:
                                      job.status === "completed"
                                        ? "#166534"
                                        : job.status === "failed"
                                          ? "#b91c1c"
                                          : "#4338ca",
                                  }}
                                >
                                  {job.status}
                                </span>
                              </td>
                              <td style={{ padding: "8px 6px", color: COLORS.muted }}>{formatHistoryDate(job.created_at)}</td>
                              <td style={{ padding: "8px 6px", color: COLORS.muted }}>{formatHistoryDate(job.completed_at)}</td>
                              <td style={{ padding: "8px 6px" }}>
                                <button
                                  onClick={() => void openStoredJob(job.job_id)}
                                  disabled={!isCompleted || isOpening}
                                  style={{
                                    padding: "4px 8px",
                                    borderRadius: 6,
                                    border: "none",
                                    background: isCompleted ? COLORS.accent : "#cbd5e1",
                                    color: "white",
                                    fontWeight: 600,
                                    fontSize: 10,
                                    cursor: !isCompleted || isOpening ? "not-allowed" : "pointer",
                                    opacity: !isCompleted || isOpening ? 0.7 : 1,
                                  }}
                                >
                                  {isOpening ? "Opening..." : isCompleted ? "View Results" : "Unavailable"}
                                </button>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>

                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
                    <div style={{ color: COLORS.muted, fontSize: 11 }}>
                      Page {historyPage + 1}
                    </div>
                    <div style={{ display: "flex", gap: 8 }}>
                      <button
                        onClick={() => void loadHistory(Math.max(0, historyPage - 1))}
                        disabled={historyLoading || historyPage === 0}
                        style={{
                          padding: "6px 10px",
                          borderRadius: 8,
                          border: `1px solid ${COLORS.panelBorder}`,
                          background: "white",
                          color: COLORS.text,
                          fontWeight: 600,
                          fontSize: 11,
                          cursor: historyLoading || historyPage === 0 ? "not-allowed" : "pointer",
                          opacity: historyLoading || historyPage === 0 ? 0.65 : 1,
                        }}
                      >
                        Previous
                      </button>
                      <button
                        onClick={() => void loadHistory(historyPage + 1)}
                        disabled={historyLoading || !hasMoreHistory}
                        style={{
                          padding: "6px 10px",
                          borderRadius: 8,
                          border: `1px solid ${COLORS.panelBorder}`,
                          background: "white",
                          color: COLORS.text,
                          fontWeight: 600,
                          fontSize: 11,
                          cursor: historyLoading || !hasMoreHistory ? "not-allowed" : "pointer",
                          opacity: historyLoading || !hasMoreHistory ? 0.65 : 1,
                        }}
                      >
                        Next
                      </button>
                    </div>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    );
  }

  if (screen === "anomaly" && result && result.analysis_type === "anomaly_detection") {
    const maxParam = Math.max(...result.parameter_breakdown.map((p) => p.anomaly_count), 1);
    const confidence = result.confidence;
    const anomalyRate = result.summary.anomaly_rate_pct;
    const anomalyPages = Math.max(1, Math.ceil(result.anomaly_list.length / 10));
    const pageStart = (anomalyPage - 1) * 10;
    const anomalyRows = result.anomaly_list.slice(pageStart, pageStart + 10);
    return (
      <div style={{ minHeight: "100vh", background: COLORS.bg, color: COLORS.text, fontFamily: "'DM Sans','Segoe UI',sans-serif", padding: 12 }}>
        <div style={{ maxWidth: 900, margin: "0 auto", display: "grid", gap: 8 }}>
          <div style={{ display: "flex", gap: 8, justifySelf: "start" }}>
            <button onClick={reset} style={{ padding: "5px 8px", borderRadius: 6, border: `1px solid ${COLORS.panelBorder}`, background: "white", color: COLORS.text, cursor: "pointer", fontSize: 11 }}>New Analysis</button>
            {fleetParentResult && (
              <button onClick={backToFleetSummary} style={{ padding: "5px 8px", borderRadius: 6, border: `1px solid ${COLORS.panelBorder}`, background: "white", color: COLORS.text, cursor: "pointer", fontSize: 11 }}>Back to Fleet Summary</button>
            )}
          </div>
          {confidence && (
            <div style={{ background: COLORS.panel, border: `1px solid ${confidence.badge_color}`, borderRadius: 8, padding: 8, color: confidence.badge_color, fontWeight: 600, fontSize: 12 }}>
              {confidence.banner_text}
            </div>
          )}
          <DataQualityBanner flags={result.data_quality_flags} />
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4,minmax(0,1fr))", gap: 8 }}>
            <Stat label="Total Anomalies" value={String(result.summary.total_anomalies)} />
            <Stat label="Anomaly Rate" value={`${result.summary.anomaly_rate_pct}%`} />
            <Stat label="Anomaly Score" value={`${result.summary.anomaly_score}/100`} />
            <Stat label="Health Impact" value={result.summary.health_impact} />
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
            <div style={panelStyle()}>
              <h3 style={titleStyle()}>Anomaly Rate Gauge</h3>
              <RadialGauge
                value={anomalyRate}
                min={0}
                max={10}
                color={anomalyRate < 3 ? COLORS.good : anomalyRate < 7 ? COLORS.warn : COLORS.bad}
                label={`${anomalyRate.toFixed(2)}%`}
                subtitle="0-3% normal · 3-7% watch · >7% critical"
              />
            </div>
            <div style={panelStyle()}>
              <h3 style={titleStyle()}>Period Summary</h3>
              <div style={{ color: COLORS.muted, fontSize: 11, marginBottom: 6 }}>
                Most affected: <b style={{ color: COLORS.text }}>{result.summary.most_affected_parameter}</b>
              </div>
              <div style={{ color: COLORS.muted, fontSize: 11 }}>
                Data points: <b style={{ color: COLORS.text }}>{result.summary.data_points_analyzed}</b>
              </div>
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 8 }}>
            <div style={panelStyle()}>
              <h3 style={titleStyle()}>Anomalies Over Time</h3>
              {result.anomalies_over_time.map((d) => (
                <div key={d.date} style={{ marginBottom: 6 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: COLORS.muted }}><span>{d.date}</span><span>{d.count}</span></div>
                  <div style={{ height: 8, background: "#e2e8f0", borderRadius: 6, overflow: "hidden", display: "flex" }}>
                    <div style={{ width: `${d.count ? (d.high_count / d.count) * 100 : 0}%`, background: COLORS.bad }} />
                    <div style={{ width: `${d.count ? (d.medium_count / d.count) * 100 : 0}%`, background: COLORS.warn }} />
                    <div style={{ width: `${d.count ? (d.low_count / d.count) * 100 : 0}%`, background: COLORS.good }} />
                  </div>
                </div>
              ))}
            </div>
            <div style={panelStyle()}>
              <h3 style={titleStyle()}>Affected Parameters</h3>
              {result.parameter_breakdown.map((p) => (
                <div key={p.parameter} style={{ marginBottom: 6 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, marginBottom: 2 }}><span>{p.parameter}</span><b>{p.anomaly_count}</b></div>
                  <div style={{ height: 8, background: "#e2e8f0", borderRadius: 6 }}>
                    <div style={{ height: "100%", width: `${(p.anomaly_count / maxParam) * 100}%`, background: "#3b82f6", borderRadius: 6 }} />
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div style={panelStyle()}>
            <h3 style={titleStyle()}>Anomaly Detail List</h3>
            {anomalyRows.map((a, i) => (
              <div key={i} style={{ display: "grid", gridTemplateColumns: "70px 1fr 140px", gap: 8, padding: "6px 0", borderBottom: "1px solid #e2e8f0", fontSize: 11 }}>
                <span style={{ color: a.severity === "high" ? COLORS.bad : a.severity === "medium" ? COLORS.warn : COLORS.good, fontWeight: 600 }}>{a.severity.toUpperCase()}</span>
                <span>{a.context}</span>
                <span style={{ color: COLORS.muted }}>{a.recommended_action}</span>
              </div>
            ))}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 8 }}>
              <span style={{ color: COLORS.muted, fontSize: 10 }}>
                Showing {result.anomaly_list.length === 0 ? 0 : pageStart + 1}-{Math.min(pageStart + 10, result.anomaly_list.length)} of {result.anomaly_list.length}
              </span>
              <div style={{ display: "flex", gap: 6 }}>
                <button
                  onClick={() => setAnomalyPage((p) => Math.max(1, p - 1))}
                  disabled={anomalyPage <= 1}
                  style={{ padding: "4px 8px", borderRadius: 6, border: `1px solid ${COLORS.panelBorder}`, background: "white", color: COLORS.text, cursor: anomalyPage <= 1 ? "not-allowed" : "pointer", opacity: anomalyPage <= 1 ? 0.5 : 1, fontSize: 10 }}
                >
                  Prev
                </button>
                <span style={{ color: COLORS.muted, fontSize: 10, alignSelf: "center" }}>Page {anomalyPage}/{anomalyPages}</span>
                <button
                  onClick={() => setAnomalyPage((p) => Math.min(anomalyPages, p + 1))}
                  disabled={anomalyPage >= anomalyPages}
                  style={{ padding: "4px 8px", borderRadius: 6, border: `1px solid ${COLORS.panelBorder}`, background: "white", color: COLORS.text, cursor: anomalyPage >= anomalyPages ? "not-allowed" : "pointer", opacity: anomalyPage >= anomalyPages ? 0.5 : 1, fontSize: 10 }}
                >
                  Next
                </button>
              </div>
            </div>
          </div>

          <div style={panelStyle()}>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center", fontSize: 11 }}>
            <div style={{ color: COLORS.muted }}>
              Type: <b style={{ color: COLORS.text }}>{formatAnalysisLabel(result)}</b>
            </div>
            <div style={{ color: COLORS.muted }}>
              Days Analysed: <b style={{ color: COLORS.text }}>{formatDaysAnalysed(result.summary.days_analyzed)}</b>
            </div>
            <div style={{ color: COLORS.good }}>
                Completion: <b>100%</b>
              </div>
            </div>
          </div>

          <ModelVotingPanel ensemble={result.ensemble} />

          {result.reasoning && (
            <div style={{ ...panelStyle(), background: "#f8fafc" }}>
              <h3 style={titleStyle()}>Why is this flagged?</h3>
              <div style={{ fontSize: 11, fontWeight: 600 }}>{result.reasoning.summary ?? "No summary available."}</div>
              {result.reasoning.affected_parameters?.length ? (
                <div style={{ marginTop: 6, fontSize: 11, color: COLORS.muted }}>
                  Affected parameters: {result.reasoning.affected_parameters.join(", ")}
                </div>
              ) : null}
              {result.reasoning.recommended_action ? (
                <div style={{ marginTop: 6, fontSize: 11 }}>→ {result.reasoning.recommended_action}</div>
              ) : null}
            </div>
          )}
        </div>
      </div>
    );
  }

  if (screen === "failure" && result && result.analysis_type === "failure_prediction") {
    const confidence = result.confidence;
    const failurePct = result.summary.failure_probability_pct;
    const safePct = result.summary.safe_probability_pct ?? Math.max(0, 100 - failurePct);
    return (
      <div style={{ minHeight: "100vh", background: COLORS.bg, color: COLORS.text, fontFamily: "'DM Sans','Segoe UI',sans-serif", padding: 12 }}>
        <div style={{ maxWidth: 900, margin: "0 auto", display: "grid", gap: 8 }}>
          <div style={{ display: "flex", gap: 8, justifySelf: "start" }}>
            <button onClick={reset} style={{ padding: "5px 8px", borderRadius: 6, border: `1px solid ${COLORS.panelBorder}`, background: "white", color: COLORS.text, cursor: "pointer", fontSize: 11 }}>New Analysis</button>
            {fleetParentResult && (
              <button onClick={backToFleetSummary} style={{ padding: "5px 8px", borderRadius: 6, border: `1px solid ${COLORS.panelBorder}`, background: "white", color: COLORS.text, cursor: "pointer", fontSize: 11 }}>Back to Fleet Summary</button>
            )}
          </div>
          {confidence && (
            <div style={{ background: COLORS.panel, border: `1px solid ${confidence.badge_color}`, borderRadius: 8, padding: 8, color: confidence.badge_color, fontWeight: 600, fontSize: 12 }}>
              {confidence.banner_text}
            </div>
          )}
          <DataQualityBanner flags={result.data_quality_flags} />
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4,minmax(0,1fr))", gap: 8 }}>
            <Stat label="Risk Level" value={result.summary.failure_risk} />
            <Stat label="Failure Probability" value={`${result.summary.failure_probability_pct.toFixed(1)}%`} />
            <Stat label="Remaining Life" value={result.summary.estimated_remaining_life} />
            <Stat label="Maintenance" value={result.summary.maintenance_urgency} />
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
            <div style={panelStyle()}>
              <h3 style={titleStyle()}>Failure Probability Meter</h3>
              <RadialGauge
                value={failurePct}
                min={0}
                max={100}
                color={failurePct < 35 ? COLORS.good : failurePct < 60 ? COLORS.warn : COLORS.bad}
                label={`${failurePct.toFixed(1)}%`}
                subtitle="0% healthy → 100% imminent"
              />
            </div>
            <div style={panelStyle()}>
              <h3 style={titleStyle()}>Contributing Risk Factors</h3>
              {result.insufficient_trend_signal ? (
                <div style={{ color: COLORS.warn, fontSize: 11 }}>No significant trend signal yet.</div>
              ) : (
                result.risk_factors.slice(0, 6).map((rf, i) => (
                  <div key={`${rf.parameter}-${i}`} style={{ padding: "4px 0", borderBottom: "1px solid #e2e8f0", fontSize: 11 }}>
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <b>{rf.parameter}</b>
                      <span>{rf.contribution_pct}%</span>
                    </div>
                    <div style={{ height: 5, background: "#e2e8f0", borderRadius: 4, margin: "3px 0 4px" }}>
                      <div style={{ height: "100%", width: `${Math.min(100, rf.contribution_pct)}%`, background: "#f59e0b", borderRadius: 4 }} />
                    </div>
                    <div style={{ color: COLORS.muted, fontSize: 10 }}>{rf.context}</div>
                  </div>
                ))
              )}
            </div>
          </div>

          <div style={panelStyle()}>
            <h3 style={titleStyle()}>Failure vs Safe Breakdown</h3>
            <div style={{ display: "grid", gridTemplateColumns: "100px 1fr", gap: 10, alignItems: "center" }}>
              <DonutChart
                segments={[
                  { value: failurePct, color: COLORS.bad, label: "Failure" },
                  { value: safePct, color: COLORS.good, label: "Safe" },
                ]}
                size={80}
                inner={35}
              />
              <div style={{ display: "grid", gap: 4 }}>
                <div style={{ display: "flex", justifyContent: "space-between", color: COLORS.muted, fontSize: 11 }}>
                  <span>Failure</span><b style={{ color: COLORS.bad }}>{failurePct.toFixed(1)}%</b>
                </div>
                <div style={{ height: 6, background: "#e2e8f0", borderRadius: 4 }}>
                  <div style={{ width: `${failurePct}%`, height: "100%", background: COLORS.bad, borderRadius: 4 }} />
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", color: COLORS.muted, fontSize: 11 }}>
                  <span>Safe</span><b style={{ color: COLORS.good }}>{safePct.toFixed(1)}%</b>
                </div>
                <div style={{ height: 6, background: "#e2e8f0", borderRadius: 4 }}>
                  <div style={{ width: `${safePct}%`, height: "100%", background: COLORS.good, borderRadius: 4 }} />
                </div>
              </div>
            </div>
          </div>

          <div style={panelStyle()}>
            <h3 style={titleStyle()}>Recommended Actions</h3>
            {result.recommended_actions.length === 0 && (
              <div style={{ color: COLORS.muted, fontSize: 11 }}>No immediate actions generated yet.</div>
            )}
            {result.recommended_actions.map((r) => (
              <div key={r.rank} style={{ display: "flex", justifyContent: "space-between", gap: 8, padding: "6px 0", borderBottom: "1px solid #e2e8f0", fontSize: 11 }}>
                <div>
                  <b>{r.rank}. {r.action}</b>
                  <div style={{ color: COLORS.muted, fontSize: 10 }}>{r.reasoning}</div>
                </div>
                <span style={{ color: COLORS.warn }}>{r.urgency}</span>
              </div>
            ))}
          </div>

          <div style={panelStyle()}>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center", fontSize: 11 }}>
            <div style={{ color: COLORS.muted }}>
              Type: <b style={{ color: COLORS.text }}>{formatAnalysisLabel(result)}</b>
            </div>
            <div style={{ color: COLORS.muted }}>
              Days Analysed: <b style={{ color: COLORS.text }}>{formatDaysAnalysed(result.summary.days_analyzed)}</b>
            </div>
            <div style={{ color: COLORS.good }}>
                Completion: <b>100%</b>
              </div>
            </div>
          </div>

          <ModelVotingPanel ensemble={result.ensemble} />

          {result.time_to_failure && (
            <div style={panelStyle()}>
              <h3 style={titleStyle()}>Failure Forecast</h3>
              <div style={{ fontSize: 13, fontWeight: 700 }}>{result.time_to_failure.label ?? "No trend forecast"}</div>
              {result.time_to_failure.confidence_interval ? (
                <div style={{ marginTop: 4, color: COLORS.muted, fontSize: 11 }}>
                  Range: {result.time_to_failure.confidence_interval[0]}–{result.time_to_failure.confidence_interval[1]} hours
                </div>
              ) : null}
              <div style={{ marginTop: 4, color: COLORS.muted, fontSize: 10 }}>
                Trend: {result.time_to_failure.trend_type ?? "unknown"}
                {result.time_to_failure.trend_r2 != null ? ` (R²=${result.time_to_failure.trend_r2.toFixed(2)})` : ""}
                {" · "}
                {result.time_to_failure.is_reliable ? "Reliable" : "Low reliability"}
              </div>
            </div>
          )}

          {result.reasoning && (
            <div style={{ ...panelStyle(), background: "#f8fafc" }}>
              <h3 style={titleStyle()}>Why is this flagged?</h3>
              <div style={{ fontSize: 11, fontWeight: 600 }}>{result.reasoning.summary ?? "No summary available."}</div>
              {result.reasoning.agreement_text ? (
                <div style={{ marginTop: 4, color: COLORS.muted, fontSize: 11 }}>{result.reasoning.agreement_text}</div>
              ) : null}
              {result.reasoning.top_risk_factors?.length ? (
                <div style={{ marginTop: 6 }}>
                  <div style={{ fontSize: 10, color: COLORS.muted, textTransform: "uppercase", letterSpacing: 1 }}>Top contributing factors</div>
                  <ol style={{ margin: "4px 0 0", paddingLeft: 16, fontSize: 11 }}>
                    {result.reasoning.top_risk_factors.map((f, i) => (
                      <li key={`rf-${i}`}>{f}</li>
                    ))}
                  </ol>
                </div>
              ) : null}
              {result.reasoning.recommended_actions?.length ? (
                <div style={{ marginTop: 6 }}>
                  <div style={{ fontSize: 10, color: COLORS.muted, textTransform: "uppercase", letterSpacing: 1 }}>Recommended actions</div>
                  <div style={{ marginTop: 4, display: "grid", gap: 2, fontSize: 11 }}>
                    {result.reasoning.recommended_actions.map((a, i) => (
                      <div key={`ra-${i}`}>→ {a}</div>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          )}

          {result.degradation_series?.length ? (
            <div style={panelStyle()}>
              <h3 style={titleStyle()}>Degradation Trend</h3>
              <ResponsiveContainer width="100%" height={200}>
                <AreaChart data={result.degradation_series.map((v, i) => ({ t: i, score: v }))}>
                  <XAxis dataKey="t" hide />
                  <YAxis domain={[0, 1]} />
                  <Tooltip />
                  <ReferenceLine
                    y={0.85}
                    stroke="red"
                    strokeDasharray="4 2"
                    label={{ value: "Failure threshold", position: "right", fontSize: 11, fill: "red" }}
                  />
                  <Area type="monotone" dataKey="score" stroke="#f97316" fill="#fed7aa" strokeWidth={2} dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          ) : null}
        </div>
      </div>
    );
  }

  if (screen === "fleet" && result && result.analysis_type === "fleet") {
    const exec = (result.execution_metadata ?? {}) as FleetExecMeta;
    const skipped = Array.isArray(exec.devices_skipped) ? exec.devices_skipped : [];
    const failed = Array.isArray(exec.devices_failed) ? exec.devices_failed : [];
    const readyCount = Array.isArray(exec.devices_ready) ? exec.devices_ready.length : result.device_summaries.length;
    const selectedCount = Number(exec.selected_device_count ?? readyCount + skipped.length + failed.length);
    const coverage = Number(exec.coverage_pct ?? (selectedCount > 0 ? (readyCount / selectedCount) * 100 : 0));
    return (
      <div style={{ minHeight: "100vh", background: COLORS.bg, color: COLORS.text, fontFamily: "'DM Sans','Segoe UI',sans-serif", padding: 12 }}>
        <div style={{ maxWidth: 900, margin: "0 auto", display: "grid", gap: 8 }}>
          <button onClick={reset} style={{ justifySelf: "start", padding: "5px 8px", borderRadius: 6, border: `1px solid ${COLORS.panelBorder}`, background: "white", color: COLORS.text, cursor: "pointer", fontSize: 11 }}>New Analysis</button>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: 8 }}>
            <Stat label="Fleet Health" value={`${result.fleet_health_score}%`} />
            <Stat label="Worst Device" value={result.worst_device_id || "N/A"} />
            <Stat label="Critical Devices" value={String(result.critical_devices.length)} />
          </div>
          <div style={panelStyle()}>
            <h3 style={titleStyle()}>Fleet Data Coverage</h3>
            <div style={{ fontSize: 11, color: COLORS.muted }}>
              Analyzed <b style={{ color: COLORS.text }}>{readyCount}</b> / <b style={{ color: COLORS.text }}>{selectedCount}</b> devices
              {" · "}
              Coverage <b style={{ color: COLORS.text }}>{coverage.toFixed(1)}%</b>
            </div>
            {(skipped.length > 0 || failed.length > 0) && (
              <div style={{ marginTop: 8, display: "grid", gap: 4 }}>
                {[...skipped, ...failed].slice(0, 20).map((item, idx: number) => (
                  <div key={`skip-${idx}`} style={{ fontSize: 11, color: COLORS.bad }}>
                    {item.device_id}: {item.message || item.reason || "Not analyzed"}
                  </div>
                ))}
                {skipped.length + failed.length > 20 && (
                  <div style={{ fontSize: 10, color: COLORS.muted }}>
                    +{skipped.length + failed.length - 20} more devices omitted
                  </div>
                )}
              </div>
            )}
          </div>
          <div style={panelStyle()}>
            <h3 style={titleStyle()}>Device Summaries</h3>
            {fleetNotice && (
              <div style={{ marginBottom: 8, color: COLORS.bad, fontSize: 11 }}>{fleetNotice}</div>
            )}
            {result.device_summaries.map((d) => (
              <button
                key={d.device_id}
                onClick={() => openFleetDevice(d.device_id, d.child_job_id)}
                style={{
                  width: "100%",
                  display: "grid",
                  gridTemplateColumns: "1fr 100px 100px",
                  gap: 8,
                  padding: "6px 0",
                  border: "none",
                  borderBottom: "1px solid #e2e8f0",
                  background: "transparent",
                  color: COLORS.text,
                  fontSize: 11,
                  textAlign: "left",
                  cursor: "pointer",
                }}
              >
                <b>{d.device_id}</b>
                <span>Health {d.health_score}%</span>
                <span>{d.failure_risk || `${d.total_anomalies || 0} anomalies`}</span>
              </button>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return <div style={{ minHeight: "100vh", background: COLORS.bg }} />;
}

function panelStyle(): React.CSSProperties {
  return {
    background: COLORS.panel,
    border: `1px solid ${COLORS.panelBorder}`,
    borderRadius: 8,
    padding: 10,
  };
}

function titleStyle(): React.CSSProperties {
  return {
    margin: "0 0 8px",
    fontSize: 12,
  };
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ background: COLORS.panel, border: `1px solid ${COLORS.panelBorder}`, borderRadius: 8, padding: 8 }}>
      <div style={{ fontSize: 10, color: COLORS.muted }}>{label}</div>
      <div style={{ marginTop: 1, fontSize: 14, fontWeight: 700, color: badgeColor(value) }}>{value}</div>
    </div>
  );
}

function RadialGauge({
  value,
  min,
  max,
  color,
  label,
  subtitle,
}: {
  value: number;
  min: number;
  max: number;
  color: string;
  label: string;
  subtitle: string;
}) {
  const clamped = Math.min(max, Math.max(min, value));
  const ratio = (clamped - min) / Math.max(1e-6, max - min);
  const sweep = 270;
  const rotate = -225;
  const dash = 235;
  const filled = dash * (ratio * (sweep / 360));
  return (
    <div style={{ display: "grid", placeItems: "center", padding: "4px 0 6px" }}>
      <div style={{ position: "relative", width: 90, height: 90 }}>
        <svg width="90" height="90">
          <g transform={`rotate(${rotate} 45 45)`}>
            <circle cx="45" cy="45" r="37" fill="none" stroke="#e2e8f0" strokeWidth="7" strokeDasharray={`${dash * (sweep / 360)} ${dash}`} strokeLinecap="round" />
            <circle cx="45" cy="45" r="37" fill="none" stroke={color} strokeWidth="7" strokeDasharray={`${filled} ${dash}`} strokeLinecap="round" />
          </g>
        </svg>
        <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div style={{ fontSize: 14, fontWeight: 700, color }}>{label}</div>
        </div>
      </div>
      <div style={{ color: COLORS.muted, fontSize: 9, marginTop: -6 }}>{subtitle}</div>
    </div>
  );
}

function DonutChart({
  segments,
  size,
  inner,
}: {
  segments: Array<{ value: number; color: string; label: string }>;
  size: number;
  inner: number;
}) {
  const total = segments.reduce((s, x) => s + Math.max(0, x.value), 0);
  const r = size / 2 - 8;
  const c = size / 2;
  const paths = segments.reduce<{ start: number; nodes: React.ReactNode[] }>(
    (acc, seg, i) => {
      const part = total > 0 ? seg.value / total : 0;
      const end = acc.start + part;
      const a0 = acc.start * Math.PI * 2 - Math.PI / 2;
      const a1 = end * Math.PI * 2 - Math.PI / 2;
      const x0 = c + r * Math.cos(a0);
      const y0 = c + r * Math.sin(a0);
      const x1 = c + r * Math.cos(a1);
      const y1 = c + r * Math.sin(a1);
      const large = end - acc.start > 0.5 ? 1 : 0;
      acc.nodes.push(
        <path
          key={`${seg.label}-${i}`}
          d={`M ${c} ${c} L ${x0} ${y0} A ${r} ${r} 0 ${large} 1 ${x1} ${y1} Z`}
          fill={seg.color}
        />
      );
      return { start: end, nodes: acc.nodes };
    },
    { start: 0, nodes: [] }
  ).nodes;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      {paths}
      <circle cx={c} cy={c} r={inner / 2} fill={COLORS.panel} />
    </svg>
  );
}

export default function AnalyticsPage() {
  return (
    <Suspense fallback={<div style={{ minHeight: "100vh", background: COLORS.bg, color: COLORS.muted, padding: 24 }}>Loading analytics...</div>}>
      <AnalyticsPageContent />
    </Suspense>
  );
}
