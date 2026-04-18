# Database Appendix

- Repository: `FactoryOPS-Cittagent-Obeya-main`
- Generation date: `2026-04-18`
- Branch: `main`
- Repository memory overview: [memory.md](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory.md)
- API appendix: [memory-appendix-api.md](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-api.md)
- Scope scanned: SQLAlchemy/declarative models, Alembic migrations, raw SQL bootstrap scripts, repository/query layers, selected service config and shared tenant-scoping helpers.
- Certainty labels used:
  - `Confirmed from model/migration`
  - `Inferred from repository/query usage`
  - `Needs runtime verification`

## 1. Database Overview

### Datastores found

| Datastore / engine | Services using it | Purpose | Evidence |
| --- | --- | --- | --- |
| MySQL / InnoDB | auth-service, device-service, data-service, analytics-service, reporting-service, rule-engine-service, waste-analysis-service | Primary relational store for auth, tenant catalog, device metadata, reports, rules, jobs, outbox, audit, and waste jobs | [auth model](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/auth-service/app/models/auth.py), [device model](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/device-service/app/models/device.py), [analytics DB model](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/analytics-service/src/models/database.py), [reporting models](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/reporting-service/src/models), [rule-engine model](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/rule-engine-service/app/models/rule.py), [waste model](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/waste-analysis-service/src/models/waste_jobs.py) |
| InfluxDB | data-service | Time-series telemetry store, measurement `device_telemetry`, tag-scoped by `tenant_id` and `device_id` | `Confirmed from model/migration` for API contract, `Confirmed from repository/query usage` for storage pattern; [Influx repository](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/data-service/src/repositories/influxdb_repository.py) |
| Redis | data-service | Telemetry stream queues, consumer groups, worker health heartbeats, stream metrics | `Confirmed from repository/query usage`; [telemetry stream](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/data-service/src/queue/telemetry_stream.py), [settings](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/data-service/src/config/settings.py) |
| MinIO / S3-compatible object storage | device-service, analytics-service, reporting-service, waste-analysis-service | Dashboard snapshots, report exports, analytics artifacts/results, waste exports | `Confirmed from model/migration` for DB pointers like `s3_key`; object layout itself `Needs runtime verification`; [dashboard snapshot migration](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/device-service/alembic/versions/add_dashboard_snapshot_minio_storage.py), [energy report model](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/reporting-service/src/models/energy_reports.py), [waste model](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/waste-analysis-service/src/models/waste_jobs.py) |

### ORM / query patterns by service

| Service | Pattern | Notes |
| --- | --- | --- |
| auth-service | SQLAlchemy 2.0 typed declarative + async repositories | Tenant ownership is first-class on `organizations`, `plants`, `users`, `auth_action_tokens`; [auth model](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/auth-service/app/models/auth.py), [user repo](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/auth-service/app/repositories/user_repository.py) |
| device-service | SQLAlchemy 2.0 typed declarative + shared `TenantScopedRepository` | Composite `(device_id, tenant_id)` ownership is central after migration `20260329_0001`; [device model](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/device-service/app/models/device.py), [device repo](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/device-service/app/repositories/device.py) |
| data-service | SQLAlchemy declarative for local MySQL tables; InfluxDB SDK for time-series; raw SQL in repositories; Redis streams | MySQL used only for durable outbox/reconciliation/DLQ adjunct state, not primary telemetry payload storage; [outbox model](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/data-service/src/models/outbox.py), [Influx repository](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/data-service/src/repositories/influxdb_repository.py) |
| analytics-service | SQLAlchemy declarative + async repository | Tenant isolation is indirect: `analytics_jobs.parameters->tenant_id` JSON is queried with `json_extract`; artifacts have no tenant column; [mysql repository](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/analytics-service/src/infrastructure/mysql_repository.py) |
| reporting-service | SQLAlchemy declarative + shared tenant-scoped repository | Queue claim/retry implemented with row updates and `FOR UPDATE SKIP LOCKED` for schedules; [report repo](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/reporting-service/src/repositories/report_repository.py), [scheduled repo](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/reporting-service/src/repositories/scheduled_repository.py) |
| rule-engine-service | SQLAlchemy 2.0 typed declarative + shared tenant-scoped repository | Uses JSON arrays on `rules.device_ids`, `rules.notification_channels`, and `rules.notification_recipients`; per-device cooldown state moved into `rule_trigger_states`; [rule model](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/rule-engine-service/app/models/rule.py), [rule repo](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/rule-engine-service/app/repositories/rule.py) |
| waste-analysis-service | SQLAlchemy declarative + custom repository | Tenant is first-class on jobs only; summaries hang off `job_id` without foreign key | [waste model](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/waste-analysis-service/src/models/waste_jobs.py), [waste repo](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/waste-analysis-service/src/repositories/waste_repository.py) |

## 2. Table / Model Catalog

### Auth service

| Table / model | Owning service/module | Purpose | Source files |
| --- | --- | --- | --- |
| `organizations` / `Organization` | auth-service | Tenant/org master record | [auth model](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/auth-service/app/models/auth.py), [0001_initial_auth_schema.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/auth-service/alembic/versions/0001_initial_auth_schema.py) |
| `plants` / `Plant` | auth-service | Plant catalog under tenant | same |
| `users` / `User` | auth-service | User accounts and tenant membership | same |
| `user_plant_access` / `UserPlantAccess` | auth-service | Plant access junction table | same |
| `refresh_tokens` / `RefreshToken` | auth-service | Stored refresh token hashes and revocation/expiry state | same, [cleanup SQL](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/auth-service/scripts/refresh_token_cleanup.sql) |
| `tenant_id_sequences` / `TenantIdSequence` | auth-service | Allocator state for SH-prefixed tenant IDs | [auth model](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/auth-service/app/models/auth.py), [0008_hard_cut_sh_tenant_ids.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/auth-service/alembic/versions/0008_hard_cut_sh_tenant_ids.py) |
| `auth_action_tokens` / `AuthActionToken` | auth-service | Invite-set-password and password-reset tokens | [auth model](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/auth-service/app/models/auth.py), [0003_add_auth_action_tokens.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/auth-service/alembic/versions/0003_add_auth_action_tokens.py) |

### Device service

| Table / model | Owning service/module | Purpose | Source files |
| --- | --- | --- | --- |
| `device_id_sequences` / `DeviceIdSequence` | device-service | Per-prefix device ID allocator | [device model](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/device-service/app/models/device.py) |
| `hardware_unit_sequences` / `HardwareUnitSequence` | device-service | Per-prefix hardware unit allocator | same |
| `devices` / `Device` | device-service | Tenant-scoped device catalog and runtime metadata | same, [0001_initial_schema.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/device-service/alembic/versions/0001_initial_schema.py), [20260329_0001_composite_device_pk.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/device-service/alembic/versions/20260329_0001_composite_device_pk.py) |
| `device_shifts` / `DeviceShift` | device-service | Shift planning windows per device | same |
| `parameter_health_config` / `ParameterHealthConfig` | device-service | Device parameter health scoring thresholds and weights | same |
| `device_performance_trends` / `DevicePerformanceTrend` | device-service | Materialized performance chart buckets | same |
| `device_properties` / `DeviceProperty` | device-service | Telemetry-discovered dynamic field inventory | same |
| `device_dashboard_widgets` / `DeviceDashboardWidget` | device-service | Per-device visible widget ordering | same |
| `device_dashboard_widget_settings` / `DeviceDashboardWidgetSetting` | device-service | Configured-vs-default widget flag | same |
| `idle_running_log` / `IdleRunningLog` | device-service | Daily idle energy/cost aggregates | same |
| `device_state_intervals` / `DeviceStateInterval` | device-service | Durable interval log for idle, overconsumption, runtime_on | same, [20260416_0001_add_device_state_intervals.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/device-service/alembic/versions/20260416_0001_add_device_state_intervals.py) |
| `device_live_state` / `DeviceLiveState` | device-service | Real-time projection row for low-latency dashboard reads | [device model](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/device-service/app/models/device.py) |
| `waste_site_config` / `WasteSiteConfig` | device-service | Site-wide default unoccupied windows for waste analysis | same |
| `dashboard_snapshots` / `DashboardSnapshot` | device-service | Cached dashboard payloads with optional MinIO pointer | same, [add_dashboard_snapshots.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/device-service/alembic/versions/add_dashboard_snapshots.py), [add_dashboard_snapshot_minio_storage.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/device-service/alembic/versions/add_dashboard_snapshot_minio_storage.py) |
| `hardware_units` / `HardwareUnit` | device-service | Physical hardware inventory | [device model](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/device-service/app/models/device.py), [20260407_0002_hardware_inventory_foundation.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/device-service/alembic/versions/20260407_0002_hardware_inventory_foundation.py) |
| `device_hardware_installations` / `DeviceHardwareInstallation` | device-service | Device-to-hardware installation history | same |
| `tenant_security_audit_log` | shared tenant guard, device-service migration owner | Audit table for blocked cross-tenant attempts | [20260331_0003_add_tenant_security_audit_log.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/device-service/alembic/versions/20260331_0003_add_tenant_security_audit_log.py), [tenant_guards.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/shared/tenant_guards.py) |

### Data service

| Table / model | Owning service/module | Purpose | Source files |
| --- | --- | --- | --- |
| `telemetry_outbox` / `OutboxMessage` | data-service | Durable relay queue for telemetry fan-out to downstream services | [outbox model](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/data-service/src/models/outbox.py), [20260324_0001_add_telemetry_outbox_and_reconciliation_log.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/data-service/alembic/versions/20260324_0001_add_telemetry_outbox_and_reconciliation_log.py) |
| `reconciliation_log` / `ReconciliationLog` | data-service | Audit log for Influx-vs-MySQL reconciliation checks | same |
| `dlq_messages` | data-service | MySQL DLQ for failed writes/relays when durable backend is MySQL | [02_data_service_dlq.sql](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/init-scripts/mysql/02_data_service_dlq.sql), [dlq_repository.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/data-service/src/repositories/dlq_repository.py) |
| Influx measurement `device_telemetry` | data-service | Primary time-series measurement for telemetry samples | [influxdb_repository.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/data-service/src/repositories/influxdb_repository.py) |

### Analytics service

