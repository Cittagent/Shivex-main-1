# FactoryOPS Handover Document

## 1. Product Overview

FactoryOPS is a multi-service Industrial IoT platform for machine monitoring, rule-based alerting, ML analytics, energy reporting, and waste analysis.

Primary user outcomes:
- Onboard devices and ingest telemetry in near real time.
- Monitor machine status, health score, uptime, and idle-running waste.
- Configure threshold and time-based rules with cooldown and notification channels.
- Generate analytics dashboards (anomaly/failure) and drill down from fleet to device.
- Generate Energy Consumption and Waste Analysis reports with downloadable PDFs.
- Manage tariff and email recipients centrally in Settings.

Core modules visible in UI:
- Machines (operational home + device details)
- Analytics
- Reports
- Waste Analysis
- Rules
- Settings

---

## 2. Runtime Architecture

## 2.1 Services and ports
- `ui-web` (Next.js): `3000`
- `device-service`: `8000`
- `rule-engine-service`: `8002`
- `analytics-service`: `8003`
- `data-export-service`: `8080`
- `data-service`: `8081`
- `reporting-service`: `8085`
- `waste-analysis-service`: `8087`
- Infrastructure: MySQL `3306`, InfluxDB `8086`, EMQX `1883/8083/8084`, MinIO `9000/9001`

## 2.2 Data stores
- MySQL (single DB): `ai_factoryops`
- InfluxDB bucket: `telemetry`
- MinIO buckets used for generated/exported artifacts.

## 2.3 Message and data flow (high level)
1. Device/simulator publishes telemetry to EMQX.
2. `data-service` consumes telemetry, validates/enriches, writes to InfluxDB.
3. `data-service` triggers property sync + rule evaluation via internal service calls.
4. `device-service` maintains device config, shifts, uptime, health config, idle stats.
5. `rule-engine-service` evaluates rules and creates alerts/activity events.
6. `analytics-service` runs asynchronous ML jobs and formatted dashboard outputs.
7. `reporting-service` runs asynchronous energy/comparison reports and PDF generation.
8. `waste-analysis-service` runs asynchronous waste analysis and PDF generation.
9. `ui-web` orchestrates all workflows.

---

## 3. Service Responsibilities

## 3.1 device-service
Ownership:
- Device lifecycle (CRUD)
- Runtime heartbeat status
- Shift configuration and uptime computation
- Health parameter configuration + health-score calculation
- Idle running config/state/stats
- Dashboard summary and performance trend materialization

Important behavior:
- Runtime status is heartbeat freshness based (running/stopped).
- Uptime is calculated in active shift window using telemetry running intervals (IST window logic).
- Idle metrics rely on `idle_current_threshold` and telemetry (`current/voltage/power`).

## 3.2 data-service
Ownership:
- Telemetry ingestion from MQTT
- Telemetry query APIs
- WebSocket streaming for live telemetry
- Telemetry stats aggregation

Important behavior:
- Device-specific telemetry APIs are always scoped by `device_id`.
- Provides bounded-range querying support for UI and downstream services.

## 3.3 rule-engine-service
Ownership:
- Rule definitions and state transitions
- Rule evaluation endpoint
- Alert lifecycle
- Activity/event feed and unread counters

Supports:
- Threshold rules
- Time-based rules (IST window handling, overnight supported)
- Cooldown modes: interval and no-repeat
- Notification channels (email integrated with Settings recipients)

## 3.4 analytics-service
Ownership:
- Async ML analytics jobs (`anomaly`, `prediction`, `forecast`)
- Fleet strict-mode orchestration (all-machines)
- Formatted dashboard payloads for UI

Important behavior:
- Fleet result includes per-device summaries and child job mapping for drilldown.
- UI can open device child dashboard directly from fleet summary without re-running jobs.

## 3.5 reporting-service
Ownership:
- Energy Consumption reports
- Comparison reports
- Report history/schedules/status/result/download
- Settings APIs (tariff + notification channels)

Important behavior:
- Tariff comes from Settings and is used live at report generation.
- Report jobs are asynchronous and downloaded via report endpoints.

## 3.6 waste-analysis-service
Ownership:
- Waste analysis run/status/result/history/download
- Waste PDF generation

Important behavior:
- Strict quality gate supported.
- Uses telemetry + device config + tariff dependencies.
- Download endpoint returns presigned URL JSON.

## 3.7 data-export-service
Ownership:
- Dataset export/checkpoint operations for analytics pipeline.

---

## 4. Functional Areas (What the Product Does)

## 4.1 Machines (home dashboard)
- Shows total devices, active alerts, system health.
- Device cards show runtime status and health visibility.
- Global alert bell provides cross-device event feed.

## 4.2 Device detail
- Persistent header: identity, status, uptime, health score.
- Idle Running Waste widget with today/month indicators.
- Tabs:
  - Overview
  - Telemetry
  - Parameter Configuration
  - Configure Rules

## 4.3 Parameter Configuration
- Shift Configuration
- Parameter Health Configuration (weights/ranges)
- Idle Running Configuration (threshold)

## 4.4 Rules
- Create/list/update/pause/delete rules.
- Threshold and time-based rules.
- Cooldown is user configurable (including no-repeat mode).
- Rule detail view shows status, scope, trigger, channels, and timestamps.

## 4.5 Analytics
- Wizard flow:
  - Select scope (all devices or selected)
  - Select date range
  - Select analysis type
  - Run and track progress
- Supports anomaly and failure dashboards with confidence and quality indicators.
- Fleet summary supports click-through per device drilldown.

