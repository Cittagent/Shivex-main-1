"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { getReportHistory, ReportHistoryItem, getSchedules, deleteSchedule, createSchedule, ScheduleListItem, ScheduleParams, getReportDownload } from "@/lib/reportApi";
import { authApi, type PlantProfile } from "@/lib/authApi";
import { getDevices, Device } from "@/lib/deviceApi";
import { formatIST } from "@/lib/utils";
import { PageHeader } from "@/components/ui/page-scaffold";
import { DeviceScopeSelector } from "@/components/reports/DeviceScopeSelector";
import { usePermissions } from "@/hooks/usePermissions";
import { ReadOnlyBanner } from "@/components/auth/ReadOnlyBanner";
import { useAuth } from "@/lib/authContext";
import { useTenantStore } from "@/lib/tenantStore";
import { resolveScopedTenantId, resolveVisiblePlants } from "@/lib/orgScope";
import {
  getEmptyReportHistoryMessage,
  getEmptyScheduleMessage,
  getReportPageSubtitle,
  getReportScopeLabel,
  getReportScopeHint,
  isPlantScopedReportRole,
} from "@/lib/reportScope";
import {
  buildDeviceScopeCatalog,
  getDeviceScopeSummary,
  normalizeDeviceScopeSelection,
  resolveDeviceIdsForSelection,
  type DeviceScopeSelection,
} from "@/lib/deviceScopeSelection";
import { buildReportScheduleParams } from "@/lib/reportScheduleScope";

type TabType = "history" | "schedules";

