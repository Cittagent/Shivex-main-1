import { ANALYTICS_SERVICE_BASE } from "./api";
import { apiFetch } from "./apiFetch";

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(message: string, status: number, body: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

async function requestJson<T = unknown>(url: string, options?: RequestInit): Promise<T> {
  const response = await apiFetch(url, options);
  const contentType = response.headers.get("content-type") ?? "";

  let body: unknown;
  try {
    if (contentType.includes("application/json")) {
      body = await response.json();
    } else {
      body = await response.text();
    }
  } catch {
    body = null;
  }

  if (!response.ok) {
    const b = body as Record<string, unknown> | null;
    const message =
      (typeof b === "object" &&
        b !== null &&
        (b.detail ?? b.message ?? b.error)) ||
      (typeof body === "string" ? body : null) ||
      `Request failed with status ${response.status}`;
    throw new ApiError(String(message), response.status, body);
  }

  return body as T;
}

export type AnalyticsType = "anomaly" | "prediction" | "forecast";

export interface RunAnalyticsRequest {
  device_id: string;
  analysis_type: AnalyticsType;
  model_name: string;
  dataset_key?: string;
  parameters?: Record<string, unknown>;
  start_time?: string;
  end_time?: string;
}

export interface RunFleetAnalyticsRequest {
  device_ids?: string[];
  start_time: string;
  end_time: string;
  analysis_type: "anomaly" | "prediction";
  model_name?: string;
  parameters?: Record<string, unknown>;
}

export interface AnomalyFormattedResult {
  analysis_type: "anomaly_detection";
  device_id: string;
  job_id: string;
  health_score: number;
  confidence?: {
    level: string;
    badge_color: string;
    banner_text: string;
    banner_style: string;
    days_available: number;
  };
  summary: {
    total_anomalies: number;
    anomaly_rate_pct: number;
    anomaly_score: number;
    health_impact: "Normal" | "Low" | "Moderate" | "Critical";
    most_affected_parameter: string;
    data_points_analyzed: number;
    days_analyzed: number;
    model_confidence: string;
    sensitivity: string;
  };
  anomaly_rate_gauge?: {
    value: number;
    max: number;
    color: "green" | "amber" | "red";
  };
  parameter_breakdown: Array<{
    parameter: string;
    anomaly_count: number;
    anomaly_pct: number;
    severity_distribution: { low: number; medium: number; high: number };
  }>;
  anomalies_over_time: Array<{
    date: string;
    count: number;
    high_count: number;
    medium_count: number;
    low_count: number;
  }>;
  anomaly_list: Array<{
    timestamp: string;
    severity: "low" | "medium" | "high";
    parameters: string[];
    context: string;
    reasoning: string;
    recommended_action: string;
  }>;
  recommendations: Array<{
    rank: number;
    action: string;
    urgency: string;
    reasoning: string;
    parameter?: string;
  }>;
  metadata: Record<string, unknown>;
  ensemble?: {
    vote_count?: number;
    confidence?: string;
    models_voted?: string[][];
    per_model?: Record<string, unknown>;
    timeline?: {
      vote_count?: number[];
      confidence?: string[];
      models_voted?: string[][];
    };
  };
  reasoning?: {
    summary?: string;
    affected_parameters?: string[];
    recommended_action?: string;
    confidence?: string;
  };
  data_quality_flags?: Array<Record<string, unknown>>;
}

export interface FailureFormattedResult {
  analysis_type: "failure_prediction";
  device_id: string;
  job_id: string;
  health_score: number;
  confidence?: {
    level: string;
    badge_color: string;
    banner_text: string;
    banner_style: string;
    days_available: number;
  };
  summary: {
    failure_risk: "Minimal" | "Low" | "Medium" | "High" | "Critical";
    failure_probability_pct: number;
    failure_probability_meter: number;
    safe_probability_pct?: number;
    estimated_remaining_life: string;
    maintenance_urgency: string;
    confidence_level: string;
    days_analyzed: number;
  };
  risk_breakdown: { safe_pct: number; warning_pct: number; critical_pct: number };
  risk_factors: Array<{
    parameter: string;
    contribution_pct: number;
    trend: "increasing" | "decreasing" | "stable" | "erratic";
    context: string;
    reasoning: string;
    current_value: number;
    baseline_value: number;
  }>;
  insufficient_trend_signal?: boolean;
  recommended_actions: Array<{
    rank: number;
    action: string;
    urgency: string;
    reasoning: string;
    parameter?: string;
  }>;
  metadata: Record<string, unknown>;
  ensemble?: {
    verdict?: string;
    votes?: number;
    confidence?: string;
    models_voted?: string[];
    combined_probability?: number;
    per_model?: Record<string, unknown>;
  };
  time_to_failure?: {
    hours?: number | null;
    label?: string;
    confidence_interval?: [number, number] | null;
    trend_type?: string;
    trend_r2?: number;
    is_reliable?: boolean;
  };
  reasoning?: {
    summary?: string;
    agreement_text?: string;
    trend_text?: string;
    top_risk_factors?: string[];
    recommended_actions?: string[];
    confidence?: string;
  };
  degradation_series?: number[];
  data_quality_flags?: Array<Record<string, unknown>>;
}

export interface FleetFormattedResult {
  analysis_type: "fleet";
  job_id: string;
  fleet_health_score: number;
  worst_device_id: string | null;
  worst_device_health: number;
  critical_devices: string[];
  source_analysis_type: string;
  device_summaries: Array<{
    device_id: string;
    health_score: number;
    failure_risk?: string;
    total_anomalies?: number;
    anomaly_rate_pct?: number;
    maintenance_urgency?: string;
    child_job_id?: string;
  }>;
  execution_metadata?: {
    fleet_policy?: string;
    children_count?: number;
    devices_ready?: string[];
    devices_failed?: Array<{ device_id: string; reason?: string; message?: string }>;
    devices_skipped?: Array<{ device_id: string; reason?: string; message?: string }>;
    skipped_reasons?: Record<string, string>;
    coverage_pct?: number;
    selected_device_count?: number;
    reason?: string;
  };
}

export interface SupportedModelsResponse {
  anomaly_detection: string[];
  failure_prediction: string[];
  forecasting: string[];
  ensembles?: Array<Record<string, unknown>>;
}

export interface AvailableDataset {
  key: string;
  size: number;
  last_modified: string;
}

export interface AvailableDatasetsResponse {
  device_id: string;
  datasets: AvailableDataset[];
}

export interface AnalyticsJobListItem {
  job_id: string;
  status: string;
  progress?: number | null;
  message?: string | null;
  error_message?: string | null;
  error_code?: string | null;
  created_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  queue_position?: number | null;
  attempt?: number | null;
  worker_lease_expires_at?: string | null;
  estimated_wait_seconds?: number | null;
}

export async function runAnalytics(payload: RunAnalyticsRequest) {
  return requestJson<{ job_id: string; status: string; message: string }>(
    `${ANALYTICS_SERVICE_BASE}/api/v1/analytics/run`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export async function runFleetAnalytics(payload: RunFleetAnalyticsRequest) {
  return requestJson<{ job_id: string; status: string; message: string }>(
    `${ANALYTICS_SERVICE_BASE}/api/v1/analytics/run-fleet`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export async function getAnalyticsStatus(jobId: string) {
  return requestJson<{
    job_id: string;
    status: string;
    progress: number;
    message: string;
    error_message?: string;
    error_code?: string;
  }>(`${ANALYTICS_SERVICE_BASE}/api/v1/analytics/status/${jobId}`);
}

export async function getAnalyticsResults(
  jobId: string
): Promise<Record<string, unknown>> {
  return requestJson<Record<string, unknown>>(
    `${ANALYTICS_SERVICE_BASE}/api/v1/analytics/results/${jobId}`
  );
}

export async function getFormattedResults(
  jobId: string
): Promise<AnomalyFormattedResult | FailureFormattedResult | FleetFormattedResult> {
  try {
    return await requestJson<
      AnomalyFormattedResult | FailureFormattedResult | FleetFormattedResult
    >(`${ANALYTICS_SERVICE_BASE}/api/v1/analytics/formatted-results/${jobId}`);
  } catch {
    const data = await requestJson<Record<string, unknown>>(
      `${ANALYTICS_SERVICE_BASE}/api/v1/analytics/results/${jobId}`
    );
    const formatted =
      (data?.results as Record<string, unknown> | undefined)?.formatted ??
      data?.formatted ??
      null;
    if (
      !formatted ||
      typeof formatted !== "object" ||
      !("analysis_type" in formatted)
    ) {
      throw new Error("No formatted results available for this job");
    }
    return formatted as
      | AnomalyFormattedResult
      | FailureFormattedResult
      | FleetFormattedResult;
  }
}

export async function getRetrainStatus(): Promise<Record<string, unknown>> {
  return requestJson<Record<string, unknown>>(
    `${ANALYTICS_SERVICE_BASE}/api/v1/analytics/retrain-status`
  );
}

export async function getSupportedModels(): Promise<SupportedModelsResponse> {
  return requestJson<SupportedModelsResponse>(
    `${ANALYTICS_SERVICE_BASE}/api/v1/analytics/models`
  );
}

export async function getAvailableDatasets(
  deviceId: string
): Promise<AvailableDatasetsResponse> {
  return requestJson<AvailableDatasetsResponse>(
    `${ANALYTICS_SERVICE_BASE}/api/v1/analytics/datasets?device_id=${deviceId}`
  );
}

export async function listAnalyticsJobs(params?: {
  status?: string;
  device_id?: string;
  limit?: number;
  offset?: number;
}): Promise<AnalyticsJobListItem[]> {
  const search = new URLSearchParams();
  if (params?.status) search.set("status", params.status);
  if (params?.device_id) search.set("device_id", params.device_id);
  if (typeof params?.limit === "number") search.set("limit", String(params.limit));
  if (typeof params?.offset === "number") search.set("offset", String(params.offset));
  const query = search.toString();
  return requestJson<AnalyticsJobListItem[]>(
    `${ANALYTICS_SERVICE_BASE}/api/v1/analytics/jobs${query ? `?${query}` : ""}`
  );
}
