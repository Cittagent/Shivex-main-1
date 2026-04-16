"use client";

import {
  formatHiddenCost,
  formatHiddenNumber,
  formatSignedKwh,
  getDifferenceVsBaselineKwh,
  getHiddenBaselineStatus,
  getUsableHiddenInsightRows,
  type HiddenOverconsumptionInsight,
} from "@/lib/hiddenOverconsumptionPresentation";

interface HiddenOverconsumptionInsightSectionProps {
  insight: HiddenOverconsumptionInsight | null | undefined;
  currency: string;
}

export function HiddenOverconsumptionInsightSection({
  insight,
  currency,
}: HiddenOverconsumptionInsightSectionProps) {
  const hiddenSummary = insight?.summary ?? null;
  const hiddenRows = getUsableHiddenInsightRows(insight?.daily_breakdown);
  const hiddenUnavailable = Boolean(insight) && hiddenRows.length === 0;

  if (!insight) {
    return null;
  }

  if (hiddenUnavailable) {
    return (
      <div className="rounded-lg border border-cyan-200 bg-cyan-50 p-4 text-sm text-cyan-900">
        Hidden overconsumption insight is unavailable for this selection due to insufficient telemetry.
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-cyan-200 bg-cyan-50 p-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <div className="rounded bg-white p-3">
          <div className="text-lg font-semibold text-cyan-900">
            {formatHiddenNumber(hiddenSummary?.total_hidden_overconsumption_kwh)}
          </div>
          <div className="text-xs text-cyan-800">Total Hidden Overconsumption</div>
        </div>
        <div className="rounded bg-white p-3">
          <div className="text-lg font-semibold text-cyan-900">
            {formatHiddenCost(hiddenSummary?.total_hidden_overconsumption_cost, currency)}
          </div>
          <div className="text-xs text-cyan-800">Hidden Overconsumption Cost</div>
        </div>
        <div className="rounded bg-white p-3">
          <div className="text-lg font-semibold text-cyan-900">
            {formatHiddenNumber(hiddenSummary?.total_baseline_energy_kwh)}
          </div>
          <div className="text-xs text-cyan-800">Total Baseline Energy</div>
        </div>
        <div className="rounded bg-white p-3">
          <div className="text-lg font-semibold text-cyan-900">
            {hiddenSummary?.aggregate_p75_baseline_reference != null
              ? `${formatHiddenNumber(hiddenSummary.aggregate_p75_baseline_reference)} W`
              : "—"}
          </div>
          <div className="text-xs text-cyan-800">Aggregate P75 Baseline</div>
        </div>
        <div className="rounded bg-white p-3">
          <div className="text-lg font-semibold text-cyan-900">
            {hiddenSummary?.selected_days != null ? hiddenSummary.selected_days : "—"}
          </div>
          <div className="text-xs text-cyan-800">Selected Days</div>
        </div>
      </div>

      <div className="mt-4 overflow-x-auto">
        <table className="min-w-full divide-y divide-cyan-200 text-sm">
          <thead className="bg-cyan-100/70">
            <tr>
              <th className="px-3 py-2 text-left font-medium text-cyan-900">Date</th>
              <th className="px-3 py-2 text-left font-medium text-cyan-900">Actual Energy (kWh)</th>
              <th className="px-3 py-2 text-left font-medium text-cyan-900">P75 Baseline Power (W)</th>
              <th className="px-3 py-2 text-left font-medium text-cyan-900">Baseline Energy (kWh)</th>
              <th className="px-3 py-2 text-left font-medium text-cyan-900">Difference vs Baseline (kWh)</th>
              <th className="px-3 py-2 text-left font-medium text-cyan-900">Status</th>
              <th className="px-3 py-2 text-left font-medium text-cyan-900">Hidden Overconsumption (kWh)</th>
              <th className="px-3 py-2 text-left font-medium text-cyan-900">Hidden Overconsumption Cost</th>
              <th className="px-3 py-2 text-left font-medium text-cyan-900">Sample Count</th>
              <th className="px-3 py-2 text-left font-medium text-cyan-900">Covered Duration (hours)</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-cyan-100 bg-white">
            {hiddenRows.map((row) => {
              const difference = getDifferenceVsBaselineKwh(row);
              const status = getHiddenBaselineStatus(row);
              return (
                <tr key={row.date}>
                  <td className="px-3 py-2 text-gray-800">{row.date}</td>
                  <td className="px-3 py-2 text-gray-800">{formatHiddenNumber(row.actual_energy_kwh)}</td>
                  <td className="px-3 py-2 text-gray-800">
                    {row.p75_power_baseline_w != null ? `${formatHiddenNumber(row.p75_power_baseline_w)} W` : "—"}
                  </td>
                  <td className="px-3 py-2 text-gray-800">{formatHiddenNumber(row.baseline_energy_kwh)}</td>
                  <td className="px-3 py-2 text-gray-800">{formatSignedKwh(difference)}</td>
                  <td className="px-3 py-2 text-gray-800">
                    <span
                      className={`inline-block rounded px-2 py-1 text-xs font-medium ${
                        status === "Above Baseline"
                          ? "bg-rose-100 text-rose-700"
                          : status === "Below Baseline"
                            ? "bg-emerald-100 text-emerald-700"
                            : "bg-slate-100 text-slate-700"
                      }`}
                    >
                      {status}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-gray-800">{formatHiddenNumber(row.hidden_overconsumption_kwh)}</td>
                  <td className="px-3 py-2 text-gray-800">
                    {formatHiddenCost(row.hidden_overconsumption_cost, currency)}
                  </td>
                  <td className="px-3 py-2 text-gray-800">
                    {row.sample_count != null ? row.sample_count : "—"}
                  </td>
                  <td className="px-3 py-2 text-gray-800">{formatHiddenNumber(row.covered_duration_hours)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
