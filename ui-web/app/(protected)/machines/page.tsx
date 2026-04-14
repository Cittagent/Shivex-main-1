"use client";

import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import Link from "next/link";
import {
  DeviceLoadState,
  DashboardBootstrapData,
  getDashboardSummary,
  DashboardSummaryData,
  getFleetSnapshot,
  connectFleetStream,
  FleetStreamEventData,
  getDashboardBootstrap,
  getTodayLossBreakdown,
  TodayLossBreakdownData,
} from "@/lib/deviceApi";
import { authApi } from "@/lib/authApi";
import {
  ActivityEvent,
  getActivityEvents,
  getActivityUnreadCount,
  markAllActivityRead,
  clearActivityHistory,
} from "@/lib/dataApi";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FilterBar, PageHeader, SectionCard, StatCard } from "@/components/ui/page-scaffold";
import { ActivationTimestampField } from "@/components/devices/ActivationTimestampField";
import { formatCompactNumber, formatCurrencyValue, formatEnergyKwh } from "@/lib/presentation";
import { formatIST } from "@/lib/utils";
import { EXCLUSIVE_LOSS_BUCKET_HELP } from "@/lib/wasteSemantics";
import { useAdaptivePolling } from "@/lib/useAdaptivePolling";
import { subscribeToBackendSessionChanges } from "@/lib/api";
import { recoverStableFleetSnapshot } from "@/lib/fleetSnapshotRecovery";
import { loadMachinesInitialChannels } from "@/lib/machinesLoadContract";
import { useAuth } from "@/lib/authContext";
import { usePermissions } from "@/hooks/usePermissions";
import { ReadOnlyBanner } from "@/components/auth/ReadOnlyBanner";
import { OnboardDeviceModal } from "@/components/devices/OnboardDeviceModal";
import { DeleteDeviceDialog } from "@/components/devices/DeleteDeviceDialog";
import { resolveScopedTenantId, resolveVisiblePlants } from "@/lib/orgScope";
import { useTenantStore } from "@/lib/tenantStore";

type MachineCard = {
  id: string;
  name: string;
  type: string;
  plant_id: string | null;
  runtime_status: string;
  load_state: DeviceLoadState;
  location: string;
  first_telemetry_timestamp: string | null;
  last_seen_timestamp: string | null;
  health_score: number | null;
  version: number;
  freshness_ts: string | null;
};

function mapFleetSnapshotDevice(
  device: {
    device_id: string;
    device_name: string;
    device_type: string;
    plant_id?: string | null;
    runtime_status: string;
    load_state: DeviceLoadState;
    location: string | null;
    first_telemetry_timestamp: string | null;
    last_seen_timestamp: string | null;
    health_score: number | null;
    version?: number;
    data_freshness_ts: string | null;
  },
  fallbackFreshnessTs: string | null,
): MachineCard {
  return {
    id: device.device_id,
    name: device.device_name,
    type: device.device_type,
    plant_id: device.plant_id ?? null,
    runtime_status: device.runtime_status || "stopped",
    load_state: device.load_state || "unknown",
    location: device.location || "",
    first_telemetry_timestamp: device.first_telemetry_timestamp,
    last_seen_timestamp: device.last_seen_timestamp,
    health_score: device.health_score,
    version: Number(device.version || 0),
    freshness_ts: device.data_freshness_ts || fallbackFreshnessTs,
  };
}

function mapBootstrapToMachineCard(bootstrap: DashboardBootstrapData, current: MachineCard | undefined): MachineCard | null {
  if (!bootstrap.device) {
    return null;
  }

  const bootstrapHealth = bootstrap.health_score as { health_score?: number | null } | null;
  const bootstrapCurrentState = bootstrap.current_state as { state?: DeviceLoadState | null } | null;

  return {
    id: bootstrap.device.id,
    name: bootstrap.device.name,
    type: bootstrap.device.type,
    plant_id: current?.plant_id ?? null,
    runtime_status: bootstrap.device.runtime_status || current?.runtime_status || "stopped",
    load_state: bootstrapCurrentState?.state || current?.load_state || "unknown",
    location: bootstrap.device.location || "",
    first_telemetry_timestamp: bootstrap.device.first_telemetry_timestamp,
    last_seen_timestamp: bootstrap.device.last_seen_timestamp,
    health_score: typeof bootstrapHealth?.health_score === "number" ? bootstrapHealth.health_score : current?.health_score ?? null,
    version: Math.max(current?.version ?? 0, Number(bootstrap.version || 0)),
    freshness_ts: bootstrap.generated_at || current?.freshness_ts || null,
  };
}

const EVENT_TYPE_LABELS: Record<string, string> = {
  rule_created: "Rule Created",
  rule_updated: "Rule Updated",
  rule_deleted: "Rule Deleted",
  rule_archived: "Rule Archived",
  rule_triggered: "Rule Triggered",
  alert_acknowledged: "Alert Acknowledged",
  alert_resolved: "Alert Resolved",
  alert_cleared: "Alert Cleared",
};

