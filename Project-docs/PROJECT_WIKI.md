# FactoryOPS Cittagent Obeya Project Wiki

## 1. Project Overview

**Project name**

`FactoryOPS-Cittagent-Obeya-main`

**Purpose**

This repository is an industrial energy-intelligence platform for factory operations. It combines telemetry ingestion, device state projection, energy accounting, rule-based alerts, reporting, waste analysis, ML analytics, and an LLM-powered copilot into a Docker-orchestrated microservice system with both web and mobile frontends.

**Problem it solves**

The platform is designed to answer operational questions such as:

- Which machines are running, idle, unloaded, or stale right now?
- How much energy and loss is being consumed today and this month?
- Which rules fired, what alerts are active, and what actions were taken?
- Which devices have poor health, low uptime, or overconsumption?
- How can operators export, analyze, and explain plant performance?

**High-level stack**

- Python 3.11 services built mostly with `FastAPI`
- MySQL 8.0 as the primary transactional database
- InfluxDB 2.7 for time-series telemetry
- Redis 7 for analytics queueing and stream-style coordination
- MinIO for object storage and artifact persistence
- Next.js 16 + React 19 for the web frontend
- Expo / React Native for the mobile client
- Docker Compose for local orchestration
- Alembic for Python-service schema migrations
- SQLAlchemy async + `aiomysql` / `PyMySQL` for MySQL access

**Environment / runtimes**

- Python: `3.11` across backend services
- Node.js: `20-alpine` in `ui-web`
- React: `19.x`
- Next.js: `16.1.6`
- Expo: `54`
- MySQL: `8.0`
- InfluxDB: `2.7-alpine`
- Redis: `7-alpine`
- EMQX: `5.3.0`

**Deployment target**

Primary deployment model in this repo is Docker Compose on a Docker-capable host. The project is not wired for Vercel/Railway/serverless deployment. The service startup model assumes containerized local networking and service names such as `device-service`, `data-service`, and `reporting-service`.

**Repo type**

This is a monorepo containing:

- `services/device-service`
- `services/data-service`
- `services/energy-service`
- `services/rule-engine-service`
- `services/reporting-service`
- `services/waste-analysis-service`
- `services/analytics-service`
- `services/data-export-service`
- `services/copilot-service`
- `ui-web`
- `shivex-mobile`
- `tools/device-simulator`
- `tests` for cross-service end-to-end verification

## 2. Directory Structure

Below is the annotated repo tree at a practical, service-level depth. Generated folders are marked explicitly.

```text
/
├── Project-docs/                     # Product and firmware documentation
│   └── Firmware/                     # Firmware-related reference material
├── db/                               # Database helper assets
├── init-scripts/                     # Database/bootstrap SQL for containers
│   └── mysql/                        # MySQL init scripts, users, grants, bootstrap schema
├── monitoring/                       # Prometheus / Grafana / Alertmanager config
│   ├── alertmanager/                 # Alertmanager config source
│   ├── grafana/                      # Grafana provisioning, dashboards
│   └── prometheus/                   # Prometheus scrape and alert rules
├── scripts/                          # Repo-level helper scripts
├── services/                         # Python microservices
│   ├── analytics-service/            # ML analytics API + worker runtime
│   │   ├── alembic/                  # Analytics schema migrations
│   │   ├── scripts/                  # Startup / migration guard scripts
│   │   ├── src/                      # Analytics source code
│   │   │   ├── api/                  # FastAPI route modules
│   │   │   ├── config/               # Settings and logging config
│   │   │   ├── infrastructure/       # DB, Redis, S3 and persistence adapters
│   │   │   ├── models/               # SQLAlchemy models / domain models
│   │   │   ├── services/             # ML orchestration and result formatting
│   │   │   ├── utils/                # Utility functions
│   │   │   └── workers/              # Queue workers and background execution
│   │   └── tests/                    # Unit + integration tests
│   ├── copilot-service/              # LLM copilot API and SQL-safe query engine
│   │   ├── src/
│   │   │   ├── ai/                   # LLM orchestration and reasoning composer
│   │   │   ├── api/                  # Chat API router
│   │   │   ├── db/                   # Query engine and DB execution helpers
│   │   │   ├── integrations/         # Model-provider integrations
│   │   │   ├── intent/               # Intent routing logic
│   │   │   ├── response/             # Response shaping and UX formatting
│   │   │   ├── templates/            # Quick questions / SQL prompt templates
│   │   │   └── utils/                # SQL guard and utilities
│   │   └── tests/                    # Copilot regression tests
│   ├── data-export-service/          # Continuous export worker and export trigger API
│   ├── data-service/                 # Telemetry ingestion, Influx, MQTT, outbox relay
│   │   ├── alembic/                  # Outbox / reconciliation migrations
│   │   ├── src/
│   │   │   ├── api/                  # REST + websocket route setup
│   │   │   ├── config/               # Settings
│   │   │   ├── handlers/             # MQTT / request handlers
│   │   │   ├── models/               # SQLAlchemy models
│   │   │   ├── repositories/         # Influx/MySQL persistence repositories
│   │   │   ├── services/             # Telemetry, DLQ, outbox, reconciliation
│   │   │   └── utils/                # Logging, circuit breakers, helpers
│   │   └── tests/                    # Outbox, batching, tag-cardinality, backpressure tests
│   ├── device-service/               # Device CRUD, live state, dashboard, fleet stream
│   │   ├── alembic/                  # Device schema migrations
│   │   ├── app/
│   │   │   ├── api/                  # Device and settings routes
│   │   │   ├── models/               # Device SQLAlchemy models
│   │   │   ├── repositories/         # Device data access
│   │   │   ├── schemas/              # Pydantic request/response schemas
│   │   │   ├── services/             # Dashboard, live projection, property sync, idle logic
│   │   │   └── tasks/                # Snapshot migration task
│   │   ├── scripts/                  # Migration guard
│   │   └── tests/                    # Projection, optimistic locking, DNS health, live-update tests
│   ├── energy-service/               # Energy summary, loss calculations, live sync
│   │   ├── alembic/                  # Energy schema migrations
│   │   ├── app/
│   │   │   ├── api/                  # Energy REST routes
│   │   │   ├── services/             # Energy engine and broadcaster
│   │   │   └── utils/                # Circuit breaker
│   │   └── scripts/                  # Migration guard
│   ├── reporting-service/            # Report generation, schedules, tariffs, notifications
│   │   ├── alembic/                  # Reporting schema migrations
│   │   ├── scripts/                  # Migration guard
│   │   └── src/
│   │       ├── handlers/             # Report and settings routes
│   │       ├── models/               # Report SQLAlchemy models
│   │       ├── pdf/                  # PDF templates/render helpers
│   │       ├── repositories/         # DB and storage access
│   │       ├── schemas/              # Pydantic response models
│   │       ├── services/             # Report generation logic
│   │       ├── storage/              # S3 / MinIO access
│   │       ├── tasks/                # Scheduled jobs
│   │       └── utils/                # Shared helpers
│   ├── rule-engine-service/          # Rules, alerts, activity events, notifications
│   │   ├── alembic/                  # Rule/alert schema migrations
│   │   ├── app/
│   │   │   ├── api/                  # Rule and alert routes
│   │   │   ├── models/               # Rule, alert, activity-event models
│   │   │   ├── notifications/        # Email notification senders
│   │   │   ├── repositories/         # Persistence layer
│   │   │   ├── schemas/              # Pydantic contracts
│   │   │   ├── services/             # Rule evaluation and alert lifecycle logic
│   │   │   └── utils/                # Helper utilities
│   │   └── scripts/                  # Migration guard
│   └── waste-analysis-service/       # Waste jobs, report generation, downloads
│       ├── alembic/                  # Waste-analysis schema migrations
│       ├── scripts/                  # Migration guard
│       ├── src/
│       │   ├── handlers/             # Waste-analysis REST routes
│       │   ├── models/               # Job and result models
│       │   ├── pdf/                  # Report rendering
│       │   ├── repositories/         # Persistence layer
│       │   ├── schemas/              # Pydantic models
│       │   ├── services/             # Waste calculation business logic
│       │   ├── storage/              # S3 / MinIO storage
│       │   ├── tasks/                # Job scheduling/background work
│       │   └── utils/                # Helpers
├── shivex-mobile/                    # Expo mobile app
│   ├── .expo/                        # Generated Expo state (generated)
│   ├── app/                          # Expo router screens
│   ├── assets/                       # Images, fonts, icons
│   ├── node_modules/                 # Installed packages (generated)
│   └── src/                          # Mobile API clients, store, constants, hooks
├── tests/                            # Cross-service pytest E2E and helpers
│   ├── e2e/                          # Workflow/system tests across services
│   ├── firmware/                     # Firmware verification docs + payloads
│   └── helpers/                      # API/DB/simulator helper clients
├── tools/                            # Developer and simulator tools
│   └── device-simulator/             # Telemetry simulator
├── ui-web/                           # Next.js web application
│   ├── .next/                        # Next build output (generated)
│   ├── app/                          # App Router pages
│   ├── components/                   # Shared UI components
│   ├── lib/                          # API clients, polling, formatters, utilities
│   ├── node_modules/                 # Installed packages (generated)
│   ├── public/                       # Static assets
│   ├── test-results/                 # Playwright artifacts (generated)
│   └── tests/                        # Frontend E2E tests
└── docker-compose.yml                # Full local topology
```

