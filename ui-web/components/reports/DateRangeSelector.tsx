"use client";

import { useState, useEffect } from "react";
import {
  formatIsoDate,
  getCustomEndDateBounds,
  getMaxSelectableDate,
  getMinSelectableDate,
  getRecentMonths,
  REPORT_DATE_PRESETS,
  resolveCustomEndFromStart,
  resolveMonthRange,
  resolvePresetRange,
} from "@/lib/reportDateRange";

interface DateRangeSelectorProps {
  onRangeChange: (start: string, end: string) => void;
  disabled?: boolean;
  initialRange?: { start: string; end: string } | null;
  initialMode?: TabMode;
}

type TabMode = "presets" | "month" | "custom";

export function DateRangeSelector({ onRangeChange, disabled, initialRange, initialMode = "presets" }: DateRangeSelectorProps) {
  const [mode, setMode] = useState<TabMode>(initialMode);
  const [startDate, setStartDate] = useState<string>("");
  const [endDate, setEndDate] = useState<string>("");
  const [selectedMonth, setSelectedMonth] = useState<string>(initialRange?.start || "");
  const today = new Date();

  const formatDisplay = (d: Date): string =>
    d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
  const presets = REPORT_DATE_PRESETS;
  const months = getRecentMonths(12, today);

  useEffect(() => {
    if (!initialRange?.start || !initialRange?.end) return;
    setStartDate(initialRange.start);
    setEndDate(initialRange.end);
    onRangeChange(initialRange.start, initialRange.end);
  }, [initialRange, onRangeChange]);

  const handlePresetClick = (days: number, offset: number = 0) => {
    const range = resolvePresetRange(days, offset, today);
    setStartDate(range.start);
    setEndDate(range.end);
    onRangeChange(range.start, range.end);
  };

  const handleMonthClick = (monthDate: Date) => {
    const range = resolveMonthRange(monthDate);
    setStartDate(range.start);
    setEndDate(range.end);
    setSelectedMonth(formatIsoDate(monthDate));
    onRangeChange(range.start, range.end);
  };

  const handleCustomStartChange = (value: string) => {
    setStartDate(value);
    const endStr = resolveCustomEndFromStart(value, today);
    setEndDate(endStr);
    onRangeChange(value, endStr);
  };

  const handleCustomEndChange = (value: string) => {
    setEndDate(value);
    onRangeChange(startDate, value);
  };

  const minDate = getMinSelectableDate(today);
  const maxDate = getMaxSelectableDate(today);
  const customEndBounds = startDate ? getCustomEndDateBounds(startDate, today) : null;
  const minEndDate = customEndBounds?.min || "";
  const maxEndDate = customEndBounds?.max || maxDate;

  const getDaysBetween = (): number => {
    if (!startDate || !endDate) return 0;
    const diff = new Date(endDate).getTime() - new Date(startDate).getTime();
    return Math.floor(diff / (1000 * 60 * 60 * 24)) + 1;
  };

  const getRangeSummary = (): string => {
    if (!startDate || !endDate) return "";
    const start = new Date(startDate);
    const end = new Date(endDate);
    const days = getDaysBetween();
    return `${formatDisplay(start)} – ${formatDisplay(end)} (${days} days)`;
  };

  return (
    <div className="space-y-4">
      <div className="flex gap-2 border-b">
        {(["presets", "month", "custom"] as TabMode[]).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            disabled={disabled}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              mode === m
                ? "border-blue-600 text-blue-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            {m === "presets" ? "Quick Presets" : m === "month" ? "Month Picker" : "Custom"}
          </button>
        ))}
      </div>

      <div className="p-4 bg-gray-50 rounded-lg">
        {mode === "presets" && (
          <div className="flex flex-wrap gap-2">
            {presets.map((p) => (
              <button
                key={p.label}
                onClick={() => handlePresetClick(p.days, p.offset || 0)}
                disabled={disabled}
                className="px-3 py-1.5 text-sm bg-white border rounded-md hover:bg-blue-50 hover:border-blue-300 transition-colors"
              >
                {p.label}
              </button>
            ))}
          </div>
        )}

        {mode === "month" && (
          <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
            {months.map((m) => (
              <button
                key={m.toISOString()}
                onClick={() => handleMonthClick(m)}
                disabled={disabled}
                className={`px-3 py-2 text-sm bg-white border rounded-md hover:bg-blue-50 hover:border-blue-300 transition-colors ${
                  selectedMonth === formatIsoDate(m) ? "border-blue-500 text-blue-700" : ""
                }`}
              >
                {m.toLocaleDateString("en-GB", { month: "short", year: "2-digit" })}
              </button>
            ))}
          </div>
        )}

        {mode === "custom" && (
          <div className="space-y-3">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Start Date</label>
              <input
                type="date"
                value={startDate}
                onChange={(e) => handleCustomStartChange(e.target.value)}
                min={minDate}
                max={maxDate}
                disabled={disabled}
                className="w-full px-3 py-2 border rounded-md text-sm"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">End Date</label>
              <input
                type="date"
                value={endDate}
                onChange={(e) => handleCustomEndChange(e.target.value)}
                min={minEndDate}
                max={maxEndDate}
                disabled={disabled}
                className="w-full px-3 py-2 border rounded-md text-sm"
              />
            </div>
            {startDate && endDate && (
              <p className="text-sm text-gray-600">{getDaysBetween()} days selected</p>
            )}
          </div>
        )}
      </div>

      {startDate && endDate && (
        <div className="text-sm text-gray-600 bg-blue-50 p-3 rounded-md">
          Selected: <strong>{getRangeSummary()}</strong>
        </div>
      )}
    </div>
  );
}
