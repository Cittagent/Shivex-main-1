"use client";

import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/authContext";
import { authApi, type PlantProfile } from "@/lib/authApi";
import { createDevice, type Device } from "@/lib/deviceApi";
import { resolveScopedTenantId } from "@/lib/orgScope";
import { useTenantStore } from "@/lib/tenantStore";

interface OnboardDeviceModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export function OnboardDeviceModal({ isOpen, onClose, onSuccess }: OnboardDeviceModalProps) {
  const { me } = useAuth();
  const { selectedTenantId } = useTenantStore();
  const tenantId = resolveScopedTenantId(me, selectedTenantId) ?? "";
  const userRole = me?.user?.role;
  const userPlantIds = useMemo(() => me?.plant_ids ?? [], [me?.plant_ids]);

  const [orgPlants, setOrgPlants] = useState<PlantProfile[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [createdDevice, setCreatedDevice] = useState<Device | null>(null);
  const [deviceName, setDeviceName] = useState("");
  const [plantId, setPlantId] = useState("");
  const [deviceType, setDeviceType] = useState("");
  const [deviceIdClass, setDeviceIdClass] = useState<"active" | "test" | "virtual">("active");
  const [phaseType, setPhaseType] = useState<"single" | "three">("three");
  const [dataSourceType, setDataSourceType] = useState<"metered" | "sensor">("metered");
  const [manufacturer, setManufacturer] = useState("");
  const [model, setModel] = useState("");
  const [location, setLocation] = useState("");

  const plants = useMemo(
    () => (userRole === "plant_manager" ? orgPlants.filter((plant) => userPlantIds.includes(plant.id)) : orgPlants),
    [orgPlants, userPlantIds, userRole],
  );
  const hasOrgPlants = orgPlants.length > 0;
  const hasSelectablePlants = plants.length > 0;
  const canSubmit = hasSelectablePlants && Boolean(plantId);

  function resetFormState() {
    setCreatedDevice(null);
    setDeviceName("");
    setPlantId("");
    setDeviceType("");
    setDeviceIdClass("active");
    setPhaseType("three");
    setDataSourceType("metered");
    setManufacturer("");
    setModel("");
    setLocation("");
  }

  useEffect(() => {
    if (!isOpen) {
      setOrgPlants([]);
      setIsSubmitting(false);
      setError(null);
      resetFormState();
      return;
    }
    if (!tenantId) {
      setError("No organisation context found for this session.");
      return;
    }
    let active = true;
    setError(null);
    void authApi
      .listPlants(tenantId)
      .then((allPlants) => {
        if (!active) return;
        setOrgPlants(allPlants);
      })
      .catch((err) => {
        if (!active) return;
        setOrgPlants([]);
        setError(err instanceof Error ? err.message : "Failed to load plants");
      });
    return () => {
      active = false;
    };
  }, [isOpen, tenantId, userPlantIds, userRole]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!deviceName || !deviceType) {
      setError("Please fill in all required fields.");
      return;
    }
    if (!hasSelectablePlants) {
      setError(hasOrgPlants ? "No plants are assigned to your account yet." : "Create a plant before adding a device.");
      return;
    }
    if (!plantId) {
      setError("Please select a plant.");
      return;
    }
    if (!tenantId) {
      setError("No organisation context found for this session.");
      return;
    }

    setIsSubmitting(true);
    try {
      const device = await createDevice({
        device_name: deviceName,
        device_type: deviceType,
        device_id_class: deviceIdClass,
        phase_type: phaseType,
        data_source_type: dataSourceType,
        manufacturer: manufacturer || undefined,
        model: model || undefined,
        location: location || undefined,
        plant_id: plantId,
      });

      setCreatedDevice(device);
      setDeviceName("");
      setPlantId("");
      setDeviceType("");
      setDeviceIdClass("active");
      setPhaseType("three");
      setDataSourceType("metered");
      setManufacturer("");
      setModel("");
      setLocation("");

      onSuccess();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to add device";
      if (msg.includes("409") || msg.toLowerCase().includes("allocate a unique device id")) {
        setError("Unable to allocate a device ID right now. Please try again.");
      } else {
        setError(msg);
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  if (!isOpen) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-950/70 p-4">
      <button
        type="button"
        aria-label="Close device onboarding modal"
        className="absolute inset-0"
        onClick={onClose}
      />
      <div className="relative z-10 flex max-h-[90vh] w-full max-w-[520px] flex-col overflow-hidden rounded-[1.5rem] border border-[var(--border-subtle)] bg-[var(--surface-0)] shadow-[var(--shadow-raised)]">
        <div className="border-b border-[var(--border-subtle)] px-5 py-4">
          <h2 className="text-lg font-semibold tracking-[-0.02em] text-[var(--text-primary)]">Add device</h2>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">
            Register a machine for this organisation and bind it to a plant.
          </p>
        </div>

        <form className="space-y-4 overflow-y-auto p-5" onSubmit={(event) => void handleSubmit(event)}>
          {createdDevice ? (
            <>
              <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-4">
                <p className="text-sm font-semibold text-emerald-900">Device created</p>
                <p className="mt-1 text-sm text-emerald-800">
                  Use this generated device ID when provisioning firmware and telemetry.
                </p>
              </div>

              <div className="space-y-1">
                <label className="block text-sm font-medium text-slate-700">Generated Device ID</label>
                <div className="rounded-xl border border-[var(--border-subtle)] bg-slate-50 px-3 py-3 font-mono text-sm text-[var(--text-primary)]">
                  {createdDevice.id}
                </div>
              </div>

              <div className="rounded border border-gray-200 bg-gray-50 p-3">
                <p className="mb-1 text-xs text-gray-500">MQTT topic for this device:</p>
                <p className="font-mono text-xs text-gray-700">
                  {tenantId || "<tenant-id>"}/devices/{createdDevice.id}/telemetry
                </p>
                <p className="mt-1 text-xs text-gray-400">Configure your firmware to publish to this topic</p>
              </div>

              <div className="flex justify-end gap-3 pt-2">
                <Button type="button" variant="secondary" onClick={onClose}>
                  Done
                </Button>
                <Button
                  type="button"
                  onClick={() => {
                    setCreatedDevice(null);
                    setError(null);
                  }}
                >
                  Add Another Device
                </Button>
              </div>
            </>
          ) : (
            <>
              <div className="space-y-1">
                <label className="block text-sm font-medium text-slate-700">Device Name *</label>
                <input
                  type="text"
                  value={deviceName}
                  onChange={(e) => setDeviceName(e.target.value)}
                  placeholder="e.g. Compressor Line A"
                  required
                  disabled={isSubmitting}
                  className="block h-10 w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-0)] px-3 text-sm text-[var(--text-primary)] shadow-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
                />
              </div>

              <div className="space-y-1">
                <label className="block text-sm font-medium text-slate-700">Plant *</label>
                {hasSelectablePlants ? (
                  <select
                    value={plantId}
                    onChange={(e) => setPlantId(e.target.value)}
                    required
                    disabled={isSubmitting}
                    className="block h-10 w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-0)] px-3 text-sm text-[var(--text-primary)] shadow-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
                  >
                    <option value="">Select a plant</option>
                    {plants.map((plant) => (
                      <option key={plant.id} value={plant.id}>
                        {plant.name}
                      </option>
                    ))}
                  </select>
                ) : (
                  <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-3 text-sm text-amber-800">
                    {hasOrgPlants
                      ? "No plants are assigned to your account yet. Ask an org admin to assign you to a plant before adding a device."
                      : "Create a plant first. Devices must belong to a plant before they can be added."}
                  </div>
                )}
                {hasSelectablePlants ? (
                  <p className="mt-1 text-xs text-gray-400">Choose the plant this device belongs to.</p>
                ) : hasOrgPlants ? (
                  <p className="mt-1 text-xs text-gray-400">No plants are assigned to your account yet.</p>
                ) : (
                  <p className="mt-1 text-xs text-gray-400">A plant must exist before a machine can be registered.</p>
                )}
              </div>

              <div className="mt-2 rounded border border-gray-200 bg-gray-50 p-3">
                <p className="mb-1 text-xs text-gray-500">MQTT topic after provisioning:</p>
                <p className="font-mono text-xs text-gray-700">
                  {tenantId || "<tenant-id>"}/devices/&lt;generated-device-id&gt;/telemetry
                </p>
                <p className="mt-1 text-xs text-gray-400">The platform generates the device ID after creation.</p>
              </div>

              <div className="space-y-1">
                <label className="block text-sm font-medium text-slate-700">Device Type *</label>
                <input
                  type="text"
                  value={deviceType}
                  onChange={(e) => setDeviceType(e.target.value)}
                  placeholder="e.g. Compressor, Chiller, Motor"
                  required
                  disabled={isSubmitting}
                  className="block h-10 w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-0)] px-3 text-sm text-[var(--text-primary)] shadow-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
                />
              </div>

              <div className="space-y-1">
                <label className="block text-sm font-medium text-slate-700">Device ID Class *</label>
                <select
                  value={deviceIdClass}
                  onChange={(e) => setDeviceIdClass(e.target.value as "active" | "test" | "virtual")}
                  disabled={isSubmitting}
                  className="block h-10 w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-0)] px-3 text-sm text-[var(--text-primary)] shadow-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
                >
                  <option value="active">Active Device</option>
                  <option value="test">Test Device</option>
                  <option value="virtual">Virtual Device</option>
                </select>
                <p className="mt-1 text-xs text-gray-400">This controls the generated device ID prefix only.</p>
              </div>

              <div className="space-y-1">
                <label className="block text-sm font-medium text-slate-700">Phase Type</label>
                <select
                  value={phaseType}
                  onChange={(e) => setPhaseType(e.target.value as "single" | "three")}
                  disabled={isSubmitting}
                  className="block h-10 w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-0)] px-3 text-sm text-[var(--text-primary)] shadow-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
                >
                  <option value="three">Three Phase</option>
                  <option value="single">Single Phase</option>
                </select>
              </div>

              <div className="space-y-1">
                <label className="block text-sm font-medium text-slate-700">Data Source</label>
                <select
                  value={dataSourceType}
                  onChange={(e) => setDataSourceType(e.target.value as "metered" | "sensor")}
                  disabled={isSubmitting}
                  className="block h-10 w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-0)] px-3 text-sm text-[var(--text-primary)] shadow-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
                >
                  <option value="metered">Metered</option>
                  <option value="sensor">Sensor</option>
                </select>
              </div>

              <div className="space-y-1">
                <label className="block text-sm font-medium text-slate-700">Manufacturer</label>
                <input
                  type="text"
                  value={manufacturer}
                  onChange={(e) => setManufacturer(e.target.value)}
                  placeholder="e.g. Atlas Copco"
                  disabled={isSubmitting}
                  className="block h-10 w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-0)] px-3 text-sm text-[var(--text-primary)] shadow-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
                />
              </div>

              <div className="space-y-1">
                <label className="block text-sm font-medium text-slate-700">Model</label>
                <input
                  type="text"
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  placeholder="e.g. GA37"
                  disabled={isSubmitting}
                  className="block h-10 w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-0)] px-3 text-sm text-[var(--text-primary)] shadow-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
                />
              </div>

              <div className="space-y-1">
                <label className="block text-sm font-medium text-slate-700">Location</label>
                <input
                  type="text"
                  value={location}
                  onChange={(e) => setLocation(e.target.value)}
                  placeholder="e.g. Building A, Floor 1"
                  disabled={isSubmitting}
                  className="block h-10 w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-0)] px-3 text-sm text-[var(--text-primary)] shadow-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
                />
              </div>

              <div className="space-y-1">
                <label className="text-xs text-gray-400">Organisation ID (read only)</label>
                <input
                  type="text"
                  value={tenantId}
                  readOnly
                  className="block h-10 w-full cursor-not-allowed rounded-xl border border-gray-200 bg-gray-50 px-3 text-xs text-gray-400 opacity-60"
                />
              </div>

              {error && (
                <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-600">
                  {error}
                </div>
              )}

              <div className="flex items-center justify-end gap-3 pt-2">
                <Button type="button" variant="secondary" onClick={onClose} disabled={isSubmitting}>
                  Cancel
                </Button>
                <Button type="submit" disabled={isSubmitting || !canSubmit}>
                  {isSubmitting ? "Adding..." : "Add Device"}
                </Button>
              </div>
            </>
          )}
        </form>
      </div>
    </div>
  );
}