## 3. Architecture Overview

**System style**

The project is a Docker Compose microservice system with separate bounded services and a single shared MySQL database. It is not a monolith and not serverless.

**Major runtime components**

- `ui-web`: Next.js operator console
- `shivex-mobile`: Expo mobile interface
- `device-service`: source of truth for device registry, live projections, fleet dashboard, snapshots
- `data-service`: MQTT ingestion, InfluxDB writes, DLQ, outbox relay, reconciliation
- `energy-service`: energy/loss calculations and device live-state energy projections
- `rule-engine-service`: rules, alerts, activity events, notification workflows
- `reporting-service`: energy/comparison reports, schedules, tariff and notification settings
- `waste-analysis-service`: waste-analysis job orchestration and downloadable reports
- `analytics-service`: ML job submission API plus worker role for heavy model execution
- `data-export-service`: continuous and on-demand export pipeline
- `copilot-service`: SQL-guarded analytics copilot over read-only MySQL access

**Inter-service communication**

- REST over internal Docker networking
- SSE/event-stream from `device-service` to `ui-web` fleet screen
- MQTT from simulator / devices into `data-service` via EMQX
- Redis for analytics queueing and service coordination
- MySQL shared DB for transactional state
- InfluxDB for telemetry history
- MinIO for exported artifacts and snapshot payloads

**Caching / state**

- `ui-web`: client-side component state, polling, sessionStorage chat persistence
- `shivex-mobile`: React Query cache and Zustand store
- `device-service`: dashboard snapshots and fleet stream broadcaster
- `reporting-service`: tariff/settings persistence and derived artifacts
- `data-service`: outbox, DLQ, websocket subscribers, circuit breaker metrics

**Third-party / infrastructure integrations**

- InfluxDB
- MySQL
- Redis
- MinIO / S3-compatible storage
- EMQX MQTT broker
- OpenAI / Groq / Gemini model providers in `copilot-service`
- WeasyPrint / Matplotlib for report rendering

## 4. Database & Data Layer

**Databases**

- MySQL `ai_factoryops`: primary relational store for most services
- InfluxDB bucket `telemetry`: raw time-series telemetry
- MinIO buckets for datasets, exports, and dashboard snapshots

**ORM / access layers**

- SQLAlchemy async for Python services
- Alembic for MySQL schema evolution
- Raw Flux queries via `influxdb-client`
- `aioboto3` / `boto3` for object storage

**Primary MySQL schema areas by service**

`device-service`

- `devices`
  - business key `device_id`
  - descriptive fields: `device_name`, `device_type`, `manufacturer`, `model`, `location`
  - telemetry source fields: `data_source_type`, `phase_type`
  - tenancy and metadata: `tenant_id`, `metadata_json`
  - timestamps: `created_at`, `updated_at`, `deleted_at`
- `device_properties`
  - per-device parameter metadata and dashboard widget config backing
- `device_shifts`
  - shift windows, day-of-week, maintenance break minutes, active flag
- `device_health_configs`
  - parameter thresholds and weights for health score
- `device_live_state`
  - projected live runtime fields
  - includes `version` for optimistic locking
  - includes `runtime_status`, `load_state`, `health_score`, `uptime_percentage`, timestamps
- `dashboard_snapshots`
  - `snapshot_key`
  - `payload_json` nullable for backward compatibility
  - `s3_key`
  - `storage_backend` enum `mysql|minio`
  - `expires_at`
- `device_performance_trends`
  - trend buckets over health and uptime
- `idle_running_configs` / related idle log tables
- waste-config tables and dashboard widget setting tables from later migrations

`data-service`

- `dlq_messages`
  - failed telemetry syncs / retries
- `telemetry_outbox`
  - `id`
  - `device_id`
  - `telemetry_json`
  - `target`
  - `status`
  - `retry_count`
  - `max_retries`
  - `created_at`
  - `last_attempted_at`
  - `delivered_at`
  - `error_message`
  - indexes on `(status, created_at)` and `(device_id, status)`
- `reconciliation_log`
  - `id`, `device_id`, `checked_at`, `influx_ts`, `mysql_ts`, `drift_seconds`, `action_taken`

`energy-service`

- energy aggregation / live-state write support tables from `0001_create_energy_tables.py`
- energy-service also writes fields such as `today_energy_kwh`, `today_idle_kwh` into `device_live_state`

`rule-engine-service`

- `rules`
  - trigger configuration, thresholds, time windows, cooldown config
- `alerts`
  - active/acknowledged/resolved lifecycle
- `activity_events`
  - operator-visible event log
- cooldown-unit and indexing migrations improve rule execution lookup patterns

