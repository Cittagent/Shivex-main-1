import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  formatSignedKwh,
  formatHiddenCost,
  getDifferenceVsBaselineKwh,
  getHiddenBaselineStatus,
  getUsableHiddenInsightRows,
  isFiniteNumber,
  type HiddenOverconsumptionInsight,
} from "../../lib/hiddenOverconsumptionPresentation.ts";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const energyPagePath = path.resolve(__dirname, "../../app/(protected)/reports/energy/page.tsx");
const sharedSectionPath = path.resolve(
  __dirname,
  "../../components/reports/HiddenOverconsumptionInsightSection.tsx",
);
const pdfBuilderPath = path.resolve(
  __dirname,
  "../../../services/reporting-service/src/pdf/builder.py",
);
const energyPageSource = readFileSync(energyPagePath, "utf-8");
const sharedSectionSource = readFileSync(sharedSectionPath, "utf-8");
const pdfBuilderSource = readFileSync(pdfBuilderPath, "utf-8");

function baseInsight(): HiddenOverconsumptionInsight {
  return {
    summary: {
      selected_days: 1,
      total_actual_energy_kwh: 15,
      aggregate_p75_baseline_reference: 450,
      total_baseline_energy_kwh: 12,
      total_hidden_overconsumption_kwh: 3,
      total_hidden_overconsumption_cost: 30,
    },
    daily_breakdown: [
      {
        date: "2026-04-10",
        actual_energy_kwh: 15,
        p75_power_baseline_w: 450,
        baseline_energy_kwh: 12,
        hidden_overconsumption_kwh: 3,
        hidden_overconsumption_cost: 30,
        sample_count: 10,
        covered_duration_hours: 24,
      },
    ],
  };
}

test("energy report page reuses the shared hidden overconsumption section", () => {
  assert.equal(
    energyPageSource.includes('import { HiddenOverconsumptionInsightSection } from "@/components/reports/HiddenOverconsumptionInsightSection";'),
    true,
  );
  assert.equal(energyPageSource.includes("<HiddenOverconsumptionInsightSection"), true);
  assert.equal(
    energyPageSource.includes('const hiddenInsight = result?.hidden_overconsumption_insight ?? null;'),
    true,
  );
});

test("completed energy report switches to a full-width result layout", () => {
  assert.equal(
    energyPageSource.includes("const isCompletedView = viewState === \"completed\" && result != null;"),
    true,
  );
  assert.equal(
    energyPageSource.includes("Completed reports use a full-width layout so detailed sections like Hidden Overconsumption stay readable."),
    true,
  );
  assert.equal(
    energyPageSource.includes("{isCompletedView ? ("),
    true,
  );
  assert.equal(
    energyPageSource.includes("grid gap-6 lg:grid-cols-[minmax(320px,420px)_minmax(0,1fr)]"),
    true,
  );
});

test("shared hidden overconsumption section includes the full rich table structure", () => {
  assert.equal(sharedSectionSource.includes("Actual Energy (kWh)"), true);
  assert.equal(sharedSectionSource.includes("P75 Baseline Power (W)"), true);
  assert.equal(sharedSectionSource.includes("Baseline Energy (kWh)"), true);
  assert.equal(sharedSectionSource.includes("Difference vs Baseline (kWh)"), true);
  assert.equal(sharedSectionSource.includes("Status"), true);
  assert.equal(sharedSectionSource.includes("Hidden Overconsumption (kWh)"), true);
  assert.equal(sharedSectionSource.includes("Hidden Overconsumption Cost"), true);
  assert.equal(sharedSectionSource.includes("Sample Count"), true);
  assert.equal(sharedSectionSource.includes("Covered Duration (hours)"), true);
});

test("shared hidden overconsumption section keeps summary cards above the records table", () => {
  assert.equal(sharedSectionSource.includes("Total Hidden Overconsumption"), true);
  assert.equal(sharedSectionSource.includes("Hidden Overconsumption Cost"), true);
  assert.equal(sharedSectionSource.includes("Total Baseline Energy"), true);
  assert.equal(sharedSectionSource.includes("Aggregate P75 Baseline"), true);
  assert.equal(sharedSectionSource.includes("Selected Days"), true);
  assert.equal(sharedSectionSource.includes("grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5"), true);
});

test("old report-specific inline hidden overconsumption block is removed from the page", () => {
  assert.equal(energyPageSource.includes("Total Hidden Overconsumption (kWh)"), false);
  assert.equal(energyPageSource.includes("Difference vs Baseline (kWh)"), false);
  assert.equal(energyPageSource.includes("Hidden Overconsumption Insight (P75 Baseline)"), false);
});

test("single-day selection keeps one usable row", () => {
  const insight = baseInsight();
  const rows = getUsableHiddenInsightRows(insight.daily_breakdown);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].date, "2026-04-10");
});

test("multi-day selection keeps one usable row per day", () => {
  const insight = baseInsight();
  insight.daily_breakdown = [
    ...(insight.daily_breakdown || []),
    {
      date: "2026-04-11",
      actual_energy_kwh: 11,
      p75_power_baseline_w: 400,
      baseline_energy_kwh: 9,
      hidden_overconsumption_kwh: 2,
      hidden_overconsumption_cost: 20,
      sample_count: 8,
      covered_duration_hours: 20,
    },
  ];
  const rows = getUsableHiddenInsightRows(insight.daily_breakdown);
  assert.equal(rows.length, 2);
  assert.deepEqual(rows.map((row) => row.date), ["2026-04-10", "2026-04-11"]);
});

