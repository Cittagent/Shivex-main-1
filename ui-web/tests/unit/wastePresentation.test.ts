import test from "node:test";
import assert from "node:assert/strict";

import { formatCurrencyCodeValue, formatCurrencyValue, formatEnergyKwh } from "../../lib/presentation.ts";
import {
  EXCLUSIVE_LOSS_BUCKET_HELP,
  IDLE_WIDGET_SCOPE_HELP,
  WASTE_ANALYSIS_POLICY_HELP,
  getIdleSaveBlockReason,
  getOverconsumptionSaveBlockReason,
  OVERCONSUMPTION_THRESHOLD_HELP,
  getOutsideShiftFinancialBucketMessage,
  getThresholdDriftWarning,
  validateIdleThresholdSave,
  validateOverconsumptionThresholdSave,
  validateThresholdGap,
} from "../../lib/wasteSemantics.ts";

test("formatEnergyKwh keeps small non-zero values visible", () => {
  assert.equal(formatEnergyKwh(0), "0.00 kWh");
  assert.equal(formatEnergyKwh(0.0042), "< 0.01 kWh");
  assert.equal(formatEnergyKwh(0.125), "0.13 kWh");
});

test("formatCurrencyValue keeps small non-zero values visible", () => {
  assert.equal(formatCurrencyValue(0, "INR"), "₹0.00");
  assert.equal(formatCurrencyValue(0.0042, "INR"), "< ₹0.01");
  assert.equal(formatCurrencyValue(12.5, "INR"), "₹12.50");
});

test("formatCurrencyCodeValue preserves cents for report summary cards", () => {
  assert.equal(formatCurrencyCodeValue(3.55, "INR"), "INR 3.55");
  assert.equal(formatCurrencyCodeValue(0.0042, "INR"), "< INR 0.01");
  assert.equal(formatCurrencyCodeValue(null, "INR"), "—");
});

test("overconsumption help text matches exclusive accounting policy", () => {
  assert.match(OVERCONSUMPTION_THRESHOLD_HELP, /after off-hours and idle-running checks/i);
  assert.doesNotMatch(OVERCONSUMPTION_THRESHOLD_HELP, /independent of idle threshold/i);
});

test("shared loss copy explains exclusive buckets and outside-shift booking", () => {
  assert.match(EXCLUSIVE_LOSS_BUCKET_HELP, /outside-shift energy is booked to Off-hours/i);
  assert.match(IDLE_WIDGET_SCOPE_HELP, /during active shifts only/i);
  assert.match(WASTE_ANALYSIS_POLICY_HELP, /outside-shift energy is counted as Off-Hours/i);
});

test("outside-shift financial bucket message separates operational state from financial loss bucket", () => {
  assert.match(
    getOutsideShiftFinancialBucketMessage("Idle"),
    /appear idle operationally outside a shift/i,
  );
  assert.match(
    getOutsideShiftFinancialBucketMessage("Idle"),
    /financially booked to Off-hours Loss/i,
  );
  assert.match(
    getOutsideShiftFinancialBucketMessage("In Load"),
    /idle and overconsumption accrue only during active shifts/i,
  );
});

test("threshold gap validation rejects overlapping idle and overconsumption thresholds", () => {
  assert.equal(
    validateThresholdGap(1, 0.5),
    "Overconsumption threshold must be greater than idle threshold so waste categories remain exclusive.",
  );
  assert.equal(validateThresholdGap(1, 2), null);
  assert.equal(validateThresholdGap(null, 2), null);
});

test("idle save validates against persisted over-threshold, not unsaved draft over-threshold", () => {
  assert.equal(
    validateIdleThresholdSave(0.6, 0.5),
    "Overconsumption threshold must be greater than idle threshold so waste categories remain exclusive.",
  );
  assert.equal(validateIdleThresholdSave(0.6, 1), null);
});

test("waste save validates against persisted idle-threshold", () => {
  assert.equal(
    validateOverconsumptionThresholdSave(0.6, 0.5),
    "Overconsumption threshold must be greater than idle threshold so waste categories remain exclusive.",
  );
  assert.equal(validateOverconsumptionThresholdSave(0.6, 1), null);
});

test("threshold drift warning explains unsaved sibling state", () => {
  assert.match(
    getThresholdDriftWarning({
      saveTarget: "idle",
      idleDraft: "0.6",
      persistedIdleThreshold: 0.6,
      overDraft: "1.0",
      persistedOverThreshold: 0.5,
    }) || "",
    /unsaved changes/i,
  );
  assert.equal(
    getThresholdDriftWarning({
      saveTarget: "overconsumption",
      idleDraft: "0.6",
      persistedIdleThreshold: 0.6,
      overDraft: "1.0",
      persistedOverThreshold: 1.0,
    }),
    null,
  );
});

test("idle save block reason references saved overconsumption threshold", () => {
  assert.match(
    getIdleSaveBlockReason(0.2, 0.1) || "",
    /saved overconsumption threshold is 0.10A/i,
  );
  assert.equal(getIdleSaveBlockReason(0.2, 0.8), null);
});

test("waste save block reason references saved idle threshold", () => {
  assert.match(
    getOverconsumptionSaveBlockReason(0.6, 0.5) || "",
    /saved idle threshold is 0.60A/i,
  );
  assert.equal(getOverconsumptionSaveBlockReason(0.2, 0.8), null);
});