`reporting-service`

- report job tables
- schedule tables
- tariff/settings tables
- notification channel tables
- indexes added in `004_add_reporting_indexes.py`

`waste-analysis-service`

- waste job and result tables
- quality-gate fields
- waste-category fields
- job indexes

`analytics-service`

- initial analytics schema
- queue and artifact tables
- worker heartbeat tables
- accuracy-evaluation tables
- artifact payload widened to `LONGBLOB`

**Enum / discrete value examples**

- `device_live_state.storage_backend`: `mysql`, `minio`
- outbox `target`: `device-service`, `energy-service`
- outbox `status`: `pending`, `delivered`, `failed`, `dead`
- analytics app role: `api`, `worker`
- load-state values in frontend/backends: `running`, `idle`, `unloaded`, `unknown`
- runtime-status values: typically `running`, `stopped`

**Migration order overview**

- `analytics-service`: `0001_initial_schema` → `0002_queue_and_artifact_tables` → `0003_worker_heartbeat_and_accuracy_tables` → `0004_artifact_payload_longblob`
- `data-service`: `20260324_0001_add_telemetry_outbox_and_reconciliation_log`
- `device-service`: `0001_initial_schema` plus successive feature migrations such as `add_phase_type`, `add_data_source_type`, `add_device_live_state_projection`, `add_device_performance_trends`, `add_dashboard_snapshots`, `add_dashboard_snapshot_minio_storage`, `shft_ovlp_dedup_v1`, `20260324_0003_backfill_legacy_tenant_ids`
- `energy-service`: `0001_create_energy_tables`
- `reporting-service`: `001_initial` → `002_add_last_result_url` → `003_settings_tables` → `004_add_reporting_indexes`
- `rule-engine-service`: `001_initial` → `002_activity_events` → `003_rules_v2_time_based_and_cooldown` → `004_add_rule_alert_indexes` → `005_add_rule_cooldown_units` → `20260324_0006_backfill_legacy_tenant_ids`
- `waste-analysis-service`: `001_initial` → `002_quality_gate_fields` → `003_add_waste_job_indexes` → `004_add_wastage_categories`

**Connection pooling**

- Python services use SQLAlchemy async engines over `aiomysql`
- InfluxDB clients are long-lived service objects
- Redis connections are long-lived in analytics and broadcasters
- MinIO/S3 clients are instantiated in service/storage layers

## 5. Data Flow Diagrams

**Device onboarding**

`[Operator creates device] -> [ui-web /devices] -> [device-service POST /api/v1/devices] -> [DeviceService.create_device] -> [MySQL devices INSERT] -> [Device response]`

**Telemetry ingestion**

`[Simulator/real device publishes MQTT] -> [EMQX] -> [data-service MQTTHandler] -> [TelemetryService] -> [InfluxDB write + MySQL outbox enqueue] -> [outbox relay] -> [device-service /live-update + energy-service /live-update] -> [device_live_state updates]`

**Fleet dashboard**

`[Open /machines] -> [ui-web machines page] -> [device-service GET /dashboard/fleet-snapshot + /dashboard/summary] -> [LiveDashboardService] -> [device_live_state/devices queries + downstream energy lookup] -> [fleet cards + KPI cards]`

**Fleet streaming**

`[Live update lands] -> [device-service LiveProjectionService] -> [fleet stream broadcaster] -> [SSE /dashboard/fleet-stream] -> [ui-web partial update merge]`

**Rules and alerts**

`[Telemetry synced] -> [rule-engine-service evaluation or triggered rule path] -> [alerts/activity_events tables] -> [ui-web rules + machines alert history]`

**Analytics jobs**

`[Operator submits analytics request] -> [analytics-service POST /api/v1/analytics/... ] -> [Redis/InMemory job queue] -> [analytics worker] -> [ML inference/training + artifact persistence] -> [job status/result endpoints]`

**Copilot query**

`[Operator asks question] -> [ui-web /copilot] -> [copilot-service /api/v1/copilot/chat] -> [intent router + SQLGuard + read-only DB engine] -> [MySQL SELECT] -> [reasoned answer + chart/table payload]`

**Waste analysis**

`[Operator runs waste report] -> [waste-analysis-service POST /analysis/run] -> [job persistence + background work] -> [report artifact in MinIO] -> [status/result/download endpoints]`

**Reporting**

`[Operator schedules or runs report] -> [reporting-service] -> [Influx/MySQL fetch + render PDF/CSV] -> [object storage + result URL] -> [download endpoint]`

**Authentication/session**

There is no implemented backend auth/session system in the current codebase. UI routes are not guarded by server auth. The mobile app only has a local role-selection gate using Zustand and Expo secure-store style client-side state.

## 6. API Reference

This is the route inventory derived from route decorators currently present.

**device-service**

- `GET /health`
- `GET /ready`
- `GET /metrics`
- `GET /api/v1/devices`
- `POST /api/v1/devices`
- `GET /api/v1/devices/common-properties`
- `GET /api/v1/devices/dashboard/summary`
- `GET /api/v1/devices/dashboard/fleet-snapshot`
- `GET /api/v1/devices/dashboard/fleet-stream`
- `GET /api/v1/devices/{device_id}/dashboard-bootstrap`
- `GET /api/v1/devices/dashboard/today-loss-breakdown`
- `GET /api/v1/devices/calendar/monthly-energy`
- CRUD and config routes for shifts, health config, widget config, idle config, waste config, uptime, current-state, live-update, per-device dashboards and lifecycle operations in [devices.py](/Users/vedanthshetty/Desktop/Obeyaa-Deployed/FactoryOPS-Cittagent-Obeya-main/services/device-service/app/api/v1/devices.py)
- settings routes in [settings.py](/Users/vedanthshetty/Desktop/Obeyaa-Deployed/FactoryOPS-Cittagent-Obeya-main/services/device-service/app/api/v1/settings.py)

**data-service**

- `GET /`
- `GET /health`
- telemetry/stat routes in [routes.py](/Users/vedanthshetty/Desktop/Obeyaa-Deployed/FactoryOPS-Cittagent-Obeya-main/services/data-service/src/api/routes.py)
- extra telemetry routes in [telemetry.py](/Users/vedanthshetty/Desktop/Obeyaa-Deployed/FactoryOPS-Cittagent-Obeya-main/services/data-service/src/api/telemetry.py)
- websocket stats route `GET /ws/stats`

**energy-service**

- `GET /health`
- router-prefixed routes in [routes.py](/Users/vedanthshetty/Desktop/Obeyaa-Deployed/FactoryOPS-Cittagent-Obeya-main/services/energy-service/app/api/routes.py):
  - `GET /health`
  - `POST /live-update`
  - `POST /device-lifecycle/{device_id}`
  - `GET /summary`
  - `GET /today-loss-breakdown`
  - `GET /calendar/monthly`
  - `GET /device/{device_id}/range`

**rule-engine-service**

