"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getMonthlyEnergyCalendar, MonthlyEnergyCalendarData } from "@/lib/deviceApi";
import { PageHeader } from "@/components/ui/page-scaffold";

function monthLabel(year: number, month: number): string {
  return new Date(year, month - 1, 1).toLocaleString("en-IN", {
    month: "long",
    year: "numeric",
  });
}

function formatCurrency(value: number, currency: string): string {
  try {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: currency || "INR",
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return `${currency} ${value.toFixed(2)}`;
  }
}

function formatCompactCurrency(value: number, currency: string): string {
  try {
    const formatted = new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: currency || "INR",
      maximumFractionDigits: 0,
    }).format(value);
    return formatted.replace(/\s/g, "");
  } catch {
    return `${currency} ${Math.round(value)}`;
  }
}

export default function CalendarPage() {
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [calendar, setCalendar] = useState<MonthlyEnergyCalendarData | null>(null);
  const refreshTimerRef = useRef<number | null>(null);

  const fetchCalendar = useCallback(async (opts?: { silent?: boolean }) => {
    if (!opts?.silent) {
      setLoading(true);
    }
    setError(null);
    try {
      const data = await getMonthlyEnergyCalendar(year, month);
      setCalendar(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch calendar data");
    } finally {
      if (!opts?.silent) {
        setLoading(false);
      }
    }
  }, [year, month]);

  useEffect(() => {
    fetchCalendar();
  }, [fetchCalendar]);

  const dayCostMap = useMemo(() => {
    const map = new Map<string, number>();
    for (const d of calendar?.days ?? []) {
      map.set(d.date, d.energy_cost_inr ?? 0);
    }
    return map;
  }, [calendar]);

  const dayEnergyMap = useMemo(() => {
    const map = new Map<string, number>();
    for (const d of calendar?.days ?? []) {
      map.set(d.date, d.energy_kwh ?? 0);
    }
    return map;
  }, [calendar]);

  const maxDayCost = useMemo(() => {
    const vals = Array.from(dayCostMap.values());
    if (vals.length === 0) return 0;
    return Math.max(...vals, 0);
  }, [dayCostMap]);

  const today = new Date();
  const todayKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;

  const getHeatTone = useCallback(
    (dayCost: number) => {
      if (dayCost <= 0 || maxDayCost <= 0) {
        return "bg-white";
      }
      const ratio = Math.min(1, dayCost / maxDayCost);
      if (ratio >= 0.8) return "bg-rose-100";
      if (ratio >= 0.55) return "bg-orange-100";
      if (ratio >= 0.3) return "bg-amber-100";
      return "bg-emerald-50";
    },
    [maxDayCost]
  );

  const cells = useMemo(() => {
    const first = new Date(year, month - 1, 1);
    const daysInMonth = new Date(year, month, 0).getDate();
    const firstWeekday = first.getDay(); // Sun=0
    const arr: Array<{ label: string; dateKey?: string; dayCost?: number; energyKwh?: number; isToday?: boolean }> = [];
    for (let i = 0; i < firstWeekday; i += 1) {
      arr.push({ label: "" });
    }
    for (let day = 1; day <= daysInMonth; day += 1) {
      const dateKey = `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
      arr.push({
        label: String(day),
        dateKey,
        dayCost: dayCostMap.get(dateKey) ?? 0,
        energyKwh: dayEnergyMap.get(dateKey) ?? 0,
        isToday: dateKey === todayKey,
      });
    }
    return arr;
  }, [year, month, dayCostMap, dayEnergyMap, todayKey]);

  const costDataState = calendar?.cost_data_state ?? "unavailable";
  const isCostFresh = costDataState === "fresh";

  useEffect(() => {
    let cancelled = false;
    const loop = async () => {
      await fetchCalendar({ silent: true });
      if (cancelled) return;
      const hidden = typeof document !== "undefined" && document.hidden;
      const nextMs = isCostFresh
        ? hidden
          ? 180000
          : 60000
        : hidden
          ? 45000
          : 5000;
      refreshTimerRef.current = window.setTimeout(loop, nextMs);
    };
    refreshTimerRef.current = window.setTimeout(loop, isCostFresh ? 60000 : 5000);
    return () => {
      cancelled = true;
      if (refreshTimerRef.current !== null) {
        window.clearTimeout(refreshTimerRef.current);
      }
    };
  }, [fetchCalendar, isCostFresh]);

  return (
    <div className="min-h-full bg-gradient-to-br from-slate-50 via-cyan-50/40 to-white px-2 py-2 sm:px-3 sm:py-3">
      <div className="max-w-7xl mx-auto">
        <PageHeader title="Calendar" subtitle="All-device daily energy overview" />
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6">
          <div className="flex flex-wrap items-center gap-2 self-start sm:self-auto">
            <button
              type="button"
              className="px-3 py-2 rounded-lg border border-slate-300 bg-white text-sm hover:bg-slate-100 shadow-sm"
              onClick={() => {
                if (month === 1) {
                  setMonth(12);
                  setYear((v) => v - 1);
                } else {
                  setMonth((v) => v - 1);
                }
              }}
            >
              Prev
            </button>
            <div className="min-w-[8.5rem] flex-1 text-center text-sm font-semibold text-slate-800 bg-white/80 rounded-lg border border-slate-200 px-3 py-2 sm:min-w-40 sm:flex-none">
              {monthLabel(year, month)}
            </div>
            <button
              type="button"
              className="px-3 py-2 rounded-lg border border-slate-300 bg-white text-sm hover:bg-slate-100 shadow-sm"
              onClick={() => {
                if (month === 12) {
                  setMonth(1);
                  setYear((v) => v + 1);
                } else {
                  setMonth((v) => v + 1);
                }
              }}
            >
              Next
            </button>
            <span
              className="status-pill"
              data-tone={isCostFresh ? "success" : "warning"}
              title={calendar?.cost_generated_at ? `Cost snapshot: ${new Date(calendar.cost_generated_at).toLocaleString("en-IN")}` : undefined}
            >
              {isCostFresh ? "Cost Live" : "Cost Updating"}
            </span>
          </div>
        </div>

        {loading ? (
          <div className="rounded-2xl border border-slate-200 bg-white p-10 text-sm text-slate-500 shadow-sm">Loading calendar...</div>
        ) : error ? (
          <div className="rounded-2xl border border-rose-200 bg-rose-50 p-6 text-sm text-rose-700 shadow-sm">{error}</div>
        ) : (
          <>
            <div className="mb-6 rounded-2xl border border-slate-200 bg-gradient-to-r from-slate-900 via-slate-800 to-cyan-900 text-white p-5 md:p-8 shadow-lg">
              <p className="text-[11px] uppercase tracking-[0.2em] text-cyan-200/90 font-semibold">Monthly Total Consumption</p>
              <p className="mt-3 text-3xl font-bold tabular-nums tracking-tight sm:text-4xl md:text-5xl">
                {isCostFresh
                  ? formatCurrency(calendar?.summary.total_energy_cost_inr ?? 0, calendar?.currency ?? "INR")
                  : "Cost updating…"}
              </p>
              <p className="mt-3 text-sm tabular-nums text-cyan-100 md:text-base">
                {isCostFresh ? "Month total spend across all devices" : "Waiting for fresh INR cost snapshot"}
              </p>
              <p className="text-xs text-cyan-100 mt-1">Total Energy: {(calendar?.summary.total_energy_kwh ?? 0).toFixed(2)} kWh</p>
              <p className="text-xs text-cyan-200 mt-2">
                Updated: {calendar?.generated_at ? new Date(calendar.generated_at).toLocaleString("en-IN") : "—"}
              </p>
            </div>

            <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white/80 shadow-sm backdrop-blur-sm">
              <div className="grid grid-cols-7 border-b border-slate-200 bg-gradient-to-r from-slate-50 to-cyan-50">
                {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((d, idx) => (
                  <div
                    key={d}
                    className={`px-1 py-3 text-center text-[10px] font-semibold sm:px-3 sm:py-3 sm:text-xs ${
                      idx === 0 || idx === 6 ? "text-indigo-700" : "text-slate-600"
                    }`}
                  >
                    <span className="sm:hidden">{d.slice(0, 1)}</span>
                    <span className="hidden sm:inline">{d}</span>
                  </div>
                ))}
              </div>
              <div className="grid grid-cols-7">
                {cells.map((cell, idx) => (
                  <div
                    key={`${cell.dateKey ?? "blank"}-${idx}`}
                    className={`min-h-[5.75rem] border-b border-r border-slate-100 p-1.5 transition-colors sm:min-h-[7.25rem] sm:p-2.5 lg:min-h-28 lg:p-3 ${cell.dayCost !== undefined ? getHeatTone(cell.dayCost) : "bg-white"}`}
                  >
                    {cell.label ? (
                      <>
                        <div className="flex items-center justify-between">
                          <div className={`text-xs font-semibold sm:text-sm ${cell.isToday ? "text-cyan-800" : "text-slate-800"}`}>
                            {cell.label}
                          </div>
                          {cell.isToday && <span className="h-2 w-2 rounded-full bg-cyan-500 ring-2 ring-cyan-200 sm:h-2.5 sm:w-2.5" />}
                        </div>
                        <div
                          className="mt-2 inline-flex min-h-8 max-w-full items-center rounded-md border border-slate-200 bg-white/85 px-2 py-1.5 sm:mt-3 sm:min-h-9 sm:px-3 sm:py-2"
                          title={`Energy: ${(cell.energyKwh ?? 0).toFixed(2)} kWh`}
                        >
                          <span className="truncate text-[11px] font-semibold tabular-nums text-slate-900 sm:text-[12px]">
                            {isCostFresh
                              ? (
                                <>
                                  <span className="sm:hidden">
                                    {formatCompactCurrency(cell.dayCost ?? 0, calendar?.currency ?? "INR")}
                                  </span>
                                  <span className="hidden sm:inline">
                                    {formatCurrency(cell.dayCost ?? 0, calendar?.currency ?? "INR")}
                                  </span>
                                </>
                              )
                              : "Updating…"}
                          </span>
                        </div>
                        <div className="mt-1 text-[10px] leading-tight text-slate-500 sm:text-[11px]">
                          <span className="sm:hidden">{(cell.energyKwh ?? 0).toFixed(1)} kWh</span>
                          <span className="hidden sm:inline">{(cell.energyKwh ?? 0).toFixed(2)} kWh</span>
                        </div>
                      </>
                    ) : null}
                  </div>
                ))}
              </div>
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-500 sm:gap-3">
              <span>Intensity scale</span>
              <span className="inline-flex h-4 w-4 rounded border border-slate-200 bg-emerald-50" />
              <span className="inline-flex h-4 w-4 rounded border border-slate-200 bg-amber-100" />
              <span className="inline-flex h-4 w-4 rounded border border-slate-200 bg-orange-100" />
              <span className="inline-flex h-4 w-4 rounded border border-slate-200 bg-rose-100" />
              <span className="text-slate-400">low to high daily cost (INR)</span>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
