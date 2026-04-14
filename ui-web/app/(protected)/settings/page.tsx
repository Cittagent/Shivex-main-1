"use client";

import { FormEvent, useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-scaffold";
import {
  CurrencyCode,
  getTariffConfig,
  saveTariffConfig,
} from "@/lib/settingsApi";
import { formatIST } from "@/lib/utils";

function formatTariff(rate: number | null, currency: CurrencyCode) {
  if (rate == null) return "Not configured";
  const symbol = currency === "INR" ? "₹" : currency === "USD" ? "$" : "€";
  return `${symbol}${rate.toFixed(2)} / kWh`;
}

function formatDate(value: string | null) {
  return formatIST(value, "Never");
}

export default function SettingsPage() {
  const [loading, setLoading] = useState(true);
  const [savingTariff, setSavingTariff] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [rateInput, setRateInput] = useState<string>("");
  const [currency, setCurrency] = useState<CurrencyCode>("INR");
  const [currentTariff, setCurrentTariff] = useState<{
    rate: number | null;
    currency: CurrencyCode;
    updated_at: string | null;
  }>({
    rate: null,
    currency: "INR",
    updated_at: null,
  });

  async function loadTariff() {
    setLoading(true);
    setError(null);
    try {
      const tariff = await getTariffConfig();
      setCurrentTariff({
        rate: tariff.rate,
        currency: tariff.currency,
        updated_at: tariff.updated_at,
      });
      setCurrency(tariff.currency || "INR");
      setRateInput(tariff.rate == null ? "" : String(tariff.rate));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load settings");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadTariff();
  }, []);

  async function handleApplyTariff(e: FormEvent) {
    e.preventDefault();
    const parsed = Number(rateInput);
    if (!Number.isFinite(parsed) || parsed <= 0) {
      setError("Rate must be a valid positive number");
      return;
    }
    setSavingTariff(true);
    setError(null);
    try {
      const saved = await saveTariffConfig({ rate: parsed, currency, updated_by: "settings-ui" });
      setCurrentTariff(saved);
      setToast("Tariff updated");
      setTimeout(() => setToast(null), 2000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update tariff");
    } finally {
      setSavingTariff(false);
    }
  }

  if (loading) {
    return (
      <div className="py-5">
        <div className="flex items-center justify-center h-64">
          <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-600"></div>
        </div>
      </div>
    );
  }

  return (
    <div className="section-spacing">
      <PageHeader title="Settings" subtitle="Configure platform tariff" />
      <div className="mx-auto w-full max-w-4xl space-y-6">
        {toast && (
          <div className="rounded-xl border border-[var(--tone-success-border)] bg-[var(--tone-success-bg)] px-3 py-2 text-sm text-[var(--tone-success-text)]">
            {toast}
          </div>
        )}
        {error && (
          <div className="rounded-xl border border-[var(--tone-danger-border)] bg-[var(--tone-danger-bg)] px-3 py-2 text-sm text-[var(--tone-danger-text)]">
            {error}
          </div>
        )}

        <Card>
          <CardHeader>
            <CardTitle>Tariff Configuration</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <form className="grid grid-cols-1 gap-3 md:grid-cols-3" onSubmit={handleApplyTariff}>
              <Input
                label="Energy Rate (per kWh)"
                type="number"
                min="0"
                step="0.01"
                value={rateInput}
                onChange={(e) => setRateInput(e.target.value)}
                placeholder="8.50"
              />
              <Select
                label="Currency"
                value={currency}
                onChange={(e) => setCurrency(e.target.value as CurrencyCode)}
                options={[
                  { value: "INR", label: "INR" },
                  { value: "USD", label: "USD" },
                  { value: "EUR", label: "EUR" },
                ]}
              />
              <div className="pt-6">
                <Button type="submit" disabled={savingTariff}>
                  {savingTariff ? "Applying..." : "Apply"}
                </Button>
              </div>
            </form>

            <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
              Current tariff: {formatTariff(currentTariff.rate, currentTariff.currency)}
              <br />
              Updated: {formatDate(currentTariff.updated_at)}
            </div>

            <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
              Alert recipients are now managed directly on each rule. Settings retains only the organisation tariff.
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