| Table / model | Owning service/module | Purpose | Source files |
| --- | --- | --- | --- |
| `analytics_jobs` / `AnalyticsJob` | analytics-service | Analytics job queue, status, results, worker lease metadata | [database.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/analytics-service/src/models/database.py), [0001_initial_schema.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/analytics-service/alembic/versions/0001_initial_schema.py), [0002_queue_and_artifact_tables.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/analytics-service/alembic/versions/0002_queue_and_artifact_tables.py), [0005_job_phase_tracking.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/analytics-service/alembic/versions/0005_job_phase_tracking.py) |
| `ml_model_artifacts` / `ModelArtifact` | analytics-service | Warm-reuse model artifact registry and payload storage | same |
| `analytics_worker_heartbeats` / `WorkerHeartbeat` | analytics-service | Worker liveness table | same, [0003_worker_heartbeat_and_accuracy_tables.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/analytics-service/alembic/versions/0003_worker_heartbeat_and_accuracy_tables.py) |
| `failure_event_labels` / `FailureEventLabel` | analytics-service | Labeled maintenance/failure events for certification/backtesting | same |
| `analytics_accuracy_evaluations` / `AccuracyEvaluation` | analytics-service | Aggregated accuracy/certification metrics | same |

### Reporting service

| Table / model | Owning service/module | Purpose | Source files |
| --- | --- | --- | --- |
| `energy_reports` / `EnergyReport` | reporting-service | Report job state, parameters, result pointer, retry/claim data | [energy_reports.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/reporting-service/src/models/energy_reports.py), [001_initial.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/reporting-service/alembic/versions/001_initial.py), [009_add_report_worker_claim_fields.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/reporting-service/alembic/versions/009_add_report_worker_claim_fields.py) |
| `scheduled_reports` / `ScheduledReport` | reporting-service | Saved recurring report schedules and claim state | [scheduled_reports.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/reporting-service/src/models/scheduled_reports.py), [001_initial.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/reporting-service/alembic/versions/001_initial.py), [007_add_schedule_processing_claim.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/reporting-service/alembic/versions/007_add_schedule_processing_claim.py) |
| `tariff_config` / `TariffConfig` | reporting-service | Legacy tenant-scoped tariff settings table retained after source-of-truth shift | [settings.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/reporting-service/src/models/settings.py), [003_settings_tables.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/reporting-service/alembic/versions/003_settings_tables.py), [006_unify_tariff_source_of_truth.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/reporting-service/alembic/versions/006_unify_tariff_source_of_truth.py) |
| `notification_channels` / `NotificationChannel` | reporting-service, read by rule-engine | Shared physical tenant notification destination table | [settings.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/reporting-service/src/models/settings.py), [005_tenant_scope_reporting_settings.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/reporting-service/alembic/versions/005_tenant_scope_reporting_settings.py), [rule model mirror](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/rule-engine-service/app/models/rule.py) |
| `tenant_tariffs` / `TenantTariff` | reporting-service | Current tariff source of truth per tenant | [tenant_tariffs.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/reporting-service/src/models/tenant_tariffs.py), [001_initial.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/reporting-service/alembic/versions/001_initial.py) |

### Rule-engine service

| Table / model | Owning service/module | Purpose | Source files |
| --- | --- | --- | --- |
| `rules` / `Rule` | rule-engine-service | Alert rules and cooldown config | [rule.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/rule-engine-service/app/models/rule.py), [001_initial.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/rule-engine-service/alembic/versions/001_initial.py) |
| `alerts` / `Alert` | rule-engine-service | Triggered alerts | same |
| `activity_events` / `ActivityEvent` | rule-engine-service | Audit/event feed rows | same, [002_activity_events.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/rule-engine-service/alembic/versions/002_activity_events.py) |
| `notification_channels` / `NotificationChannelSetting` | shared physical table | Rule-engine mirror model over reporting-service `notification_channels` table; not a second physical table | [rule.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/rule-engine-service/app/models/rule.py), [settings.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/reporting-service/src/models/settings.py) |
| `notification_delivery_logs` / `NotificationDeliveryLog` | rule-engine-service | Permanent notification delivery audit ledger | [rule.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/rule-engine-service/app/models/rule.py), [20260416_0010_notification_delivery_audit_ledger.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/rule-engine-service/alembic/versions/20260416_0010_notification_delivery_audit_ledger.py), [20260416_0011_notification_delivery_hardening_constraints.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/rule-engine-service/alembic/versions/20260416_0011_notification_delivery_hardening_constraints.py) |
| `rule_trigger_states` / `RuleTriggerState` | rule-engine-service | Per-device cooldown state | [rule.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/rule-engine-service/app/models/rule.py), [20260416_0012_rule_device_trigger_state.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/rule-engine-service/alembic/versions/20260416_0012_rule_device_trigger_state.py) |
| `notification_outbox` / `NotificationOutbox` | rule-engine-service | Durable async notification send queue | [rule.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/rule-engine-service/app/models/rule.py), [20260417_0013_notification_outbox.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/rule-engine-service/alembic/versions/20260417_0013_notification_outbox.py) |

### Waste-analysis service

| Table / model | Owning service/module | Purpose | Source files |
| --- | --- | --- | --- |
| `waste_analysis_jobs` / `WasteAnalysisJob` | waste-analysis-service | Waste analysis job queue and result pointer | [waste_jobs.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/waste-analysis-service/src/models/waste_jobs.py), [001_initial.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/waste-analysis-service/alembic/versions/001_initial.py), [005_add_tenant_scope_to_waste_jobs.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/waste-analysis-service/alembic/versions/005_add_tenant_scope_to_waste_jobs.py) |
| `waste_device_summary` / `WasteDeviceSummary` | waste-analysis-service | Per-device waste summary rows for a job | [waste_jobs.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/waste-analysis-service/src/models/waste_jobs.py), [004_add_wastage_categories.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/waste-analysis-service/alembic/versions/004_add_wastage_categories.py) |

## 3. Schema Details

Status legend inside this section:
- `Confirmed from model/migration`: current ORM model and/or migration directly defines the field.
- `Inferred from repository/query usage`: repository code assumes column semantics not fully encoded in model.
- `Needs runtime verification`: current code suggests presence/behavior but exact deployed schema/default may differ.

### Auth service schemas

#### `organizations`
Source: [auth model](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/auth-service/app/models/auth.py), [0001_initial_auth_schema.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/auth-service/alembic/versions/0001_initial_auth_schema.py), [0008_hard_cut_sh_tenant_ids.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/auth-service/alembic/versions/0008_hard_cut_sh_tenant_ids.py)

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `id` | `String(10)` | no | allocator-generated | PK; SH-prefixed tenant ID after hard cut. `Confirmed from model/migration` |
| `name` | `String(255)` | no | none |  |
| `slug` | `String(100)` | no | none | unique; index `ix_organizations_slug` |
| `is_active` | `Boolean` | no | true |  |
| `entitlements_version` | `Integer` | no | `0` |  |
| `premium_feature_grants_json` | `JSON` | no | `[]` |  |
| `role_feature_matrix_json` | `JSON` | no | `{}` |  |
| `created_at` | `DateTime(timezone=True)` | no | `now()` / `CURRENT_TIMESTAMP` | audit timestamp |
| `updated_at` | `DateTime(timezone=True)` | no | `now()` with update hook | audit timestamp |

#### `plants`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `id` | `String(36)` | no | UUID | PK |
| `tenant_id` | `String(10)` | no | none | FK `organizations.id` cascade delete; index `ix_plants_tenant_id` |
| `name` | `String(255)` | no | none |  |
| `location` | `String(500)` | yes | none |  |
| `timezone` | `String(64)` | no | `Asia/Kolkata` |  |
| `is_active` | `Boolean` | no | true |  |
| `created_at` | `DateTime(timezone=True)` | no | current timestamp |  |
| `updated_at` | `DateTime(timezone=True)` | no | current timestamp / on update |  |

#### `users`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `id` | `String(36)` | no | UUID | PK |
| `tenant_id` | `String(10)` | yes | none | FK `organizations.id` set null; index `ix_users_tenant_id` |
| `email` | `String(255)` | no | none | unique; index `ix_users_email` |
| `hashed_password` | `String(255)` | no | none | sensitive |
| `full_name` | `String(255)` | yes | none |  |
| `role` | enum `userrole` | no | none | values: `super_admin`, `org_admin`, `plant_manager`, `operator`, `viewer` |
| `permissions_version` | `Integer` | no | `0` | added by migration `0002_add_user_permissions_version.py`; `Confirmed from model`, migration name only scanned |
| `is_active` | `Boolean` | no | true |  |
| `invited_at` | `DateTime(timezone=True)` | yes | none | explicit onboarding timestamp added by `0009_user_lifecycle_timestamps.py`; used to distinguish invite lifecycle from activation lifecycle |
| `activated_at` | `DateTime(timezone=True)` | yes | none | first successful invite acceptance / activation marker |
| `deactivated_at` | `DateTime(timezone=True)` | yes | none | explicit deactivation timestamp for reactivation semantics |
| `created_at` | `DateTime(timezone=True)` | no | current timestamp |  |
| `updated_at` | `DateTime(timezone=True)` | no | current timestamp / on update |  |
| `last_login_at` | `DateTime(timezone=True)` | yes | none | interactive-login audit timestamp; intended to move on successful login only, not on invite acceptance, password reset, or refresh |

#### `user_plant_access`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `user_id` | `String(36)` | no | none | PK component; FK `users.id` cascade delete |
| `plant_id` | `String(36)` | no | none | PK component; FK `plants.id` cascade delete |
| `granted_at` | `DateTime(timezone=True)` | no | current timestamp |  |

#### `refresh_tokens`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `id` | `String(36)` | no | UUID | PK |
| `user_id` | `String(36)` | no | none | FK `users.id` cascade delete; index `ix_refresh_tokens_user_id` |
| `token_hash` | `String(255)` | no | none | unique; index `ix_refresh_tokens_token_hash` |
| `expires_at` | `DateTime(timezone=True)` | no | none | index `ix_refresh_tokens_expires_at` |
| `revoked_at` | `DateTime(timezone=True)` | yes | none | index `ix_refresh_tokens_revoked_at` |
| `created_at` | `DateTime(timezone=True)` | no | current timestamp |  |

