# FactoryOPS API Endpoints (UI Integration Guide)

This file lists the current backend API contracts used by the UI.
Base local URL (via `docker compose`): `http://localhost`.

## Service Map

- `device-service`: `http://localhost:8000`
- `data-service`: `http://localhost:8081`
- `rule-engine-service`: `http://localhost:8002`
- `analytics-service`: `http://localhost:8003`
- `reporting-service`: `http://localhost:8085`
- `waste-analysis-service`: `http://localhost:8087`
- `ui-web`: `http://localhost:3000`

---

## 1) Device Service (`/api/v1/devices`)
Base: `http://localhost:8000/api/v1/devices`

### Health
- `GET /health`
- `GET /ready`

### Device CRUD
- `GET /`  
  Query: `tenant_id?`, `device_type?`, `status?`, `page=1`, `page_size=20`
- `POST /`  
  Body: `device_id, device_name, device_type, manufacturer?, model?, location?, data_source_type(metered|sensor), phase_type?`
- `GET /{device_id}`
- `PUT /{device_id}`
- `DELETE /{device_id}`  
  Query: `tenant_id?`, `soft=true|false`

### Dashboard + Dynamic Properties
- `GET /dashboard/summary`
- `GET /properties`
- `POST /properties/common`  
  Body: `{ "device_ids": ["COMPRESSOR-001", "..."] }`
- `GET /{device_id}/properties`
- `POST /{device_id}/properties/sync`  
  Body: raw telemetry JSON map

### Runtime / Heartbeat
- `POST /{device_id}/heartbeat`

### Shift + Uptime
- `POST /{device_id}/shifts`
- `GET /{device_id}/shifts`
- `GET /{device_id}/shifts/{shift_id}`
- `PUT /{device_id}/shifts/{shift_id}`
- `DELETE /{device_id}/shifts/{shift_id}`
- `GET /{device_id}/uptime`  
  Runtime-calculated fields include `uptime_percentage`, `actual_running_minutes`, `window_start`, `window_end`, `data_coverage_pct`, `data_quality`.

### Performance Trends
- `GET /{device_id}/performance-trends`  
  Query: `metric=health|uptime`, `range=30m|1h|6h|24h|7d|30d`

### Health Config + Score
- `POST /{device_id}/health-config`
- `GET /{device_id}/health-config`
- `GET /{device_id}/health-config/validate-weights`
- `GET /{device_id}/health-config/{config_id}`
- `PUT /{device_id}/health-config/{config_id}`
- `DELETE /{device_id}/health-config/{config_id}`
- `POST /{device_id}/health-config/bulk`
- `POST /{device_id}/health-score`  
  Body: `{ "values": { "current": 1.2, ... }, "machine_state": "RUNNING" }`

### Idle Running APIs
- `GET /{device_id}/idle-config`
- `POST /{device_id}/idle-config`  
  Body: `{ "idle_current_threshold": 5.0 }`
- `GET /{device_id}/current-state`
- `GET /{device_id}/idle-stats`

---

## 2) Data Service (`/api/v1/data`)
Base: `http://localhost:8081/api/v1/data`

### Health / Root
- `GET /` (service info)
- `GET /health`

### Telemetry Read APIs
- `GET /telemetry/{device_id}`  
  Query: `start_time?`, `end_time?`, `fields?` (comma list), `aggregate?`, `interval?`, `limit<=10000`
- `GET /stats/{device_id}`  
  Query: `start_time?`, `end_time?`
- `POST /query`  
  Body: telemetry query object (`device_id`, range, fields, aggregate, interval, limit)

### WebSocket APIs
- `WS /ws/telemetry/{device_id}` (live telemetry stream)
- `GET /ws/stats` (websocket connection stats)

---

## 3) Rule Engine Service
Base: `http://localhost:8002/api/v1`

### Health
- `GET /health`
- `GET /ready`

### Rules (`/rules`)
- `GET /rules`  
  Query: `tenant_id?`, `status?`, `device_id?`, `page`, `page_size`
- `POST /rules`  
  Supports both:
  - Threshold rule: `rule_type=threshold`, `property`, `condition`, `threshold`
  - Time rule: `rule_type=time_based`, `time_window_start`, `time_window_end`, `timezone` (IST default)
  Common fields: `rule_name`, `scope`, `device_ids`, `notification_channels`, `cooldown_mode(interval|no_repeat)`, `cooldown_minutes`
- `GET /rules/{rule_id}`
- `PUT /rules/{rule_id}`
- `PATCH /rules/{rule_id}/status`
- `DELETE /rules/{rule_id}`
- `POST /rules/evaluate`  
  Used by data pipeline to evaluate incoming telemetry.

### Alerts + Activity (`/alerts`)
- `GET /alerts`  
  Query: `tenant_id?`, `device_id?`, `rule_id?`, `status?`, `page`, `page_size`
- `PATCH /alerts/{alert_id}/acknowledge`
- `PATCH /alerts/{alert_id}/resolve`
- `GET /alerts/events` (activity history)
- `GET /alerts/events/unread-count`
- `PATCH /alerts/events/mark-all-read`
- `DELETE /alerts/events`
- `GET /alerts/events/summary` (global cards: active alerts, triggered, cleared, etc.)