- `GET /health`
- `GET /ready`
- rules CRUD + archive/trigger routes in [rules.py](/Users/vedanthshetty/Desktop/Obeyaa-Deployed/FactoryOPS-Cittagent-Obeya-main/services/rule-engine-service/app/api/v1/rules.py)
- alert list/ack/resolve/events/unread/clear routes in [alerts.py](/Users/vedanthshetty/Desktop/Obeyaa-Deployed/FactoryOPS-Cittagent-Obeya-main/services/rule-engine-service/app/api/v1/alerts.py)

**reporting-service**

- `GET /health`
- `GET /ready`
- energy report route `POST /consumption`
- comparison report routes `POST /` and `POST ""`
- common report routes:
  - `GET /history`
  - `POST /schedules`
  - `GET /schedules`
  - `DELETE /schedules/{schedule_id}`
  - `GET /{report_id}/status`
  - `GET /{report_id}/result`
  - `GET /{report_id}/download`
- tariff/settings routes:
  - `GET /tariff`
  - `POST /tariff`
  - `GET /notifications`
  - `POST /notifications/email`
  - `DELETE /notifications/email/{channel_id}`
  - legacy tenant tariff routes in [tariffs.py](/Users/vedanthshetty/Desktop/Obeyaa-Deployed/FactoryOPS-Cittagent-Obeya-main/services/reporting-service/src/handlers/tariffs.py)

**waste-analysis-service**

- `GET /health`
- `GET /ready`
- `POST /analysis/run`
- `GET /analysis/{job_id}/status`
- `GET /analysis/{job_id}/result`
- `GET /analysis/{job_id}/download`
- `GET /analysis/history`

**analytics-service**

- `GET /health/live`
- `GET /health/ready`
- multiple analytics job and ops routes in [analytics.py](/Users/vedanthshetty/Desktop/Obeyaa-Deployed/FactoryOPS-Cittagent-Obeya-main/services/analytics-service/src/api/routes/analytics.py):
  - job submission
  - labels/failure-events
  - accuracy/evaluate
  - accuracy/latest
  - datasets
  - retrain-status
  - formatted-results/{job_id}
  - ops/queue

**data-export-service**

- `GET /health`
- `GET /ready`
- `POST /api/v1/exports/run`
- `GET /api/v1/exports/status/{device_id}`

**copilot-service**

- `GET /health`
- `GET /ready`
- `POST /api/v1/copilot/chat`

**WebSockets / streams**

- `device-service` fleet stream via SSE: `/api/v1/devices/dashboard/fleet-stream`
- `data-service` websocket router under `/ws/...`

**Auth requirement**

Current routes are effectively unauthenticated in this codebase.

## 7. Authentication & Authorization

**Backend auth**

Not implemented as a real production auth layer in the current backend services.

**Frontend auth**

- `ui-web`: no login system, no token storage, no middleware-based auth guard
- `shivex-mobile`: local role selection and persisted client role via store, not a backend-backed auth model

**Roles / permissions**

- Mobile role concept exists in `shivex-mobile/src/store/user`
- No cross-service enforced RBAC in the backend APIs

**Session expiry / refresh**

Not implemented.

## 8. State Management (Frontend)

**ui-web**

- Plain React state and hooks
- Custom polling via [useAdaptivePolling.ts](/Users/vedanthshetty/Desktop/Obeyaa-Deployed/FactoryOPS-Cittagent-Obeya-main/ui-web/lib/useAdaptivePolling.ts)
- SSE for fleet updates
- `sessionStorage` for copilot message history
- No React Query / SWR / Redux in the web app

**shivex-mobile**

- React Query for server-state caching
- Zustand for persistent user role and lightweight app state

## 9. Key Business Logic

**Live device projection**

- `device-service` converts telemetry into `device_live_state`
- optimistic locking on `version` protects concurrent writers
- stale lower-version partial stream updates are now rejected in the web client

**Cross-database consistency**

- `data-service` writes telemetry to InfluxDB and MySQL outbox
- outbox relay delivers to `device-service` and `energy-service`
- DLQ captures permanently failed deliveries

**Energy / loss calculations**

- `energy-service` calculates today/month energy, idle, off-hours, and overconsumption losses
- `device-service` consumes energy summaries for dashboard widgets

**Health score**

- parameter thresholds + weights configured per device
- weighted health score derived from latest telemetry fields

**Rules**

- rule engine supports thresholds, time-based rules, cooldowns, activity events, acknowledgements, and clear/resolution flows

**Reports**

- reporting and waste-analysis services generate downloadable artifacts and history records

**Analytics**

- split API/worker role via `APP_ROLE`
- API submits jobs
- worker performs model execution, retraining, and artifact generation

**Copilot**

- quick-question templates
- intent router
- SQL guard that blocks unsafe statements
- tenant filter injection and read-only DB engine

**Scheduled/background tasks**

- `device-service`: performance trends scheduler, dashboard snapshot scheduler, live projection reconciler, optional snapshot migration task
- `data-service`: MQTT consumer, outbox relay, DLQ retry, reconciliation job
- `analytics-service`: worker queue processor, retrainer
- `reporting-service` and `waste-analysis-service`: scheduled/report jobs
- `data-export-service`: continuous export worker

## 10. Environment Variables

The authoritative sources are the service settings modules, [docker-compose.yml](/Users/vedanthshetty/Desktop/Obeyaa-Deployed/FactoryOPS-Cittagent-Obeya-main/docker-compose.yml), and the checked-in env examples. This section intentionally lists variable names, meaning, and safe example values, but does not repeat real secrets from the local `.env`.

**Root / shared infrastructure**

