export interface DateRangeValue {
  start: string;
  end: string;
}

export interface DatePreset {
  label: string;
  days: number;
  offset?: number;
}

export const REPORT_DATE_PRESETS: DatePreset[] = [
  { label: "Today", days: 1 },
  { label: "Yesterday", days: 2, offset: 1 },
  { label: "Last 7 days", days: 7 },
  { label: "Last 30 days", days: 30 },
  { label: "Last 90 days", days: 90 },
];

function utcDate(year: number, month: number, day: number): Date {
  return new Date(Date.UTC(year, month, day));
}

export function formatIsoDate(date: Date): string {
  return date.toISOString().split("T")[0];
}

export function resolvePresetRange(days: number, offset: number = 0, now: Date = new Date()): DateRangeValue {
  const end = utcDate(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() - offset);
  const start = utcDate(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() - days);
  return {
    start: formatIsoDate(start),
    end: formatIsoDate(end),
  };
}

export function resolveMonthRange(monthDate: Date): DateRangeValue {
  const start = utcDate(monthDate.getUTCFullYear(), monthDate.getUTCMonth(), 1);
  const end = utcDate(monthDate.getUTCFullYear(), monthDate.getUTCMonth() + 1, 0);
  return {
    start: formatIsoDate(start),
    end: formatIsoDate(end),
  };
}

export function getRecentMonths(count: number = 12, now: Date = new Date()): Date[] {
  const months: Date[] = [];
  for (let i = 0; i < count; i++) {
    months.push(new Date(now.getFullYear(), now.getMonth() - i, 1));
  }
  return months;
}

export function resolveYesterday(now: Date = new Date()): Date {
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  return yesterday;
}

export function resolveCustomEndFromStart(startDate: string, now: Date = new Date()): string {
  const start = new Date(`${startDate}T00:00:00Z`);
  let end = new Date(`${startDate}T00:00:00Z`);
  end.setUTCDate(end.getUTCDate() + 90);
  const yesterday = resolveYesterday(now);
  const yesterdayUtc = utcDate(yesterday.getUTCFullYear(), yesterday.getUTCMonth(), yesterday.getUTCDate());
  if (end > yesterdayUtc) {
    end = yesterdayUtc;
  }
  return formatIsoDate(end);
}

export function getMinSelectableDate(now: Date = new Date()): string {
  return formatIsoDate(utcDate(now.getUTCFullYear() - 1, now.getUTCMonth(), now.getUTCDate()));
}

export function getMaxSelectableDate(now: Date = new Date()): string {
  return formatIsoDate(resolveYesterday(now));
}

export function getCustomEndDateBounds(startDate: string, now: Date = new Date()): { min: string; max: string } {
  const start = new Date(`${startDate}T00:00:00Z`);
  const min = new Date(start.getTime() + 24 * 60 * 60 * 1000);
  const max = new Date(
    Math.min(
      start.getTime() + 90 * 24 * 60 * 60 * 1000,
      resolveYesterday(now).getTime(),
    ),
  );
  return {
    min: formatIsoDate(min),
    max: formatIsoDate(max),
  };
}

export function getWasteDefaultRange(now: Date = new Date()): DateRangeValue {
  const end = resolveYesterday(now);
  const start = new Date(end);
  start.setDate(start.getDate() - 7);
  return {
    start: formatIsoDate(start),
    end: formatIsoDate(end),
  };
}