#### `tenant_id_sequences`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `prefix` | `String(2)` | no | none | PK |
| `next_value` | `BigInteger` | no | none | allocator cursor |
| `updated_at` | `DateTime(timezone=True)` | no | current timestamp / on update |  |

#### `auth_action_tokens`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `id` | `String(36)` | no | UUID | PK |
| `user_id` | `String(36)` | no | none | FK `users.id` cascade delete; index |
| `action_type` | enum `authactiontype` | no | none | values: `invite_set_password`, `password_reset` |
| `token_hash` | `String(64)` | no | none | unique; index |
| `expires_at` | `DateTime(timezone=True)` | no | none |  |
| `used_at` | `DateTime(timezone=True)` | yes | none |  |
| `created_by_user_id` | `String(36)` | yes | none | no FK in model |
| `created_by_role` | `String(50)` | yes | none |  |
| `tenant_id` | `String(10)` | yes | none | index |
| `metadata_json` | `String(2000)` | yes | none | stringified metadata, not JSON column |
| `created_at` | `DateTime(timezone=True)` | no | current timestamp |  |

Additional retention/index semantics:
- `Confirmed from code`: cleanup/index hardening migration `0010_add_auth_action_token_cleanup_indexes.py` exists to support bounded purge of stale used and long-expired unused action tokens.
- `Confirmed from code`: application cleanup policy is driven by `ACTION_TOKEN_RETENTION_HOURS` in auth config and enforced by `services/auth-service/app/services/token_cleanup_service.py`.

### Device service schemas

#### `device_id_sequences`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `prefix` | `String(2)` | no | none | PK |
| `next_value` | `BigInteger` | no | none | allocator cursor |
| `updated_at` | `DateTime(timezone=True)` | no | `datetime.utcnow` / on update |  |

#### `hardware_unit_sequences`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `prefix` | `String(3)` | no | none | PK |
| `next_value` | `BigInteger` | no | none | allocator cursor |
| `updated_at` | `DateTime(timezone=True)` | no | `datetime.utcnow` / on update |  |

#### `devices`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `device_id` | `String(50)` | no | none | PK component; unique `uq_devices_device_id` remains declared |
| `tenant_id` | `String(10)` | no | none | PK component; index; composite ownership key after `20260329_0001` |
| `plant_id` | `String(36)` | no | none | indexed soft reference to auth-service `plants.id`; no DB FK |
| `device_name` | `String(255)` | no | none |  |
| `device_type` | `String(100)` | no | none | index |
| `device_id_class` | `String(20)` | yes | none | index; values inferred from enum: `active`, `test`, `virtual` |
| `manufacturer` | `String(255)` | yes | none |  |
| `model` | `String(255)` | yes | none |  |
| `location` | `String(500)` | yes | none |  |
| `phase_type` | `String(20)` | yes | none | indexed; enum usage suggests `single`, `three` |
| `data_source_type` | `String(20)` | no | `metered` | index; enum usage suggests `metered`, `sensor` |
| `energy_flow_mode` | `String(32)` | no | `consumption_only` | index; enum usage suggests `consumption_only`, `bidirectional` |
| `polarity_mode` | `String(32)` | no | `normal` | index; enum usage suggests `normal`, `inverted` |
| `idle_current_threshold` | `Numeric(10,4)` | yes | none |  |
| `overconsumption_current_threshold_a` | `Numeric(10,4)` | yes | none |  |
| `full_load_current_a` | `Numeric(10,4)` | yes | none |  |
| `idle_threshold_pct_of_fla` | `Numeric(6,4)` | no | `0.25` |  |
| `unoccupied_weekday_start_time` | `Time` | yes | none |  |
| `unoccupied_weekday_end_time` | `Time` | yes | none |  |
| `unoccupied_weekend_start_time` | `Time` | yes | none |  |
| `unoccupied_weekend_end_time` | `Time` | yes | none |  |
| `legacy_status` | `String(50)` | no | `active` | deprecated, indexed |
| `last_seen_timestamp` | `DateTime(timezone=True)` | yes | none | indexed |
| `first_telemetry_timestamp` | `DateTime(timezone=True)` | yes | none | indexed |
| `metadata_json` | `Text` | yes | none |  |
| `created_at` | `DateTime(timezone=True)` | no | `datetime.utcnow` | timestamp |
| `updated_at` | `DateTime(timezone=True)` | no | `datetime.utcnow` / on update | timestamp |
| `deleted_at` | `DateTime(timezone=True)` | yes | none | soft delete marker |

#### `device_shifts`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `id` | `Integer` | no | autoincrement | PK |
| `device_id` | `String(50)` | no | none | FK to `devices.device_id` in early migration; current model plus composite-PK migration adds tenant column + composite FK |
| `tenant_id` | `String(10)` | yes in model, later enforced in migration history | none | index; `Needs runtime verification` for nullability on long-lived DBs, but intended tenant-scoped |
| `shift_name` | `String(100)` | no | none |  |
| `shift_start` | `Time` | no | none |  |
| `shift_end` | `Time` | no | none |  |
| `maintenance_break_minutes` | `Integer` | no | `0` |  |
| `day_of_week` | `Integer` | yes | none | 0 Monday to 6 Sunday by code comment |
| `is_active` | `Boolean` | no | true |  |
| `created_at` | `DateTime(timezone=True)` | no | `datetime.utcnow` |  |
| `updated_at` | `DateTime(timezone=True)` | no | `datetime.utcnow` / on update |  |

#### `parameter_health_config`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `id` | `Integer` | no | autoincrement | PK |
| `device_id` | `String(50)` | no | none | device FK |
| `tenant_id` | `String(10)` | yes in model | none | indexed; tenant-scoped by migration history |
| `parameter_name` | `String(100)` | no | none |  |
| `canonical_parameter_name` | `String(100)` | no | event-populated | index |
| `normal_min` | float-compatible | yes | none | SQLAlchemy type omitted in model; `Needs runtime verification` exact physical type; old migration used `Float` |
| `normal_max` | float-compatible | yes | none | same |
| `weight` | float-compatible | no | `0.0` | same |
| `ignore_zero_value` | `Boolean` | no | false |  |
| `is_active` | `Boolean` | no | true |  |
| `created_at` | `DateTime(timezone=True)` | no | `datetime.utcnow` |  |
| `updated_at` | `DateTime(timezone=True)` | no | `datetime.utcnow` / on update |  |

#### `device_performance_trends`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `id` | `Integer` | no | autoincrement | PK |
| `device_id` | `String(50)` | no | none | device FK |
| `tenant_id` | `String(10)` | no | none | index |
| `bucket_start_utc` | `DateTime(timezone=True)` | no | none | index; unique with `device_id`,`tenant_id` |
| `bucket_end_utc` | `DateTime(timezone=True)` | no | none |  |
| `bucket_timezone` | `String(64)` | no | `Asia/Kolkata` |  |
| `interval_minutes` | `Integer` | no | `5` |  |
| `health_score` | `Float` | yes | none |  |
| `uptime_percentage` | `Float` | yes | none |  |
| `planned_minutes` | `Integer` | no | `0` |  |
| `effective_minutes` | `Integer` | no | `0` |  |
| `break_minutes` | `Integer` | no | `0` |  |
| `points_used` | `Integer` | no | `0` |  |
| `is_valid` | `Boolean` | no | true |  |
| `message` | `Text` | yes | none |  |
| `created_at` | `DateTime(timezone=True)` | no | `datetime.utcnow` | indexed |

#### `device_properties`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `id` | `Integer` | no | autoincrement | PK |
| `device_id` | `String(50)` | no | none | device FK |
| `tenant_id` | `String(10)` | no in current model | none | index |
| `property_name` | `String(100)` | no | none | unique with `device_id` in initial migration; tenant not part of unique key |
| `data_type` | `String(20)` | no | `float` |  |
| `is_numeric` | `Boolean` | no | true |  |
| `discovered_at` | `DateTime(timezone=True)` | no | `datetime.utcnow` |  |
| `last_seen_at` | `DateTime(timezone=True)` | no | `datetime.utcnow` / on update |  |

#### `device_dashboard_widgets`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `id` | `Integer` | no | autoincrement | PK |
| `device_id` | `String(50)` | no | none | device FK |
| `tenant_id` | `String(10)` | no | none | index |
| `field_name` | `String(100)` | no | none | unique with `device_id`,`tenant_id` |
| `display_order` | `Integer` | no | `0` | index with `device_id`,`tenant_id` |
| `created_at` | `DateTime(timezone=True)` | no | `datetime.utcnow` |  |
| `updated_at` | `DateTime(timezone=True)` | no | `datetime.utcnow` / on update |  |

#### `device_dashboard_widget_settings`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `device_id` | `String(50)` | no | none | PK component; device FK |
| `tenant_id` | `String(10)` | no | none | PK component |
| `is_configured` | `Boolean` | no | false |  |
| `created_at` | `DateTime(timezone=True)` | no | `datetime.utcnow` |  |
| `updated_at` | `DateTime(timezone=True)` | no | `datetime.utcnow` / on update |  |

#### `idle_running_log`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `id` | `BigInteger` | no | autoincrement | PK |
| `device_id` | `String(50)` | no | none | device FK |
| `tenant_id` | `String(10)` | no | none | index |
| `period_start` | `DateTime(timezone=True)` | no | none | unique with `device_id`,`tenant_id`; part of `idx_idle_log_device_period` |
| `period_end` | `DateTime(timezone=True)` | no | none |  |
| `idle_duration_sec` | `Integer` | no | `0` |  |
| `idle_energy_kwh` | `Numeric(12,6)` | no | `0` |  |
| `idle_cost` | `Numeric(12,4)` | no | `0` |  |
| `currency` | `String(10)` | no | `INR` |  |
| `tariff_rate_used` | `Numeric(10,4)` | no | `0` |  |
| `pf_estimated` | `Boolean` | no | false |  |
| `created_at` | `DateTime(timezone=True)` | no | `datetime.utcnow` |  |
| `updated_at` | `DateTime(timezone=True)` | no | `datetime.utcnow` / on update |  |