- `MYSQL_ROOT_PASSWORD` — MySQL root password for container bootstrap — local/dev required — example `rootpassword`
- `MYSQL_USER` — app MySQL user — local/dev required — example `energy`
- `MYSQL_PASSWORD` — app MySQL password — local/dev required — example `energy`
- `MYSQL_HOST` — MySQL host used by some scripts/services — optional when `DATABASE_URL` is present — example `mysql`
- `MYSQL_PORT` — MySQL port — optional defaulted in many services — example `3306`
- `DB_DEVICE` / `DB_RULE` / `DB_ANALYTICS` / `DB_EXPORT` / `DB_REPORTING` — legacy bootstrap database names from [db/bootstrap.sql](/Users/vedanthshetty/Desktop/Obeyaa-Deployed/FactoryOPS-Cittagent-Obeya-main/db/bootstrap.sql) and root `.env` — optional in current single-DB runtime — example `energy_device_db`
- `INFLUXDB_URL` — InfluxDB base URL — required for telemetry/report/waste/export flows — example `http://influxdb:8086`
- `INFLUXDB_TOKEN` — InfluxDB API token — required when using InfluxDB — example `energy-token`
- `INFLUXDB_ORG` — InfluxDB organization — required with token auth — example `energy-org`
- `INFLUXDB_BUCKET` — InfluxDB bucket name — required for telemetry reads/writes — example `telemetry`
- `INFLUXDB_RETENTION_DAYS` — desired retention for telemetry bucket — optional — example `365`
- `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` — MinIO bootstrap credentials — required for local object storage — example `minio` / `minio123`
- `MINIO_ENDPOINT` — internal MinIO endpoint — required for services that write objects — example `minio:9000`
- `MINIO_EXTERNAL_URL` — externally reachable MinIO URL for presigned/download links — optional but important in production — example `http://localhost:9000`
- `S3_BUCKET` — generic dataset bucket name from root `.env` and export service examples — optional alias to service-specific bucket vars — example `energy-platform-datasets`
- `AWS_REGION` / `AWS_ENDPOINT_URL` / `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` — S3-compatible object-storage config — required when not using service defaults — example `us-east-1`
- `MQTT_BROKER_HOST` / `MQTT_BROKER_PORT` / `MQTT_WS_PORT` — EMQX broker host/ports — required for data ingestion and simulator routing — example `emqx`, `1883`, `8083`
- `ENVIRONMENT` — shared environment label — optional/defaulted — example `development`
- `LOG_LEVEL` — log verbosity — optional/defaulted — example `INFO`
- `PLATFORM_TIMEZONE` — reporting/waste/device timezone convention — optional/defaulted — example `Asia/Kolkata`
- `EXTERNAL_URL` / `API_EXTERNAL_URL` — root deployment URLs from `.env` — optional — example `http://localhost:3000`
- `EMAIL_ENABLED` / `SMTP_SERVER` / `EMAIL_SENDER` / `EMAIL_PASSWORD` — root SMTP-style settings used by notification paths — production-only if email is enabled — example `smtp.gmail.com`
- `AI_PROVIDER` / `GROQ_API_KEY` / `GEMINI_API_KEY` / `OPENAI_API_KEY` / `COPILOT_DB_PASSWORD` — root Copilot provider and DB-reader settings — production-only for Copilot — example provider `groq`

**device-service**

- `APP_NAME` — service name — optional defaulted — example `device-service`
- `APP_VERSION` — service version label — optional defaulted — example `1.0.0`
- `ENVIRONMENT` — service environment — optional defaulted — example `development`
- `LOG_LEVEL` — service log level — optional defaulted — example `INFO`
- `HOST` / `PORT` — HTTP bind settings — optional defaulted — example `0.0.0.0`, `8000`
- `DATABASE_URL` — async SQLAlchemy DSN — required — example `mysql+aiomysql://energy:energy@mysql:3306/ai_factoryops`
- `DATA_SERVICE_BASE_URL` — data-service base URL — required for telemetry lookups and bootstrap payloads — example `http://data-service:8081`
- `RULE_ENGINE_SERVICE_BASE_URL` — rule-engine base URL — required for alert summaries — example `http://rule-engine-service:8002`
- `REPORTING_SERVICE_BASE_URL` — reporting base URL — required for tariff/cost lookups — example `http://reporting-service:8085`
- `ENERGY_SERVICE_BASE_URL` — energy-service base URL — required for loss and calendar APIs — example `http://energy-service:8010`
- `BOOTSTRAP_DEMO_DEVICES` — optionally seed demo compressors at startup — optional — example `false`
- `PERFORMANCE_TRENDS_ENABLED` / `PERFORMANCE_TRENDS_CRON_ENABLED` / `PERFORMANCE_TRENDS_INTERVAL_MINUTES` / `PERFORMANCE_TRENDS_TIMEZONE` — scheduler controls for materialized health/uptime trends — optional — example `true`, `5`, `Asia/Kolkata`
- `DASHBOARD_SNAPSHOT_ENABLED` / `DASHBOARD_SNAPSHOT_INTERVAL_SECONDS` / `DASHBOARD_ENERGY_REFRESH_SECONDS` / `DASHBOARD_SNAPSHOT_STALE_AFTER_SECONDS` / `DASHBOARD_SCHEDULER_MAX_DRIFT_SECONDS` — dashboard snapshot lifecycle controls — optional — example `true`, `5`, `15`
- `DASHBOARD_STREAM_HEARTBEAT_SECONDS` / `DASHBOARD_STREAM_QUEUE_SIZE` / `DASHBOARD_STREAM_SEND_TIMEOUT_SECONDS` — SSE fleet-stream tuning — optional — example `5`, `64`, `10`
- `DASHBOARD_RECONCILE_INTERVAL_SECONDS` — live projection repair interval — optional — example `600`
- `REDIS_URL` — Redis connection for cross-instance fleet stream fanout — optional in single-instance, recommended in prod — example `redis://redis:6379/0`
- `FLEET_STREAM_REDIS_CHANNEL` — Redis pub/sub channel name for fleet updates — optional — example `factoryops:fleet_stream:v1`
- `SNAPSHOT_STORAGE_BACKEND` — dashboard snapshot backend selector — optional — example `minio`
- `SNAPSHOT_MINIO_BUCKET` / `SNAPSHOT_MINIO_ENDPOINT` / `SNAPSHOT_MINIO_ACCESS_KEY` / `SNAPSHOT_MINIO_SECRET_KEY` / `SNAPSHOT_MINIO_SECURE` — snapshot object-storage config — required when `SNAPSHOT_STORAGE_BACKEND=minio` — example bucket `dashboard-snapshots`
- `MIGRATE_SNAPSHOTS_TO_MINIO` — one-off startup migration toggle for existing MySQL snapshot payloads — optional — example `false`

**data-service**

