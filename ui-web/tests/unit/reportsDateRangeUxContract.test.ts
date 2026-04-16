import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const wastePagePath = path.resolve(__dirname, "../../app/(protected)/waste-analysis/page.tsx");
const energyPagePath = path.resolve(__dirname, "../../app/(protected)/reports/energy/page.tsx");

const wastePageSource = readFileSync(wastePagePath, "utf-8");
const energyPageSource = readFileSync(energyPagePath, "utf-8");

test("waste analysis uses shared report DateRangeSelector", () => {
  assert.equal(wastePageSource.includes('import { DateRangeSelector } from "@/components/reports/DateRangeSelector";'), true);
  assert.equal(wastePageSource.includes("<DateRangeSelector"), true);
});

test("energy report keeps using shared report DateRangeSelector", () => {
  assert.equal(energyPageSource.includes('import { DateRangeSelector } from "@/components/reports/DateRangeSelector";'), true);
  assert.equal(energyPageSource.includes("<DateRangeSelector"), true);
});

test("waste analysis no longer renders separate Start Date and End Date inputs", () => {
  assert.equal(wastePageSource.includes(">Start Date<"), false);
  assert.equal(wastePageSource.includes(">End Date<"), false);
  assert.equal(wastePageSource.includes("<input type=\"date\" value={startDate}"), false);
  assert.equal(wastePageSource.includes("<input type=\"date\" value={endDate}"), false);
});
