"use client";

import { useEffect, useMemo, useState } from "react";
import { useAuth } from "@/lib/authContext";
import { authApi, type FeatureEntitlements } from "@/lib/authApi";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { FEATURE_LABELS, type FeatureKey } from "@/lib/features";

const PREMIUM_MODULES: FeatureKey[] = ["analytics", "reports", "waste_analysis", "copilot"];
const PLANT_MANAGER_PREMIUM_MODULES: FeatureKey[] = ["analytics", "reports", "waste_analysis"];

type EditorMode = "org_grants" | "plant_manager";

interface OrgFeatureAccessEditorProps {
  tenantId: string;
  mode: EditorMode;
}

function toSet(values: string[] | undefined | null): Set<FeatureKey> {
  return new Set((values ?? []).filter((value): value is FeatureKey => PREMIUM_MODULES.includes(value as FeatureKey) || PLANT_MANAGER_PREMIUM_MODULES.includes(value as FeatureKey)));
}

export function OrgFeatureAccessEditor({ tenantId, mode }: OrgFeatureAccessEditorProps) {
  const { refetchMe } = useAuth();
  const [entitlements, setEntitlements] = useState<FeatureEntitlements | null>(null);
  const [selected, setSelected] = useState<Set<FeatureKey>>(new Set());
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    if (!toast) return undefined;
    const timer = window.setTimeout(() => setToast(null), 2500);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    let active = true;
    async function load(): Promise<void> {
      setLoading(true);
      setError(null);
      try {
        const current = await authApi.getTenantEntitlements(tenantId);
        if (!active) return;
        setEntitlements(current);
        const initial =
          mode === "org_grants"
            ? toSet(current.premium_feature_grants)
            : toSet((current.role_feature_matrix.plant_manager ?? []).filter((feature) => current.premium_feature_grants.includes(feature)));
        setSelected(initial);
      } catch (err) {
        if (active) {
          setError(err instanceof Error ? err.message : "Failed to load feature entitlements");
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void load();
    return () => {
      active = false;
    };
  }, [mode, tenantId]);

  const visibleModules = useMemo(
    () => (mode === "org_grants" ? PREMIUM_MODULES : PLANT_MANAGER_PREMIUM_MODULES),
    [mode],
  );

  const lockedModules = useMemo(() => {
    if (mode !== "plant_manager") {
      return new Set<FeatureKey>();
    }
    const grants = new Set(entitlements?.premium_feature_grants ?? []);
    return new Set(PLANT_MANAGER_PREMIUM_MODULES.filter((feature) => !grants.has(feature)));
  }, [entitlements?.premium_feature_grants, mode]);

  async function handleSave(): Promise<void> {
    setSaving(true);
    setError(null);
    try {
      const payload =
        mode === "org_grants"
          ? { premium_feature_grants: Array.from(selected) }
          : { role_feature_matrix: { plant_manager: Array.from(selected), operator: [], viewer: [] } };

      const updated = await authApi.updateTenantEntitlements(tenantId, payload);
      setEntitlements(updated);
      setToast("Feature access updated");
      await refetchMe();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save feature access");
    } finally {
      setSaving(false);
    }
  }

  function toggle(feature: FeatureKey): void {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(feature)) {
        next.delete(feature);
      } else {
        next.add(feature);
      }
      return next;
    });
  }

  const title = mode === "org_grants" ? "Premium modules" : "Plant manager access";
  const subtitle =
    mode === "org_grants"
      ? "These modules are enabled for the organisation and exposed to org admin."
      : "These premium modules can be delegated to plant managers only when the organisation has them enabled.";

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{title}</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-[var(--text-secondary)]">Loading feature entitlements...</CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <p className="text-sm text-[var(--text-secondary)]">{subtitle}</p>
      </CardHeader>
      <CardContent className="space-y-4">
        {toast ? (
          <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
            {toast}
          </div>
        ) : null}
        {error ? (
          <div className="rounded-2xl border border-[var(--tone-danger-border)] bg-[var(--tone-danger-bg)] px-4 py-3 text-sm text-[var(--tone-danger-text)]">
            {error}
          </div>
        ) : null}

        {mode === "org_grants" ? (
          <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--surface-1)] p-4 text-sm text-[var(--text-secondary)]">
            Core access is always on for org admin: Machines, Calendar, Rules, and Settings.
          </div>
        ) : (
          <div className="space-y-2 rounded-2xl border border-[var(--border-subtle)] bg-[var(--surface-1)] p-4 text-sm text-[var(--text-secondary)]">
            <div>Fixed baseline for plant manager: Machines, Rules, Settings.</div>
            <div>Operator baseline: Machines, Rules.</div>
            <div>Viewer baseline: Machines.</div>
          </div>
        )}

        <div className="grid gap-3 md:grid-cols-2">
          {visibleModules.map((feature) => {
            const checked = selected.has(feature);
            const disabled = mode === "plant_manager" && lockedModules.has(feature);
            return (
              <label
                key={feature}
                className={`flex items-start justify-between rounded-2xl border px-4 py-4 ${
                  disabled
                    ? "border-[var(--border-subtle)] bg-[var(--surface-2)] opacity-75"
                    : "border-[var(--border-subtle)] bg-[var(--surface-0)]"
                }`}
              >
                <div className="pr-3">
                  <div className="font-medium text-[var(--text-primary)]">{FEATURE_LABELS[feature]}</div>
                  <div className="mt-1 text-xs text-[var(--text-tertiary)]">
                    {disabled ? "Disabled until super admin enables this module for the organisation." : "Available to assign."}
                  </div>
                </div>
                <div className="flex flex-col items-end gap-2">
                  <input
                    type="checkbox"
                    checked={checked}
                    disabled={disabled || saving}
                    onChange={() => toggle(feature)}
                    className="h-4 w-4 rounded border-[var(--border-subtle)] text-[var(--tone-info-solid)]"
                  />
                  {disabled ? <Badge variant="default">Locked</Badge> : null}
                </div>
              </label>
            );
          })}
        </div>

        <div className="flex items-center justify-end gap-2">
          <Button
            variant="outline"
            disabled={saving}
            onClick={() =>
              setSelected(
                mode === "org_grants"
                  ? toSet(entitlements?.premium_feature_grants)
                  : toSet(
                      (entitlements?.role_feature_matrix.plant_manager ?? []).filter((feature) =>
                        (entitlements?.premium_feature_grants ?? []).includes(feature),
                      ),
                    )
              )
            }
          >
            Reset
          </Button>
          <Button onClick={() => void handleSave()} isLoading={saving} disabled={saving}>
            Save changes
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