export default function MachinesPage() {
  const { me } = useAuth();
  const { selectedTenantId } = useTenantStore();
  const { canAcknowledgeAlert, canCreateDevice, canDeleteDevice } = usePermissions();
  const [dashboard, setDashboard] = useState<DashboardSummaryData | null>(null);
  const [machines, setMachines] = useState<MachineCard[]>([]);
  const [plants, setPlants] = useState<Array<{ id: string; name: string }>>([]);
  const [selectedPlantId, setSelectedPlantId] = useState<string | null>(null);
  const [globalAlerts, setGlobalAlerts] = useState<ActivityEvent[]>([]);
  const [globalUnreadCount, setGlobalUnreadCount] = useState(0);
  const [showGlobalAlerts, setShowGlobalAlerts] = useState(false);
  const [showOnboard, setShowOnboard] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<{
    deviceId: string;
    deviceName: string;
  } | null>(null);
  const [showLossDrawer, setShowLossDrawer] = useState(false);
  const [lossLoading, setLossLoading] = useState(false);
  const [lossBreakdown, setLossBreakdown] = useState<TodayLossBreakdownData | null>(null);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isReconnecting, setIsReconnecting] = useState(false);
  const [streamEpoch, setStreamEpoch] = useState(0);
  const lastEventIdRef = useRef<string | undefined>(undefined);
  const costRefreshTimerRef = useRef<number | null>(null);
  const lastSummaryRefreshRef = useRef<number>(0);
  const deviceServiceSessionRef = useRef<string | null>(null);
  const reconnectInFlightRef = useRef(false);
  const reconnectBannerActiveRef = useRef(false);
  const pendingRecoverySessionRef = useRef<string | null>(null);
  const recoveredSessionRef = useRef<string | null>(null);
  const summaryRecoveryPendingRef = useRef(false);
  const refetchAfterBackendRestartRef = useRef<() => Promise<void>>(async () => {});
  const targetedRefetchesRef = useRef<Set<string>>(new Set());
  const refetchSingleDeviceRef = useRef<(deviceId: string) => Promise<void>>(async () => {});
  const role = me?.user.role ?? null;
  const currentOrgId = resolveScopedTenantId(me, selectedTenantId);
  const showPlantTabs = Boolean(currentOrgId);
  const visiblePlants = useMemo(() => resolveVisiblePlants(me, plants), [me, plants]);
  const canOnboardDevice = canCreateDevice && visiblePlants.length > 0;
  const visibleDevices = useMemo(
    () =>
      selectedPlantId
        ? machines.filter((d: any) => d.plant_id === selectedPlantId)
        : machines,
    [machines, selectedPlantId],
  );

  const isIncomingFresher = useCallback((current: MachineCard | undefined, incoming: MachineCard): boolean => {
    if (!current) return true;
    const currentVersion = Number.isFinite(current.version) ? current.version : 0;
    const incomingVersion = Number.isFinite(incoming.version) ? incoming.version : 0;
    if (incomingVersion > currentVersion) return true;
    if (incomingVersion < currentVersion) return false;
    const currentFreshness = Date.parse(current.freshness_ts || current.last_seen_timestamp || "");
    const incomingFreshness = Date.parse(incoming.freshness_ts || incoming.last_seen_timestamp || "");
    if (Number.isFinite(currentFreshness) && Number.isFinite(incomingFreshness)) {
      return incomingFreshness >= currentFreshness;
    }
    return true;
  }, []);

  const applyFleetUpdate = useCallback((snapshot: { devices?: MachineCard[]; total_pages?: number }) => {
    if (snapshot.devices) {
      setMachines((prev) => {
        const prevMap = new Map(prev.map((item) => [item.id, item]));
        const merged = snapshot.devices!.map((incoming) => {
          const current = prevMap.get(incoming.id);
          return isIncomingFresher(current, incoming) ? incoming : current!;
        });
        return merged.sort((a, b) => a.name.localeCompare(b.name));
      });
    }
    if (snapshot.total_pages) setTotalPages(snapshot.total_pages);
  }, [isIncomingFresher]);

  const applyFleetPartialUpdate = useCallback((updates: MachineCard[]) => {
    if (!updates.length) return;
    const staleDeviceIds: string[] = [];
    setMachines((prev) => {
      const map = new Map(prev.map((item) => [item.id, item]));
      for (const update of updates) {
        if (!update?.id) continue;
        const current = map.get(update.id);
        if (current && Number(update.version || 0) < Number(current.version || 0)) {
          staleDeviceIds.push(update.id);
          continue;
        }
        if (!isIncomingFresher(current, update)) continue;
        map.set(update.id, { ...(current || update), ...update });
      }
      return Array.from(map.values()).sort((a, b) => a.name.localeCompare(b.name));
    });

    staleDeviceIds.forEach((deviceId) => {
      void refetchSingleDeviceRef.current(deviceId);
    });
  }, [isIncomingFresher]);

  const fetchGlobalAlerts = useCallback(async () => {
    try {
      const [eventsResult, unreadCount] = await Promise.all([
        getActivityEvents({ page: 1, pageSize: 25 }),
        getActivityUnreadCount(),
      ]);
      setGlobalAlerts(eventsResult.data);
      setGlobalUnreadCount(unreadCount);
    } catch {
      // Keep the dashboard usable even if alert feed is temporarily unavailable.
      setGlobalAlerts([]);
      setGlobalUnreadCount(0);
    }
  }, []);

  useEffect(() => {
    if (!currentOrgId) {
      setPlants([]);
      setSelectedPlantId(null);
      return;
    }

    let active = true;
    void authApi
      .listPlants(currentOrgId)
      .then((rows) => {
        if (active) {
          setPlants(rows);
        }
      })
      .catch(() => {
        if (active) {
          setPlants([]);
        }
      });

    return () => {
      active = false;
    };
  }, [currentOrgId]);

  useEffect(() => {
    if (selectedPlantId && visiblePlants.length > 0 && !visiblePlants.some((plant) => plant.id === selectedPlantId)) {
      setSelectedPlantId(null);
    }
  }, [selectedPlantId, visiblePlants]);

  const configuredHealthCount = useMemo(
    () => machines.filter((m) => m.health_score !== null && m.health_score !== undefined).length,
    [machines]
  );
  const notConfiguredHealthCount = useMemo(
    () => machines.filter((m) => m.health_score === null || m.health_score === undefined).length,
    [machines]
  );

  const loadBadge = (state: DeviceLoadState) => {
    const cfg: Record<DeviceLoadState, { label: string; className: string }> = {
      running: { label: "In Load", className: "bg-emerald-100 text-emerald-800 border-emerald-200" },
      idle: { label: "Idle", className: "bg-amber-100 text-amber-800 border-amber-200" },
      unloaded: { label: "Unloaded", className: "bg-orange-100 text-orange-800 border-orange-200" },
      unknown: { label: "Unknown", className: "bg-slate-100 text-slate-700 border-slate-200" },
    };
    const item = cfg[state] || cfg.unknown;
    return (
      <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold ${item.className}`}>
        {item.label}
      </span>
    );
  };

  const getEffectiveLoadState = (
    runtimeStatus: string | undefined,
    rawState: DeviceLoadState | undefined
  ): DeviceLoadState => {
    if ((runtimeStatus || "").toLowerCase() !== "running") {
      return "unknown";
    }
    return rawState || "unknown";
  };

  const getHealthTone = (score: number | null) => {
    if (score === null || score === undefined) {
      return {
        label: "Not configured",
        valueClass: "text-slate-500",
        barClass: "bg-slate-300",
      };
    }
    if (score >= 75) {
      return {
        label: "Healthy",
        valueClass: "text-emerald-600",
        barClass: "bg-emerald-500",
      };
    }
    if (score >= 50) {
      return {
        label: "Moderate",
        valueClass: "text-amber-600",
        barClass: "bg-amber-500",
      };
    }
    return {
      label: "Attention",
      valueClass: "text-rose-600",
      barClass: "bg-rose-500",
    };
  };

  const formatEventType = (eventType: string) => EVENT_TYPE_LABELS[eventType] || eventType.replace(/_/g, " ");

  const handleMarkAllRead = async () => {
    try {
      await markAllActivityRead();
      await fetchGlobalAlerts();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to mark alerts as read");
    }
  };

  const handleClearHistory = async () => {
    if (!confirm("Clear all global alert history?")) return;
    try {
      await clearActivityHistory();
      await fetchGlobalAlerts();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to clear alert history");
    }
  };

  const openLossDrawer = useCallback(async () => {
    setShowLossDrawer(true);
    setLossLoading(true);
    try {
      const data = await getTodayLossBreakdown(selectedPlantId);
      setLossBreakdown(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch today loss breakdown");
    } finally {
      setLossLoading(false);
    }
  }, [selectedPlantId]);

  const formatKwh = (value: number | null | undefined) => {
    return formatEnergyKwh(value);
  };

  const formatCurrency = (value: number | null | undefined, currency = "INR") => {
    return formatCurrencyValue(value, currency);
  };

  const costDataState = dashboard?.cost_data_state ?? "unavailable";
  const isCostFresh = costDataState === "fresh";
  const isLossCostFresh = (lossBreakdown?.cost_data_state ?? "unavailable") === "fresh";

  const requestBackendRestartRecovery = useCallback((sessionId: string | null) => {
    if (sessionId) {
      pendingRecoverySessionRef.current = sessionId;
    }
    if (reconnectInFlightRef.current) {
      return;
    }
    void refetchAfterBackendRestartRef.current();
  }, []);

  const refreshDashboardSummary = useCallback(async () => {
    try {
      const summary = await getDashboardSummary(selectedPlantId);
      const nextSession = summary.service_started_at ?? null;
      const previousSession = deviceServiceSessionRef.current;
      if (nextSession) {
        deviceServiceSessionRef.current = nextSession;
      }
      setDashboard(summary);
      const sessionChanged = Boolean(
        nextSession &&
        previousSession &&
        previousSession !== nextSession,
      );
      const summaryRecovered = summaryRecoveryPendingRef.current;
      if (summaryRecovered || sessionChanged) {
        summaryRecoveryPendingRef.current = false;
        pendingRecoverySessionRef.current = nextSession ?? previousSession ?? pendingRecoverySessionRef.current;
        await refetchAfterBackendRestartRef.current();
      }
      return summary.cost_data_state === "fresh";
    } catch {
      if (machines.length > 0) {
        summaryRecoveryPendingRef.current = true;
      }
      return false;
    }
  }, [machines.length, requestBackendRestartRecovery, selectedPlantId]);

  const loadFleetCards = useCallback(async () => {
    const snapshot = await getFleetSnapshot(page, 60);
    const normalizedMachines: MachineCard[] = (snapshot.devices || []).map((device) =>
      mapFleetSnapshotDevice(device, snapshot.generated_at || null),
    );
    return {
      devices: normalizedMachines,
      total_pages: snapshot.total_pages || 1,
    };
  }, [page]);

  const fetchFleetCards = useCallback(async () => {
    const snapshot = await loadFleetCards();
    applyFleetUpdate(snapshot);
    return snapshot.devices;
  }, [applyFleetUpdate, loadFleetCards]);

  const recoverFleetCardsAfterReconnect = useCallback(async () => {
    const stableDevices = await recoverStableFleetSnapshot<MachineCard>({
      fetchSnapshot: async () => {
        const snapshot = await loadFleetCards();
        applyFleetUpdate(snapshot);
        return snapshot.devices;
      },
    });
    return stableDevices;
  }, [applyFleetUpdate, loadFleetCards]);

  const refetchSingleDevice = useCallback(async (deviceId: string) => {
    if (!deviceId || targetedRefetchesRef.current.has(deviceId)) {
      return;
    }

    targetedRefetchesRef.current.add(deviceId);
    try {
      const bootstrap = await getDashboardBootstrap(deviceId);
      setMachines((prev) =>
        prev
          .map((machine) => {
            if (machine.id !== deviceId) {
              return machine;
            }
            return mapBootstrapToMachineCard(bootstrap, machine) ?? machine;
          })
          .sort((a, b) => a.name.localeCompare(b.name)),
      );
    } catch {
      try {
        await fetchFleetCards();
      } catch {
        // Keep the existing device card if targeted refresh also fails.
      }
    } finally {
      targetedRefetchesRef.current.delete(deviceId);
    }
  }, [fetchFleetCards]);

  refetchSingleDeviceRef.current = refetchSingleDevice;

  const refetchAfterBackendRestart = useCallback(async () => {
    if (reconnectInFlightRef.current) {
      return;
    }

    const targetSession = pendingRecoverySessionRef.current ?? deviceServiceSessionRef.current;
    reconnectInFlightRef.current = true;
    setIsReconnecting(true);
    reconnectBannerActiveRef.current = true;
    setError(null);
    lastEventIdRef.current = undefined;
    setStreamEpoch((value) => value + 1);
    const reconnectBannerStartedAt = Date.now();
    const deadline = reconnectBannerStartedAt + 30_000;
    let lastFailure: Error | null = null;

    try {
      while (Date.now() < deadline) {
        try {
          await Promise.all([
            recoverFleetCardsAfterReconnect(),
            refreshDashboardSummary(),
            fetchGlobalAlerts(),
          ]);
          lastFailure = null;
          break;
        } catch (err) {
          lastFailure = err instanceof Error ? err : new Error("Failed to refresh machines after backend restart");
          await new Promise((resolve) => window.setTimeout(resolve, 1000));
        }
      }

      if (lastFailure) {
        throw lastFailure;
      }

      const recoveredSession = deviceServiceSessionRef.current ?? targetSession;
      if (recoveredSession) {
        recoveredSessionRef.current = recoveredSession;
        if (pendingRecoverySessionRef.current === recoveredSession) {
          pendingRecoverySessionRef.current = null;
        }
      }
    } catch (err) {
      reconnectBannerActiveRef.current = false;
      setIsReconnecting(false);
      if (machines.length === 0) {
        setError(err instanceof Error ? err.message : "Failed to refresh machines after backend restart");
      }
    } finally {
      reconnectInFlightRef.current = false;
      const pendingSession = pendingRecoverySessionRef.current;
      if (pendingSession && pendingSession !== recoveredSessionRef.current) {
        queueMicrotask(() => {
          void refetchAfterBackendRestartRef.current();
        });
      }
    }
  }, [fetchGlobalAlerts, machines.length, recoverFleetCardsAfterReconnect, refreshDashboardSummary]);

  refetchAfterBackendRestartRef.current = refetchAfterBackendRestart;

  const fetchDashboard = useCallback(async () => {
    setError(null);
    const { fatalError, summaryPromise } = await loadMachinesInitialChannels({
      loadFleet: fetchFleetCards,
      loadSummary: refreshDashboardSummary,
      fallbackError: "Failed to fetch machines",
    });
    try {
      if (fatalError) {
        setError(fatalError);
      }
    } finally {
      setLoading(false);
    }
    void summaryPromise;
  }, [fetchFleetCards, refreshDashboardSummary]);

  useEffect(() => {
    void fetchDashboard();
  }, [fetchDashboard]);

  useAdaptivePolling(fetchGlobalAlerts, 6000, 20000, {
    onBackendRestart: refetchAfterBackendRestart,
  });
  useAdaptivePolling(
    async () => {
      try {
        await fetchFleetCards();
      } catch {
        // Keep the current fleet cards until the next reconciliation attempt.
      }
    },
    5000,
    15000,
    {
      onBackendRestart: refetchAfterBackendRestart,
    },
  );
  useEffect(() => {
    void fetchGlobalAlerts();
  }, [fetchGlobalAlerts]);

  useEffect(() => {
    return subscribeToBackendSessionChanges((nextSession) => {
      requestBackendRestartRecovery(nextSession);
    });
  }, [requestBackendRestartRecovery]);

  useEffect(() => {
    const stopStream = connectFleetStream({
      pageSize: 200,
      lastEventId: lastEventIdRef.current,
      onOpen: () => {
        if (!reconnectBannerActiveRef.current) {
          return;
        }
        void Promise.allSettled([
          recoverFleetCardsAfterReconnect(),
          refreshDashboardSummary(),
          fetchGlobalAlerts(),
        ]).finally(() => {
          reconnectBannerActiveRef.current = false;
          setIsReconnecting(false);
        });
      },
      onError: () => {
        void refetchAfterBackendRestart();
      },
      onReconnectStart: (reason) => {
        if (reason !== "stream_error") {
          return;
        }
        reconnectBannerActiveRef.current = true;
        setIsReconnecting(true);
      },
      onEvent: (parsed) => {
      try {
        if (parsed?.id) lastEventIdRef.current = parsed.id;
        if (parsed?.event !== "fleet_update" || !Array.isArray(parsed.devices)) return;
        const normalizedMachines: MachineCard[] = parsed.devices.map((device) =>
          mapFleetSnapshotDevice(
            { ...device, version: Number(device.version || parsed.version || 0) },
            parsed.freshness_ts || parsed.generated_at || null,
          ),
        );
        if (parsed.partial) {
          applyFleetPartialUpdate(normalizedMachines);
        } else {
          applyFleetUpdate({ devices: normalizedMachines });
        }
        const now = Date.now();
        if (now - lastSummaryRefreshRef.current > 750) {
          lastSummaryRefreshRef.current = now;
          void refreshDashboardSummary();
        }
      } catch {
        // Ignore malformed stream event and keep connection alive.
      }
      },
    });

    return () => {
      stopStream();
    };
  }, [applyFleetPartialUpdate, applyFleetUpdate, fetchGlobalAlerts, recoverFleetCardsAfterReconnect, refetchAfterBackendRestart, refreshDashboardSummary, streamEpoch]);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      const fresh = await refreshDashboardSummary();
      if (cancelled) return;
      const hidden = typeof document !== "undefined" && document.hidden;
      const nextMs = fresh
        ? hidden
          ? 10000
          : 2000
        : hidden
          ? 5000
          : 1000;
      costRefreshTimerRef.current = window.setTimeout(tick, nextMs);
    };
    void tick();
    return () => {
      cancelled = true;
      if (costRefreshTimerRef.current !== null) {
        window.clearTimeout(costRefreshTimerRef.current);
      }
    };
  }, [refreshDashboardSummary]);

  if (loading) {
    return (
      <div className="py-5">
        <div className="flex items-center justify-center h-64">
          <div className="text-center">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
            <p className="mt-4 text-slate-600">Loading machines...</p>
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="py-5">
        <div className="surface-panel border-[var(--tone-danger-border)] bg-[var(--tone-danger-bg)] p-6">
          <h2 className="text-red-800 font-semibold mb-2">Error loading machines</h2>
          <p className="text-red-600">{error}</p>
          <Button
            variant="outline"
            className="mt-4"
            onClick={() => void fetchDashboard()}
          >
            Retry
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="section-spacing">
      <ReadOnlyBanner />
      {isReconnecting && (
        <div
          data-testid="machines-reconnecting-banner"
          className="mb-4 rounded-2xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-800 shadow-sm"
        >
          Reconnecting...
        </div>
      )}
      <PageHeader
        title="Machines"
        subtitle="Operational dashboard across all devices"
        actions={
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setShowGlobalAlerts((prev) => !prev)}
              className="relative inline-flex h-10 w-10 items-center justify-center rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-0)] hover:bg-[var(--surface-1)]"
              title="Global alert history"
            >
              <svg className="h-5 w-5 text-[var(--text-secondary)]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M15 17h5l-1.4-1.4A2 2 0 0 1 18 14.2V11a6 6 0 1 0-12 0v3.2a2 2 0 0 1-.6 1.4L4 17h5" />
                <path d="M10 17a2 2 0 0 0 4 0" />
              </svg>
              {globalUnreadCount > 0 && (
                <span className="absolute -top-1 -right-1 min-w-5 h-5 px-1 rounded-full bg-red-600 text-white text-[10px] leading-5 text-center">
                  {globalUnreadCount > 99 ? "99+" : globalUnreadCount}
                </span>
              )}
            </button>
            <div className="text-sm text-[var(--text-secondary)]">
              {dashboard?.summary.total_devices ?? machines.length} device
              {(dashboard?.summary.total_devices ?? machines.length) !== 1 ? "s" : ""}
            </div>
            {canOnboardDevice && (
              <Button type="button" onClick={() => setShowOnboard(true)}>
                + Add Device
              </Button>
            )}
          </div>
        }
      />

      <div className="relative">
          {showGlobalAlerts && (
            <div className="surface-panel absolute right-0 top-1 z-40 max-h-[520px] w-full max-w-[460px] overflow-hidden shadow-[var(--shadow-raised)]">
              <div className="flex items-center justify-between border-b border-[var(--border-subtle)] px-4 py-3">
                <div>
                  <p className="text-sm font-semibold text-slate-900">Global Alerts</p>
                  <p className="text-xs text-slate-500">All devices</p>
                </div>
                <button
                  type="button"
                  onClick={() => setShowGlobalAlerts(false)}
                  className="text-slate-400 hover:text-slate-700"
                >
                  ✕
                </button>
              </div>
              <div className="max-h-[380px] space-y-3 overflow-y-auto p-3">
                {globalAlerts.length === 0 ? (
                  <div className="text-center text-sm text-slate-500 py-8">No alert history</div>
                ) : (
                  globalAlerts.map((event) => (
                    <div
                      key={event.eventId}
                      className={`rounded-lg border p-3 ${
                        event.isRead ? "bg-slate-50 border-slate-200" : "bg-red-50 border-red-200"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-sm font-semibold text-slate-900">{event.title}</p>
                        <span className="text-[11px] px-2 py-0.5 rounded bg-slate-100 text-slate-700">
                          {formatEventType(event.eventType)}
                        </span>
                      </div>
                      <p className="text-xs text-slate-600 mt-1">{event.message}</p>
                      <div className="mt-2 text-[11px] text-slate-500 flex items-center justify-between">
                        <span>{event.deviceId || "all-devices"}</span>
                        <span>{formatIST(event.createdAt, "No timestamp")}</span>
                      </div>
                    </div>
                  ))
                )}
              </div>
              {canAcknowledgeAlert ? (
                <div className="flex items-center justify-between gap-2 border-t border-[var(--border-subtle)] px-4 py-3">
                  <Button variant="outline" size="sm" onClick={handleMarkAllRead}>
                    Mark all read
                  </Button>
                  <Button variant="danger" size="sm" onClick={handleClearHistory}>
                    Clear history
                  </Button>
                </div>
              ) : null}
            </div>
          )}
      </div>

      <div className="kpi-grid">
        <StatCard
          label="Month Energy Consumption"
          value={formatKwh(dashboard?.energy_widgets?.month_energy_kwh)}
          meta={
            isCostFresh
              ? formatCurrency(dashboard?.energy_widgets?.month_energy_cost_inr, dashboard?.energy_widgets?.currency)
              : "Cost updating…"
          }
          tone="info"
        />
        <StatCard
          label="Today's Energy Consumption"
          value={formatKwh(dashboard?.energy_widgets?.today_energy_kwh)}
          meta={
            isCostFresh
              ? formatCurrency(dashboard?.energy_widgets?.today_energy_cost_inr, dashboard?.energy_widgets?.currency)
              : "Cost updating…"
          }
          tone="success"
        />
        <button
            type="button"
            onClick={openLossDrawer}
          className="surface-panel border-[var(--tone-danger-border)] bg-[var(--tone-danger-bg)] p-5 text-left transition-colors hover:bg-[#ffe4e6]"
          >
            <p className="text-xs uppercase tracking-[0.14em] text-rose-700 font-semibold">Today&apos;s Total Loss</p>
            <p className="text-2xl font-bold text-rose-700 mt-2">{formatKwh(dashboard?.energy_widgets?.today_loss_kwh)}</p>
            <p className="text-sm text-rose-700 mt-1">
              {isCostFresh
                ? formatCurrency(dashboard?.energy_widgets?.today_loss_cost_inr, dashboard?.energy_widgets?.currency)
                : "Cost updating…"}
            </p>
            <p className="text-xs text-rose-700 mt-2">Click for breakdown</p>
        </button>
      </div>
      {!isCostFresh && (
        <p className="text-xs text-[var(--text-secondary)]">
          INR totals are updating.
          {dashboard?.cost_generated_at ? ` Last cost snapshot: ${formatIST(dashboard.cost_generated_at, "—")}.` : ""}
        </p>
      )}

      <div className="kpi-grid">
        <StatCard
          label="Total Devices"
          value={formatCompactNumber(dashboard?.summary.total_devices ?? machines.length)}
          meta="Fleet inventory"
          tone="info"
        />
        <StatCard
          label="Active Alerts"
          value={formatCompactNumber(dashboard?.alerts.active_alerts ?? 0)}
          meta="Requires operator attention"
          tone="danger"
        />
        <StatCard
          label="System Health"
          value={
            dashboard?.summary.system_health !== null && dashboard?.summary.system_health !== undefined
              ? `${dashboard.summary.system_health.toFixed(1)}%`
              : "—"
          }
          meta={`Configured: ${configuredHealthCount}/${machines.length} • Not configured: ${notConfiguredHealthCount}`}
          tone="success"
        />
      </div>

      {showPlantTabs ? (
        <div className="surface-panel mb-4 flex flex-wrap items-center gap-2 px-3 py-2 sm:px-4">
          <button
            type="button"
            onClick={() => setSelectedPlantId(null)}
            className={`rounded-xl border px-3 py-2 text-sm font-medium transition-colors ${
              selectedPlantId === null
                ? "border-[var(--tone-info-border)] bg-[var(--tone-info-bg)] text-[var(--tone-info-text)]"
                : "border-[var(--border-subtle)] bg-[var(--surface-0)] text-[var(--text-secondary)] hover:bg-[var(--surface-1)] hover:text-[var(--text-primary)]"
            }`}
          >
            All Plants
          </button>
          {visiblePlants.map((plant) => (
            <button
              key={plant.id}
              type="button"
              onClick={() => setSelectedPlantId(plant.id)}
              className={`rounded-xl border px-3 py-2 text-sm font-medium transition-colors ${
                selectedPlantId === plant.id
                  ? "border-[var(--tone-info-border)] bg-[var(--tone-info-bg)] text-[var(--tone-info-text)]"
                  : "border-[var(--border-subtle)] bg-[var(--surface-0)] text-[var(--text-secondary)] hover:bg-[var(--surface-1)] hover:text-[var(--text-primary)]"
              }`}
            >
              {plant.name}
            </button>
          ))}
        </div>
      ) : null}

        {visibleDevices.length === 0 ? (
          <div className="surface-panel p-12 text-center">
            <div className="w-16 h-16 bg-slate-100 rounded-full flex items-center justify-center mx-auto mb-4">
              <svg
                className="w-8 h-8 text-slate-400"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z"
                />
              </svg>
            </div>
            <h3 className="text-lg font-medium text-slate-900 mb-2">No machines found</h3>
            <p className="text-slate-500 mb-4">
              Get started by adding your first machine to the platform.
            </p>
          </div>
        ) : (
          <SectionCard title="Fleet Overview" subtitle="Click a machine for detailed diagnostics">
            <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 xl:grid-cols-3">
              {visibleDevices.map((machine) => (
                <Link key={machine.id} href={`/machines/${machine.id}`}>
                  <Card
                    data-device-id={machine.id}
                    data-device-version={machine.version}
                    className="h-full cursor-pointer transition-shadow hover:shadow-lg"
                  >
                    <CardHeader className="pb-3">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 flex-1">
                          <h2 className="truncate text-lg font-semibold text-slate-900" title={machine.name}>{machine.name}</h2>
                          <p
                            className="mt-0.5 truncate font-mono text-xs text-slate-500 sm:text-sm"
                            title={machine.id}
                          >
                            {machine.id}
                          </p>
                          <div className="mt-2">{loadBadge(getEffectiveLoadState(machine.runtime_status, machine.load_state))}</div>
                        </div>
                        <div className="flex shrink-0 items-start gap-2">
                          <StatusBadge status={machine.runtime_status} />
                          {canDeleteDevice && (
                            <button
                              type="button"
                              onClick={(e) => {
                                e.preventDefault();
                                e.stopPropagation();
                                setDeleteTarget({
                                  deviceId: machine.id,
                                  deviceName: machine.name,
                                });
                              }}
                              className="rounded border border-red-200 px-2 py-1 text-xs text-red-500 transition-colors hover:border-red-400 hover:text-red-700"
                              title="Delete device"
                            >
                              Delete
                            </button>
                          )}
                        </div>
                      </div>
                    </CardHeader>
                    <CardContent className="pt-0">
                      <div className="space-y-3">
                        <div className="flex items-center justify-between text-sm">
                          <span className="text-slate-500">Type</span>
                          <span className="capitalize text-slate-900">{machine.type}</span>
                        </div>
                        <div className="flex items-center justify-between text-sm">
                          <span className="text-slate-500">Location</span>
                          <span className="text-slate-900">{machine.location || "—"}</span>
                        </div>
                        <ActivationTimestampField
                          label="Activated"
                          timestamp={machine.first_telemetry_timestamp}
                          emptyText="Not activated yet"
                          className="flex items-center justify-between text-sm"
                          labelClassName="text-slate-500"
                          valueClassName="text-xs text-slate-900"
                        />
                        <div className="flex items-center justify-between text-sm">
                          <span className="text-slate-500">Last Seen</span>
                          <span className="text-xs text-slate-900">
                            {machine.last_seen_timestamp ? formatIST(machine.last_seen_timestamp) : "No data received"}
                          </span>
                        </div>
                        <div className="pt-2">
                          <div className="flex items-center justify-between text-sm">
                            <span className="text-slate-500">Health Score</span>
                            {machine.health_score !== null && machine.health_score !== undefined ? (
                              <span className={`font-semibold ${getHealthTone(machine.health_score).valueClass}`}>
                                {machine.health_score.toFixed(1)}%
                              </span>
                            ) : (
                              <span className="font-medium text-slate-500">Not configured</span>
                            )}
                          </div>
                          <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-200">
                            <div
                              className={`h-full ${getHealthTone(machine.health_score).barClass}`}
                              style={{
                                width:
                                  machine.health_score !== null && machine.health_score !== undefined
                                    ? `${Math.max(0, Math.min(100, machine.health_score))}%`
                                    : "0%",
                              }}
                            />
                          </div>
                        </div>
                      </div>
                      <div className="mt-4 flex items-center gap-1 border-t border-slate-100 pt-4 text-sm font-medium text-blue-600">
                        View Dashboard
                        <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                        </svg>
                      </div>
                    </CardContent>
                  </Card>
                </Link>
              ))}
            </div>
          </SectionCard>
        )}

      <FilterBar>
        <div className="text-sm text-[var(--text-secondary)]">
          Page {page} of {totalPages}
        </div>
        <div className="ml-auto flex items-center gap-2">
          <Button variant="outline" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
            Previous
          </Button>
          <Button variant="outline" disabled={page >= totalPages} onClick={() => setPage((p) => Math.min(totalPages, p + 1))}>
            Next
          </Button>
        </div>
      </FilterBar>

      {showLossDrawer && (
        <div className="fixed inset-0 z-50 bg-slate-900/40">
          <div className="absolute right-0 top-0 flex h-full w-full max-w-2xl flex-col border-l border-[var(--border-subtle)] bg-[var(--surface-0)] shadow-2xl">
            <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between">
              <div>
                <h2 className="text-lg font-semibold text-slate-900">Today&apos;s Total Loss Breakdown</h2>
                <p className="text-sm text-slate-500">Idle + Off-Hours + Overconsumption</p>
                <p className="text-xs text-slate-500 mt-1">{EXCLUSIVE_LOSS_BUCKET_HELP}</p>
              </div>
              <button
                type="button"
                onClick={() => setShowLossDrawer(false)}
                className="text-slate-500 hover:text-slate-800"
              >
                ✕
              </button>
            </div>
            <div className="p-6 overflow-y-auto space-y-4">
              {lossLoading ? (
                <div className="text-sm text-slate-500">Loading loss breakdown...</div>
              ) : (
                <>
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                    <div className="rounded-lg border border-slate-200 p-3">
                      <p className="text-xs text-slate-500">Idle Running</p>
                      <p className="text-base font-semibold text-slate-900">{formatKwh(lossBreakdown?.totals.idle_kwh)}</p>
                      <p className="text-xs text-slate-500">
                        {isLossCostFresh ? formatCurrency(lossBreakdown?.totals.idle_cost_inr, lossBreakdown?.currency) : "Cost updating…"}
                      </p>
                    </div>
                    <div className="rounded-lg border border-slate-200 p-3">
                      <p className="text-xs text-slate-500">Off-Hours Running</p>
                      <p className="text-base font-semibold text-slate-900">{formatKwh(lossBreakdown?.totals.off_hours_kwh)}</p>
                      <p className="text-xs text-slate-500">
                        {isLossCostFresh ? formatCurrency(lossBreakdown?.totals.off_hours_cost_inr, lossBreakdown?.currency) : "Cost updating…"}
                      </p>
                    </div>
                    <div className="rounded-lg border border-slate-200 p-3">
                      <p className="text-xs text-slate-500">Overconsumption</p>
                      <p className="text-base font-semibold text-slate-900">{formatKwh(lossBreakdown?.totals.overconsumption_kwh)}</p>
                      <p className="text-xs text-slate-500">
                        {isLossCostFresh ? formatCurrency(lossBreakdown?.totals.overconsumption_cost_inr, lossBreakdown?.currency) : "Cost updating…"}
                      </p>
                    </div>
                  </div>

                  <div className="rounded-lg border border-slate-200 overflow-hidden">
                    <table className="min-w-full divide-y divide-slate-200">
                      <thead className="bg-slate-50">
                        <tr>
                          <th className="px-4 py-2 text-left text-xs font-semibold text-slate-600">Device</th>
                          <th className="px-4 py-2 text-left text-xs font-semibold text-slate-600">Idle</th>
                          <th className="px-4 py-2 text-left text-xs font-semibold text-slate-600">Off-Hours</th>
                          <th className="px-4 py-2 text-left text-xs font-semibold text-slate-600">Overconsumption</th>
                          <th className="px-4 py-2 text-left text-xs font-semibold text-slate-600">Total Loss</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {(lossBreakdown?.rows ?? []).map((row) => (
                          <tr key={row.device_id}>
                            <td className="px-4 py-2 text-sm text-slate-900">
                              <div className="font-medium">{row.device_name}</div>
                              <div className="text-xs text-slate-500">{row.device_id}</div>
                              {row.reason && <div className="text-xs text-amber-600 mt-1">{row.reason}</div>}
                            </td>
                            <td className="px-4 py-2 text-sm text-slate-700">
                              {isLossCostFresh ? formatCurrency(row.idle_cost_inr, lossBreakdown?.currency) : "Cost updating…"}
                            </td>
                            <td className="px-4 py-2 text-sm text-slate-700">
                              {isLossCostFresh ? formatCurrency(row.off_hours_cost_inr, lossBreakdown?.currency) : "Cost updating…"}
                            </td>
                            <td className="px-4 py-2 text-sm text-slate-700">
                              {isLossCostFresh ? formatCurrency(row.overconsumption_cost_inr, lossBreakdown?.currency) : "Cost updating…"}
                            </td>
                            <td className="px-4 py-2 text-sm font-semibold text-rose-700">
                              {isLossCostFresh ? formatCurrency(row.total_loss_cost_inr, lossBreakdown?.currency) : "Cost updating…"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}

      <OnboardDeviceModal
        isOpen={showOnboard}
        onClose={() => setShowOnboard(false)}
        onSuccess={() => {
          void fetchDashboard();
        }}
      />

      <DeleteDeviceDialog
        isOpen={deleteTarget !== null}
        deviceId={deleteTarget?.deviceId ?? ""}
        deviceName={deleteTarget?.deviceName ?? ""}
        onClose={() => setDeleteTarget(null)}
        onSuccess={(deletedId) => {
          setDeleteTarget(null);
          setMachines((prev) => prev.filter((device) => device.id !== deletedId));
          void fetchDashboard();
        }}
      />
    </div>
  );
}
