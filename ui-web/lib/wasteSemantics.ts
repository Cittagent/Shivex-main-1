export const OVERCONSUMPTION_THRESHOLD_HELP =
  "Overconsumption is applied only after off-hours and idle-running checks. Inside an active shift, only non-idle load above this threshold is counted as overconsumption.";

export const EXCLUSIVE_LOSS_BUCKET_HELP =
  "Loss buckets are exclusive: outside-shift energy is booked to Off-hours, inside-shift idle energy is booked to Idle, and only non-idle load above threshold inside an active shift is booked to Overconsumption.";

export const IDLE_WIDGET_SCOPE_HELP =
  "Idle Running Waste shows idle loss during active shifts only. Monthly idle cost continues to use historical idle aggregation.";

export const WASTE_ANALYSIS_POLICY_HELP =
  "Waste Analysis uses the same exclusive policy as device and dashboard loss views. Outside-shift energy is counted as Off-Hours even if the machine was operationally idle during that interval.";

export function getOutsideShiftFinancialBucketMessage(loadStateLabel?: string | null): string {
  const normalizedLabel = (loadStateLabel || "").trim().toLowerCase();
  const operationalStateText =
    normalizedLabel && normalizedLabel !== "unknown"
      ? `The machine can still appear ${normalizedLabel} operationally outside a shift`
      : "The machine can still report an operational state outside a shift";
  return `${operationalStateText}, but outside-shift energy is financially booked to Off-hours Loss. Idle and Overconsumption accrue only during active shifts.`;
}

export function validateThresholdGap(
  idleThreshold: number | null | undefined,
  overThreshold: number | null | undefined,
): string | null {
  if (idleThreshold == null || overThreshold == null) {
    return null;
  }
  if (overThreshold <= idleThreshold) {
    return "Overconsumption threshold must be greater than idle threshold so waste categories remain exclusive.";
  }
  return null;
}

export function parseThresholdDraft(input: string): number | null {
  const trimmed = input.trim();
  if (!trimmed) {
    return null;
  }
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

export function hasUnsavedThresholdDraft(
  draft: string,
  persisted: number | null | undefined,
): boolean {
  const parsedDraft = parseThresholdDraft(draft);
  return parsedDraft !== (persisted ?? null);
}

export function validateIdleThresholdSave(
  nextIdleThreshold: number,
  persistedOverThreshold: number | null | undefined,
): string | null {
  return validateThresholdGap(nextIdleThreshold, persistedOverThreshold);
}

export function validateOverconsumptionThresholdSave(
  persistedIdleThreshold: number | null | undefined,
  nextOverThreshold: number | null,
): string | null {
  return validateThresholdGap(persistedIdleThreshold, nextOverThreshold);
}

export function getThresholdDriftWarning(params: {
  saveTarget: "idle" | "overconsumption";
  idleDraft: string;
  persistedIdleThreshold: number | null | undefined;
  overDraft: string;
  persistedOverThreshold: number | null | undefined;
}): string | null {
  const idleDirty = hasUnsavedThresholdDraft(params.idleDraft, params.persistedIdleThreshold);
  const overDirty = hasUnsavedThresholdDraft(params.overDraft, params.persistedOverThreshold);
  if (params.saveTarget === "idle" && overDirty) {
    return "Overconsumption threshold has unsaved changes. Idle validation still uses the last saved overconsumption threshold until Waste Config is saved.";
  }
  if (params.saveTarget === "overconsumption" && idleDirty) {
    return "Idle threshold has unsaved changes. Waste validation still uses the last saved idle threshold until Idle Threshold is saved.";
  }
  return null;
}

export function getIdleSaveBlockReason(
  nextIdleThreshold: number | null,
  persistedOverThreshold: number | null | undefined,
): string | null {
  if (nextIdleThreshold == null || !Number.isFinite(nextIdleThreshold) || nextIdleThreshold <= 0) {
    return "Idle threshold must be a positive number.";
  }
  if (persistedOverThreshold != null && nextIdleThreshold >= persistedOverThreshold) {
    return `Idle ${nextIdleThreshold.toFixed(2)}A cannot be saved because saved overconsumption threshold is ${persistedOverThreshold.toFixed(2)}A. Save Waste Configuration first or lower idle threshold.`;
  }
  return null;
}

export function getOverconsumptionSaveBlockReason(
  persistedIdleThreshold: number | null | undefined,
  nextOverThreshold: number | null,
): string | null {
  if (nextOverThreshold != null && (!Number.isFinite(nextOverThreshold) || nextOverThreshold <= 0)) {
    return "Overconsumption threshold must be a positive number.";
  }
  if (persistedIdleThreshold != null && nextOverThreshold != null && nextOverThreshold <= persistedIdleThreshold) {
    return `Overconsumption ${nextOverThreshold.toFixed(2)}A cannot be saved because saved idle threshold is ${persistedIdleThreshold.toFixed(2)}A. Save Idle Threshold first or raise overconsumption threshold.`;
  }
  return null;
}