#### `device_state_intervals`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `id` | `BigInteger` / `Integer` in sqlite variant | no | autoincrement | PK |
| `tenant_id` | `String(10)` | no | none | indexed |
| `device_id` | `String(50)` | no | none | composite FK with tenant |
| `state_type` | `String(32)` | no | none | check constraint values: `idle`,`overconsumption`,`runtime_on` |
| `started_at` | aware timestamp | no | none | index in composite time query |
| `ended_at` | aware timestamp | yes | none |  |
| `duration_sec` | `Integer` | yes | none |  |
| `is_open` | `Boolean` | no | true | index with tenant+device |
| `opened_by_sample_ts` | aware timestamp | yes | none |  |
| `closed_by_sample_ts` | aware timestamp | yes | none |  |
| `opened_reason` | `String(64)` | yes | none |  |
| `closed_reason` | `String(64)` | yes | none |  |
| `source` | `String(32)` | yes | none |  |
| `created_at` | aware timestamp | no | current UTC |  |
| `updated_at` | aware timestamp | no | current UTC / on update |  |

#### `device_live_state`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `device_id` | `String(50)` | no | none | PK component; device FK |
| `tenant_id` | `String(10)` | no | none | PK component |
| `last_telemetry_ts` | `DateTime(timezone=True)` | yes | none |  |
| `last_sample_ts` | `DateTime(timezone=True)` | yes | none |  |
| `runtime_status` | `String(32)` | no | `stopped` | index |
| `load_state` | `String(32)` | no | `unknown` |  |
| `health_score` | `Float` | yes | none |  |
| `uptime_percentage` | `Float` | yes | none |  |
| `today_energy_kwh` | `Numeric(14,6)` | no | `0` |  |
| `today_idle_kwh` | `Numeric(14,6)` | no | `0` |  |
| `today_offhours_kwh` | `Numeric(14,6)` | no | `0` |  |
| `today_overconsumption_kwh` | `Numeric(14,6)` | no | `0` |  |
| `today_loss_kwh` | `Numeric(14,6)` | no | `0` |  |
| `today_loss_cost_inr` | `Numeric(14,4)` | no | `0` |  |
| `month_energy_kwh` | `Numeric(14,6)` | no | `0` |  |
| `month_energy_cost_inr` | `Numeric(14,4)` | no | `0` |  |
| `today_running_seconds` | `Integer` | no | `0` |  |
| `today_effective_seconds` | `Integer` | no | `0` |  |
| `day_bucket` | `Date` | yes | none | index |
| `month_bucket` | `Date` | yes | none | index |
| `last_energy_kwh` | `Numeric(14,6)` | yes | none |  |
| `last_power_kw` | `Numeric(14,6)` | yes | none |  |
| `last_current_a` | `Numeric(14,6)` | yes | none |  |
| `last_voltage_v` | `Numeric(14,6)` | yes | none |  |
| `idle_streak_started_at` | `DateTime(timezone=True)` | yes | none |  |
| `idle_streak_duration_sec` | `Integer` | no | `0` |  |
| `version` | `BigInteger` | no | `0` | index |
| `updated_at` | `DateTime(timezone=True)` | no | `datetime.utcnow` / on update | index |

#### `waste_site_config`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `id` | `Integer` | no | autoincrement | PK |
| `tenant_id` | `String(10)` | yes | none | unique `uq_waste_site_config_tenant`; nullable global/default row possible |
| `default_unoccupied_weekday_start_time` | `Time` | yes | none |  |
| `default_unoccupied_weekday_end_time` | `Time` | yes | none |  |
| `default_unoccupied_weekend_start_time` | `Time` | yes | none |  |
| `default_unoccupied_weekend_end_time` | `Time` | yes | none |  |
| `timezone` | `String(50)` | yes | none |  |
| `updated_by` | `String(100)` | yes | none |  |
| `created_at` | `DateTime(timezone=True)` | no | `datetime.utcnow` |  |
| `updated_at` | `DateTime(timezone=True)` | no | `datetime.utcnow` / on update |  |

#### `dashboard_snapshots`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `tenant_id` | `String(10)` | no | none | PK component in current model; older migration started without tenant field |
| `snapshot_key` | `String(120)` | no | none | PK component |
| `payload_json` | `Text` | yes | none | became nullable when MinIO storage added |
| `s3_key` | `String(512)` | yes | none | object-storage pointer |
| `storage_backend` | enum `dashboard_snapshot_storage_backend` | no | `mysql` | values `mysql`, `minio` |
| `generated_at` | `DateTime(timezone=True)` | no | none | indexed |
| `expires_at` | `DateTime(timezone=True)` | yes | none | indexed |
| `created_at` | `DateTime(timezone=True)` | no | `datetime.utcnow` |  |
| `updated_at` | `DateTime(timezone=True)` | no | `datetime.utcnow` / on update |  |

#### `hardware_units`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `id` | `Integer` | no | autoincrement | PK |
| `hardware_unit_id` | `String(100)` | no | none | unique with `tenant_id` |
| `tenant_id` | `String(10)` | no | none | index |
| `plant_id` | `String(36)` | no | none | index; soft ref to auth-service plant |
| `unit_type` | `String(100)` | no | none | index |
| `unit_name` | `String(255)` | no | none | present in current model; initial migration omitted this column, so current DB requires later migration path not separately inspected |
| `manufacturer` | `String(255)` | yes | none |  |
| `model` | `String(255)` | yes | none |  |
| `serial_number` | `String(255)` | yes | none |  |
| `status` | `String(32)` | no | `available` | index; enum usage suggests `available`,`retired` |
| `created_at` | `DateTime(timezone=True)` | no | `datetime.utcnow` |  |
| `updated_at` | `DateTime(timezone=True)` | no | `datetime.utcnow` / on update |  |

#### `device_hardware_installations`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `id` | `Integer` | no | autoincrement | PK |
| `tenant_id` | `String(10)` | no | none | indexed |
| `plant_id` | `String(36)` | no | none | index |
| `device_id` | `String(50)` | no | none | index; composite FK with tenant to `devices` |
| `hardware_unit_id` | `String(100)` | no | none | index; composite FK with tenant to `hardware_units` |
| `installation_role` | `String(100)` | no | none |  |
| `commissioned_at` | `DateTime(timezone=True)` | no | `datetime.utcnow` | history sort key |
| `decommissioned_at` | `DateTime(timezone=True)` | yes | none | null indicates active |
| `notes` | `Text` | yes | none |  |
| `active_hardware_unit_key` | `String(100)` | yes | none | unique with tenant for active install lock |
| `active_device_role_key` | `String(255)` | yes | none | unique with tenant for one active role per device |
| `created_at` | `DateTime(timezone=True)` | no | `datetime.utcnow` |  |
| `updated_at` | `DateTime(timezone=True)` | no | `datetime.utcnow` / on update |  |

#### `tenant_security_audit_log`
Defined only in migration and written via raw SQL from tenant guards.

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `id` | `BigInteger` | no | autoincrement | PK |
| `event_type` | `String(50)` | no | none | current writer uses `CROSS_TENANT_ATTEMPT` |
| `caller_tenant_id` | `String(50)` | yes | none | index `ix_audit_caller_tenant` |
| `caller_user_id` | `String(100)` | yes | none |  |
| `target_tenant_id` | `String(50)` | yes | none |  |
| `target_resource_type` | `String(50)` | yes | none |  |
| `target_resource_id` | `String(100)` | yes | none |  |
| `http_path` | `String(500)` | yes | none |  |
| `outcome` | `String(20)` | no | none | current writer uses `BLOCKED` |
| `detail` | `Text` | yes | none |  |
| `created_at` | `DateTime` | no | `CURRENT_TIMESTAMP` | index `ix_audit_created_at` |

### Data service schemas

#### `telemetry_outbox`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `id` | `BIGINT` | no | autoincrement | PK |
| `device_id` | `String(255)` | no | none | index with `status` |
| `telemetry_json` | `JSON` | no | none | payload includes `tenant_id` by service contract |
| `target` | enum `telemetry_outbox_target` | no | none | values `device-service`,`energy-service` |
| `status` | enum `telemetry_outbox_status` | no | `pending` | values `pending`,`delivered`,`failed`,`dead` |
| `retry_count` | `Integer` | no | `0` |  |
| `max_retries` | `Integer` | no | `5` |  |
| `created_at` | `DateTime(timezone=False)` | no | `CURRENT_TIMESTAMP` | index with `status` |
| `last_attempted_at` | `DateTime(timezone=False)` | yes | none |  |
| `delivered_at` | `DateTime(timezone=False)` | yes | none |  |
| `error_message` | `Text` | yes | none |  |

#### `reconciliation_log`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `id` | `BIGINT` | no | autoincrement | PK |
| `device_id` | `String(255)` | no | none | index with `checked_at` |
| `checked_at` | `DateTime(timezone=False)` | no | `CURRENT_TIMESTAMP` |  |
| `influx_ts` | `DateTime(timezone=False)` | yes | none |  |
| `mysql_ts` | `DateTime(timezone=False)` | yes | none |  |
| `drift_seconds` | `Integer` | yes | none |  |
| `action_taken` | `String(255)` | no | `none` |  |

#### `dlq_messages`
Raw SQL bootstrap table, not declared as ORM model.

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `id` | `BIGINT` | no | autoincrement | PK |
| `timestamp` | `DATETIME(6)` | no | none | original failure time |
| `error_type` | `VARCHAR(128)` | no | none | index `idx_dlq_messages_error_type` |
| `error_message` | `TEXT` | no | none |  |
| `retry_count` | `INT` | no | `0` |  |
| `original_payload` | `JSON` | no | none |  |
| `status` | `VARCHAR(32)` | no | `pending` | index `idx_dlq_messages_status_created` |
| `created_at` | `DATETIME(6)` | no | `CURRENT_TIMESTAMP(6)` | index `idx_dlq_messages_created_at` |

#### Influx measurement `device_telemetry`

- `Confirmed from repository/query usage`
- Tags confirmed in code: `device_id`, `tenant_id`; extra tags are rejected unless in `ALLOWED_TAGS`.
- Fields are dynamic numeric telemetry keys only; exact deployed field set depends on incoming payloads and shared telemetry contract.
- Measurement name: `device_telemetry`.
- Time column: sample timestamp supplied by telemetry payload.
- Retention is bucket-level, configured on startup by data-service, not per-measurement schema.
- Evidence: [influxdb_repository.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/data-service/src/repositories/influxdb_repository.py), [telemetry model](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/data-service/src/models/telemetry.py), [influxdb_retention.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/data-service/src/services/influxdb_retention.py)

### Analytics service schemas