- `HOST` / `PORT` / `LOG_LEVEL` / `ENVIRONMENT` — HTTP/service runtime config — optional/defaulted — example `0.0.0.0`, `8081`, `INFO`, `development`
- `MQTT_BROKER_HOST` / `MQTT_BROKER_PORT` / `MQTT_USERNAME` / `MQTT_PASSWORD` / `MQTT_TOPIC` / `MQTT_QOS` / `MQTT_RECONNECT_INTERVAL` / `MQTT_MAX_RECONNECT_ATTEMPTS` / `MQTT_KEEPALIVE` — broker connection, topic, and reconnect behavior — required for ingestion — example topic `devices/+/telemetry`
- `INFLUXDB_URL` / `INFLUXDB_TOKEN` / `INFLUXDB_ORG` / `INFLUXDB_BUCKET` / `INFLUXDB_TIMEOUT` — Influx client config — required — example `telemetry`
- `INFLUX_BATCH_SIZE` / `INFLUX_FLUSH_INTERVAL_MS` / `INFLUX_MAX_RETRIES` — write batching behavior — optional — example `100`, `1000`, `3`
- `DEVICE_SERVICE_URL` / `DEVICE_SERVICE_TIMEOUT` / `DEVICE_SERVICE_MAX_RETRIES` — downstream heartbeat/property sync target — required for full platform mode — example `http://device-service:8000`
- `DEVICE_SYNC_ENABLED` / `DEVICE_SYNC_WORKERS` / `DEVICE_SYNC_QUEUE_MAXSIZE` / `DEVICE_SYNC_MAX_RETRIES` / `DEVICE_SYNC_RETRY_BACKOFF_SEC` / `DEVICE_SYNC_RETRY_BACKOFF_MAX_SEC` — async device-sync worker tuning — optional — example `true`, `2`, `5000`
- `ENERGY_SERVICE_URL` / `ENERGY_SYNC_ENABLED` — downstream energy projection sync target/toggle — optional but enabled in compose — example `http://energy-service:8010`
- `QUEUE_OVERFLOW_LOG_LEVEL` / `QUEUE_DEPTH_CHECK_INTERVAL_SEC` / `QUEUE_DRAIN_TIMEOUT_SEC` — ingestion queue observability and shutdown behavior — optional
- `MYSQL_HOST` / `MYSQL_PORT` / `MYSQL_DATABASE` / `MYSQL_USER` / `MYSQL_PASSWORD` — durable DLQ/outbox MySQL config — required when `DLQ_BACKEND=mysql` — example `ai_factoryops`
- `OUTBOX_POLL_INTERVAL_SEC` / `OUTBOX_BATCH_SIZE` / `OUTBOX_MAX_RETRIES` — outbox relay controls — optional — example `2`, `50`, `5`
- `RECONCILIATION_INTERVAL_SEC` / `RECONCILIATION_DRIFT_WARN_MINUTES` / `RECONCILIATION_DRIFT_RESYNC_MINUTES` — cross-store drift detection settings — optional — example `300`, `10`, `30`
- `CIRCUIT_BREAKER_FAILURE_THRESHOLD` / `CIRCUIT_BREAKER_OPEN_TIMEOUT_SEC` / `CIRCUIT_BREAKER_SUCCESS_THRESHOLD` — downstream circuit breaker tuning — optional
- `RULE_ENGINE_URL` / `RULE_ENGINE_TIMEOUT` / `RULE_ENGINE_MAX_RETRIES` / `RULE_ENGINE_RETRY_DELAY` — rule evaluation target and retry policy — optional but used in compose — example `http://rule-engine-service:8002`
- `DLQ_ENABLED` / `DLQ_BACKEND` / `DLQ_DIRECTORY` / `DLQ_MAX_FILE_SIZE` / `DLQ_MAX_FILES` / `DLQ_RETENTION_DAYS` / `DLQ_FLUSH_BATCH_SIZE` — dead-letter queue backend selection and limits — optional
- `TELEMETRY_SCHEMA_VERSION` / `TELEMETRY_MAX_VOLTAGE` / `TELEMETRY_MIN_VOLTAGE` / `TELEMETRY_MAX_CURRENT` / `TELEMETRY_MIN_CURRENT` / `TELEMETRY_MAX_POWER` / `TELEMETRY_MIN_POWER` / `TELEMETRY_MAX_TEMPERATURE` / `TELEMETRY_MIN_TEMPERATURE` / `TELEMETRY_DEFAULT_LOOKBACK_HOURS` — payload validation and query defaults — optional
- `WS_HEARTBEAT_INTERVAL` / `WS_MAX_CONNECTIONS` — websocket keepalive and scaling limits — optional
- `API_PREFIX` — REST prefix — optional defaulted — example `/api/v1/data`
- `CORS_ORIGINS` — allowed origins — optional defaulted in code to `["*"]`

**energy-service**

- `APP_NAME` / `APP_VERSION` / `ENVIRONMENT` — service metadata — optional
- `DATABASE_URL` — MySQL DSN — required — example `mysql+aiomysql://energy:energy@mysql:3306/ai_factoryops`
- `REDIS_URL` — Redis connection for energy broadcaster — optional in single-instance, enabled in compose
- `ENERGY_STREAM_REDIS_CHANNEL` — energy pub/sub channel — optional — example `factoryops:energy_stream:v1`
- `REPORTING_SERVICE_BASE_URL` or `REPORTING_SERVICE_URL` — tariff/report dependency base URL — optional but used in compose — example `http://reporting-service:8085`
- `DEVICE_SERVICE_BASE_URL` or `DEVICE_SERVICE_URL` — device metadata dependency base URL — optional but used in compose — example `http://device-service:8000`

**rule-engine-service**

- `APP_NAME` / `APP_VERSION` / `ENVIRONMENT` / `LOG_LEVEL` / `HOST` / `PORT` — service runtime metadata — optional/defaulted
- `DATABASE_URL` — MySQL DSN — required
- `EMAIL_ENABLED` — enables notification adapter email behavior — optional — example `true`
- `EMAIL_FROM` / `EMAIL_SMTP_HOST` / `EMAIL_SMTP_PORT` / `EMAIL_SMTP_USERNAME` / `EMAIL_SMTP_PASSWORD` / `EMAIL_SMTP_TLS` — SMTP delivery settings for alert notifications — production-only if email is enabled
- `REPORTING_SERVICE_URL` — settings/tariff integration endpoint — optional — example `http://reporting-service:8085`

**reporting-service**

- `DATABASE_URL` — MySQL DSN — required
- `INFLUXDB_URL` / `INFLUXDB_TOKEN` / `INFLUXDB_ORG` / `INFLUXDB_BUCKET` / `INFLUXDB_MEASUREMENT` — Influx report-read settings — required for actual report generation
- `INFLUX_POWER_FIELD` / `INFLUX_VOLTAGE_FIELD` / `INFLUX_CURRENT_FIELD` / `INFLUX_POWER_FACTOR_FIELD` / `INFLUX_REACTIVE_POWER_FIELD` / `INFLUX_FREQUENCY_FIELD` / `INFLUX_THD_FIELD` — field-name mapping used by report engines — optional/defaulted
- `INFLUX_AGGREGATION_WINDOW` / `INFLUX_MAX_POINTS` — read aggregation limits — optional
- `DEVICE_SERVICE_URL` / `ENERGY_SERVICE_URL` — downstream service dependencies — optional but used in compose
- `DATABASE_POOL_SIZE` / `DATABASE_MAX_OVERFLOW` / `DATABASE_POOL_TIMEOUT` / `DATABASE_POOL_RECYCLE` — SQLAlchemy pool tuning — optional
- `MINIO_ENDPOINT` / `MINIO_EXTERNAL_URL` / `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` / `MINIO_BUCKET` / `MINIO_SECURE` — report artifact storage settings — required for PDF persistence/download
- `PLATFORM_TIMEZONE` — business timezone for reporting windows — optional — example `Asia/Kolkata`
- `DEMAND_WINDOW_MINUTES` — demand calculation interval — optional — example `15`
- `REPORT_JOB_TIMEOUT_SECONDS` — async report timeout guard — optional — example `600`
- `SERVICE_NAME` — service label — optional

**waste-analysis-service**