## 4.6 Reports
- Energy Consumption report generation and download.
- Comparison report generation.
- Report history and scheduling support.

## 4.7 Waste Analysis
- Scope/date/granularity based analysis jobs.
- Progress and history tracking.
- PDF download from completed jobs.

## 4.8 Settings
- Alert Notifications (email recipients; add/remove, DB-backed)
- Tariff Configuration (rate/currency, DB-backed)
- WhatsApp/SMS placeholders present as non-functional UI placeholders.

---

## 5. Computation Logic (Business Formulas)

## 5.1 Health Score
Concept:
- Weighted score from configured parameters, ranges, and weights.
- If no usable config/data, score should be null/low-confidence path (not forced 100).

## 5.2 Uptime (active shift runtime model)
- Compute active shift window in IST.
- `planned_minutes` from shift.
- `effective_minutes = planned_minutes - maintenance_break_minutes`.
- `actual_running_minutes` from telemetry intervals classified as running.
- `uptime_pct = clamp((actual_running_minutes / effective_minutes) * 100, 0, 100)`.

## 5.3 Idle state classification
- `unloaded`: `current <= 0 && voltage > 0`
- `idle`: `0 < current < idle_threshold && voltage > 0`
- `running`: `current >= idle_threshold && voltage > 0`
- `unknown`: missing required telemetry or threshold context

## 5.4 Energy calculation priority (reporting + waste consistency target)
1. `energy_kwh` delta (if cumulative meter present)
2. Integrate `power` over actual timestamp intervals
3. Derive `power = V * I * PF / 1000`, then integrate
4. If PF missing, may assume `PF = 1.0` with degraded quality flag
5. Insufficient signal => low/insufficient quality path

## 5.5 Costing
- `cost = energy_kwh * tariff_rate`
- Tariff source is Settings API/database (no hardcoded tariff intended).

---

## 6. API Surface (UI-Facing Summary)

Detailed endpoint listing exists in service READMEs and route handlers.
Use these base prefixes:

- Device APIs: `http://localhost:8000/api/v1/devices`
- Data APIs: `http://localhost:8081/api/v1/data`
- Rule APIs: `http://localhost:8002/api/v1/rules`
- Alert/Event APIs: `http://localhost:8002/api/v1/alerts`
- Analytics APIs: `http://localhost:8003/api/v1/analytics`
- Reporting APIs: `http://localhost:8085/api/reports` and `http://localhost:8085/api/v1/settings`
- Waste APIs: `http://localhost:8087/api/v1/waste`

UI integration patterns:
- Async jobs use polling (`status` endpoint) then fetch `result` and/or `download`.
- Reporting download is direct PDF stream.
- Waste download returns a presigned URL.
- Alert history and unread counters are paginated/scoped endpoints.

---

## 7. Firmware / Telemetry Contract

Reference docs:
- `Project-docs/Firmware/firmwareonboarding.md`
- `Project-docs/Firmware/parameterverification.md`

Minimum expected fields:
- `device_id` (must match onboarded ID)
- `timestamp` (ISO UTC)
- Numeric telemetry fields as numbers (not unit strings)

Common canonical units:
- `current`: A
- `voltage`: V
- `power`: W
- `energy_kwh`: cumulative kWh
- `power_factor`: 0..1

Contract principle:
- Timestamp monotonicity and unit consistency are critical for reliable uptime/report/waste results.

---

## 8. Operations Runbook

## 8.1 Start platform
```bash
docker compose up -d --build
```

## 8.2 Stop platform
```bash
docker compose down
```

## 8.3 Check running services
```bash
docker compose ps
```

## 8.4 Health checks
```bash
curl -sS http://localhost:8000/health
curl -sS http://localhost:8081/api/v1/data/health
curl -sS http://localhost:8002/health
curl -sS http://localhost:8003/health/live
curl -sS http://localhost:8085/health
curl -sS http://localhost:8087/health
```

## 8.5 Local URLs
- UI: `http://localhost:3000`
- EMQX dashboard: `http://localhost:18083`
- MinIO console: `http://localhost:9001`

---

## 9. Configuration Model

Single source principles:
- Tariff and notification recipients are settings-driven (not hardcoded in UI).
- Device-specific thresholds and health configs are stored in device-service DB tables.
- Reports and waste use live platform settings and device configuration at runtime.

Critical deployment parameters:
- MySQL connectivity (`ai_factoryops`)
- InfluxDB connectivity (`telemetry` bucket)
- MinIO endpoint and buckets
- SMTP settings for email alerts

---

## 10. Quality, Reliability, and Known Constraints

Reliability design intents:
- Structured JSON errors from services.
- Async jobs with explicit states (`pending/running/completed/failed`).
- Device- and time-scoped querying to avoid cross-device leakage.
- Strict-mode gates in selected premium flows.

Known practical constraints:
- Final numerical accuracy depends on firmware unit/timestamp correctness.
- Missing telemetry fields degrade quality and can block strict flows.
- Historical outputs are not retroactively recalculated unless a new job is run.

---

## 11. Handover Checklist for New Team Members

1. Bring stack up with Docker Compose.
2. Verify all health endpoints.
3. Onboard one test device.
4. Start simulator / publish telemetry.
5. Confirm device runtime and telemetry cards update.
6. Configure shifts + health parameters + idle threshold.
7. Create one threshold rule and verify alert flow.
8. Configure Settings (tariff + email recipient).
9. Run Analytics, Reports, and Waste jobs end-to-end.
10. Validate download flows and timestamps display in IST on UI.

This checklist is the fastest confidence path before demo or production deployment.
