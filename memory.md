# Repository Memory

- Repository name: `FactoryOPS-Cittagent-Obeya-main`
- Generation date: `2026-04-18`
- Branch: `main` (confirmed from `git branch --show-current`)
- Related appendices:
  - API appendix: [memory-appendix-api.md](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)
  - DB appendix: [memory-appendix-db.md](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md)
- Scan summary:
  - Confirmed from code/config: root `README.md`, `docker-compose.yml`, `.env.production.example`, root `requirements*.txt`, all major service config/startup files, shared multi-tenant/auth code, major API entrypoints, key worker implementations, `ui-web` route/auth/api layers, `shivex-mobile` auth/store/routes, monitoring configs, MySQL init scripts, and top-level/service test layout.
  - Confirmed from docs where code matched or code was not the source of truth: service `README.md` files, `docs/auth_cutover_runbook.md`, `docs/aws_production_deployment.md`, `docs/preprod_validation.md`.
  - Not exhaustively scanned line-by-line: every schema/model/repository, every React component, every test body, legacy `Project-docs/` narrative docs, generated assets.
- Status legend used throughout:
  - `Confirmed from code`
  - `Inferred from usage`
  - `Not found in repository`
  - `Needs runtime verification`

## Memory Maintenance

- Refresh [memory-appendix-api.md](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md) fully when routes, DTOs, auth middleware behavior, internal HTTP calls, frontend rewrites, or realtime interfaces change.
- Refresh [memory-appendix-db.md](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md) fully when models, migrations, raw SQL bootstrap files, repository query patterns, or tenant-scoping rules change.
- Update [memory.md](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory.md) incrementally for service ownership, flows, runtime entrypoints, environment/config, and change-impact guidance if the appendices still match code.
- Rebuild all three together after branding changes, auth/session refactors, tenant-isolation refactors, queue/worker redesigns, or any service split/merge.

## Appendix Guide

- Use [memory-appendix-api.md](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md) for exact endpoint maps, DTOs, internal service-to-service calls, polling/SSE/WebSocket surfaces, and API risk areas.
- Use [memory-appendix-db.md](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md) for schema truth, migration history, repository/query patterns, tenant-scoping at the data layer, and DB risk areas.
- This file stays focused on architecture, business flows, module ownership, runtime/config, and change impact.

## Fast Paths For Common Changes

