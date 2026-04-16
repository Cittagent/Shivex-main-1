import test from "node:test";
import assert from "node:assert/strict";

import {
  getCustomEndDateBounds,
  getWasteDefaultRange,
  resolveCustomEndFromStart,
  resolveMonthRange,
  resolvePresetRange,
} from "../../lib/reportDateRange.ts";

const FIXED_NOW = new Date("2026-04-16T08:00:00Z");

test("quick preset range resolves expected waste/energy-compatible ISO dates", () => {
  const lastSeven = resolvePresetRange(7, 0, FIXED_NOW);
  assert.deepEqual(lastSeven, {
    start: "2026-04-09",
    end: "2026-04-16",
  });
});

test("month picker range resolves first and last day of target month", () => {
  const marchRange = resolveMonthRange(new Date("2026-03-01T00:00:00Z"));
  assert.deepEqual(marchRange, {
    start: "2026-03-01",
    end: "2026-03-31",
  });
});

test("custom start auto-resolves bounded custom end date", () => {
  const end = resolveCustomEndFromStart("2026-02-01", FIXED_NOW);
  assert.equal(end, "2026-04-15");
});

test("custom end bounds enforce +1 day minimum and 90-day/yesterday max", () => {
  const bounds = getCustomEndDateBounds("2026-04-01", FIXED_NOW);
  assert.deepEqual(bounds, {
    min: "2026-04-02",
    max: "2026-04-15",
  });
});

test("waste default range remains sensible and deterministic", () => {
  assert.deepEqual(getWasteDefaultRange(FIXED_NOW), {
    start: "2026-04-08",
    end: "2026-04-15",
  });
});
