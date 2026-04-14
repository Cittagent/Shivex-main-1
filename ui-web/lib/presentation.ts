export type Tone = "success" | "warning" | "danger" | "info" | "neutral";

export function getStatusTone(status: string | null | undefined): Tone {
  const value = (status || "").toLowerCase();
  if (["active", "online", "running", "healthy", "up", "classified"].includes(value)) return "success";
  if (["warning", "degraded", "idle", "maintenance", "pending"].includes(value)) return "warning";
  if (["inactive", "offline", "stopped", "down", "error", "failed"].includes(value)) return "danger";
  if (["paused", "open", "unclassified", "info"].includes(value)) return "info";
  return "neutral";
}

export function formatCompactNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

export function formatCurrencyINR(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 }).format(value);
}

function isVisibleSmallNonZero(value: number, threshold: number): boolean {
  return Number.isFinite(value) && value > 0 && value < threshold;
}

export function formatEnergyKwh(value: number | null | undefined, threshold = 0.01): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  if (isVisibleSmallNonZero(value, threshold)) {
    return `< ${threshold.toFixed(2)} kWh`;
  }
  return `${value.toFixed(2)} kWh`;
}

export function formatCurrencyValue(
  value: number | null | undefined,
  currency = "INR",
  threshold = 0.01,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const formatter = new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  if (isVisibleSmallNonZero(value, threshold)) {
    return `< ${formatter.format(threshold)}`;
  }
  return formatter.format(value);
}

export function formatCurrencyCodeValue(
  value: number | null | undefined,
  currency = "INR",
  threshold = 0.01,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  if (isVisibleSmallNonZero(value, threshold)) {
    return `< ${currency} ${threshold.toFixed(2)}`;
  }
  return `${currency} ${value.toFixed(2)}`;
}