- Change auth/session behavior:
  - start in `services/auth-service/app/api/v1/auth.py`, `services/auth-service/app/services/auth_service.py`, `services/auth-service/app/services/token_service.py`, `services/shared/auth_middleware.py`, `ui-web/lib/authApi.ts`, `ui-web/lib/browserSession.ts`, `shivex-mobile/src/api/authApi.ts`
  - API map: [memory-appendix-api.md#auth-service](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)
  - DB map: [memory-appendix-db.md#auth-service-schemas](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md)

- Change analytics behavior:
  - start in `services/analytics-service/src/api/routes/analytics.py`, `src/infrastructure/mysql_repository.py`, `src/workers/job_queue.py`, `src/workers/job_worker.py`, `src/services/scaling_policy.py`, `ui-web/app/(protected)/analytics/*`
  - API map: [memory-appendix-api.md#analytics-service](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)
  - DB map: [memory-appendix-db.md#analytics-service-schemas](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md)

- Change reports:
  - start in `services/reporting-service/src/handlers/`, `src/services/report_engine.py`, `src/repositories/report_repository.py`, `src/repositories/scheduled_repository.py`, `ui-web/app/(protected)/reports/*`
  - API map: [memory-appendix-api.md#reporting-service](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)
  - DB map: [memory-appendix-db.md#reporting-service-schemas](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md)

- Change telemetry ingest or public telemetry APIs:
  - start in `services/data-service/src/handlers/mqtt_handler.py`, `src/services/telemetry_service.py`, `src/workers/telemetry_pipeline.py`, `src/repositories/influxdb_repository.py`, `src/repositories/outbox_repository.py`
  - API map: [memory-appendix-api.md#data-service](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)
  - DB map: [memory-appendix-db.md#data-service-schemas](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md)

- Change notifications or alert delivery:
  - start in `services/rule-engine-service/app/services/evaluator.py`, `app/services/notification_outbox.py`, `app/workers/notification_worker.py`, `app/repositories/notification_delivery.py`, `app/repositories/notification_outbox.py`, and reporting-service `src/models/settings.py` / `src/repositories/settings_repository.py` for shared notification channels
  - API map: [memory-appendix-api.md#rule-engine-service](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)
  - DB map: [memory-appendix-db.md#rule-engine-service-schemas](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md)

- Change dashboard status/runtime/load behavior:
  - start in `services/device-service/app/services/live_projection.py`, `app/services/idle_running.py`, `app/api/v1/devices.py`, `services/energy-service/app/api/routes.py`, and frontend dashboard pages under `ui-web/app/(protected)/devices/*`, `machines/*`, and related client hooks
  - API map: [memory-appendix-api.md#device-service](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)
  - DB map: [memory-appendix-db.md#device-service-schemas](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md)

- Change branding:
  - start in root `README.md`, `services/auth-service/app/config.py`, `ui-web` metadata/layout files, and `shivex-mobile` app config plus auth-facing email/template strings
  - current state is mixed `FactoryOPS / Cittagent / Shivex`; do not assume one canonical name without checking code paths and user-facing copy

- Change tenant isolation:
  - start in `services/shared/auth_middleware.py`, `services/shared/tenant_context.py`, `services/shared/tenant_guards.py`, `services/shared/scoped_repository.py`, then inspect service-specific repository filters and internal header builders
  - API map: [memory-appendix-api.md#6-api-contracts-and-shared-types](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)
  - DB map: [memory-appendix-db.md#5-tenant-isolation-in-data-model](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md)

## 1. Platform Overview

- Product identity:
  - `Confirmed from code`: the repository contains a multi-service industrial monitoring / energy operations platform with device telemetry, dashboards, alerts/rules, analytics, reporting, waste analysis, and AI copilot capabilities (`README.md`, `docker-compose.yml`, service folders under `services/`).
  - `Confirmed from code`: current branding is mixed.
    - `FactoryOPS / Cittagent` appears in root repo naming and `README.md`.
    - `Shivex` appears in auth defaults and web/mobile branding defaults, for example `services/auth-service/app/config.py:38-48` and web/mobile naming in `ui-web` / `shivex-mobile`.
  - `Inferred from usage`: this is B2B SaaS for industrial/factory operators and administrators. Evidence: tenant/org/plant hierarchy, invitation flows, org feature entitlements, plant-scoped users, dashboards by machine/fleet/energy/reporting domain.

- Business purpose:
  - `Confirmed from code`: ingest power/telemetry data from devices, normalize and persist it, project live state to dashboards, evaluate rules/alerts, compute energy and waste insights, generate reports, and optionally answer tenant-scoped questions through AI copilot.

- Primary actors:
  - `Confirmed from code`: `super_admin`, `org_admin`, `plant_manager`, `operator`, `viewer` are the implemented role set (`app.models.auth.UserRole` usage in auth routes and `services/shared/feature_entitlements.py:23-49`).
  - `Confirmed from code`: org/tenant admins can create users and plants; plant managers are constrained to lower-privilege users (`services/auth-service/app/api/v1/orgs.py:79-224`).

- Major product capabilities:
  - `Confirmed from code`: auth, login, refresh, invite acceptance, password reset (`services/auth-service/app/api/v1/auth.py`, `services/auth-service/app/services/auth_service.py`).
  - `Confirmed from code`: device inventory, live dashboard state, health config, machine runtime/load classification, fleet streams (`services/device-service/app/...`, `services/device-service/README.md`).
  - `Confirmed from code`: MQTT telemetry ingest, validation, Influx persistence, Redis-stream pipeline, WebSocket/broadcast, downstream projection, energy/rules fan-out (`services/data-service/src/...`).
  - `Confirmed from code`: energy projections and summaries (`services/energy-service/app/api/routes.py`).
  - `Confirmed from code`: alert/rule evaluation and notification outbox delivery (`services/rule-engine-service/app/services/evaluator.py`, `notification_outbox.py`, `workers/notification_worker.py`).
  - `Confirmed from code`: analytics jobs and ML job queueing (`services/analytics-service/src/...`).
  - `Confirmed from code`: report generation and downloadable artifacts via MinIO/object storage (`services/reporting-service/src/...`).
  - `Confirmed from code`: waste-analysis jobs with PDF/object storage outputs (`services/waste-analysis-service/src/...`).
  - `Confirmed from code`: AI copilot with tenant-scoped SQL guard and curated prompts (`services/copilot-service/src/...`).

- Multi-tenant model:
  - `Confirmed from code`: tenant isolation is a first-class concern. Shared middleware derives tenant context from JWT claims and request headers (`services/shared/auth_middleware.py`, `services/shared/tenant_context.py`).
  - `Confirmed from code`: tenant-scoped repositories automatically filter on `tenant_id` when models include that column (`services/shared/scoped_repository.py`).
  - `Confirmed from code`: cross-tenant access is blocked and audited through tenant guards (`services/shared/tenant_guards.py:87-141`).
  - `Confirmed from code`: super admins can operate without a tenant claim and select a target tenant via `X-Target-Tenant-Id` / query parameter (`services/shared/auth_middleware.py:179-214`, `services/shared/tenant_context.py`).
  - Detailed API-side auth/tenant contract: [memory-appendix-api.md#6-api-contracts-and-shared-types](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)
  - Detailed data-side tenant map: [memory-appendix-db.md#5-tenant-isolation-in-data-model](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md)

## 2. High-Level Architecture

- Architecture style:
  - `Confirmed from code`: hybrid service-oriented architecture, not a single monolith. Services are independently containerized in `docker-compose.yml` and have separate codebases under `services/`.
  - Detailed HTTP/API surface: [memory-appendix-api.md#1-api-surface-overview](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)
  - Detailed persistence/service datastore map: [memory-appendix-db.md#1-database-overview](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md)

- Service boundaries:
  - `Confirmed from code`:
    - `auth-service`: identity, orgs/plants/users, tokens, invitations, entitlements.
    - `device-service`: device CRUD, live/fleet state, health configs, machine runtime/load state, dashboard materialization.
    - `data-service`: telemetry ingest API/MQTT bridge, Redis stage pipeline, Influx persistence, DLQ/outbox.
    - `energy-service`: energy projections and summaries.
    - `rule-engine-service`: rule evaluation, alert creation, notification delivery.
    - `analytics-service`: queued analytics/ML jobs and result formatting.
    - `reporting-service`: report jobs, datasets, report files, tariff-driven reporting.
    - `waste-analysis-service`: waste-analysis jobs and artifacts.
    - `data-export-service`: telemetry export to Parquet/CSV datasets in object storage.
    - `copilot-service`: AI-assisted tenant-scoped querying and curated Q&A.
    - shared cross-cutting package: `services/shared`.

- Request flow overview:
  - `Confirmed from code`: browser/mobile -> `ui-web` Next.js rewrite proxy or direct mobile API -> backend services.
  - `Confirmed from code`: most service-to-service calls carry internal service and tenant headers built from shared helpers (`services/shared/tenant_context.py`).
  - `Confirmed from code`: backend auth enforcement is middleware-first; feature gating is route-level in some services.

- Real-time / live-update architecture:
  - `Confirmed from code`: telemetry lands in `data-service`, persists to Influx, then projection/broadcast stages update dashboard consumers.
  - `Confirmed from code`: device live state is persisted in MySQL table/model layer via live projection logic and distributed to fleet subscribers through Redis fan-out (`services/device-service/app/services/live_projection.py`, `services/device-service/app/config.py:91-96`).
  - `Confirmed from code`: energy-service publishes Redis energy update events (`services/energy-service/app/main.py` startup + broadcaster).
  - `Needs runtime verification`: exact browser subscription transport for every dashboard page. Web app clearly consumes protected APIs and has live pages, but not every component path was traced end-to-end.

- Async / background architecture:
  - `Confirmed from code`: Redis streams are used for durable telemetry and analytics/reporting queueing.
  - `Confirmed from code`: background workers exist for:
    - telemetry pipeline (`data-service`)
    - rule-engine notification outbox worker
    - analytics job workers
    - reporting job workers
    - data export worker
    - refresh token cleanup loop in auth-service
    - APScheduler tasks in reporting-service
    - weekly retrainer in analytics-service

- Internal communication patterns:
  - `Confirmed from code`: synchronous HTTP service calls with tenant-scoped internal headers.
  - `Confirmed from code`: Redis streams / consumer groups for durable background pipelines.
  - `Confirmed from code`: Redis pub/sub channels for live fan-out in device/energy domains.
  - `Confirmed from code`: MQTT input through EMQX to `data-service`.

- Deployment model:
  - `Confirmed from code`: local/dev/preprod orchestration via Docker Compose (`docker-compose.yml`).
  - `Confirmed from docs`: production deployment guidance exists in `docs/aws_production_deployment.md`.
  - `Not found in repository`: Terraform / Helm / Kubernetes manifests.
  - `Needs runtime verification`: actual production hosting/runtime topology.

## 3. Technology Stack

### Frontend

- `Confirmed from code`: Next.js 16, React 19, TypeScript, Tailwind CSS 4, Radix UI, Recharts, `@tanstack/react-query`, `framer-motion`, `lucide-react` (`ui-web/package.json`).
- `Confirmed from code`: Expo / React Native mobile app with Expo Router, Zustand, SecureStore (`shivex-mobile/package.json`).

### Backend

- `Confirmed from code`: Python FastAPI across services.
- `Confirmed from code`: Uvicorn process startup for API services.
- `Confirmed from code`: SQLAlchemy async + Alembic migrations.
- `Confirmed from code`: Pydantic / `pydantic-settings`.
- `Confirmed from code`: Pandas / NumPy in reporting and waste/analytics codepaths.

### Databases

- `Confirmed from code`: MySQL for relational tenant/auth/device/job/outbox data.
- `Confirmed from code`: InfluxDB for telemetry time-series (`data-service`, reporting, waste).

### Queues / Messaging

- `Confirmed from code`: Redis Streams for telemetry, analytics jobs, report jobs, rule notification outbox.
- `Confirmed from code`: Redis pub/sub for live fleet / energy broadcasts.
- `Confirmed from code`: MQTT via EMQX for telemetry ingress.

### Caching

- `Confirmed from code`: Redis for auth token revocation state, issued token tracking, queueing, and live channels.
- `Confirmed from code`: in-process tariff caches and stale fallbacks in device/waste/energy code.

### Auth

- `Confirmed from code`: JWT access tokens signed with shared secret (`services/auth-service/app/services/token_service.py`).
- `Confirmed from code`: refresh tokens stored hashed in MySQL.
- `Confirmed from code`: HttpOnly cookie refresh for web; explicit refresh token storage for mobile.

### Storage

- `Confirmed from code`: MinIO / S3-compatible object storage for datasets and generated reports.
- `Confirmed from code`: buckets include `energy-platform-datasets` and `factoryops-waste-reports` (`docker-compose.yml`, `createbuckets` service).

### Observability

- `Confirmed from code`: Prometheus, Grafana, Alertmanager in `monitoring/`.
- `Confirmed from code`: health/ready/metrics endpoints across services.
- `Confirmed from code`: structured logging patterns in several services.

### Testing

- `Confirmed from code`: `pytest`-based backend tests.
- `Confirmed from code`: Playwright for web e2e (`ui-web/package.json`).
- `Confirmed from code`: Vitest / Testing Library unit tests in `ui-web`.

### DevOps / Containers / Infra

- `Confirmed from code`: Dockerfiles per service, Docker Compose, initialization SQL scripts.
- `Confirmed from code`: Mailpit for local email capture.
- `Not found in repository`: Kubernetes, ECS task definitions, Terraform state, CD pipeline definitions.

## 4. Project Structure

### Directory tree (up to 4 levels)

```text
.
├── README.md
├── docker-compose.yml
├── docs/
│   ├── auth_cutover_runbook.md
│   ├── aws_production_deployment.md
│   ├── preprod_validation.md
│   └── validation/
├── init-scripts/
│   └── mysql/
│       ├── 01_init.sql
│       ├── 02_data_service_dlq.sql
│       └── 03_copilot_reader.sql
├── monitoring/
│   ├── alertmanager/
│   │   └── alertmanager.yml
│   ├── grafana/
│   │   └── dashboards/
│   └── prometheus/
│       ├── prometheus.yml
│       └── rules/
├── services/
│   ├── analytics-service/
│   │   ├── src/
│   │   │   ├── api/
│   │   │   ├── config/
│   │   │   ├── services/
│   │   │   ├── workers/
│   │   │   └── ...
│   │   └── tests/
│   ├── auth-service/
│   │   ├── app/
│   │   │   ├── api/v1/
│   │   │   ├── repositories/
│   │   │   ├── services/
│   │   │   ├── schemas/
│   │   │   └── ...
│   │   └── tests/
│   ├── copilot-service/
│   │   ├── src/
│   │   │   ├── ai/
│   │   │   ├── api/
│   │   │   ├── db/
│   │   │   ├── integrations/
│   │   │   └── ...
│   │   └── tests/
│   ├── data-export-service/
│   │   ├── main.py
│   │   ├── worker.py
│   │   ├── exporter.py
│   │   ├── data_source.py
│   │   └── ...
│   ├── data-service/
│   │   ├── src/
│   │   │   ├── api/
│   │   │   ├── config/
│   │   │   ├── services/
│   │   │   ├── workers/
│   │   │   └── ...
│   │   └── tests/
│   ├── device-service/
│   │   ├── app/
│   │   │   ├── api/
│   │   │   ├── services/
│   │   │   ├── repositories/
│   │   │   └── ...
│   │   └── tests/
│   ├── energy-service/
│   │   ├── app/
│   │   │   ├── api/
│   │   │   ├── services/
│   │   │   └── ...
│   │   └── tests/
│   ├── reporting-service/
│   │   ├── src/
│   │   │   ├── api/
│   │   │   ├── services/
│   │   │   ├── workers/
│   │   │   └── ...
│   │   └── tests/
│   ├── rule-engine-service/
│   │   ├── app/
│   │   │   ├── api/
│   │   │   ├── services/
│   │   │   ├── workers/
│   │   │   └── ...
│   │   └── tests/
│   ├── shared/
│   └── waste-analysis-service/
│       ├── src/
│       │   ├── handlers/
│       │   ├── services/
│       │   ├── tasks/
│       │   └── ...
│       └── tests/
├── tests/
│   ├── e2e/
│   ├── integration/
│   └── regression/
├── tools/
│   └── device-simulator/
├── ui-web/
│   ├── app/
│   │   ├── (protected)/
│   │   ├── login/
│   │   ├── forgot-password/
│   │   └── ...
│   ├── components/
│   ├── hooks/
│   ├── lib/
│   └── tests/
└── shivex-mobile/
    ├── app/
    ├── src/
    │   ├── api/
    │   ├── store/
    │   └── ...
    └── components/
```

### Top-level folders

- `services/`: all backend services plus shared backend package.
- `ui-web/`: Next.js web frontend.
- `shivex-mobile/`: Expo mobile frontend.
- `tests/`: cross-service higher-level tests.
- `monitoring/`: Prometheus, Grafana, Alertmanager config.
- `init-scripts/`: DB/bootstrap SQL.
- `docs/`: deployment/auth validation docs.
- `tools/device-simulator/`: telemetry simulator tooling.

## 5. Module Map

### Auth and Tenant Administration

- Folder: `services/auth-service/app`
- Responsibility:
  - `Confirmed from code`: login, refresh, logout, `/me`, invite acceptance, password reset, super-admin bootstrap, tenant/org/plant/user administration, feature entitlements.
- Key files:
  - `services/auth-service/app/main.py`
  - `services/auth-service/app/api/v1/auth.py`
  - `services/auth-service/app/api/v1/admin.py`
  - `services/auth-service/app/api/v1/orgs.py`
  - `services/auth-service/app/services/auth_service.py`
  - `services/auth-service/app/services/token_service.py`
  - `services/auth-service/app/config.py`
- Dependencies:
  - MySQL, Redis, SMTP/Mailpit, shared tenant/auth helpers.
- Critical contracts:
  - access token claims include `sub`, `email`, `tenant_id`, `role`, `plant_ids`, `permissions_version`, `tenant_entitlements_version`, `jti` (`token_service.py:64-88`).
  - refresh cookie name/path/domain behavior in `auth.py` + `config.py`.
  - exact endpoint map: [memory-appendix-api.md#auth-service](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)
  - exact schema map: [memory-appendix-db.md#auth-service-schemas](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md)

### Shared Tenant/Auth Infrastructure

- Folder: `services/shared`
- Responsibility:
  - `Confirmed from code`: middleware, tenant context derivation, feature entitlement resolution, tenant-scoped repositories, telemetry normalization.
- Key files:
  - `services/shared/auth_middleware.py`
  - `services/shared/tenant_context.py`
  - `services/shared/tenant_guards.py`
  - `services/shared/scoped_repository.py`
  - `services/shared/feature_entitlements.py`
  - `services/shared/telemetry_normalization.py`
  - `services/shared/energy_accounting.py`
- Critical contracts:
  - internal header names `X-Internal-Service`, `X-Tenant-Id`, `X-Target-Tenant-Id` (`tenant_context.py:11-13`).
  - role baseline features and grantable premium features (`feature_entitlements.py:12-49`).
  - shared auth contract: [memory-appendix-api.md#shared-auth--tenant-contract](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)
  - tenant-isolation data map: [memory-appendix-db.md#5-tenant-isolation-in-data-model](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md)

### Device Domain

- Folder: `services/device-service/app`
- Responsibility:
  - `Confirmed from code`: devices, heartbeat/property sync, dashboard summaries, health configs, live state, runtime/load/idle classification, fleet streaming.
- Key files:
  - `app/api/v1/router.py`
  - `app/services/live_projection.py`
  - `app/services/idle_running.py`
  - `app/services/health_config.py`
  - `app/config.py`
- Dependencies:
  - auth-service (middleware auth), data-service, energy-service, reporting-service, Redis, MySQL.
- Critical contracts:
  - machine states and canonical parameter aliases in `health_config.py`.
  - optimistic `version` updates for device live state in `live_projection.py:87-148`.
  - exact endpoint map: [memory-appendix-api.md#device-service](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)
  - exact schema map: [memory-appendix-db.md#device-service-schemas](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md)

### Telemetry Ingest and Pipeline

- Folder: `services/data-service/src`
- Responsibility:
  - `Confirmed from code`: MQTT ingest, validation, Redis stream staging, Influx persistence, projection/broadcast/energy/rules fan-out, DLQ, outbox relay, WebSocket/data APIs.
- Key files:
  - `src/main.py`
  - `src/worker_main.py`
  - `src/services/telemetry_service.py`
  - `src/workers/telemetry_pipeline.py`
  - `src/services/outbox_relay.py`
  - `src/config/settings.py`
- Dependencies:
  - EMQX, Redis, InfluxDB, MySQL, device-service, energy-service, rule-engine-service.
- Critical contracts:
  - stage stream names/defaults in `settings.py`.
  - API prefix `/api/v1/data` in `settings.py`.
  - exact endpoint map: [memory-appendix-api.md#data-service](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)
  - exact schema map: [memory-appendix-db.md#data-service-schemas](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md)

### Energy Domain

- Folder: `services/energy-service/app`
- Responsibility:
  - `Confirmed from code`: live energy updates, summary and calendar views, device lifecycle/range calculations, downstream energy broadcast.
- Key files:
  - `app/main.py`
  - `app/api/routes.py`
  - `app/config.py`
- Dependencies:
  - MySQL, Redis, device-service, reporting-service.
- Exact references:
  - API map: [memory-appendix-api.md#energy-service](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)

### Rules and Notifications

- Folder: `services/rule-engine-service/app`
- Responsibility:
  - `Confirmed from code`: rule evaluation against telemetry/live state, alert creation, notification outbox and delivery worker.
- Key files:
  - `app/services/evaluator.py`
  - `app/services/notification_outbox.py`
  - `app/workers/notification_worker.py`
  - `app/config.py`
- Dependencies:
  - MySQL, Redis, SMTP, optional Twilio.
- Critical contracts:
  - notification settings come from the shared physical `notification_channels` table owned by reporting-service and read by rule-engine through a mirror model.
  - exact endpoint map: [memory-appendix-api.md#rule-engine-service](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)
  - exact schema map: [memory-appendix-db.md#rule-engine-service-schemas](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md)

### Analytics / ML Jobs

- Folder: `services/analytics-service/src`
- Responsibility:
  - `Confirmed from code`: analytics job queueing, worker execution, backlog fairness/caps, result formatting, optional weekly retraining.
- Key files:
  - `src/main.py`
  - `src/worker_main.py`
  - `src/workers/job_queue.py`
  - `src/services/scaling_policy.py`
  - `src/services/result_formatter.py`
  - `src/config/settings.py`
- Dependencies:
  - MySQL, Redis, data-export-service, data-service, device-service, object storage.
- Critical contracts:
  - tenant scoping partly lives in job `parameters->tenant_id` and request context rather than a dedicated DB column.
  - exact endpoint map: [memory-appendix-api.md#analytics-service](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)
  - exact schema map: [memory-appendix-db.md#analytics-service-schemas](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md)

### Reporting

- Folder: `services/reporting-service/src`
- Responsibility:
  - `Confirmed from code`: queued report generation, metrics, MinIO storage, report history/download/result APIs, tariff-linked reporting settings.
- Key files:
  - `src/main.py`
  - `src/worker_main.py`
  - `src/services/report_engine.py`
  - `src/workers/report_worker.py`
  - `src/config.py`
- Dependencies:
  - MySQL, Redis, InfluxDB, MinIO, device-service, energy-service.
- Critical contracts:
  - report jobs, schedules, tariff rows, and notification channels are tightly linked.
  - exact endpoint map: [memory-appendix-api.md#reporting-service](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)
  - exact schema map: [memory-appendix-db.md#reporting-service-schemas](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md)

### Waste Analysis

- Folder: `services/waste-analysis-service/src`
- Responsibility:
  - `Confirmed from code`: waste-analysis job creation/history/status/result/download, quality gates, per-device waste summaries, object output.
- Key files:
  - `src/main.py`
  - `src/handlers/waste_analysis.py`
  - `src/tasks/waste_task.py`
  - `src/config.py`
- Dependencies:
  - MySQL, InfluxDB, MinIO, device-service, reporting-service, energy-service.
- Exact references:
  - API map: [memory-appendix-api.md#waste-analysis-service](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)
  - schema map: [memory-appendix-db.md#waste-analysis-service-schemas](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md)

### Data Export

- Folder: `services/data-export-service`
- Responsibility:
  - `Confirmed from code`: continuous and forced telemetry export to object storage with checkpointing (`main.py`, `config.py`).
- Key files:
  - `main.py`
  - `worker.py`
  - `exporter.py`
  - `data_source.py`
  - `checkpoint.py`
  - `s3_writer.py`
- Dependencies:
  - InfluxDB, MySQL checkpoint store, S3/MinIO, data-service.
- Critical contracts:
  - forced export endpoint `/api/v1/exports/run` validates date ranges and tenant-scoped devices (`main.py`).
  - API map: [memory-appendix-api.md#data-export-service](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)

### Copilot

- Folder: `services/copilot-service/src`
- Responsibility:
  - `Confirmed from code`: curated AI copilot, tenant-scoped SQL execution guard, tariff-aware answers.
- Key files:
  - `src/main.py`
  - `src/api/chat.py`
  - `src/db/query_engine.py`
  - `src/config.py`
- Dependencies:
  - readonly MySQL, AI provider APIs, data/reporting/energy services.
- Critical contracts:
  - SQL tenant filter injection based on schema manifest and `tenant_id` columns (`query_engine.py:29-112`).
  - exact endpoint map: [memory-appendix-api.md#copilot-service](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)

### Web Frontend

- Folder: `ui-web`
- Responsibility:
  - `Confirmed from code`: user-facing product UI, route protection, session handling, tenant selection, API proxying.
- Key files:
  - `ui-web/app/layout.tsx`
  - `ui-web/app/(protected)/layout.tsx`
  - `ui-web/lib/authContext.tsx`
  - `ui-web/lib/authApi.ts`
  - `ui-web/lib/apiFetch.ts`
  - `ui-web/lib/browserSession.ts`
  - `ui-web/lib/tenantStore.ts`
  - `ui-web/components/AuthGuard.tsx`
  - `ui-web/components/SuperAdminOrgGate.tsx`
  - `ui-web/next.config.ts`

### Mobile Frontend

- Folder: `shivex-mobile`
- Responsibility:
  - `Confirmed from code`: mobile access to auth, machines, alerts, reports, rules, waste, copilot.
- Key files:
  - `shivex-mobile/src/api/authApi.ts`
  - `shivex-mobile/src/store/useUserStore.ts`
  - Expo route folders under `shivex-mobile/app`.

## 6. Runtime Entry Points

### Service startup commands

- `Confirmed from code`:
  - `auth-service`: `uvicorn app.main:app --host 0.0.0.0 --port 8090` via `services/auth-service/start.sh`
  - `device-service`: `uvicorn app:app --host 0.0.0.0 --port 8000` via `services/device-service/start.sh`
  - `data-service`: `uvicorn src.main:app --host 0.0.0.0 --port 8081` via Dockerfile
  - `energy-service`: `uvicorn app.main:app --host 0.0.0.0 --port 8010` via `services/energy-service/start.sh`
  - `rule-engine-service` API: `uvicorn app:app --host 0.0.0.0 --port 8002`
  - `analytics-service` API: `uvicorn src.main:app --host 0.0.0.0 --port 8003`
  - `reporting-service` API: `uvicorn src.main:app --host 0.0.0.0 --port 8085`
  - `waste-analysis-service`: `uvicorn src.main:app --host 0.0.0.0 --port 8087`
  - `data-export-service`: FastAPI app in `main.py` on port `8080`
  - `copilot-service`: `uvicorn main:app --host 0.0.0.0 --port 8007`

### Worker startup commands

- `Confirmed from code`:
  - `data-service` worker: `python -m src.worker_main`
  - `rule-engine-service` worker: `python -m app.worker_main`
  - `analytics-service` worker: `python -m src.worker_main`
  - `reporting-service` worker: `python -m src.worker_main`
  - `data-export-service`: worker lifecycle starts inside API app lifespan (`main.py`)

### Docker Compose services, ports, and internal names

- `Confirmed from code` (`docker-compose.yml`):
  - `ui-web`: `3000`
  - `device-service`: `8000`
  - `data-service`: `8081`
  - `rule-engine-service`: `8002`
  - `analytics-service`: `8003`
  - `copilot-service`: `8007`
  - `data-export-service`: `8080`
  - `reporting-service`: `8085`
  - `waste-analysis-service`: `8087`
  - `energy-service`: `8010`
  - `auth-service`: `8090`
  - `mysql`: `3306`
  - `redis`: `6379`
  - `influxdb`: `8086`
  - `emqx`: `1883` plus management/UI ports
  - `minio`: `9000`, console `9001`
  - `mailpit`: SMTP `1025`, UI `8025`
  - `prometheus`: `9090`
  - `alertmanager`: `9093`
  - `grafana`: `3001`

### Healthchecks

- `Confirmed from code`: most services expose `/health`.
- `Confirmed from code`: many services expose `/ready`.
- `Confirmed from code`: several services expose `/metrics`.
- `Confirmed from code`: auth middleware skips auth for `/health`, `/ready`, `/metrics`, docs, OpenAPI, login and refresh (`services/shared/auth_middleware.py:42-55`).

### Main background workers

- `Confirmed from code`:
  - telemetry stage workers and maintenance loops (`data-service`)
  - rule notification worker
  - analytics job worker(s)
  - reporting worker
  - export worker
  - auth refresh-token cleanup service
  - analytics weekly retrainer

## 7. Core Data Flows

- Endpoint-level detail for these flows lives in [memory-appendix-api.md](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md); table/model detail lives in [memory-appendix-db.md](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md).

### Login / auth / session

- Trigger:
  - web/mobile login form posts credentials to auth-service.
- Services touched:
  - `auth-service`, Redis, MySQL, then frontend session helpers.
- Persistence points:
  - MySQL `users`, `refresh_tokens`.
  - Redis issued token index / revoked token keys.
- Async boundaries:
  - none required for basic login; auth-service startup also runs cleanup loop.
- Output/result:
  - `Confirmed from code`: access token returned in response body; refresh token returned in cookie for browser and in body for mobile usage path.
- Critical rules:
  - pending invite blocks login with `PASSWORD_SETUP_REQUIRED` (`auth_service.py:203-221`).
  - disabled account blocks login (`auth_service.py:223-228`).
  - org suspension blocks login (`auth_service.py:186-197`).
  - access tokens carry `permissions_version` and `tenant_entitlements_version`; mismatch invalidates token (`token_service.py:64-88`, `auth_service.py:307-339`, `services/shared/auth_middleware.py:123-170`).
  - web refresh token cookie is HttpOnly, path-scoped to `/backend/auth/api/v1/auth` (`auth-service/app/config.py:40-44`, `auth.py` cookie setter).
  - web frontend keeps access token only in memory (`ui-web/lib/browserSession.ts`).
  - mobile stores access and refresh tokens in SecureStore (`shivex-mobile/src/api/authApi.ts`).
  - exact endpoint map: [memory-appendix-api.md#auth-and-session-endpoints](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)
  - exact schema map: [memory-appendix-db.md#auth-service-schemas](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md)

### Invite user flow

- Trigger:
  - org/super admin or plant manager creates a user without password.
- Services touched:
  - `auth-service`, SMTP/Mailpit.
- Persistence points:
  - new `users` row, optional plant access rows, action token rows.
- Async boundaries:
  - email delivery call; not queued through separate worker in current auth service code.
- Output/result:
  - invitation email with frontend `/accept-invite?token=...` link.
- Critical rules:
  - plant managers can only create `operator` or `viewer` (`orgs.py:125-133`).
  - org admins cannot create `org_admin` or `super_admin` (`orgs.py:135-151`).
  - plant-scoped roles must have plant IDs; plant managers must assign exactly one plant (`orgs.py:176-204`).
  - invite acceptance hashes password, activates user, revokes prior tokens (`auth_service.py:86-111`).

### Telemetry ingest

- Trigger:
  - MQTT message on configured topic (default `devices/+/telemetry`; tenant-prefixed use is documented in README and simulator tooling).
- Services touched:
  - EMQX -> `data-service` API role -> Redis Streams -> InfluxDB -> device-service / energy-service / rule-engine-service.
- Persistence points:
  - Redis stage streams, InfluxDB telemetry bucket, MySQL outbox / DLQ rows.
- Async boundaries:
  - raw message publish to ingest stream.
  - worker stages: ingest -> projection -> broadcast -> energy -> rules.
- Output/result:
  - persisted time-series, updated device live state, downstream energy projection, rule evaluation, live broadcasts.
- Critical rules:
  - invalid messages are dead-lettered (`telemetry_service.py`, `README.md`).
  - backpressure thresholds can reject new ingest (`data-service/src/config/settings.py`).
  - projection batching groups by tenant before sync to device-service.
  - projection failures can defer/retry or continue downstream with projection error context depending on failure type.
  - exact API map: [memory-appendix-api.md#data-service](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md), [memory-appendix-api.md#5-realtime--polling-interfaces](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)
  - exact DB map: [memory-appendix-db.md#data-service-schemas](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md), [memory-appendix-db.md#device-service-schemas](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md)

### Dashboard live state

- Trigger:
  - downstream projection from telemetry pipeline and/or energy live update endpoints.
- Services touched:
  - `data-service` -> `device-service`, optionally `energy-service`, frontend protected pages.
- Persistence points:
  - `device_live_state` and related dashboard materialized data in MySQL.
  - Redis fleet/energy channels.
- Async boundaries:
  - telemetry projection stage and Redis broadcast.
- Output/result:
  - machine/fleet dashboard shows current runtime, load, health, and cost/energy state.
- Critical rules:
  - `device_live_state` is updated with optimistic locking on `version` (`live_projection.py:87-148`).
  - shift windows support overnight spans (`live_projection.py:223-242`).
  - runtime status and load state are separate concepts (`device-service/README.md`).
  - exact API map: [memory-appendix-api.md#device-service](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md), [memory-appendix-api.md#5-realtime--polling-interfaces](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)
  - exact DB map: [memory-appendix-db.md#device_live_state](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md), [memory-appendix-db.md#device_state_intervals](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md)

### Analytics job lifecycle

- Trigger:
  - analytics API job submission from UI/mobile.
- Services touched:
  - `analytics-service` API -> Redis stream or in-memory queue -> analytics worker -> MySQL/object storage/related downstreams.
- Persistence points:
  - job rows/state in MySQL, queue stream in Redis, optionally dataset access from object storage.
- Async boundaries:
  - durable queue claim/ack/retry via Redis stream.
- Output/result:
  - analytics job result persisted and returned through analytics APIs.
- Critical rules:
  - global queue backlog reject threshold -> `503` (`scaling_policy.py`, settings).
  - tenant queued/active caps -> `429`.
  - stale queued/running jobs are failed on service restart (`analytics-service/src/main.py`).
  - API role avoids importing heavyweight ML libs (`analytics-service/src/main.py`).
  - exact API map: [memory-appendix-api.md#analytics-service](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)
  - exact DB map: [memory-appendix-db.md#analytics_jobs](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md), [memory-appendix-db.md#ml_model_artifacts](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md)

### Report generation

- Trigger:
  - report request from web/mobile.
- Services touched:
  - `reporting-service` API -> Redis report queue -> reporting worker -> InfluxDB / device/energy data -> MinIO.
- Persistence points:
  - MySQL report job rows, Redis queue stream, object storage output.
- Async boundaries:
  - report queue and worker claim/timeout/retry cycle.
- Output/result:
  - report history/status/result/download URLs and stored artifact.
- Critical rules:
  - retries up to `REPORT_JOB_MAX_RETRIES` then dead-letter (`report_worker.py`, `src/config.py`).
  - report engine normalizes telemetry through shared normalization (`report_engine.py:8-10`, `58-91`).
  - `Needs runtime verification`: full precedence logic between direct energy counter vs normalized power integration because README describes a multi-step fallback order, while the scanned code path clearly computes from normalized business power.
  - exact API map: [memory-appendix-api.md#reporting-service](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)
  - exact DB map: [memory-appendix-db.md#energy_reports](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md), [memory-appendix-db.md#scheduled_reports](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md)

### Notification / alert delivery

- Trigger:
  - rule evaluates to triggered condition.
- Services touched:
  - `rule-engine-service`, SMTP, optional Twilio.
- Persistence points:
  - alert rows, notification outbox rows, delivery audit ledger, Redis stream.
- Async boundaries:
  - notification outbox queue and worker.
- Output/result:
  - queued, delivered, skipped, retried, or dead-lettered notifications.
- Critical rules:
  - alert storm protection skips evaluation if >50 alerts/device in 60s (`evaluator.py`).
  - if no recipients, outbox is marked skipped with `NO_ACTIVE_RECIPIENTS`.
  - exponential backoff and max retry logic in notification worker.
  - exact API map: [memory-appendix-api.md#rule-engine-service](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)
  - exact DB map: [memory-appendix-db.md#notification_delivery_logs](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md), [memory-appendix-db.md#notification_outbox](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md)

### Tenant switching

- Trigger:
  - super admin selects tenant in web UI or sends target tenant header.
- Services touched:
  - frontend auth context/store, auth-service `/me`, all tenant-scoped backend services through shared middleware.
- Persistence points:
  - selected tenant in web `sessionStorage` (`factoryops_selected_tenant`).
- Async boundaries:
  - none required.
- Output/result:
  - super admin can browse tenant-scoped pages as chosen org.
- Critical rules:
  - super admins may omit tenant claim and resolve tenant from `X-Target-Tenant-Id` or query param (`auth_middleware.py:179-214`).
  - non-super-admins must stay within token tenant scope.
  - web gate `SuperAdminOrgGate` blocks tenant-scoped pages until a tenant is selected.

### Export flow

- Trigger:
  - continuous export loop or manual `/api/v1/exports/run`.
- Services touched:
  - `data-export-service`, InfluxDB, MySQL checkpoint store, S3/MinIO.
- Persistence points:
  - export checkpoints table, object storage datasets.
- Async boundaries:
  - worker lifecycle inside service lifespan.
- Output/result:
  - Parquet/CSV datasets under object storage.
- Critical rules:
  - forced export validates paired `start_time` / `end_time` and maximum export window (`data-export-service/main.py`).
  - tenant/device scoping enforced before force export.

### Waste-analysis flow

- Trigger:
  - `/analysis/run` request.
- Services touched:
  - `waste-analysis-service`, device-service, InfluxDB, reporting-service, energy-service, MinIO.
- Persistence points:
  - MySQL waste job rows/history, MinIO report output.
- Async boundaries:
  - FastAPI background task with timeout wrapper.
- Output/result:
  - job history/status/result/download artifact URL.
- Critical rules:
  - active duplicate requests are deduped at job creation.
  - concurrency is bounded by configured value and CPU-based safety cap (`waste_task.py:40-44`).
  - quality gate can fail the job if `WASTE_STRICT_QUALITY_GATE` is enabled.
  - public warnings suppress internal/noise warnings before returning results (`waste_task.py:20-37`, `73-81`).

### Copilot flow

- Trigger:
  - `/api/v1/copilot/chat`.
- Services touched:
  - `copilot-service`, readonly MySQL, AI provider, tariff service client.
- Persistence points:
  - none obvious for conversation persistence in scanned code.
- Async boundaries:
  - AI provider call and SQL execution timeout boundary.
- Output/result:
  - natural-language answer, reasoning, error code if unavailable.
- Critical rules:
  - tenant required from request context (`chat.py:35-37`).
  - SQL is validated by `SQLGuard` and tenant filters are injected on tenant-scoped tables (`query_engine.py:29-112`).
  - query timeout and max rows enforced (`query_engine.py:113-137`, `src/config.py`).

## 8. Authentication and Authorization

- Detailed auth endpoint and DTO catalog: [memory-appendix-api.md#auth-service](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)
- Detailed auth schema and tenant-isolation map: [memory-appendix-db.md#auth-service-schemas](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md), [memory-appendix-db.md#5-tenant-isolation-in-data-model](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md)

- Auth model:
  - `Confirmed from code`: JWT access token + DB-backed refresh token model.

- Token/session model:
  - `Confirmed from code`: access tokens are signed JWTs with revocation via Redis `token:revoked:{jti}` (`token_service.py:24-46`, `154-165`).
  - `Confirmed from code`: issued token JTIs are tracked per user in Redis for bulk revocation (`token_service.py:33-61`, `167-190`).
  - `Confirmed from code`: refresh tokens are opaque random strings; only SHA-256 hashes are stored in DB (`token_service.py:191-246`).

- Refresh flow:
  - `Confirmed from code`: refresh endpoint accepts body token or cookie token; web path expects cookie and enforces origin validation.
  - `Confirmed from code`: refresh rotation revokes old refresh token and issues a new one (`auth_service.py:276-305`).
  - `Confirmed from code`: endpoint changes must preserve both cookie-based web refresh and body-token/mobile refresh.

- Cookie handling:
  - `Confirmed from code`: refresh cookie is HttpOnly, path-scoped, same-site configurable, secure only in production (`auth-service/app/config.py:40-62`).

- Browser storage behavior:
  - `Confirmed from code`: web keeps access token in memory only and stores `/me` plus selected tenant in `sessionStorage`.
  - `Confirmed from code`: mobile stores access token, refresh token, and cached profile in Expo SecureStore.

- Roles found:
  - `Confirmed from code`: `super_admin`, `org_admin`, `plant_manager`, `operator`, `viewer`.

- Auth middleware:
  - `Confirmed from code`: `services/shared/auth_middleware.py` runs on services, validates Bearer tokens, refreshes tenant/entitlement freshness from DB, resolves tenant context, and attaches request state.
  - `Confirmed from code`: internal services can bypass Bearer auth using `X-Internal-Service` plus tenant headers (`auth_middleware.py:58-75`, `300-307`).

- Tenant isolation enforcement points:
  - `Confirmed from code`:
    - middleware tenant resolution
    - tenant guards (`assert_same_tenant`, `assert_plants_belong_to_tenant`)
    - tenant-scoped repositories
    - copilot SQL tenant injection
    - frontend super-admin gate

- Super-admin / tenant switching:
  - `Confirmed from code`: super admins are treated as org-admin for entitlement display but can switch target tenant via header/query/UI selector.

## 9. Frontend Architecture

- Routing structure:
  - `Confirmed from code`: App Router in `ui-web/app`.
  - public routes: `/login`, `/forgot-password`, `/reset-password`, `/accept-invite`.
  - protected domains include `/admin`, `/analytics`, `/calendar`, `/copilot`, `/devices`, `/machines`, `/org/*`, `/tenant/*`, `/reports`, `/rules`, `/settings`, `/waste-analysis`, `/profile`.

- Protected vs public:
  - `Confirmed from code`: root layout wraps `AuthProvider`; protected layout uses `AuthGuard`.
  - `Confirmed from code`: `SuperAdminOrgGate` enforces tenant selection for super admins on tenant-scoped views.

- API calling pattern:
  - `Confirmed from code`: Next.js rewrites proxy `/backend/*` and `/api/reports/*`, `/api/waste/*` to internal service URLs (`ui-web/next.config.ts`).
  - `Confirmed from code`: `apiFetch` injects access token and tenant headers.

- Auth/session handling:
  - `Confirmed from code`: `authApi` handles login, refresh, `/me`, org selection flows.
  - `Confirmed from code`: no persistent access-token local storage on web.

- Reusable UI systems:
  - `Confirmed from code`: shared components under `ui-web/components`, Radix-based component patterns, React Query data layer.
  - `Needs runtime verification`: exact design-system completeness because only architecture files, not every component, were inspected.

- Live update / polling / stream patterns:
  - `Inferred from usage`: device/machine dashboard pages likely consume device/energy live APIs and/or WebSocket/polling helpers.
  - `Confirmed from code`: backend supports live-update and fleet streams; frontend route domains exist for dashboards.
  - Detailed interfaces: [memory-appendix-api.md#5-realtime--polling-interfaces](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)

- Major page domains:
  - `Confirmed from code`: auth, admin/tenants/orgs, devices/machines, analytics, reports, rules, settings, waste-analysis, copilot, calendar, profile.

## 10. Background Jobs and Workers

### Data-service telemetry pipeline

- Responsibility:
  - persist telemetry, project device state, fan out broadcast/energy/rules.
- Queue source:
  - Redis Streams.
- Retry behavior:
  - max attempts and DLQ settings in `data-service/src/config/settings.py`.
- Trigger type:
  - MQTT ingress and stage publish chain.
- Key files:
  - `src/workers/telemetry_pipeline.py`
  - `src/services/telemetry_service.py`
  - `src/services/outbox_relay.py`

### Data-service outbox relay / reconciliation

- Responsibility:
  - durable relay of downstream energy deliveries and drift repair.
- Queue source:
  - MySQL outbox rows + reconciliation scans.
- Retry behavior:
  - `outbox_max_retries`, circuit breaker thresholds, dead-letter retention.
- Trigger type:
  - polling loops on worker maintenance instance.

### Rule-engine notification worker

- Responsibility:
  - deliver queued notifications.
- Queue source:
  - Redis stream `rule-engine:notification-outbox` by default (`app/config.py`).
- Retry behavior:
  - exponential backoff, terminal dead-letter after `NOTIFICATION_OUTBOX_MAX_RETRIES`.
- Trigger type:
  - rule trigger outbox enqueue.

### Analytics job worker

- Responsibility:
  - claim and execute analytics jobs, heartbeat, stale recovery.
- Queue source:
  - Redis stream or in-memory queue.
- Retry behavior:
  - `queue_max_attempts`, dead-letter stream.
- Trigger type:
  - analytics API job submission.

### Analytics weekly retrainer

- Responsibility:
  - scheduled retraining (`Inferred from usage` based on `WeeklyRetrainer` startup path).
- Queue source:
  - internal scheduler, not an external queue.
- Retry behavior:
  - `Needs runtime verification`.

### Reporting worker

- Responsibility:
  - claim and generate reports.
- Queue source:
  - Redis stream `reporting:jobs`.
- Retry behavior:
  - retries until `REPORT_JOB_MAX_RETRIES`, then dead-letter.
- Trigger type:
  - report creation API.

### Data export worker

- Responsibility:
  - export telemetry windows to object storage, maintain checkpoints.
- Queue source:
  - internal continuous worker loop, plus forced export triggers.
- Retry behavior:
  - `Needs runtime verification` for exact backoff implementation unless inspecting `worker.py`.

### Auth refresh token cleanup service

- Responsibility:
  - background cleanup of expired refresh tokens.
- Trigger type:
  - startup in auth-service lifespan.

## 11. Environment Variables and Configuration

### Shared / cross-service

- `JWT_SECRET_KEY`
  - purpose: sign and validate access tokens.
  - used by: auth-service, shared auth middleware.
  - required: effectively required.
  - sensitive: yes.
- `REDIS_URL`
  - purpose: token revocation, queueing, pub/sub, streams.
  - used by: auth-service, device-service, rule-engine-service, analytics-service, reporting-service, data-service, energy-service.
  - sensitive: no.
- `DATABASE_URL`
  - purpose: primary MySQL DSN for many services.
  - used by: auth-service, device-service, energy-service, rule-engine-service, reporting-service, waste-analysis-service.
  - sensitive: yes.
- `INFLUXDB_URL`, `INFLUXDB_TOKEN`, `INFLUXDB_ORG`, `INFLUXDB_BUCKET`
  - purpose: telemetry time-series connection.
  - used by: data-service, reporting-service, waste-analysis-service, data-export-service.
  - sensitive: token yes.
- `MINIO_ENDPOINT`, `MINIO_EXTERNAL_URL`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`
  - purpose: object storage.
  - used by: reporting-service, waste-analysis-service.
  - sensitive: access/secret yes.

### Auth-service (`services/auth-service/app/config.py`)

- `DATABASE_URL`
- `REDIS_URL`
- `JWT_SECRET_KEY`
- `JWT_ALGORITHM`
- `ACCESS_TOKEN_EXPIRE_MINUTES`
- `REFRESH_TOKEN_EXPIRE_DAYS`
- `SERVICE_HOST`
- `SERVICE_PORT`
- `LOG_LEVEL`
- `ENVIRONMENT`
- `SQLALCHEMY_ECHO`
- `EMAIL_ENABLED`
- `EMAIL_SMTP_HOST` / aliases `SMTP_SERVER`, `AUTH_SMTP_SERVER`
- `EMAIL_SMTP_PORT` / aliases `SMTP_PORT`, `AUTH_SMTP_PORT`
- `EMAIL_SMTP_USERNAME` / aliases `SMTP_USERNAME`, `AUTH_SMTP_USERNAME`, `EMAIL_SENDER`
- `EMAIL_SMTP_PASSWORD` / aliases `EMAIL_PASSWORD`, `AUTH_EMAIL_PASSWORD`
- `EMAIL_FROM_ADDRESS` / aliases `EMAIL_FROM_ADDRESS`, `EMAIL_SENDER`, `EMAIL_SMTP_USERNAME`
- `PLATFORM_NAME`
- `FRONTEND_BASE_URL`
- `AUTH_ALLOWED_ORIGINS`
- `REFRESH_COOKIE_NAME`
- `REFRESH_COOKIE_DOMAIN`
- `REFRESH_COOKIE_PATH`
- `REFRESH_COOKIE_SAMESITE`
- `BOOTSTRAP_SUPER_ADMIN_EMAIL`
- `BOOTSTRAP_SUPER_ADMIN_PASSWORD`
- `BOOTSTRAP_SUPER_ADMIN_FULL_NAME`
- `INVITE_TOKEN_EXPIRE_MINUTES`
- `PASSWORD_RESET_EXPIRE_MINUTES`
- `LOGIN_RATE_LIMIT`
- `PASSWORD_FORGOT_RATE_LIMIT`
- `INVITATION_ACCEPT_RATE_LIMIT`

### Device-service (`services/device-service/app/config.py`)

- `DATABASE_URL`
- `AUTH_SERVICE_URL` / `AUTH_SERVICE_BASE_URL`
- `DATA_SERVICE_BASE_URL`
- `RULE_ENGINE_SERVICE_BASE_URL`
- `REPORTING_SERVICE_BASE_URL`
- `ENERGY_SERVICE_BASE_URL`
- `ENERGY_SERVICE_TIMEOUT_SECONDS`
- `PROJECTION_BATCH_CHUNK_SIZE`
- performance/dashboard/snapshot settings:
  - `PERFORMANCE_TRENDS_*`
  - `DASHBOARD_*`
  - `STATE_INTERVAL_*`
  - `SNAPSHOT_STORAGE_BACKEND`
  - `SNAPSHOT_MINIO_BUCKET`
  - `SNAPSHOT_MINIO_ENDPOINT`
  - `SNAPSHOT_MINIO_ACCESS_KEY`
  - `SNAPSHOT_MINIO_SECRET_KEY`
  - `SNAPSHOT_MINIO_SECURE`
  - `MIGRATE_SNAPSHOTS_TO_MINIO`
- `REDIS_URL`
- `FLEET_STREAM_REDIS_CHANNEL_TEMPLATE`
- `BOOTSTRAP_DEMO_DEVICES`

### Data-service (`services/data-service/src/config/settings.py`)

- MQTT:
  - `MQTT_BROKER_HOST`, `MQTT_BROKER_PORT`, `MQTT_USERNAME`, `MQTT_PASSWORD`, `MQTT_TOPIC`, `MQTT_QOS`, `MQTT_RECONNECT_INTERVAL`, `MQTT_MAX_RECONNECT_ATTEMPTS`, `MQTT_KEEPALIVE`, `MQTT_CLEAN_SESSION`
- Redis / worker:
  - `REDIS_URL`, `APP_ROLE`, `TELEMETRY_WORKER_CONSUMER_NAME`, `TELEMETRY_WORKER_MAINTENANCE_ENABLED`, `TELEMETRY_WORKER_OUTBOX_RELAY_ENABLED`
  - all `telemetry_*stream*`, `telemetry_*threshold*`, `telemetry_*workers`, `telemetry_*batch_size`, heartbeat, reclaim, retry settings
- Influx:
  - `INFLUXDB_URL`, `INFLUXDB_TOKEN`, `INFLUXDB_ORG`, `INFLUXDB_BUCKET`, `INFLUXDB_TIMEOUT`
- Downstream:
  - `DEVICE_SERVICE_URL`, `ENERGY_SERVICE_URL`, `RULE_ENGINE_URL`
- MySQL helper vars:
  - `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD`
- Outbox / reconciliation / DLQ:
  - `OUTBOX_*`, `RECONCILIATION_*`, `CIRCUIT_BREAKER_*`, `DLQ_*`
- Telemetry validation:
  - `TELEMETRY_MAX_VOLTAGE`, `TELEMETRY_MIN_VOLTAGE`, `TELEMETRY_MAX_CURRENT`, `TELEMETRY_MAX_POWER`, etc.
- WebSocket:
  - `WS_HEARTBEAT_INTERVAL`, `WS_MAX_CONNECTIONS`

### Energy-service (`services/energy-service/app/config.py`)

- `DATABASE_URL`
- `REDIS_URL`
- `ENERGY_STREAM_REDIS_CHANNEL`
- `REPORTING_SERVICE_BASE_URL`
- `DEVICE_SERVICE_BASE_URL`
- `PLATFORM_TIMEZONE`
- `TARIFF_CACHE_TTL_SECONDS`
- `MAX_FALLBACK_GAP_SECONDS`
- `LIVE_UPDATE_MAX_REORDER_SECONDS`
- `CIRCUIT_BREAKER_FAILURE_THRESHOLD`
- `CIRCUIT_BREAKER_OPEN_TIMEOUT_SEC`
- `CIRCUIT_BREAKER_SUCCESS_THRESHOLD`
- `ENERGY_BATCH_CHUNK_SIZE`

### Rule-engine-service (`services/rule-engine-service/app/config.py`)

- `DATABASE_URL`
- `EMAIL_SMTP_HOST`
- `EMAIL_SMTP_PORT`
- `EMAIL_SMTP_USERNAME`
- `EMAIL_SMTP_PASSWORD`
- `EMAIL_FROM_ADDRESS`
- `SMS_ENABLED`
- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `TWILIO_SMS_FROM_NUMBER`
- `WHATSAPP_ENABLED`
- `TWILIO_WHATSAPP_FROM_NUMBER`
- `DEVICE_SERVICE_URL`
- `REDIS_URL`
- `APP_ROLE`
- `QUEUE_BACKEND`
- queue settings for notification outbox streams/groups/consumer/retries/backoff/timeouts
- `NOTIFICATION_COOLDOWN_MINUTES`
- `MAX_RULES_PER_DEVICE`
- `PLATFORM_TIMEZONE`

### Analytics-service (`services/analytics-service/src/config/settings.py`)

- MySQL:
  - `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD`
- Object storage:
  - `S3_BUCKET_NAME`, `S3_REGION`, `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`
- Queue/scaling:
  - `MAX_CONCURRENT_JOBS`, `GLOBAL_ACTIVE_JOB_LIMIT`, `QUEUE_MAX_LENGTH`, `QUEUE_BACKLOG_REJECT_THRESHOLD`, `TENANT_MAX_QUEUED_JOBS`, `TENANT_MAX_ACTIVE_JOBS`
  - `QUEUE_BACKEND`, `REDIS_URL`, stream/group/consumer names, heartbeat TTL
- ML feature flags:
  - `ML_ANALYTICS_V2_ENABLED`, `ML_FORMATTED_RESULTS_ENABLED`, `ML_WEEKLY_RETRAINER_ENABLED`, `ML_FLEET_STRICT_ENABLED`, `ML_DATA_READINESS_GATE_ENABLED`, `ML_REQUIRE_EXACT_DATASET_RANGE`, `ML_MAX_DATASET_ROWS`
- Downstream:
  - `DATA_EXPORT_SERVICE_URL`, `DATA_SERVICE_URL`, `DEVICE_SERVICE_URL`

### Reporting-service (`services/reporting-service/src/config.py`)

- `DATABASE_URL`
- `INFLUXDB_URL`
- `INFLUXDB_TOKEN`
- `INFLUXDB_ORG`
- `INFLUXDB_BUCKET`
- measurement/field names such as `INFLUX_POWER_FIELD`, `INFLUX_VOLTAGE_FIELD`, `INFLUX_CURRENT_FIELD`
- `DEVICE_SERVICE_URL`
- `ENERGY_SERVICE_URL`
- MinIO vars listed above
- `PLATFORM_TIMEZONE`
- `DEMAND_WINDOW_MINUTES`
- `REPORT_JOB_TIMEOUT_SECONDS`
- `APP_ROLE`
- queue vars: `QUEUE_BACKEND`, `REDIS_URL`, `REPORT_QUEUE_*`, `REPORT_WORKER_CONCURRENCY`, retry and metrics cache settings

### Waste-analysis-service (`services/waste-analysis-service/src/config.py`)

- `DATABASE_URL`
- `INFLUXDB_URL`
- `INFLUXDB_TOKEN`
- `INFLUXDB_ORG`
- `INFLUXDB_BUCKET`
- `DEVICE_SERVICE_URL`
- `REPORTING_SERVICE_URL`
- `ENERGY_SERVICE_URL`
- MinIO vars listed above
- `MINIO_BUCKET`
- `PLATFORM_TIMEZONE`
- `TARIFF_CACHE_TTL_SECONDS`
- `WASTE_STRICT_QUALITY_GATE`
- `WASTE_JOB_TIMEOUT_SECONDS`
- `WASTE_DEVICE_CONCURRENCY`
- `WASTE_DB_BATCH_SIZE`
- `WASTE_PDF_MAX_DEVICES`

### Data-export-service (`services/data-export-service/config.py`)

- `influxdb_url`
- `influxdb_token`
- `influxdb_org`
- `influxdb_bucket`
- `data_service_url`
- `export_interval_seconds`
- `export_batch_size`
- `export_format`
- `s3_bucket`
- `s3_prefix`
- `s3_region`
- `s3_endpoint_url`
- `aws_access_key_id`
- `aws_secret_access_key`
- checkpoint DB vars:
  - `checkpoint_db_host`, `checkpoint_db_port`, `checkpoint_db_name`, `checkpoint_db_user`, `checkpoint_db_password`, `checkpoint_table`
- `lookback_hours`
- `max_export_window_hours`
- `max_force_export_window_hours`
- `device_ids`

### Copilot-service (`services/copilot-service/src/config.py`)

- `AI_PROVIDER`
- `GROQ_API_KEY`
- `GROQ_MODEL`
- `GEMINI_API_KEY`
- `OPENAI_API_KEY`
- `MYSQL_URL`
- `MYSQL_READONLY_URL`
- `DATA_SERVICE_URL`
- `REPORTING_SERVICE_URL`
- `ENERGY_SERVICE_URL`
- `FACTORY_TIMEZONE`
- `MAX_QUERY_ROWS`
- `QUERY_TIMEOUT_SEC`
- `MAX_HISTORY_TURNS`
- `STAGE1_MAX_TOKENS`
- `STAGE2_MAX_TOKENS`

### Frontend proxy/runtime configuration

- `Confirmed from code`: `ui-web/next.config.ts` expects backend service base URLs for rewrites. Exact env var names should be confirmed in that file before changing deployment configuration.
- `Needs runtime verification`: production hostnames and CDN/proxy layout.

## 12. External Integrations

- EMQX / MQTT
  - purpose: device telemetry ingress.
  - protocol: MQTT.
  - files: `data-service` settings and README, simulator tooling, `docker-compose.yml`.
  - auth: username/password optional in settings.

- MySQL
  - purpose: relational source of truth for auth, tenant, device, job, outbox, checkpoints.
  - protocol: SQLAlchemy/MySQL drivers.

- InfluxDB
  - purpose: telemetry time-series storage and reporting source.
  - protocol: Influx HTTP client.
  - files: data-service, reporting-service, waste-analysis-service, data-export-service configs.
  - auth: token.

- Redis
  - purpose: auth revocation, queues, pub/sub, stream heartbeats.
  - protocol: Redis client.

- MinIO / S3-compatible storage
  - purpose: report files, datasets, waste outputs, dashboard snapshot migration path.
  - protocol: S3 API / MinIO client.
  - auth: access key + secret.

- SMTP / Mailpit
  - purpose: invitation and password reset emails, alert emails.
  - protocol: SMTP.
  - files: auth-service mailer config, rule-engine notification adapters, `docker-compose.yml`.

- Twilio SMS / WhatsApp
  - purpose: notification delivery from rule-engine.
  - protocol: Twilio API/SDK path inferred from config and adapter naming.
  - auth: account SID + auth token.

- Groq
  - purpose: default AI provider for copilot.
  - protocol: API SDK/client.
  - files: `services/copilot-service/src/config.py`.

- Gemini
  - purpose: optional AI provider.
  - protocol: API.

- OpenAI
  - purpose: optional AI provider for copilot.
  - protocol: API.

- Prometheus / Grafana / Alertmanager
  - purpose: metrics scraping, dashboards, alert routing.
  - protocol: HTTP scraping/configured dashboards.

## 13. Business Logic Rules

- Feature entitlements:
  - `Confirmed from code`: baseline role features:
    - `org_admin`: `machines`, `calendar`, `rules`, `settings`
    - `plant_manager`: `machines`, `rules`, `settings`
    - `operator`: `machines`, `rules`
    - `viewer`: `machines`
    (`services/shared/feature_entitlements.py:23-28`)
  - `Confirmed from code`: org grantable premium features are `analytics`, `reports`, `waste_analysis`, `copilot` (`feature_entitlements.py:30-35`).
  - `Confirmed from code`: plant managers can delegate only `analytics`, `reports`, `waste_analysis` (`feature_entitlements.py:37-41`).

- Telemetry normalization:
  - `Confirmed from code`: shared normalization version is `signed-power-v1` (`services/shared/telemetry_normalization.py:13`).
  - `Confirmed from code`: default energy flow mode is `consumption_only`; default fallback power factor is `0.85` (`telemetry_normalization.py:14-17`).

- Device health / runtime:
  - `Confirmed from code`: valid machine states include `RUNNING`, `OFF`, `IDLE`, `UNLOAD`, `POWER CUT`.
  - `Confirmed from code`: scoreable states are `RUNNING`, `IDLE`, `UNLOAD`.
  - `Confirmed from code`: standby states are `OFF`, `POWER CUT`.
  - `Confirmed from code`: duplicate health configs for the same canonical parameter are blocked.

- Alert/rule behavior:
  - `Confirmed from code`: max 100 rules per device by config default.
  - `Confirmed from code`: alert storm suppression after >50 alerts/device in 60 seconds.
  - `Confirmed from code`: notification cooldown defaults to 15 minutes.
  - `Confirmed from code`: time-window rules support overnight windows using platform timezone.

- Analytics fairness/caps:
  - `Confirmed from code`:
    - global active job limit `48`
    - queue backlog reject threshold `500`
    - tenant max queued `25`
    - tenant max active `8`
    - queue max attempts `3`
    (`analytics-service/src/config/settings.py`)

- Reporting:
  - `Confirmed from code`: reporting normalizes telemetry before computing energy/peak/load-factor values (`report_engine.py:58-91`, `188-227`).
  - `Confirmed from code`: load-factor band thresholds:
    - `<30`: `poor`
    - `30-70`: `moderate`
    - `>70`: `good`
    (`report_engine.py:165-172`)

- Waste-analysis:
  - `Confirmed from code`: public-facing warnings intentionally suppress internal markers and some no-op warnings (`waste_task.py:20-37`, `73-81`).
  - `Confirmed from code`: result includes off-hours, overconsumption, unoccupied-running, idle breakdowns.
  - `Confirmed from code`: per-device concurrency is capped to `min(configured, max(4, cpu*4))` (`waste_task.py:40-44`).
  - `Confirmed from code`: config default `WASTE_STRICT_QUALITY_GATE=False` (`waste-analysis-service/src/config.py:38`).
  - `Confirmed from docs`: waste README appears to describe stricter quality-gate behavior as default.
  - Repository discrepancy:
    - `Confirmed from code`: config default is false.
    - `Confirmed from docs`: README indicates strict mode behavior.
    - Treat this as a real configuration/documentation mismatch.

- Copilot:
  - `Confirmed from code`: SQL queries are tenant-filtered if referenced tables carry `tenant_id` in the schema manifest.
  - `Confirmed from code`: blocked/invalid SQL returns structured `QUERY_BLOCKED`, `QUERY_TIMEOUT`, or `QUERY_FAILED`.

- Tenant constraints:
  - `Confirmed from code`: non-super-admins cannot operate without tenant scope.
  - `Confirmed from code`: cross-tenant access may return 404 for obscurity and logs an audit record in `tenant_security_audit_log`.

## 14. Error Handling and Observability

- Error handling style:
  - `Confirmed from code`: FastAPI exception handlers return structured JSON payloads with `code`, `message`, and sometimes `details`.
  - `Confirmed from code`: services often convert internal errors to stable domain codes like `INVALID_TOKEN`, `EXPORT_TRIGGER_FAILED`, `AI_UNAVAILABLE`.

- Custom exception patterns:
  - `Confirmed from code`: auth and tenant helpers raise `HTTPException` with structured details.
  - `Confirmed from code`: frontend throws client-side `TenantNotSelectedError` for super-admin flows.

- Logging style:
  - `Confirmed from code`: Python `logging` used throughout; several services favor structured `extra={...}` payloads.
  - `Confirmed from code`: data-export-service sets up structured logging via `logging_config.py`.

- Health endpoints:
  - `Confirmed from code`: `/health`, `/ready`, `/metrics` are common across services.

- Metrics/monitoring:
  - `Confirmed from code`: Prometheus stack is configured in `monitoring/prometheus/prometheus.yml`.
  - `Confirmed from code`: device SLO rules exist in `monitoring/prometheus/rules/device-slo-alerts.yml`.
  - `Confirmed from code`: Grafana dashboard JSON exists for device SLOs.

- Retry/dead-letter concepts:
  - `Confirmed from code`: data-service DLQ with durable MySQL backend by default.
  - `Confirmed from code`: analytics dead-letter stream.
  - `Confirmed from code`: reporting dead-letter stream.
  - `Confirmed from code`: rule notification outbox dead-letter stream.

## 15. Testing Structure

- Layout:
  - `Confirmed from code`: per-service `tests/` directories under backend services.
  - `Confirmed from code`: top-level `tests/e2e`, `tests/integration`, `tests/regression`.
  - `Confirmed from code`: `ui-web/tests/unit` and `ui-web/tests/e2e`.

- Naming conventions:
  - `Confirmed from code`: backend uses `test_*.py`.
  - `Confirmed from code`: top-level regression/e2e tests use numbered files like `test_19_energy_dashboard_regression.py`.

- Test types:
  - `Confirmed from code`: unit and integration coverage for auth, tenant scoping, energy/reporting/waste flows.
  - `Confirmed from code`: Playwright/browser tests in web app.
  - `Not found in repository`: obvious dedicated mobile test suite.

- Common test commands:
  - `Confirmed from code`: web package scripts include `test:unit` and `test:e2e`.
  - `Inferred from usage`: backend services use `pytest`.

## 16. Change Impact Map

### Auth / tenant / entitlements

- Files usually touched together:
  - auth routes, `auth_service.py`, `token_service.py`, shared middleware, frontend auth context/api, mobile auth API.
- Regression risks:
  - web refresh cookie path/origin behavior
  - token freshness invalidation
  - super-admin tenant switching
  - invite/reset flow links
- Tests to run:
  - auth-service tests, top-level tenant scope/auth regression tests, web auth unit/e2e tests.
- Common pitfalls:
  - forgetting `permissions_version` or `tenant_entitlements_version`
  - breaking cookie-based refresh while mobile still uses body token
  - bypassing tenant guards in service-to-service paths
- Exact API/DB references:
  - [memory-appendix-api.md#auth-service](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)
  - [memory-appendix-db.md#auth-service-schemas](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md)
  - [memory-appendix-db.md#5-tenant-isolation-in-data-model](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md)

### Telemetry / live dashboard

- Files usually touched together:
  - data-service pipeline + device live projection + energy-service live update + frontend dashboard clients.
- Regression risks:
  - backlog thresholds
  - DLQ classification
  - duplicate/reordered telemetry behavior
  - optimistic lock conflicts in live state
- Tests to run:
  - data-service tests, energy/device regression tests, energy dashboard top-level regression.
- Common pitfalls:
  - changing telemetry field names without updating shared normalization
  - missing tenant headers on downstream calls
- Exact API/DB references:
  - [memory-appendix-api.md#data-service](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)
  - [memory-appendix-api.md#device-service](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)
  - [memory-appendix-db.md#data-service-schemas](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md)
  - [memory-appendix-db.md#device-service-schemas](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md)

### Rules / alerts / notifications

- Files usually touched together:
  - evaluator, notification outbox, worker, frontend rules pages.
- Regression risks:
  - alert storms
  - cooldown logic
  - no-recipient behavior
  - dead-letter growth
- Tests to run:
  - rule-engine tests, notification-related integration tests.
- Exact API/DB references:
  - [memory-appendix-api.md#rule-engine-service](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)
  - [memory-appendix-db.md#rule-engine-service-schemas](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md)

### Analytics

- Files usually touched together:
  - analytics API, queue worker, scaling policy, result formatter, frontend analytics pages.
- Regression risks:
  - queue fairness and tenant throttling
  - stale-job restart handling
  - ML import leakage into API role
- Tests to run:
  - analytics service tests, any end-to-end analytics regression coverage.
- Exact API/DB references:
  - [memory-appendix-api.md#analytics-service](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)
  - [memory-appendix-db.md#analytics-service-schemas](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md)

### Reporting / exports / waste

- Files usually touched together:
  - reporting engine, report worker, data export, waste-analysis task/handlers, MinIO configs, frontend reports/waste pages.
- Regression risks:
  - telemetry normalization consistency
  - report artifact storage URLs
  - quality gate behavior
  - cross-service tenant-scoped HTTP calls
- Tests to run:
  - reporting, waste-analysis, export-related tests and top-level report/waste regressions.
- Common pitfalls:
  - README/config mismatches
  - assuming energy counter precedence not actually implemented in scanned code path
- Exact API/DB references:
  - [memory-appendix-api.md#reporting-service](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)
  - [memory-appendix-api.md#waste-analysis-service](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)
  - [memory-appendix-api.md#data-export-service](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)
  - [memory-appendix-db.md#reporting-service-schemas](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md)
  - [memory-appendix-db.md#waste-analysis-service-schemas](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md)

### Copilot

- Files usually touched together:
  - chat API, model client, SQL guard, schema loader, web/mobile copilot pages.
- Regression risks:
  - unsafe SQL allowance
  - missing tenant filter injection
  - provider fallback handling
- Tests to run:
  - copilot service tests plus tenant-scope/security regressions.
- Exact API/DB references:
  - [memory-appendix-api.md#copilot-service](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)

## 17. Known Issues / Tech Debt

- Waste strict-quality gate documentation mismatch
  - file reference: `services/waste-analysis-service/src/config.py`, service README.
  - impact: operators may assume stricter default enforcement than the running config actually provides.

- Branding inconsistency across product names
  - file reference: root `README.md`, `services/auth-service/app/config.py`, `shivex-mobile/`, likely web metadata files.
  - impact: naming drift may cause confusion in prompts, emails, tenant-facing UI, and deployment configuration.

- Reporting energy precedence not fully self-evident from scanned implementation
  - file reference: `services/reporting-service/src/services/report_engine.py`, reporting README.
  - impact: future changes to energy calculations need careful verification against tests and expected contract.

- Default bootstrap super-admin credentials are hard-coded in config
  - file reference: `services/auth-service/app/config.py:45-47`
  - impact: acceptable for bootstrap/dev flow only; high operational sensitivity if not overridden outside local/dev.

## 18. Glossary

- tenant
  - `Confirmed from code`: organization-level isolation boundary, often synonymous with org in request routing and data ownership.

- org / organization
  - `Confirmed from code`: tenant record managed by auth-service; carries activation status and premium feature entitlements.

- plant
  - `Confirmed from code`: sub-scope within a tenant used for plant-manager/operator/viewer access control.

- telemetry
  - `Confirmed from code`: device sensor/time-series payload including energy and electrical metrics persisted to InfluxDB.

- FLA
  - `Inferred from usage`: full-load amps / full-load current. Appears in waste-analysis result fields such as `full_load_current_a`.

- load state
  - `Confirmed from code`: machine load classification persisted in device live state; distinct from runtime status.

- runtime status
  - `Confirmed from code`: running/stopped-style state separate from load classification in device-service.

- overconsumption
  - `Confirmed from code`: waste-analysis category comparing measured behavior against overconsumption thresholds/config.

- idle
  - `Confirmed from code`: machine state / waste category representing low-load but active behavior; used by rules and waste/reporting logic.

- fleet
  - `Confirmed from code`: multi-device dashboard/live stream view in device-service.

- outbox
  - `Confirmed from code`: durable table/stream-backed dispatch record used for energy delivery and notifications.

- DLQ
  - `Confirmed from code`: dead-letter queue/stream/table for failed telemetry, notification, analytics, or reporting items.

- curated questions
  - `Confirmed from code`: predefined copilot starter prompts returned by `/api/v1/copilot/curated-questions`.

- premium feature grants
  - `Confirmed from code`: organization-level enabled premium modules: `analytics`, `reports`, `waste_analysis`, `copilot`.

- role feature matrix
  - `Confirmed from code`: delegated feature enablement matrix applied to tenant roles beneath the org-level premium grants.