test("insufficient telemetry rows are filtered and page contains clean fallback text", () => {
  const rows = getUsableHiddenInsightRows([
    {
      date: "2026-04-10",
      actual_energy_kwh: 10,
      p75_power_baseline_w: null,
      baseline_energy_kwh: null,
      hidden_overconsumption_kwh: 0,
    },
  ]);
  assert.equal(rows.length, 0);
  assert.equal(
    sharedSectionSource.includes(
      "Hidden overconsumption insight is unavailable for this selection due to insufficient telemetry.",
    ),
    true,
  );
});

test("absent hidden insight contract remains safe through nullish handling", () => {
  const hiddenInsight: HiddenOverconsumptionInsight | null = null;
  const rows = getUsableHiddenInsightRows(hiddenInsight?.daily_breakdown);
  assert.equal(rows.length, 0);
  assert.equal(
    energyPageSource.includes("const hiddenInsight = result?.hidden_overconsumption_insight ?? null;"),
    true,
  );
  assert.equal(sharedSectionSource.includes("if (!insight) {"), true);
});

test("empty daily breakdown is handled safely", () => {
  const rows = getUsableHiddenInsightRows([]);
  assert.deepEqual(rows, []);
});

test("missing tariff cost uses clean N/A fallback", () => {
  assert.equal(formatHiddenCost(null, "INR"), "N/A");
  assert.equal(formatHiddenCost(undefined, "INR"), "N/A");
});

test("difference and status clarify below/within/above baseline days", () => {
  const belowRow = {
    date: "2026-04-10",
    actual_energy_kwh: 1.357,
    baseline_energy_kwh: 1.9596,
    p75_power_baseline_w: 250,
    hidden_overconsumption_kwh: 0,
    hidden_overconsumption_cost: 0,
  };
  const aboveRow = {
    ...belowRow,
    actual_energy_kwh: 2.5,
    baseline_energy_kwh: 2.0,
    hidden_overconsumption_kwh: 0.5,
    hidden_overconsumption_cost: 4.15,
  };
  const withinRow = {
    ...belowRow,
    actual_energy_kwh: 2.0,
    baseline_energy_kwh: 2.0,
  };

  assert.equal(getDifferenceVsBaselineKwh(belowRow), -0.6026);
  assert.equal(getDifferenceVsBaselineKwh(aboveRow), 0.5);
  assert.equal(getDifferenceVsBaselineKwh(withinRow), 0);

  assert.equal(getHiddenBaselineStatus(belowRow), "Below Baseline");
  assert.equal(getHiddenBaselineStatus(aboveRow), "Above Baseline");
  assert.equal(getHiddenBaselineStatus(withinRow), "Within Baseline");

  assert.equal(formatSignedKwh(getDifferenceVsBaselineKwh(belowRow), 4), "-0.6026");
  assert.equal(formatSignedKwh(getDifferenceVsBaselineKwh(aboveRow), 4), "+0.5000");
  assert.equal(formatSignedKwh(getDifferenceVsBaselineKwh(withinRow), 4), "0.0000");
});

test("zero values remain valid display values, not treated as missing", () => {
  assert.equal(isFiniteNumber(0), true);
  assert.equal(formatHiddenCost(0, "INR"), "INR 0.00");
});

test("existing energy report sections remain present", () => {
  assert.equal(energyPageSource.includes("Data Notes"), true);
  assert.equal(energyPageSource.includes("Key Insights"), true);
  assert.equal(energyPageSource.includes("Download PDF"), true);
  assert.equal(energyPageSource.includes("Configure Another Report"), true);
});

test("quick snapshot shared section and pdf keep aligned rich hidden-insight table structure", () => {
  const labels = [
    "Actual Energy (kWh)",
    "P75 Baseline Power (W)",
    "Baseline Energy (kWh)",
    "Difference vs Baseline (kWh)",
    "Status",
    "Hidden Overconsumption (kWh)",
    "Hidden Overconsumption Cost",
    "Sample Count",
    "Covered Duration (hours)",
  ];

  for (const label of labels) {
    assert.equal(sharedSectionSource.includes(label), true, `UI missing label: ${label}`);
    assert.equal(pdfBuilderSource.includes(label), true, `PDF missing label: ${label}`);
  }

  assert.equal(sharedSectionSource.includes("colSpan={4}"), false);
  assert.equal(pdfBuilderSource.includes("colspan=\"4\">Reference"), false);
  assert.equal(pdfBuilderSource.includes("Aggregation Rule"), false);
  assert.equal(pdfBuilderSource.includes("hidden-record-card"), true);
  assert.equal(pdfBuilderSource.includes("hidden-record-grid"), true);
  assert.equal(pdfBuilderSource.includes("<th class=\"align-right\">Hidden Overconsumption (kWh)</th>"), false);
  assert.equal(pdfBuilderSource.includes("<th class=\"align-right\">Covered Duration (hours)</th>"), false);
});

test("pdf template keeps hidden overconsumption summary cards", () => {
  assert.equal(pdfBuilderSource.includes("Total Hidden Overconsumption"), true);
  assert.equal(pdfBuilderSource.includes("Hidden Overconsumption Cost"), true);
  assert.equal(pdfBuilderSource.includes("Total Baseline Energy"), true);
  assert.equal(pdfBuilderSource.includes("Aggregate P75 Baseline"), true);
  assert.equal(pdfBuilderSource.includes("selected day"), true);
});