- `DATABASE_URL` — MySQL DSN — required
- `DATABASE_POOL_SIZE` / `DATABASE_MAX_OVERFLOW` / `DATABASE_POOL_TIMEOUT` / `DATABASE_POOL_RECYCLE` — DB pool tuning — optional
- `INFLUXDB_URL` / `INFLUXDB_TOKEN` / `INFLUXDB_ORG` / `INFLUXDB_BUCKET` / `INFLUXDB_MEASUREMENT` / `INFLUX_AGGREGATION_WINDOW` / `INFLUX_MAX_POINTS` — telemetry read settings — required for actual runs
- `DEVICE_SERVICE_URL` / `REPORTING_SERVICE_URL` / `ENERGY_SERVICE_URL` — remote dependencies for device config, tariff, and loss context — required for full fidelity
- `MINIO_ENDPOINT` / `MINIO_EXTERNAL_URL` / `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` / `MINIO_BUCKET` / `MINIO_SECURE` — waste PDF storage settings — required for downloads
- `PLATFORM_TIMEZONE` — waste calculation timezone — optional — example `Asia/Kolkata`
- `TARIFF_CACHE_TTL_SECONDS` — in-process tariff cache TTL — optional
- `WASTE_STRICT_QUALITY_GATE` — toggles stricter insufficient-data behavior — optional
- `WASTE_JOB_TIMEOUT_SECONDS` — background job timeout — optional
- `WASTE_DEVICE_CONCURRENCY` / `WASTE_DB_BATCH_SIZE` / `WASTE_PDF_MAX_DEVICES` — scale/perf controls — optional

**analytics-service**

- `APP_ENV` / `LOG_LEVEL` / `APP_ROLE` — runtime mode and logging — required in practice because the service hard-fails unless `APP_ROLE` is `api` or `worker` — example `api`
- `API_HOST` / `API_PORT` — API bind settings — optional/defaulted — example `0.0.0.0`, `8000`
- `MYSQL_HOST` / `MYSQL_PORT` / `MYSQL_DATABASE` / `MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_POOL_SIZE` — MySQL config — required — example `ai_factoryops`
- `S3_BUCKET_NAME` / `S3_REGION` / `S3_ENDPOINT_URL` / `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` — dataset/model-artifact storage config — required for export-backed dataset loading
- `DEFAULT_TRAIN_TEST_SPLIT` / `MAX_DATASET_SIZE_MB` / `SUPPORTED_MODELS` — ML/data defaults — optional
- `MAX_CONCURRENT_JOBS` / `JOB_TIMEOUT_SECONDS` / `JOB_LEASE_SECONDS` / `JOB_HEARTBEAT_SECONDS` — job scheduler/worker controls — optional
- `QUEUE_BACKEND` / `REDIS_URL` / `REDIS_STREAM_NAME` / `REDIS_DEAD_LETTER_STREAM` / `REDIS_CONSUMER_GROUP` / `REDIS_CONSUMER_NAME` / `QUEUE_MAX_ATTEMPTS` / `WORKER_HEARTBEAT_TTL_SECONDS` — queue backend config — required for Redis-backed production mode
- `ACCURACY_MIN_LABELED_EVENTS` / `ACCURACY_CERTIFICATION_MIN_PRECISION` / `ACCURACY_CERTIFICATION_MIN_RECALL` — certification thresholds — optional
- `ML_ANALYTICS_V2_ENABLED` / `ML_FORMATTED_RESULTS_ENABLED` / `ML_WEEKLY_RETRAINER_ENABLED` / `ML_FLEET_STRICT_ENABLED` / `ML_DATA_READINESS_GATE_ENABLED` / `ML_REQUIRE_EXACT_DATASET_RANGE` / `ML_MAX_DATASET_ROWS` — feature flags and result policy controls — optional
- `DATA_EXPORT_SERVICE_URL` / `DATA_SERVICE_URL` — upstream data dependencies — required for readiness/export orchestration
- `DATA_READINESS_POLL_ATTEMPTS` / `DATA_READINESS_INITIAL_DELAY_SECONDS` / `DATA_READINESS_WAIT_TIMEOUT_SECONDS` / `DATA_READINESS_EXTENDED_WAIT_TIMEOUT_SECONDS` / `DATA_READINESS_MAX_CONCURRENCY` / `DATA_READINESS_EXPORT_COOLDOWN_SECONDS` / `DATA_READINESS_TRIGGER_RETRIES` / `DATA_READINESS_STATUS_RETRIES` / `DATA_SERVICE_QUERY_TIMEOUT_SECONDS` / `DATA_SERVICE_QUERY_LIMIT` / `DATA_SERVICE_FALLBACK_CHUNK_HOURS` — readiness/export fallback controls — optional

**data-export-service**

- `SERVICE_NAME` / `SERVICE_VERSION` / `ENVIRONMENT` / `HOST` / `PORT` / `LOG_LEVEL` — service runtime metadata — optional/defaulted
- `INFLUXDB_URL` / `INFLUXDB_TOKEN` / `INFLUXDB_ORG` / `INFLUXDB_BUCKET` / `INFLUXDB_TIMEOUT_SECONDS` — telemetry source settings — required
- `DATA_SERVICE_URL` / `DATA_SERVICE_TIMEOUT_SECONDS` — optional data-service dependency for export orchestration
- `EXPORT_INTERVAL_SECONDS` / `EXPORT_BATCH_SIZE` / `EXPORT_FORMAT` — export cadence and file format — optional/defaulted
- `S3_BUCKET` / `S3_PREFIX` / `S3_REGION` / `S3_ENDPOINT_URL` / `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` — export destination object storage settings — required for uploads
- `CHECKPOINT_DB_HOST` / `CHECKPOINT_DB_PORT` / `CHECKPOINT_DB_NAME` / `CHECKPOINT_DB_USER` / `CHECKPOINT_DB_PASSWORD` / `CHECKPOINT_TABLE` — MySQL checkpoint storage config — required
- `LOOKBACK_HOURS` / `MAX_EXPORT_WINDOW_HOURS` / `MAX_FORCE_EXPORT_WINDOW_HOURS` — export window safety limits — optional
- `DEVICE_IDS` — comma-separated export targets for continuous mode — optional — example `COMPRESSOR-001,COMPRESSOR-002`

**copilot-service**

- `APP_NAME` / `APP_VERSION` / `LOG_LEVEL` — service metadata — optional/defaulted
- `AI_PROVIDER` — active LLM backend selector — required for non-degraded Copilot — example `groq`
- `GROQ_API_KEY` / `GEMINI_API_KEY` / `OPENAI_API_KEY` — provider credentials — production-only depending on chosen provider
- `MYSQL_URL` — primary MySQL DSN — required for schema loading and fallback queries
- `MYSQL_READONLY_URL` — read-only MySQL DSN used by query engine — strongly recommended — example `mysql+aiomysql://copilot_reader:***@mysql:3306/ai_factoryops`
- `DATA_SERVICE_URL` / `REPORTING_SERVICE_URL` / `ENERGY_SERVICE_URL` — downstream services used for telemetry and tariff enrichment — optional but expected in full platform mode
- `FACTORY_TIMEZONE` — timezone used in reasoning — optional — example `Asia/Kolkata`
- `MAX_QUERY_ROWS` / `QUERY_TIMEOUT_SEC` / `MAX_HISTORY_TURNS` / `STAGE1_MAX_TOKENS` / `STAGE2_MAX_TOKENS` — Copilot guardrails and prompt-budget settings — optional

**ui-web and mobile**

