"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusBadge } from "@/components/ui/badge";
import { formatIST } from "@/lib/utils";
import { getRule, updateRule, updateRuleStatus, deleteRule, Rule, RuleStatus } from "@/lib/ruleApi";
import { formatCooldownLabel } from "@/lib/ruleCooldown";
import { getRuleConditionSummary, getRuleTriggerSummary, getRuleTypeBadgeLabel } from "@/lib/rulePresentation";
import { getDevices, Device } from "@/lib/deviceApi";
import { Input, Checkbox } from "@/components/ui/input";
import { usePermissions } from "@/hooks/usePermissions";
import { getAllDevicesScopeLabel, getRuleDeviceScopeDisplay } from "@/lib/ruleScope";
import {
  dedupeRuleRecipientEmails,
  dedupeRuleRecipientPhones,
  isValidRuleRecipientEmail,
  isValidRuleRecipientPhone,
  normalizeRuleRecipientEmail,
  normalizeRuleRecipientPhone,
} from "@/lib/ruleRecipients";

function formatScope(scope: Rule["scope"], role: string | null | undefined) {
  return scope === "all_devices" ? getAllDevicesScopeLabel(role) : "Selected Devices";
}

export default function RuleDetailsPage() {
  const { canCreateRule, currentRole } = usePermissions();
  const params = useParams();
  const router = useRouter();
  const ruleId = (params.ruleId as string) || "";

  const [rule, setRule] = useState<Rule | null>(null);
  const [devices, setDevices] = useState<Device[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notificationForm, setNotificationForm] = useState<{
    email: boolean;
    sms: boolean;
    whatsapp: boolean;
    emailRecipients: string[];
    emailRecipientInput: string;
    phoneRecipients: string[];
    phoneRecipientInput: string;
  }>({
    email: false,
    sms: false,
    whatsapp: false,
    emailRecipients: [],
    emailRecipientInput: "",
    phoneRecipients: [],
    phoneRecipientInput: "",
  });

  const deviceLabel = useMemo(() => {
    if (!rule) return [];
    if (rule.scope === "all_devices") return [getAllDevicesScopeLabel(currentRole)];
    const map = new Map(devices.map((d) => [d.id, d.name]));
    const joined = getRuleDeviceScopeDisplay(rule.deviceIds, currentRole, (id) => map.get(id) || id);
    return joined.split(", ").map((name) => {
      const matchingDevice = devices.find((device) => device.name === name || device.id === name);
      return matchingDevice ? `${matchingDevice.name} (${matchingDevice.id})` : name;
    });
  }, [rule, devices, currentRole]);

  const load = async () => {
    if (!ruleId) return;
    setLoading(true);
    setError(null);
    try {
      const [r, d] = await Promise.all([getRule(ruleId), getDevices()]);
      setRule(r);
      setDevices(d);
      setNotificationForm({
        email: r.notificationChannels.includes("email"),
        sms: r.notificationChannels.includes("sms"),
        whatsapp: r.notificationChannels.includes("whatsapp"),
        emailRecipients: dedupeRuleRecipientEmails(
          r.notificationRecipients
            .filter((recipient) => recipient.channel === "email")
            .map((recipient) => recipient.value),
        ),
        phoneRecipients: dedupeRuleRecipientPhones(
          r.notificationRecipients
            .filter((recipient) => recipient.channel === "sms" || recipient.channel === "whatsapp")
            .map((recipient) => recipient.value),
        ),
        emailRecipientInput: "",
        phoneRecipientInput: "",
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load rule details");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ruleId]);

  const handleToggleStatus = async () => {
    if (!rule) return;
    const nextStatus: RuleStatus = rule.status === "active" ? "paused" : "active";
    try {
      setBusy(true);
      await updateRuleStatus(rule.ruleId, nextStatus);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update rule status");
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async () => {
    if (!rule) return;
    if (!confirm("Are you sure you want to delete this rule?")) return;
    try {
      setBusy(true);
      await deleteRule(rule.ruleId);
      router.push("/rules");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete rule");
      setBusy(false);
    }
  };

  const handleAddEmailRecipient = () => {
    const normalized = normalizeRuleRecipientEmail(notificationForm.emailRecipientInput);
    if (!normalized) {
      setError("Enter an email recipient.");
      return;
    }
    if (!isValidRuleRecipientEmail(normalized)) {
      setError("Enter a valid email recipient.");
      return;
    }
    setError(null);
    setNotificationForm((prev) => ({
      ...prev,
      email: true,
      emailRecipients: dedupeRuleRecipientEmails([...prev.emailRecipients, normalized]),
      emailRecipientInput: "",
    }));
  };

  const handleRemoveEmailRecipient = (email: string) => {
    setNotificationForm((prev) => ({
      ...prev,
      emailRecipients: prev.emailRecipients.filter((value) => value !== email),
    }));
  };

  const handleAddPhoneRecipient = () => {
    const normalized = normalizeRuleRecipientPhone(notificationForm.phoneRecipientInput);
    if (!normalized) {
      setError("Enter a phone recipient.");
      return;
    }
    if (!isValidRuleRecipientPhone(normalized)) {
      setError("Enter a valid phone recipient.");
      return;
    }
    setError(null);
    setNotificationForm((prev) => ({
      ...prev,
      phoneRecipients: dedupeRuleRecipientPhones([...prev.phoneRecipients, normalized]),
      phoneRecipientInput: "",
    }));
  };

  const handleSaveNotificationSettings = async () => {
    if (!rule) return;
    const channels: string[] = [];
    if (notificationForm.email) channels.push("email");
    if (notificationForm.sms) channels.push("sms");
    if (notificationForm.whatsapp) channels.push("whatsapp");

    if (channels.length === 0) {
      setError("Select at least one notification channel.");
      return;
    }
    if (notificationForm.email && notificationForm.emailRecipients.length === 0) {
      setError("Add at least one email recipient when email notifications are enabled.");
      return;
    }
    if ((notificationForm.sms || notificationForm.whatsapp) && notificationForm.phoneRecipients.length === 0) {
      setError("Add at least one phone recipient when SMS or WhatsApp notifications are enabled.");
      return;
    }

    try {
      setBusy(true);
      setError(null);
      await updateRule(rule.ruleId, {
        notificationChannels: channels,
        notificationRecipients: [
          ...(notificationForm.email
            ? notificationForm.emailRecipients.map((value) => ({ channel: "email", value }))
            : []),
          ...(notificationForm.sms
            ? notificationForm.phoneRecipients.map((value) => ({ channel: "sms", value }))
            : []),
          ...(notificationForm.whatsapp
            ? notificationForm.phoneRecipients.map((value) => ({ channel: "whatsapp", value }))
            : []),
        ],
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update notification settings");
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <div className="p-8">
        <div className="flex items-center justify-center h-64">
          <div className="text-center">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
            <p className="mt-4 text-slate-600">Loading rule details...</p>
          </div>
        </div>
      </div>
    );
  }

  if (error || !rule) {
    return (
      <div className="p-8">
        <div className="max-w-4xl mx-auto bg-red-50 border border-red-200 rounded-lg p-6">
          <h2 className="text-red-800 font-semibold mb-2">Unable to load rule details</h2>
          <p className="text-red-700">{error || "Rule not found"}</p>
          <div className="mt-4">
            <Link href="/rules">
              <Button variant="outline">Back to Rules</Button>
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="p-8">
      <div className="max-w-7xl mx-auto space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <Link href="/rules" className="text-sm text-slate-500 hover:text-slate-800">
              ← Back to Rules
            </Link>
            <h1 className="text-3xl font-bold text-slate-900 mt-3">{rule.ruleName}</h1>
          </div>
          <div className="flex items-center gap-3">
            {canCreateRule ? (
              <Button variant="outline" onClick={handleToggleStatus} disabled={busy}>
                {rule.status === "active" ? "Pause" : "Enable"}
              </Button>
            ) : null}
            {canCreateRule ? (
              <Button variant="danger" onClick={handleDelete} disabled={busy}>
                Delete
              </Button>
            ) : null}
          </div>
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          <Card>
            <CardHeader>
              <CardTitle>Rule Details</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-slate-500">Status</span>
                <StatusBadge status={rule.status} />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-500">Type</span>
                <span className="text-slate-900">{getRuleTypeBadgeLabel(rule.ruleType)}</span>
              </div>
              <div className="flex items-start justify-between gap-3">
                <span className="text-slate-500">Trigger</span>
                <span className="text-slate-900 text-right">{getRuleTriggerSummary(rule)}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-500">Condition</span>
                <span className="text-slate-900 text-right">{getRuleConditionSummary(rule)}</span>
              </div>
              {rule.ruleType === "continuous_idle_duration" ? (
                <div className="flex items-center justify-between">
                  <span className="text-slate-500">Duration</span>
                  <span className="text-slate-900">{rule.durationMinutes ?? "-"} minutes</span>
                </div>
              ) : null}
              {rule.ruleType === "time_based" ? (
                <div className="flex items-center justify-between">
                  <span className="text-slate-500">Window</span>
                  <span className="text-slate-900">
                    {rule.timeWindowStart ?? "--:--"} - {rule.timeWindowEnd ?? "--:--"} IST
                  </span>
                </div>
              ) : null}
              {rule.ruleType === "threshold" ? (
                <div className="flex items-center justify-between">
                  <span className="text-slate-500">Threshold</span>
                  <span className="text-slate-900">
                    {rule.property ?? "property"} {rule.condition ?? "="} {rule.threshold ?? "-"}
                  </span>
                </div>
              ) : null}
              <div className="flex items-center justify-between">
                <span className="text-slate-500">Rule Type Contract</span>
                <span className="text-slate-900">
                  {rule.ruleType === "continuous_idle_duration"
                    ? "Idle continuously for N minutes"
                    : rule.ruleType === "time_based"
                      ? "Running in restricted wall-clock window"
                      : "Threshold comparison"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-500">Scope</span>
                <span className="text-slate-900">{formatScope(rule.scope, currentRole)}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-500">Cooldown</span>
                <span className="text-slate-900">{formatCooldownLabel(rule)}</span>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Devices</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                {deviceLabel.map((name) => (
                  <div key={name} className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-800">
                    {name}
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Notification Channels</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center gap-2 text-sm">
              <span className="text-slate-500">Channels:</span>
              <span className="text-slate-900">{rule.notificationChannels.join(", ") || "None"}</span>
            </div>
            {rule.notificationChannels.includes("email") ? (
              <div>
                <p className="text-sm text-slate-500 mb-2">
                  Attached email recipients ({notificationForm.emailRecipients.length})
                </p>
                {notificationForm.emailRecipients.length === 0 ? (
                  <p className="text-sm text-amber-700">No email recipients are attached to this rule.</p>
                ) : (
                  <div className="rounded-lg border border-slate-200 divide-y divide-slate-100">
                    {notificationForm.emailRecipients.map((email) => (
                      <div key={email} className="px-3 py-2 text-sm text-slate-800">
                        {email}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <p className="text-sm text-slate-500">Email channel not enabled for this rule.</p>
            )}
            {canCreateRule ? (
              <div className="space-y-4 rounded-lg border border-slate-200 bg-slate-50 p-4">
                <p className="text-sm font-medium text-slate-900">Edit Notification Settings</p>
                <div className="flex gap-6">
                  <Checkbox
                    label="Email"
                    checked={notificationForm.email}
                    onChange={(e) =>
                      setNotificationForm((prev) => ({
                        ...prev,
                        email: e.target.checked,
                        emailRecipients: e.target.checked ? prev.emailRecipients : [],
                        emailRecipientInput: e.target.checked ? prev.emailRecipientInput : "",
                      }))
                    }
                  />
                  <Checkbox
                    label="SMS"
                    checked={notificationForm.sms}
                    onChange={(e) =>
                      setNotificationForm((prev) => {
                        const nextSms = e.target.checked;
                        const keepPhoneState = nextSms || prev.whatsapp;
                        return {
                          ...prev,
                          sms: nextSms,
                          phoneRecipients: keepPhoneState ? prev.phoneRecipients : [],
                          phoneRecipientInput: keepPhoneState ? prev.phoneRecipientInput : "",
                        };
                      })
                    }
                  />
                  <Checkbox
                    label="WhatsApp"
                    checked={notificationForm.whatsapp}
                    onChange={(e) =>
                      setNotificationForm((prev) => {
                        const nextWhatsapp = e.target.checked;
                        const keepPhoneState = prev.sms || nextWhatsapp;
                        return {
                          ...prev,
                          whatsapp: nextWhatsapp,
                          phoneRecipients: keepPhoneState ? prev.phoneRecipients : [],
                          phoneRecipientInput: keepPhoneState ? prev.phoneRecipientInput : "",
                        };
                      })
                    }
                  />
                </div>
                {notificationForm.email ? (
                  <div className="space-y-3">
                    <div className="flex gap-2">
                      <Input
                        label="Email Recipients"
                        type="email"
                        value={notificationForm.emailRecipientInput}
                        onChange={(e) =>
                          setNotificationForm((prev) => ({ ...prev, emailRecipientInput: e.target.value }))
                        }
                        placeholder="alerts@planta.com"
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            e.preventDefault();
                            handleAddEmailRecipient();
                          }
                        }}
                      />
                      <div className="pt-6">
                        <Button type="button" variant="outline" onClick={handleAddEmailRecipient}>
                          Add Email
                        </Button>
                      </div>
                    </div>
                    {notificationForm.emailRecipients.length > 0 ? (
                      <div className="rounded-lg border border-slate-200 bg-white divide-y divide-slate-100">
                        {notificationForm.emailRecipients.map((email) => (
                          <div key={email} className="flex items-center justify-between px-3 py-2 text-sm text-slate-800">
                            <span>{email}</span>
                            <button
                              type="button"
                              className="rounded-md px-2 py-1 text-xs text-red-600 hover:bg-red-50"
                              onClick={() => handleRemoveEmailRecipient(email)}
                            >
                              Remove
                            </button>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-sm text-amber-700">
                        Add the recipients who should receive alerts for this rule.
                      </p>
                    )}
                  </div>
                ) : null}
                {notificationForm.sms || notificationForm.whatsapp ? (
                  <div className="space-y-3">
                    <div className="flex gap-2">
                      <Input
                        label="Phone Recipients"
                        type="tel"
                        value={notificationForm.phoneRecipientInput}
                        onChange={(e) =>
                          setNotificationForm((prev) => ({ ...prev, phoneRecipientInput: e.target.value }))
                        }
                        placeholder="+15551234567"
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            e.preventDefault();
                            handleAddPhoneRecipient();
                          }
                        }}
                      />
                      <div className="pt-6">
                        <Button type="button" variant="outline" onClick={handleAddPhoneRecipient}>
                          Add Phone
                        </Button>
                      </div>
                    </div>
                    {notificationForm.phoneRecipients.length > 0 ? (
                      <div className="rounded-lg border border-slate-200 bg-white divide-y divide-slate-100">
                        {notificationForm.phoneRecipients.map((phone) => (
                          <div key={phone} className="flex items-center justify-between px-3 py-2 text-sm text-slate-800">
                            <span>{phone}</span>
                            <button
                              type="button"
                              className="rounded-md px-2 py-1 text-xs text-red-600 hover:bg-red-50"
                              onClick={() =>
                                setNotificationForm((prev) => ({
                                  ...prev,
                                  phoneRecipients: prev.phoneRecipients.filter((value) => value !== phone),
                                }))
                              }
                            >
                              Remove
                            </button>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-sm text-amber-700">
                        Add the phone recipients who should receive SMS or WhatsApp alerts for this rule.
                      </p>
                    )}
                  </div>
                ) : null}
                <div>
                  <Button type="button" onClick={handleSaveNotificationSettings} disabled={busy}>
                    Save Notification Settings
                  </Button>
                </div>
              </div>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Timestamps</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="flex items-center justify-between">
              <span className="text-slate-500">Created</span>
              <span className="text-slate-900">{formatIST(rule.createdAt, "N/A")}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-500">Last Updated</span>
              <span className="text-slate-900">{formatIST(rule.updatedAt || null, "N/A")}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-500">Last Triggered</span>
              <span className="text-slate-900">{formatIST(rule.lastTriggeredAt || null, "Not triggered yet")}</span>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