#### `analytics_jobs`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `id` | `String(36)` | no | UUID | PK |
| `job_id` | `String(100)` | no | none | unique; indexed |
| `device_id` | `String(50)` | no | none | indexed; can be `"ALL"` for fleet jobs by repository logic |
| `analysis_type` | `String(50)` | no | none |  |
| `model_name` | `String(100)` | no | none |  |
| `date_range_start` | `DateTime(timezone=True)` | no | none |  |
| `date_range_end` | `DateTime(timezone=True)` | no | none |  |
| `parameters` | `JSON` | yes | none | contains `tenant_id` and sometimes `device_ids`, `parent_job_id` |
| `status` | `String(50)` | no | `pending` | index `idx_analytics_jobs_status` |
| `progress` | `Float` | yes | none |  |
| `phase` | `String(50)` | yes | none | added in `0005_job_phase_tracking` |
| `phase_label` | `String(255)` | yes | none |  |
| `phase_progress` | `Float` | yes | none |  |
| `message` | `Text` | yes | none |  |
| `error_message` | `Text` | yes | none |  |
| `results` | `JSON` | yes | none |  |
| `accuracy_metrics` | `JSON` | yes | none |  |
| `execution_time_seconds` | `Integer` | yes | none |  |
| `created_at` | `DateTime(timezone=True)` | no | current timestamp | indexed |
| `started_at` | `DateTime(timezone=True)` | yes | none |  |
| `completed_at` | `DateTime(timezone=True)` | yes | none |  |
| `attempt` | `Integer` | no | `0` | index |
| `queue_position` | `Integer` | yes | none |  |
| `queue_enqueued_at` | `DateTime(timezone=True)` | yes | none |  |
| `queue_started_at` | `DateTime(timezone=True)` | yes | none |  |
| `worker_lease_expires_at` | `DateTime(timezone=True)` | yes | none |  |
| `last_heartbeat_at` | `DateTime(timezone=True)` | yes | none |  |
| `error_code` | `String(100)` | yes | none |  |
| `updated_at` | `DateTime(timezone=True)` | no | current timestamp / on update |  |

#### `ml_model_artifacts`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `id` | `String(36)` | no | UUID | PK |
| `device_id` | `String(50)` | no | none | indexed |
| `analysis_type` | `String(50)` | no | none | indexed |
| `model_key` | `String(100)` | no | none | indexed |
| `feature_schema_hash` | `String(128)` | no | none |  |
| `model_version` | `String(64)` | no | `v1` |  |
| `artifact_payload` | `LONGBLOB` | no | none | binary model payload |
| `metrics` | `JSON` | yes | none |  |
| `created_at` | `DateTime(timezone=True)` | no | current timestamp |  |
| `updated_at` | `DateTime(timezone=True)` | no | current timestamp / on update |  |
| `expires_at` | `DateTime(timezone=True)` | yes | none |  |

#### `analytics_worker_heartbeats`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `worker_id` | `String(128)` | no | none | PK |
| `app_role` | `String(32)` | no | `worker` |  |
| `last_heartbeat_at` | `DateTime(timezone=True)` | no | current timestamp | indexed |
| `status` | `String(32)` | no | `alive` |  |

#### `failure_event_labels`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `id` | `String(36)` | no | UUID | PK |
| `device_id` | `String(50)` | no | none | indexed; composite index with `event_time` |
| `event_time` | `DateTime(timezone=True)` | no | none | indexed |
| `event_type` | `String(50)` | no | `failure` |  |
| `severity` | `String(32)` | yes | none |  |
| `source` | `String(100)` | yes | none |  |
| `metadata_json` | `JSON` | yes | none |  |
| `created_at` | `DateTime(timezone=True)` | no | current timestamp |  |

#### `analytics_accuracy_evaluations`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `id` | `String(36)` | no | UUID | PK |
| `analysis_type` | `String(50)` | no | none | indexed |
| `scope_device_id` | `String(50)` | yes | none | indexed |
| `sample_size` | `Integer` | no | `0` |  |
| `labeled_events` | `Integer` | no | `0` |  |
| `precision` | `Float` | yes | none |  |
| `recall` | `Float` | yes | none |  |
| `f1_score` | `Float` | yes | none |  |
| `false_alert_rate` | `Float` | yes | none |  |
| `avg_lead_hours` | `Float` | yes | none |  |
| `is_certified` | `Integer` | no | `0` | integer boolean |
| `notes` | `Text` | yes | none |  |
| `created_at` | `DateTime(timezone=True)` | no | current timestamp | indexed; composite index with `analysis_type`,`scope_device_id` |

### Reporting service schemas

#### `energy_reports`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `id` | `Integer` | no | autoincrement | PK |
| `report_id` | `String(36)` | no | none | unique |
| `tenant_id` | `String(10)` | no | none | indexes `ix_energy_reports_tenant_status`, `ix_energy_reports_tenant_type_created` |
| `report_type` | enum `ReportType` | no | none | `consumption`, `comparison` |
| `status` | enum `ReportStatus` | no | `pending` | `pending`,`processing`,`completed`,`failed` |
| `params` | `JSON` | no | none | report scope lives here |
| `computation_mode` | enum `ComputationMode` | yes | none | `direct_power`,`derived_single`,`derived_three` |
| `phase_type_used` | `String(20)` | yes | none |  |
| `result_json` | `JSON` | yes | none |  |
| `s3_key` | `String(500)` | yes | none | object storage pointer |
| `error_code` | `String(100)` | yes | none |  |
| `error_message` | `Text` | yes | none |  |
| `progress` | `Integer` | no | `0` |  |
| `enqueued_at` | `DateTime` | yes | none |  |
| `processing_started_at` | `DateTime` | yes | none | indexed with status |
| `worker_id` | `String(128)` | yes | none |  |
| `retry_count` | `Integer` | no | `0` |  |
| `timeout_count` | `Integer` | no | `0` |  |
| `last_attempt_at` | `DateTime` | yes | none |  |
| `created_at` | `DateTime` | no | `datetime.utcnow` |  |
| `completed_at` | `DateTime` | yes | none |  |

#### `scheduled_reports`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `id` | `Integer` | no | autoincrement | PK |
| `schedule_id` | `String(36)` | no | none | unique |
| `tenant_id` | `String(10)` | no | none | index; due-claim index includes it |
| `report_type` | enum `ScheduledReportType` | no | none | `consumption`,`comparison` |
| `frequency` | enum `ScheduledFrequency` | no | none | `daily`,`weekly`,`monthly` |
| `params_template` | `JSON` | no | none |  |
| `is_active` | `Boolean` | no | true |  |
| `last_run_at` | `DateTime` | yes | none |  |
| `next_run_at` | `DateTime` | yes | none |  |
| `processing_started_at` | `DateTime` | yes | none | added for worker claim |
| `last_status` | `String(50)` | yes | none |  |
| `retry_count` | `Integer` | no | `0` |  |
| `last_result_url` | `String(2000)` | yes | none | added in migration `002_add_last_result_url.py`; present in model |
| `created_at` | `DateTime` | no | `datetime.utcnow` |  |
| `updated_at` | `DateTime` | no | `datetime.utcnow` / on update |  |

#### `tariff_config`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `id` | `Integer` | no | autoincrement | PK |
| `tenant_id` | `String(10)` | no | none | unique `uq_tariff_config_tenant_id`; tenant-scoped after migration `005` |
| `rate` | `Numeric(10,4)` | no | none | legacy tariff rate |
| `currency` | `String(10)` | no | `INR` |  |
| `updated_at` | `DateTime` | no | `datetime.utcnow` / on update |  |
| `updated_by` | `String(100)` | yes | none |  |

#### `notification_channels`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `id` | `Integer` | no | autoincrement | PK |
| `tenant_id` | `String(10)` | no | none | unique with `channel_type`,`value`; index with `channel_type`,`is_active` |
| `channel_type` | `String(20)` | no | none | indexed |
| `value` | `String(255)` | no | none | email values normalized lowercase during backfill/repository writes |
| `is_active` | `Boolean` | no | true | indexed |
| `created_at` | `DateTime` | no | `datetime.utcnow` |  |

#### `tenant_tariffs`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `id` | `Integer` | no | autoincrement | PK |
| `tenant_id` | `String(10)` | no | none | unique |
| `energy_rate_per_kwh` | `Float` | no | none |  |
| `demand_charge_per_kw` | `Float` | yes at DB? model default 0.0 | `0.0` | `Needs runtime verification` exact nullability because migration used non-null with server default |
| `reactive_penalty_rate` | `Float` | yes at DB? model default 0.0 | `0.0` | same |
| `fixed_monthly_charge` | `Float` | yes at DB? model default 0.0 | `0.0` | same |
| `power_factor_threshold` | `Float` | yes at DB? model default 0.90 | `0.90` | same |
| `currency` | `String(10)` | no | `INR` |  |
| `created_at` | `DateTime` | no | `datetime.utcnow` |  |
| `updated_at` | `DateTime` | no | `datetime.utcnow` / on update |  |

### Rule-engine service schemas

#### `rules`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `rule_id` | `String(36)` | no | UUID | PK |
| `tenant_id` | `String(10)` | yes | none | index |
| `rule_name` | `String(255)` | no | none |  |
| `description` | `Text` | yes | none |  |
| `scope` | `String(50)` | no | `selected_devices` | enum usage: `all_devices`,`selected_devices` |
| `property` | `String(100)` | yes in current model | none | indexed; initial migration had non-null |
| `condition` | `String(20)` | yes in current model | none | operators `>`,`<`,`=`,`!=`,`>=`,`<=` |
| `threshold` | `Float` | yes in current model | none | initial migration had non-null |
| `rule_type` | `String(20)` | no | `threshold` | values in code: `threshold`,`time_based`,`continuous_idle_duration` |
| `cooldown_mode` | `String(20)` | no | `interval` | values `interval`,`no_repeat` |
| `cooldown_unit` | `String(20)` | no | `minutes` | values `minutes`,`seconds` |
| `time_window_start` | `String(5)` | yes | none |  |
| `time_window_end` | `String(5)` | yes | none |  |
| `timezone` | `String(64)` | no | `Asia/Kolkata` |  |
| `time_condition` | `String(50)` | yes | none |  |
| `duration_minutes` | `Integer` | yes | none |  |
| `triggered_once` | `Boolean` | no | false | rule-level legacy no-repeat state |
| `status` | `String(50)` | no | `active` | index; values `active`,`paused`,`archived` |
| `notification_channels` | `JSON` | no | `[]` |  |
| `notification_recipients` | `JSON` | no | `[]` | added in `20260406_0007_add_rule_notification_recipients.py`; migration file not opened but model confirms |
| `cooldown_minutes` | `Integer` | no | `15` | legacy field retained |
| `cooldown_seconds` | `Integer` | no | `900` | current source of truth in code |
| `last_triggered_at` | `DateTime(timezone=True)` | yes | none |  |
| `created_at` | `DateTime(timezone=True)` | no | `datetime.utcnow` |  |
| `updated_at` | `DateTime(timezone=True)` | no | `datetime.utcnow` / on update |  |
| `deleted_at` | `DateTime(timezone=True)` | yes | none | soft delete |
| `device_ids` | `JSON` | no | `[]` | MySQL `json_contains` used in repository |