- `UI_WEB_BASE_URL` — Playwright base URL override for web e2e tests — optional — example `http://localhost:3000`
- Expo `extra.apiBaseUrl` in [app.json](/Users/vedanthshetty/Desktop/Obeyaa-Deployed/FactoryOPS-Cittagent-Obeya-main/shivex-mobile/app.json) — mobile API host root — required for the native client — example `https://shivex.ai`

**Local dev vs production**

- Local Docker dev mainly needs MySQL, InfluxDB, MinIO, Redis, EMQX, service URLs, and non-secret defaults.
- Production additionally needs real SMTP credentials, object-storage external URLs, Copilot provider keys, and hardened DB credentials.
- The root `.env` in this workspace contains live-looking values and should be treated as sensitive operational data, not documentation source of truth.

## 11. External Integrations

- `InfluxDB`: telemetry writes and analytics reads
- `MinIO / S3`: report artifacts, datasets, dashboard snapshot payloads
- `Redis`: analytics queue backend and stream coordination
- `EMQX`: MQTT broker for inbound telemetry
- `OpenAI`, `Groq`, `Google Generative AI`: LLM providers for copilot
- `SMTP`: notification delivery via rule-engine/reporting settings

**Data sent / received**

- telemetry payloads over MQTT and HTTP
- report and waste artifacts to object storage
- SQL-derived context to LLM providers in copilot orchestration
- alert emails via SMTP-compatible providers

**Webhook endpoints**

No conventional inbound public webhook framework is prominently defined in the current route map.

## 12. Error Handling & Logging

**Patterns**

- Most FastAPI services define:
  - `RequestValidationError` handler
  - `HTTPException` handler
  - generic `Exception` handler returning `INTERNAL_ERROR`

**Response shape**

Common error JSON shape:

```json
{
  "error": "INTERNAL_ERROR",
  "message": "Unexpected server error",
  "code": "INTERNAL_ERROR"
}
```

**Logging**

- `python-json-logger` and `structlog` in several services
- standard logging in others
- startup/shutdown logs are explicit across services
- migration guards log to stderr and intentionally fail hard on migration errors

**Tracked vs swallowed**

- background tasks often log and continue instead of crashing the service
- some dashboard/cost fetch paths intentionally degrade silently to preserve UI availability
- copilot blocks unsafe SQL and returns guarded user-friendly errors

## 13. Testing Strategy

**Frameworks**

- `pytest` / `pytest-asyncio` for backend and system tests
- Playwright for `ui-web` restart-regression browser testing

**Test layers**

- Service unit/integration tests inside each service directory
- Cross-service `tests/e2e/*.py`
- Frontend browser regression in [machines-reconnect.spec.js](/Users/vedanthshetty/Desktop/Obeyaa-Deployed/FactoryOPS-Cittagent-Obeya-main/ui-web/tests/e2e/machines-reconnect.spec.js)

**Important verified areas**

- outbox integrity
- Influx batching
- optimistic locking
- queue backpressure
- circuit breakers
- tag cardinality protections
- copilot SQL guard
- snapshot storage to MinIO
- analytics ML isolation
- frontend reconnect handling

**How to run**

- backend service tests: `docker compose exec <service> python -m pytest ...`
- system tests: `pytest tests/e2e/...`
- frontend restart test: `cd ui-web && npm run test:e2e -- tests/e2e/machines-reconnect.spec.js`

## 14. Local Development Setup

**Prerequisites**

- Docker + Docker Compose
- Python 3.11 if running services/tests outside containers
- Node 20+ for `ui-web`
- npm

**Primary startup**

```bash
docker compose down -v
docker compose up -d --build
```

**Useful local commands**

- `docker compose ps`
- `docker compose logs -f <service>`
- `docker compose exec <service> python -m pytest ...`
- `cd ui-web && npm run lint`
- `cd ui-web && npm run test:e2e -- tests/e2e/machines-reconnect.spec.js`

**Known local gotchas**

- services assume Docker DNS service names
- startup depends on Alembic migrations completing successfully
- volume resets clear MySQL/Influx/MinIO state, but UI can still show session-stored state until refreshed
- some services will start healthy while degraded dependencies still produce runtime warnings

## 15. Deployment & CI/CD

**Build process**

- each service has a Dockerfile
- Python services install requirements and run `start.sh` or `uvicorn`
- `ui-web` performs `npm ci`, `lint:hooks`, and `next build`

**Migration strategy**

- migrations run at container startup
- migration guards now serialize per-service Alembic upgrades with MySQL advisory locks

**CI/CD**

- No `.github/workflows` or other CI pipeline is present in the audited repo root
- Deployment flow is Docker Compose oriented rather than a formal dev/staging/prod promotion pipeline

## 16. Known Issues & Tech Debt

**Observed structural debt**

- No real backend authentication / authorization
- `.env` / secret management posture is weak for production if local defaults are reused
- Shared MySQL database across many services increases blast radius
- Several services degrade gracefully but still expose runtime warnings rather than explicit degraded-health states
- Existing repo-wide ESLint warnings remain in multiple frontend files
- Generated folders like `.next`, `.expo`, `node_modules`, `test-results`, and `__pycache__` are present in the workspace and should not be treated as source of truth

**TODO/FIXME audit**

Repo-wide grep did not surface actionable `TODO` / `FIXME` markers in source files; most matches were incidental mentions of `DEBUG` log levels or older generated documentation. The remaining notable soft-debt markers are deprecation comments and operational notes in:

- device schema comments about deprecated `status`
- frontend comments around temporary degraded-path behavior
- service startup comments describing migration-managed schema ownership

**Performance risks**

- shared MySQL under write-heavy multi-service load
- dashboard summary fan-out when downstream services are slow
- ML worker memory/CPU footprint
- report rendering using WeasyPrint/Matplotlib under concurrent demand

## 17. Glossary

- `DLQ`: Dead-letter queue for failed deliveries
- `Outbox`: durable relay table for cross-service write consistency
- `Fleet snapshot`: device-service view of all machine cards for the dashboard
- `Fleet stream`: SSE feed of full or partial fleet updates
- `Live projection`: `device_live_state` materialized current state per device
- `Idle running`: machine drawing power while not productively loaded
- `Overconsumption`: power/loss above configured thresholds
- `Health score`: weighted equipment health metric derived from telemetry and configured parameter ranges
- `Uptime percentage`: operational efficiency metric derived from shifts and effective running time
- `APP_ROLE`: analytics-service split between API process and ML worker process
- `tenant_id`: logical tenancy boundary used across newer multi-tenant tables and copilot filtering

## Appendix: Audit Notes

- The repo contains roughly `601` non-generated tracked source/config/test files under the filters used during this audit.
- Generated directories such as `ui-web/.next`, `shivex-mobile/.expo`, `node_modules`, and `__pycache__` were identified as generated artifacts rather than source code.
- Route inventory was derived from route decorators currently present in the checked-out code, not from stale docs.
- Service health and startup behavior were cross-checked against the active `docker-compose.yml`.