---

## 4) Analytics Service (`/api/v1/analytics`)
Base: `http://localhost:8003`

### Health
- `GET /health/live`
- `GET /health/ready`

### Job APIs
- `POST /api/v1/analytics/run`  
  Body (`AnalyticsRequest`): `device_id`, `analysis_type(anomaly|prediction|forecast)`, `model_name`, and either:
  - `dataset_key`, or
  - `start_time + end_time`
- `POST /api/v1/analytics/run-fleet`  
  Body: `device_ids[]`, `start_time`, `end_time`, `analysis_type(anomaly|prediction)`, `model_name?`, `parameters?`
- `GET /api/v1/analytics/status/{job_id}`
- `GET /api/v1/analytics/results/{job_id}`
- `GET /api/v1/analytics/formatted-results/{job_id}` (dashboard-ready payload; fleet contains per-device summaries + child linkage)
- `GET /api/v1/analytics/jobs`  
  Query: `status?`, `device_id?`, `limit`, `offset`

### Metadata
- `GET /api/v1/analytics/models`
- `GET /api/v1/analytics/datasets?device_id=...`
- `GET /api/v1/analytics/retrain-status`

---

## 5) Reporting Service
Base: `http://localhost:8085`

### Health
- `GET /health`
- `GET /ready`

### Energy Reports (`/api/reports/energy`)
- `POST /api/reports/energy/consumption`  
  Body: `{ "device_id": "COMPRESSOR-001|ALL", "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD", "report_name?": "...", "tenant_id": "default" }`

### Comparison Reports
- `POST /api/reports/energy/comparison`
- `POST /api/reports/energy/comparison/`  
  Body (`ComparisonReportRequest`):  
  - machine vs machine: `comparison_type=machine_vs_machine`, `machine_a_id`, `machine_b_id`, `start_date`, `end_date`, `tenant_id`
  - period vs period: `comparison_type=period_vs_period`, `device_id`, `period_a_*`, `period_b_*`, `tenant_id`

### Common Report Ops (`/api/reports`)
- `GET /api/reports/history?tenant_id=...&limit=...&offset=...&report_type?...`
- `GET /api/reports/{report_id}/status?tenant_id=...`
- `GET /api/reports/{report_id}/result?tenant_id=...`
- `GET /api/reports/{report_id}/download?tenant_id=...` (PDF stream)

### Scheduling
- `POST /api/reports/schedules?tenant_id=...`
- `GET /api/reports/schedules?tenant_id=...`
- `DELETE /api/reports/schedules/{schedule_id}?tenant_id=...`

### Settings APIs used across platform (`/api/v1/settings`)
- `GET /api/v1/settings/tariff`
- `POST /api/v1/settings/tariff`  
  Body: `{ "rate": 8.5, "currency": "INR|USD|EUR", "updated_by?" }`
- `GET /api/v1/settings/notifications`
- `POST /api/v1/settings/notifications/email`  
  Body: `{ "email": "user@company.com" }`
- `DELETE /api/v1/settings/notifications/email/{channel_id}`

### Legacy Tariff APIs (still present)
- `POST /api/reports/tariffs/`
- `GET /api/reports/tariffs/{tenant_id}`

---

## 6) Waste Analysis Service (`/api/v1/waste`)
Base: `http://localhost:8087`

### Health
- `GET /health`
- `GET /ready`

### Waste Job APIs
- `POST /api/v1/waste/analysis/run`  
  Body:
  - `job_name?`
  - `scope`: `all|selected`
  - `device_ids?` (required if `scope=selected`)
  - `start_date`, `end_date`
  - `granularity`: `daily|weekly|monthly`
- `GET /api/v1/waste/analysis/{job_id}/status`
- `GET /api/v1/waste/analysis/{job_id}/result`
- `GET /api/v1/waste/analysis/{job_id}/download` (returns presigned URL JSON)
- `GET /api/v1/waste/analysis/history?limit=20&offset=0`

---

## UI Team Notes (Important)

- Use status polling for async modules:
  - Analytics: poll `/status/{job_id}` every ~3s
  - Reports: poll `/api/reports/{id}/status`
  - Waste: poll `/analysis/{job_id}/status` every ~3s
- Download behavior:
  - Reporting: direct PDF stream endpoint
  - Waste: first call download endpoint, then open returned `download_url`
- Use pagination params wherever available (`page/page_size` or `limit/offset`).
- Always handle structured errors:
  - `VALIDATION_ERROR`, `NOT_FOUND`, `INTERNAL_ERROR`, `QUALITY_GATE_FAILED`, etc.
- Display timestamps in IST on UI (backend stores/transmits UTC in many paths).
- Never assume missing numeric values are zero; show `N/A`/`—` when null.

---

## Recommended Integration Order for New UI

1. Device list + detail + health/uptime/idle cards  
2. Rules + alerts + activity bell  
3. Analytics (single + fleet + drilldown)  
4. Energy reports  
5. Waste analysis  
6. Settings (tariff + notification channels)