#### `alerts`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `alert_id` | `String(36)` | no | UUID | PK |
| `tenant_id` | `String(10)` | yes | none | index |
| `rule_id` | `String(36)` | no | none | FK `rules.rule_id` cascade delete; index |
| `device_id` | `String(50)` | no | none | index |
| `severity` | `String(50)` | no | none |  |
| `message` | `Text` | no | none |  |
| `actual_value` | `Float` | no | none |  |
| `threshold_value` | `Float` | no | none |  |
| `status` | `String(50)` | no | `open` | index |
| `acknowledged_by` | `String(255)` | yes | none |  |
| `acknowledged_at` | `DateTime(timezone=True)` | yes | none |  |
| `resolved_at` | `DateTime(timezone=True)` | yes | none |  |
| `created_at` | `DateTime(timezone=True)` | no | `datetime.utcnow` |  |

#### `activity_events`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `event_id` | `String(36)` | no | UUID | PK |
| `tenant_id` | `String(10)` | yes | none | index |
| `device_id` | `String(50)` | yes | none | index |
| `rule_id` | `String(36)` | yes | none | index |
| `alert_id` | `String(36)` | yes | none | index |
| `event_type` | `String(100)` | no | none | index |
| `title` | `String(255)` | no | none |  |
| `message` | `Text` | no | none |  |
| `metadata_json` | `JSON` | no | `{}` |  |
| `is_read` | `Boolean` | no | false | index |
| `read_at` | `DateTime(timezone=True)` | yes | none |  |
| `created_at` | `DateTime(timezone=True)` | no | `datetime.utcnow` | index |

#### `notification_delivery_logs`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `id` | `String(36)` | no | UUID | PK |
| `tenant_id` | `String(10)` | no after hardening migration | none | index; check `tenant_id IS NOT NULL` implied by altered nullability and model constraint |
| `alert_id` | `String(36)` | yes | none | FK `alerts.alert_id` set null; index |
| `rule_id` | `String(36)` | yes | none | FK `rules.rule_id` set null; index |
| `device_id` | `String(50)` | yes | none |  |
| `event_type` | `String(100)` | no | none |  |
| `channel` | `String(32)` | no | none | index with tenant/time |
| `recipient_masked` | `String(255)` | no | none |  |
| `recipient_hash` | `String(64)` | no | none |  |
| `provider_name` | `String(100)` | no | none |  |
| `provider_message_id` | `String(255)` | yes | none | index |
| `status` | `String(32)` | no | none | check values `queued`,`attempted`,`provider_accepted`,`delivered`,`failed`,`skipped` |
| `billable_units` | `Integer` | no | `0` | check non-negative; check consistent with status |
| `attempted_at` | `DateTime(timezone=True)` | no | none |  |
| `accepted_at` | `DateTime(timezone=True)` | yes | none |  |
| `delivered_at` | `DateTime(timezone=True)` | yes | none |  |
| `failed_at` | `DateTime(timezone=True)` | yes | none |  |
| `failure_code` | `String(100)` | yes | none |  |
| `failure_message` | `Text` | yes | none |  |
| `metadata_json` | `JSON` | yes | none |  |
| `created_at` | `DateTime(timezone=True)` | no | current UTC |  |
| `updated_at` | `DateTime(timezone=True)` | no | current UTC / on update |  |

#### `rule_trigger_states`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `id` | `String(36)` | no | UUID | PK |
| `tenant_id` | `String(10)` | no | none | unique with `rule_id`,`device_id`; indexes by tenant+rule and tenant+device |
| `rule_id` | `String(36)` | no | none | FK `rules.rule_id` cascade delete |
| `device_id` | `String(50)` | no | none |  |
| `last_triggered_at` | `DateTime(timezone=True)` | yes | none |  |
| `triggered_once` | `Boolean` | no | false |  |
| `created_at` | `DateTime(timezone=True)` | no | current timestamp |  |
| `updated_at` | `DateTime(timezone=True)` | no | current timestamp / on update |  |

#### `notification_outbox`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `id` | `String(36)` | no | UUID | PK |
| `tenant_id` | `String(10)` | no | none | indexed with status/next_attempt and channel/status |
| `alert_id` | `String(36)` | yes | none | FK `alerts.alert_id` set null; unique with `channel`,`recipient_hash` |
| `rule_id` | `String(36)` | yes | none | FK `rules.rule_id` set null |
| `ledger_log_id` | `String(36)` | yes | none | FK `notification_delivery_logs.id` set null; unique |
| `device_id` | `String(50)` | yes | none | index |
| `event_type` | `String(100)` | no | none |  |
| `channel` | `String(32)` | no | none |  |
| `provider_name` | `String(100)` | no | none |  |
| `recipient_raw` | `Text` | no | empty string in model | sensitive |
| `recipient_masked` | `String(255)` | no | none |  |
| `recipient_hash` | `String(64)` | no | none |  |
| `subject` | `String(255)` | no | none |  |
| `message` | `Text` | no | none |  |
| `payload_json` | `JSON` | no | `{}` |  |
| `status` | `String(32)` | no | none | values align to notification delivery status enum |
| `worker_id` | `String(128)` | yes | none |  |
| `retry_count` | `Integer` | no | `0` |  |
| `processing_started_at` | `DateTime(timezone=True)` | yes | none | indexed with status |
| `next_attempt_at` | `DateTime(timezone=True)` | no | none |  |
| `last_attempt_at` | `DateTime(timezone=True)` | yes | none |  |
| `accepted_at` | `DateTime(timezone=True)` | yes | none |  |
| `delivered_at` | `DateTime(timezone=True)` | yes | none |  |
| `failed_at` | `DateTime(timezone=True)` | yes | none |  |
| `dead_lettered_at` | `DateTime(timezone=True)` | yes | none |  |
| `provider_message_id` | `String(255)` | yes | none |  |
| `failure_code` | `String(100)` | yes | none |  |
| `failure_message` | `Text` | yes | none |  |
| `created_at` | `DateTime(timezone=True)` | no | current UTC |  |
| `updated_at` | `DateTime(timezone=True)` | no | current UTC / on update |  |

### Waste-analysis service schemas

#### `waste_analysis_jobs`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `id` | `String(36)` | no | none | PK |
| `tenant_id` | `String(10)` | no | none | indexes `idx_waste_jobs_history_tenant_created`, `idx_waste_jobs_tenant_duplicate_lookup` |
| `job_name` | `String(255)` | yes | none |  |
| `scope` | enum `WasteScope` | no | none | `all`,`selected` |
| `device_ids` | `JSON` | yes | none | selected scope list |
| `start_date` | `Date` | no | none |  |
| `end_date` | `Date` | no | none |  |
| `granularity` | enum `WasteGranularity` | no | none | `daily`,`weekly`,`monthly` |
| `status` | enum `WasteStatus` | no | `pending` | `pending`,`running`,`completed`,`failed` |
| `progress_pct` | `Integer` | no | `0` |  |
| `stage` | `String(255)` | yes | none | repository starts with `Queued` |
| `result_json` | `JSON` | yes | none | repository preserves embedded `tenant_id` |
| `s3_key` | `String(500)` | yes | none | export pointer |
| `download_url` | `String(500)` | yes | none |  |
| `tariff_rate_used` | `Float` | yes | none |  |
| `currency` | `String(10)` | yes | none |  |
| `error_code` | `String(64)` | yes | none | added in `002_quality_gate_fields` |
| `error_message` | `Text` | yes | none |  |
| `created_at` | `DateTime` | no | `datetime.utcnow` |  |
| `completed_at` | `DateTime` | yes | none |  |

#### `waste_device_summary`

| Column | Type | Nullable | Default | PK / FK / constraints / notes |
| --- | --- | --- | --- | --- |
| `id` | `Integer` | no | autoincrement | PK |
| `job_id` | `String(36)` | no | none | index `idx_waste_job_device`; unique with `device_id`; no FK declared |
| `device_id` | `String(100)` | no | none | unique with `job_id` |
| `device_name` | `String(255)` | yes | none |  |
| `data_source_type` | `String(20)` | yes | none |  |
| `idle_duration_sec` | `Integer` | no | `0` |  |
| `idle_energy_kwh` | `Float` | no | `0` |  |
| `idle_cost` | `Float` | yes | none |  |
| `standby_power_kw` | `Float` | yes | none |  |
| `standby_energy_kwh` | `Float` | yes | none |  |
| `standby_cost` | `Float` | yes | none |  |
| `total_energy_kwh` | `Float` | no | `0` |  |
| `total_cost` | `Float` | yes | none |  |
| `offhours_energy_kwh` | `Float` | yes | none |  |
| `offhours_cost` | `Float` | yes | none |  |
| `offhours_duration_sec` | `Integer` | yes | none | added in `004_add_wastage_categories` |
| `offhours_skipped_reason` | `String(100)` | yes | none | compatibility bridge `008` exists but current model already has column |
| `offhours_pf_estimated` | `Boolean` | no | false |  |
| `overconsumption_duration_sec` | `Integer` | yes | none |  |
| `overconsumption_kwh` | `Float` | yes | none |  |
| `overconsumption_cost` | `Float` | yes | none |  |
| `overconsumption_skipped_reason` | `String(100)` | yes | none |  |
| `overconsumption_pf_estimated` | `Boolean` | no | false |  |
| `unoccupied_duration_sec` | `Integer` | yes | none |  |
| `unoccupied_energy_kwh` | `Float` | yes | none |  |
| `unoccupied_cost` | `Float` | yes | none |  |
| `unoccupied_skipped_reason` | `String(100)` | yes | none |  |
| `unoccupied_pf_estimated` | `Boolean` | no | false |  |
| `data_quality` | `String(20)` | yes | none |  |
| `energy_quality` | `String(20)` | yes | none |  |
| `idle_quality` | `String(20)` | yes | none |  |
| `standby_quality` | `String(20)` | yes | none |  |
| `overall_quality` | `String(20)` | yes | none |  |
| `idle_status` | `String(32)` | yes | none |  |
| `pf_estimated` | `Boolean` | no | false |  |
| `warnings` | `JSON` | yes | none |  |
| `calculation_method` | `String(50)` | yes | none |  |