export default function ReportsPage() {
  const { canGenerateReport } = usePermissions();
  const { me } = useAuth();
  const { selectedTenantId } = useTenantStore();
  const [activeTab, setActiveTab] = useState<TabType>("history");
  const [history, setHistory] = useState<ReportHistoryItem[]>([]);
  const [schedules, setSchedules] = useState<ScheduleListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [devices, setDevices] = useState<Device[]>([]);
  const [plants, setPlants] = useState<PlantProfile[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null);
  const isPlantScopedRole = isPlantScopedReportRole(me?.user.role);
  const reportScopeHint = getReportScopeHint(me?.user.role);
  const scopedOrgId = resolveScopedTenantId(me, selectedTenantId);
  const visiblePlants = useMemo(() => resolveVisiblePlants(me, plants), [me, plants]);
  const scopeCatalog = useMemo(
    () => buildDeviceScopeCatalog(devices, visiblePlants),
    [devices, visiblePlants],
  );
  const [scopeSelection, setScopeSelection] = useState<DeviceScopeSelection>({
    mode: "all",
    plantId: null,
    deviceIds: [],
  });
  const normalizedScopeSelection = useMemo(
    () => normalizeDeviceScopeSelection(scopeSelection, scopeCatalog),
    [scopeCatalog, scopeSelection],
  );
  const selectedDeviceIds = useMemo(
    () => resolveDeviceIdsForSelection(normalizedScopeSelection, scopeCatalog),
    [normalizedScopeSelection, scopeCatalog],
  );
  const selectedScopeSummary = useMemo(
    () => getDeviceScopeSummary(normalizedScopeSelection, scopeCatalog),
    [normalizedScopeSelection, scopeCatalog],
  );

  const [formData, setFormData] = useState<{
    report_type: "consumption" | "comparison";
    frequency: "daily" | "weekly" | "monthly";
    group_by: "daily" | "weekly";
  }>({
    report_type: "consumption",
    frequency: "daily",
    group_by: "daily",
  });

  useEffect(() => {
    if (!selectedTenantId) {
      setHistory([]);
      setSchedules([]);
      setDevices([]);
      setPlants([]);
      setLoading(false);
      return;
    }

    async function fetchData() {
      const tenantId = selectedTenantId;
      if (!tenantId) {
        return;
      }
      try {
        const [historyData, schedulesData, devicesData] = await Promise.all([
          getReportHistory(tenantId, { limit: 10 }),
          getSchedules(tenantId),
          getDevices(),
        ]);
        setHistory(historyData.reports);
        setSchedules(schedulesData.schedules);
        setDevices(devicesData);
        if (scopedOrgId) {
          setPlants(await authApi.listPlants(scopedOrgId));
        } else {
          setPlants([]);
        }
      } catch {
        setToast({ message: "Failed to load reports data", type: "error" });
        setTimeout(() => setToast(null), 3000);
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, [scopedOrgId, selectedTenantId]);

  useEffect(() => {
    const selectionChanged =
      normalizedScopeSelection.mode !== scopeSelection.mode ||
      normalizedScopeSelection.plantId !== scopeSelection.plantId ||
      normalizedScopeSelection.deviceIds.length !== scopeSelection.deviceIds.length ||
      normalizedScopeSelection.deviceIds.some((deviceId, index) => deviceId !== scopeSelection.deviceIds[index]);
    if (selectionChanged) {
      setScopeSelection(normalizedScopeSelection);
    }
  }, [normalizedScopeSelection, scopeSelection]);

  const showToast = (message: string, type: "success" | "error") => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
  };

  const handleCreateSchedule = async () => {
    if (selectedDeviceIds.length === 0) {
      showToast("Please select a scope with at least one accessible device", "error");
      return;
    }

    setSubmitting(true);
    try {
      const params: ScheduleParams = buildReportScheduleParams(formData, normalizedScopeSelection, scopeCatalog);
      if (!selectedTenantId) {
        throw new Error("Select an organisation before creating a schedule");
      }
      await createSchedule(selectedTenantId, params);
      const schedulesData = await getSchedules(selectedTenantId);
      setSchedules(schedulesData.schedules);
      setShowModal(false);
      setFormData({
        report_type: "consumption",
        frequency: "daily",
        group_by: "daily",
      });
      setScopeSelection({
        mode: "all",
        plantId: null,
        deviceIds: [],
      });
      showToast("Schedule created successfully", "success");
    } catch (error) {
      console.error("Failed to create schedule:", error);
      showToast(error instanceof Error ? error.message : "Failed to create schedule", "error");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDeleteSchedule = async (scheduleId: string) => {
    if (!confirm("Are you sure you want to deactivate this schedule?")) return;
    
    try {
      if (!selectedTenantId) {
        throw new Error("Select an organisation before managing schedules");
      }
      await deleteSchedule(scheduleId, selectedTenantId);
      const schedulesData = await getSchedules(selectedTenantId);
      setSchedules(schedulesData.schedules);
      showToast("Schedule deactivated", "success");
    } catch (error) {
      console.error("Failed to delete schedule:", error);
      showToast(error instanceof Error ? error.message : "Failed to deactivate schedule", "error");
    }
  };

  const handleDownload = async (reportId: string) => {
    try {
      setDownloadingId(reportId);
      if (!selectedTenantId) {
        throw new Error("Select an organisation before downloading reports");
      }
      const blob = await getReportDownload(reportId, selectedTenantId);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `energy_report_${reportId}.pdf`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
      showToast("Download started", "success");
    } catch (error) {
      console.error("Failed to download report:", error);
      showToast(error instanceof Error ? error.message : "Failed to download report", "error");
    } finally {
      setDownloadingId(null);
    }
  };

  const formatDate = (dateStr: string | null): string => {
    if (!dateStr) return "-";
    return formatIST(dateStr, "-");
  };

  const getStatusBadge = (status: string) => {
    const styles: Record<string, string> = {
      pending: "bg-gray-100 text-gray-800",
      processing: "bg-blue-100 text-blue-800",
      completed: "bg-green-100 text-green-800",
      failed: "bg-red-100 text-red-800",
      skipped: "bg-yellow-100 text-yellow-800",
    };
    return (
      <span className={`px-2 py-1 text-xs font-medium rounded-full ${styles[status] || styles.pending}`}>
        {status || "pending"}
      </span>
    );
  };

  return (
    <div className="section-spacing">
      <ReadOnlyBanner />
      {toast && (
        <div className={`fixed top-4 right-4 px-4 py-2 rounded-lg shadow-lg z-50 ${
          toast.type === "success" ? "bg-green-600" : "bg-red-600"
        } text-white`}>
          {toast.message}
        </div>
      )}

      <PageHeader title="Reports" subtitle={getReportPageSubtitle(me?.user.role)} />

      {me?.user.role === "super_admin" && !selectedTenantId ? (
        <div className="surface-panel border-amber-200 bg-amber-50 p-6 text-amber-900">
          <h2 className="text-lg font-semibold">Select organisation</h2>
          <p className="mt-2 text-sm text-amber-800">
            Reports are tenant-scoped. Choose an organisation first so the app can send the correct tenant header.
          </p>
        </div>
      ) : null}

      {reportScopeHint ? (
        <div className="surface-panel border-amber-200 bg-amber-50 p-4 text-amber-900">
          <h2 className="text-sm font-semibold">Assigned plant scope</h2>
          <p className="mt-1 text-sm text-amber-800">{reportScopeHint}</p>
        </div>
      ) : null}

      <div className={`grid md:grid-cols-1 gap-6 ${me?.user.role === "super_admin" && !selectedTenantId ? "pointer-events-none opacity-50" : ""}`}>
        <Link
          href="/reports/energy"
          className="surface-panel block p-6 transition-shadow hover:shadow-lg"
        >
          <div className="w-12 h-12 bg-blue-100 rounded-lg flex items-center justify-center mb-4">
            <svg className="w-6 h-6 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </div>
          <h2 className="text-lg font-semibold text-gray-900">Energy Consumption Report</h2>
          <p className="text-sm text-gray-600 mt-1">
            kWh breakdown, demand analysis, load factor, cost estimation
          </p>
          {canGenerateReport ? (
            <button className="mt-4 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700">
              Generate Report
            </button>
          ) : null}
        </Link>
      </div>

      <div className="border-b border-[var(--border-subtle)]">
        <nav className="-mb-px flex space-x-8">
          <button
            onClick={() => setActiveTab("history")}
            className={`py-4 px-1 border-b-2 font-medium text-sm ${
              activeTab === "history"
                ? "border-blue-500 text-blue-600"
                : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"
            }`}
          >
            Report History
          </button>
          {canGenerateReport ? (
            <button
              onClick={() => setActiveTab("schedules")}
              className={`py-4 px-1 border-b-2 font-medium text-sm ${
                activeTab === "schedules"
                  ? "border-blue-500 text-blue-600"
                  : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"
              }`}
            >
              Schedules
            </button>
          ) : null}
        </nav>
      </div>

      {activeTab === "history" && (
        <div>
          {loading ? (
            <div className="text-center py-8 text-gray-500">Loading...</div>
          ) : history.length === 0 ? (
            <div className="surface-panel text-center py-8 text-gray-500">
              {getEmptyReportHistoryMessage(me?.user.role)}
            </div>
          ) : (
            <div className="w-full overflow-x-auto -mx-0 surface-panel overflow-hidden">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Report Type</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Created</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {history.map((item) => (
                    <tr key={item.report_id}>
                      <td className="px-6 py-4 text-sm text-gray-900 capitalize">
                        {item.report_type}
                      </td>
                      <td className="px-6 py-4">{getStatusBadge(item.status)}</td>
                      <td className="px-6 py-4 text-sm text-gray-500">
                        {formatDate(item.created_at)}
                      </td>
                      <td className="px-6 py-4">
                        {item.status === "completed" && (
                          <button
                            onClick={() => handleDownload(item.report_id)}
                            disabled={downloadingId === item.report_id}
                            className="text-blue-600 hover:text-blue-800 text-sm font-medium disabled:text-gray-400"
                          >
                            {downloadingId === item.report_id ? "Downloading..." : "Download"}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {activeTab === "schedules" && (
        <div>
          <div className="flex flex-wrap items-center gap-2 mb-4">
            <h2 className="text-lg font-semibold text-gray-900">Scheduled Reports</h2>
            {canGenerateReport ? (
              <button
                onClick={() => setShowModal(true)}
                className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700"
              >
                New Schedule
              </button>
            ) : null}
          </div>

          {loading ? (
            <div className="text-center py-8 text-gray-500">Loading...</div>
          ) : schedules.length === 0 ? (
            <div className="surface-panel text-center py-8 text-gray-500">
              {getEmptyScheduleMessage(me?.user.role)}
            </div>
          ) : (
            <div className="w-full overflow-x-auto -mx-0 surface-panel overflow-hidden">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Type</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Frequency</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Devices</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Next Run</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Last Status</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {schedules.map((schedule) => (
                    <tr key={schedule.schedule_id}>
                      <td className="px-6 py-4 text-sm text-gray-900 capitalize">
                        {schedule.report_type}
                      </td>
                      <td className="px-6 py-4 text-sm text-gray-500 capitalize">
                        {schedule.frequency}
                      </td>
                      <td className="px-6 py-4 text-sm text-gray-500">
                        {schedule.params_template?.device_ids?.length || 0} devices
                      </td>
                      <td className="px-6 py-4 text-sm text-gray-500">
                        {formatDate(schedule.next_run_at)}
                      </td>
                      <td className="px-6 py-4">
                        {getStatusBadge(schedule.last_status || "pending")}
                      </td>
                      <td className="px-6 py-4">
                        {canGenerateReport && schedule.is_active ? (
                          <button
                            onClick={() => handleDeleteSchedule(schedule.schedule_id)}
                            className="text-red-600 hover:text-red-800 text-sm font-medium"
                          >
                            Deactivate
                          </button>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {showModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="surface-panel w-full max-w-md p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">Create Schedule</h3>
            
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Report Type</label>
                <select
                  value={formData.report_type}
                  onChange={(e) => setFormData({ ...formData, report_type: e.target.value as "consumption" | "comparison" })}
                  className="w-full border rounded-lg px-3 py-2"
                >
                  <option value="consumption">Energy Consumption</option>
                  <option value="comparison">Comparison</option>
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Frequency</label>
                <select
                  value={formData.frequency}
                  onChange={(e) => setFormData({ ...formData, frequency: e.target.value as "daily" | "weekly" | "monthly" })}
                  className="w-full border rounded-lg px-3 py-2"
                >
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                  <option value="monthly">Monthly</option>
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Group By</label>
                <select
                  value={formData.group_by}
                  onChange={(e) => setFormData({ ...formData, group_by: e.target.value as "daily" | "weekly" })}
                  className="w-full border rounded-lg px-3 py-2"
                >
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Scope</label>
                {isPlantScopedRole ? (
                  <p className="mb-2 text-xs text-amber-700">
                    Only devices from your assigned plants are available for scheduling.
                  </p>
                ) : null}
                <DeviceScopeSelector
                  catalog={scopeCatalog}
                  value={normalizedScopeSelection}
                  onChange={setScopeSelection}
                  disabled={submitting}
                  helperText={reportScopeHint}
                  allModeTitle={getReportScopeLabel(me?.user.role)}
                />
                <p className="mt-2 text-xs text-slate-600">{selectedScopeSummary}</p>
              </div>
            </div>

            <div className="flex justify-end space-x-3 mt-6">
              <button
                onClick={() => {
                  setShowModal(false);
                  setScopeSelection({
                    mode: "all",
                    plantId: null,
                    deviceIds: [],
                  });
                }}
                className="px-4 py-2 border text-gray-700 rounded-lg hover:bg-gray-50"
              >
                Cancel
              </button>
              {canGenerateReport ? (
                <button
                  onClick={handleCreateSchedule}
                  disabled={submitting}
                  className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
                >
                  {submitting ? "Creating..." : "Create"}
                </button>
              ) : null}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