## 4. Relationship Map

Text ERD grounded in model/migration truth:

- `organizations.id` -> `plants.tenant_id`
- `organizations.id` -> `users.tenant_id`
- `users.id` -> `refresh_tokens.user_id`
- `users.id` -> `auth_action_tokens.user_id`
- `users.id` -> `user_plant_access.user_id`
- `plants.id` -> `user_plant_access.plant_id`

- `devices.(device_id, tenant_id)` <- `device_shifts.(device_id, tenant_id)` after composite-PK migration
- `devices.(device_id, tenant_id)` <- `parameter_health_config.(device_id, tenant_id)`
- `devices.(device_id, tenant_id)` <- `device_properties.(device_id, tenant_id)`
- `devices.(device_id, tenant_id)` <- `device_dashboard_widgets.(device_id, tenant_id)`
- `devices.(device_id, tenant_id)` <- `device_dashboard_widget_settings.(device_id, tenant_id)`
- `devices.(device_id, tenant_id)` <- `device_performance_trends.(device_id, tenant_id)`
- `devices.(device_id, tenant_id)` <- `idle_running_log.(device_id, tenant_id)`
- `devices.(device_id, tenant_id)` <- `device_state_intervals.(device_id, tenant_id)`
- `devices.(device_id, tenant_id)` <- `device_live_state.(device_id, tenant_id)`
- `devices.(device_id, tenant_id)` <- `device_hardware_installations.(device_id, tenant_id)`

- `hardware_units.(tenant_id, hardware_unit_id)` <- `device_hardware_installations.(tenant_id, hardware_unit_id)`

- `rules.rule_id` -> `alerts.rule_id`
- `rules.rule_id` -> `rule_trigger_states.rule_id`
- `rules.rule_id` -> `notification_delivery_logs.rule_id`
- `rules.rule_id` -> `notification_outbox.rule_id`
- `alerts.alert_id` -> `notification_delivery_logs.alert_id`
- `alerts.alert_id` -> `notification_outbox.alert_id`
- `notification_delivery_logs.id` -> `notification_outbox.ledger_log_id`

- `waste_analysis_jobs.id` -> `waste_device_summary.job_id`
  - `Confirmed from model/migration` that `job_id` exists and is unique with `device_id`
  - `Confirmed from model/migration` that no foreign key constraint is declared

- `analytics_jobs` has no FK to device/auth tables.
  - Tenant scope is extracted from `analytics_jobs.parameters->tenant_id`
  - Device scope is partly from `device_id`, partly from `parameters->device_ids`

- `energy_reports`, `scheduled_reports`, `tenant_tariffs`, `tariff_config`, `notification_channels`, `waste_analysis_jobs`, `devices`, `rules`, and auth tenant tables all carry first-class tenant IDs.

## 5. Tenant Isolation in Data Model

### Tables with first-class tenant scope

- Auth: `organizations`, `plants`, `users`, `auth_action_tokens`
- Device: `devices`, `device_shifts`, `parameter_health_config`, `device_properties`, `device_dashboard_widgets`, `device_dashboard_widget_settings`, `device_performance_trends`, `idle_running_log`, `device_state_intervals`, `device_live_state`, `waste_site_config`, `dashboard_snapshots`, `hardware_units`, `device_hardware_installations`, `tenant_security_audit_log`
- Reporting: `energy_reports`, `scheduled_reports`, `tariff_config`, `notification_channels`, `tenant_tariffs`
- Rule-engine: `rules`, `alerts`, `activity_events`, `notification_delivery_logs`, `rule_trigger_states`, `notification_outbox`
- Waste: `waste_analysis_jobs`

### Tables with indirect or missing tenant scope

- `refresh_tokens`: tenant scope is indirect through `users.user_id`. `Confirmed from model/migration`
- `user_plant_access`: indirect through `users` and `plants`. `Confirmed from model/migration`
- `waste_device_summary`: no `tenant_id` column; tenant derives from parent job. `Confirmed from model/migration`
- `telemetry_outbox`: no `tenant_id` column; repository assumes payload JSON contains `tenant_id`. `Confirmed from model/migration` for absence, `Confirmed from repository/query usage` for payload convention
- `reconciliation_log`: no tenant column. `Confirmed from model/migration`
- `dlq_messages`: no tenant column. `Confirmed from raw SQL`
- `analytics_jobs`: no tenant column; tenant stored in `parameters->tenant_id` JSON and filtered with MySQL `json_extract`. `Confirmed from model/migration` for absence, `Confirmed from repository/query usage` for isolation pattern
- `ml_model_artifacts`: no tenant column. Isolation appears to rely on `device_id` and call context only. `Confirmed from model/migration`; cross-tenant safety `Needs runtime verification`
- `failure_event_labels` and `analytics_accuracy_evaluations`: no tenant column. `Confirmed from model/migration`

### How tenant identity is stored

- SH-prefixed 10-character business tenant IDs are the current tenant identifier format in auth, reporting, rule-engine, device, and waste migrations. `Confirmed from model/migration`
- Device-service moved to composite ownership key `(device_id, tenant_id)`, which is the strongest tenant-isolation pattern in the repo. `Confirmed from migration`
- Data-service telemetry uses `tenant_id` as an Influx tag and as a payload field carried through outbox and downstream relay. `Confirmed from repository/query usage`
- Analytics-service stores tenant ownership inside job JSON parameters, not a dedicated column. `Confirmed from repository/query usage`

### Global/shared tables

- `tenant_id_sequences`, `device_id_sequences`, `hardware_unit_sequences` are global allocator tables.
- `analytics_worker_heartbeats` is global across workers.
- `tenant_security_audit_log` is cross-tenant audit infrastructure, not tenant-owned business data.
- `notification_channels` is a shared physical table read from both reporting-service and rule-engine-service.

### Device identity assumptions

- Device-service now treats `(device_id, tenant_id)` as the physical PK.
- Some services still query by plain `device_id` only:
  - waste backfill joins `devices` by `device_id` only in `005_add_tenant_scope_to_waste_jobs.py`
  - analytics artifacts key on `device_id` only
  - data-service enrichers query shared `devices` table by `device_id` and expect either one tenant or treat multi-tenant matches as exceptional
- This means global uniqueness of `device_id` is not consistently enforced across the whole repo even though device-service keeps a unique constraint on plain `device_id`. `Confirmed from model/migration` plus `Confirmed from repository/query usage`

## 6. Migration History Overview

### Auth

- `0001_initial_auth_schema.py`: creates `organizations`, `plants`, `users`, `user_plant_access`, `refresh_tokens`.
- `0003_add_auth_action_tokens.py`: adds invite/password-reset token table.
- `0007_rename_org_id_to_tenant_id.py`: renames auth ownership columns to `tenant_id`.
- `0008_hard_cut_sh_tenant_ids.py`: converts auth tenant IDs to 10-char SH business IDs and creates `tenant_id_sequences`.
- `0009_user_lifecycle_timestamps.py`: adds `invited_at`, `activated_at`, and `deactivated_at` to `users` for explicit invite/reactivate/deactivate lifecycle handling.
- `0010_add_auth_action_token_cleanup_indexes.py`: adds idempotent cleanup-support indexes for `auth_action_tokens` retention queries.

### Device

- `0001_initial_schema.py`: creates initial device metadata, shifts, health config, properties, performance trends, idle log.
- `20260329_0001_composite_device_pk.py`: makes `(device_id, tenant_id)` the PK and backfills child table tenant columns.
- `20260331_0003_add_tenant_security_audit_log.py`: adds audit table for blocked cross-tenant access.
- `add_dashboard_snapshots.py` and `add_dashboard_snapshot_minio_storage.py`: introduce dashboard cache rows and later S3/MinIO pointers.
- `20260407_0002_hardware_inventory_foundation.py`: adds `hardware_units` and `device_hardware_installations`.
- `20260416_0001_add_device_state_intervals.py`: introduces durable interval logging.
- Multiple interim migrations add device live projection, widget configuration, signed telemetry config, FLA redesign, and SH tenant hard cut. Names only are confirmed where contents were not opened.

### Data

- `20260324_0001_add_telemetry_outbox_and_reconciliation_log.py`: creates local MySQL outbox and reconciliation log.
- `02_data_service_dlq.sql`: bootstrap SQL creates `dlq_messages` outside Alembic.

### Analytics

- `0001_initial_schema.py`: creates `analytics_jobs`.
- `0002_queue_and_artifact_tables.py`: adds queue/lease fields and `ml_model_artifacts`.
- `0003_worker_heartbeat_and_accuracy_tables.py`: adds worker heartbeat, failure labels, accuracy evaluations.
- `0004_artifact_payload_longblob.py`: not opened, but migration name indicates payload widening to long blob.
- `0005_job_phase_tracking.py`: adds `phase`, `phase_label`, `phase_progress`.

### Reporting

- `001_initial.py`: creates `energy_reports`, `scheduled_reports`, `tenant_tariffs`.
- `003_settings_tables.py`: adds `tariff_config` and `notification_channels`.
- `005_tenant_scope_reporting_settings.py`: backfills tenant IDs into settings tables using auth `organizations`.
- `006_unify_tariff_source_of_truth.py`: migrates legacy `tariff_config` rows into `tenant_tariffs` and deletes legacy rows.
- `007_add_schedule_processing_claim.py`: adds `processing_started_at` and due-claim index to schedules.
- `008_sh_tenant_id_hard_cut.py`: enforces SH tenant IDs on reporting tables.
- `009_add_report_worker_claim_fields.py`: adds worker claim/retry/timeout fields to report jobs.

### Rule-engine

- `001_initial.py`: creates `rules` and `alerts`.
- `002_activity_events.py`: adds activity feed.
- `003_rules_v2_time_based_and_cooldown.py`, `005_add_rule_cooldown_units.py`, `20260412_0009_add_continuous_idle_duration_rule.py`: extend rule semantics. Names are confirmed; exact column deltas not fully inspected.
- `20260411_0008_sh_tenant_id_hard_cut.py`: enforces SH tenant IDs on `rules`, `alerts`, `activity_events`.
- `20260416_0010_notification_delivery_audit_ledger.py`: adds permanent delivery ledger.
- `20260416_0011_notification_delivery_hardening_constraints.py`: enforces status/billing invariants and non-null tenant ID on delivery ledger.
- `20260416_0012_rule_device_trigger_state.py`: moves cooldown state to per-device table.
- `20260417_0013_notification_outbox.py`: adds durable async notification queue.

### Waste-analysis

- `001_initial.py`: creates job and summary tables.
- `002_quality_gate_fields.py`: adds `error_code` and quality/status columns.
- `004_add_wastage_categories.py`: adds off-hours, overconsumption, and unoccupied metrics.
- `005_add_tenant_scope_to_waste_jobs.py`: backfills and enforces tenant ownership on jobs.
- `006_sh_tenant_id_hard_cut.py`: enforces SH tenant ID format.
- `008_expand_skipped_reason_columns.py`: currently a no-op compatibility bridge for previously-applied revision.

## 7. Query and Repository Map

### Shared tenant-scoping infrastructure

- `TenantScopedRepository` automatically injects `tenant_id = ctx.require_tenant()` filters for models that have a `tenant_id` column and blocks cross-tenant access unless explicit super-admin/system context is used.
- `tenant_guards.assert_same_tenant` writes blocked attempts to `tenant_security_audit_log`.
- Sources:
  - [scoped_repository.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/shared/scoped_repository.py)
  - [tenant_guards.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/shared/tenant_guards.py)
  - [tenant_context.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/shared/tenant_context.py)

### Auth repositories

| Repository | Tables touched | Query shapes / notes |
| --- | --- | --- |
| [user_repository.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/auth-service/app/repositories/user_repository.py) | `users`, `user_plant_access` | Lookup by email/id, tenant-scoped user lookup, list-by-tenant ordered by `created_at desc`, replace-all plant access via delete+bulk insert, permissions-version bump for auth invalidation |
| [org_repository.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/auth-service/app/repositories/org_repository.py) | `organizations`, `tenant_id_sequences` indirectly through allocator | create/list/update orgs, increment `entitlements_version` on entitlement changes |
| [plant_repository.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/auth-service/app/repositories/plant_repository.py) | `plants` | list-by-tenant and list-by-ids-for-tenant |

### Device repositories

| Repository | Tables touched | Query shapes / notes |
| --- | --- | --- |
| [device.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/device-service/app/repositories/device.py) | `devices` | tenant-scoped list with plant/device-type/status filters, count + paged query, soft delete, one-time update of `first_telemetry_timestamp` with conditional `UPDATE ... WHERE ... IS NULL` |
| [device_state_intervals.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/device-service/app/repositories/device_state_intervals.py) | `device_state_intervals` | open interval lookup, range-overlap query, tenant/device/state filtered counts, batched delete of old closed intervals |
| [hardware_inventory.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/device-service/app/repositories/hardware_inventory.py) | `hardware_units`, `device_hardware_installations` | tenant-scoped inventory list; join current installations to hardware units for active mapping view |

### Data-service repositories

| Repository | Tables / stores touched | Query shapes / notes |
| --- | --- | --- |
| [outbox_repository.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/data-service/src/repositories/outbox_repository.py) | `telemetry_outbox`, `reconciliation_log` | bulk insert outbox rows; claim pending/failed rows with exponential-backoff predicate and `FOR UPDATE SKIP LOCKED`; batch delivered/failure/dead cleanup operations |
| [dlq_repository.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/data-service/src/repositories/dlq_repository.py) | `dlq_messages` or file backend | MySQL backend creates indexes if missing; fetches retryable rows by status/error type/retry count/age; purges expired entries |
| [influxdb_repository.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/data-service/src/repositories/influxdb_repository.py) | Influx `device_telemetry` | Flux queries always validate `tenant_id` and `device_id`; tenant filter is explicit in Flux; batch write retry via Influx SDK; tag-cardinality audit |

### Analytics repositories

| Repository | Tables touched | Query shapes / notes |
| --- | --- | --- |
| [mysql_repository.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/analytics-service/src/infrastructure/mysql_repository.py) | `analytics_jobs`, `ml_model_artifacts` | Tenant filtering uses `json_extract(parameters, '$.tenant_id')`; accessible-device filtering may require in-memory post-filtering; parent/child jobs linked by `parameters.parent_job_id`; artifacts upserted by device+analysis+model_key+feature hash |

### Reporting repositories

| Repository | Tables touched | Query shapes / notes |
| --- | --- | --- |
| [report_repository.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/reporting-service/src/repositories/report_repository.py) | `energy_reports` | tenant-scoped create/get/list; dedup scans recent pending/processing rows by `params.dedup_signature`; worker claim and requeue use conditional `UPDATE`; one comment explicitly avoids extra tenant secondary-index lock to reduce deadlocks |
| [scheduled_repository.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/reporting-service/src/repositories/scheduled_repository.py) | `scheduled_reports` | due schedule claim uses `FOR UPDATE SKIP LOCKED`, stale-claim recovery on `processing_started_at`, then commits claim state |
| [settings_repository.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/reporting-service/src/repositories/settings_repository.py) | `notification_channels` | list active channels, lower-case email normalization, soft-disable by `is_active=false` |
| [tariff_repository.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/reporting-service/src/repositories/tariff_repository.py) | `tenant_tariffs` | tenant-scoped singleton read and upsert |

### Rule-engine repositories

| Repository | Tables touched | Query shapes / notes |
| --- | --- | --- |
| [rule.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/rule-engine-service/app/repositories/rule.py) | `rules`, `rule_trigger_states` | active-rule fetch for device uses MySQL `json_contains` on `device_ids`; list pagination is partly in-memory after visibility checks; `try_acquire_trigger_slot` uses nested transaction + `FOR UPDATE` on trigger state to enforce cooldown atomically |
| [notification_delivery.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/rule-engine-service/app/repositories/notification_delivery.py) | `notification_delivery_logs` | status transitions, provider-message-id lookup, monthly summary aggregates, search/filter support |
| [notification_outbox.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/rule-engine-service/app/repositories/notification_outbox.py) | `notification_outbox` | claim/requeue/terminal updates; due queue list ordered by `next_attempt_at`; aggregate retry counters |
| [notification_settings.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/rule-engine-service/app/repositories/notification_settings.py) | `notification_channels` | read-only lookup of active tenant channel values |

### Waste-analysis repositories

| Repository | Tables touched | Query shapes / notes |
| --- | --- | --- |
| [waste_repository.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/waste-analysis-service/src/repositories/waste_repository.py) | `waste_analysis_jobs`, `waste_device_summary` | tenant-scoped job list; duplicate detection scans recent pending/running jobs and compares sorted `device_ids`; summary replace is delete-all then insert batch/chunks |

## 8. DB Risk Areas

### High-risk isolation gaps

- `analytics_jobs` tenant ownership is stored in JSON (`parameters->tenant_id`) instead of a dedicated indexed column.
  - Risk: missed filters, expensive JSON scans, inconsistent writes.
  - Evidence: [mysql_repository.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/analytics-service/src/infrastructure/mysql_repository.py)

- `ml_model_artifacts` has no tenant column.
  - Risk: artifact reuse across tenants if `device_id` is not globally unique in practice.
  - Evidence: [database.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/analytics-service/src/models/database.py)

- `telemetry_outbox`, `reconciliation_log`, and `dlq_messages` are not tenant-scoped at schema level.
  - Risk: operational queries and support tooling must rely on payload inspection or external context.
  - Evidence: [outbox model](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/data-service/src/models/outbox.py), [02_data_service_dlq.sql](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/init-scripts/mysql/02_data_service_dlq.sql)

- `waste_device_summary` has no FK to `waste_analysis_jobs`.
  - Risk: orphan summaries and referential drift.
  - Evidence: [waste_jobs.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/waste-analysis-service/src/models/waste_jobs.py)

### Query and performance hotspots

- Rule visibility on selected devices uses MySQL `json_contains` over `rules.device_ids`.
  - Risk: JSON array scans and subtle behavior changes if schema or MySQL JSON semantics change.

- Reporting duplicate detection and scoped visibility depend on parsing JSON params in application code.
  - Risk: regressions if report param shape changes.

- Schedule and outbox claiming rely on row-level locking / `FOR UPDATE SKIP LOCKED`.
  - Risk: deadlocks or starvation if indexes change or tenant filters are removed.

- Device-service composite PK migration means any query or new table that joins on `device_id` alone is a leakage/regression risk.
  - Existing examples already remain in waste backfill and analytics/data-service side reads.

- Notification ledger and outbox status invariants are protected by DB check constraints.
  - Risk: code paths that attempt unsupported status values will fail at commit time.

### Operational schema mismatches to watch

- `hardware_units.unit_name` exists in the current model but was not present in the inspected foundation migration.
  - Impact: any environment missing later migrations will not match the model.
  - Evidence: [device model](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/device-service/app/models/device.py), [20260407_0002_hardware_inventory_foundation.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/device-service/alembic/versions/20260407_0002_hardware_inventory_foundation.py)

- `device_shifts` and `parameter_health_config` model nullability/types do not perfectly mirror the earliest migration snapshots.
  - Impact: old local DBs may diverge from model intent.
  - Evidence: [device model](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/device-service/app/models/device.py), [0001_initial_schema.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/device-service/alembic/versions/0001_initial_schema.py)

- Waste migration `008_expand_skipped_reason_columns.py` is now only a compatibility bridge.
  - Impact: migration history can look complete while current schema depends on previously-applied branch state.
  - Evidence: [008_expand_skipped_reason_columns.py](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/services/waste-analysis-service/alembic/versions/008_expand_skipped_reason_columns.py)
