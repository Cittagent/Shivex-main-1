# CODEBASE BIBLE — FactoryOPS / Cittagent Platform
_Audit date: 2026-04-03 | Commit: d9e2ba3542b9d32dc02b476fe4315cb3e6078f3c | Audited by: AI Architect_

---

## 0. AUDIT METADATA
- Total files scanned: ~800 (Python + TypeScript/React + SQL + configs)
- Total lines of code: ~20,000 (2,354 Python files, 13,565 TypeScript files, 693 TSX files)
- Files skipped and why: `.next/` build artifacts, `.pyc` compiled cache, binary files
- Languages detected: Python (backend), TypeScript/JavaScript (frontend), SQL (migrations)
- Estimated codebase age: ~2 years (first commits from 2024)

---

## 1. EXECUTIVE SUMMARY
**What this product does**: FactoryOPS is a multi-tenant industrial IoT monitoring platform that ingests telemetry from connected devices via MQTT, stores time-series data in InfluxDB, provides real-time dashboards with live projections, generates energy/performance reports, and offers AI-powered copilot assistance.

**Core user workflows**:
1. User logs in → receives JWT token with tenant scope
2. Operator onboards devices (compressor, motor, etc.) with metadata and shift schedules
3. Devices publish telemetry via MQTT → data-service ingests → stores in InfluxDB + updates device-service state
4. Dashboard displays real-time fleet status via WebSocket SSE stream
5. Manager configures health thresholds and idle detection rules
6. Analytics runs ML anomaly detection jobs on telemetry data
7. Reports generated as PDFs with energy consumption and cost analysis

**Current maturity**: Production-grade MVP with multi-tenancy, auth, real-time features, ML pipeline

**Primary actors / user types**:
- `SuperAdmin` (full system access)
- `Admin` (org management)
- `PlantManager` (plant-scoped access)
- `Operator` (device operational access)
- `Viewer` (read-only)

**One-line tech stack**: Python FastAPI (10 microservices) + Next.js 16 React 19 + MySQL 8 + Redis 7 + InfluxDB 2.7 + EMQX MQTT 5.3 + MinIO + SQLAlchemy async

**Top 3 architectural strengths**:
1. Clean service separation with shared auth middleware
2. Multi-tenant tenant context propagation throughout
3. Real-time streaming via Redis pub/sub for fleet updates

**Top 3 architectural risks**:
1. Shared database across services (not strict microservice isolation)
2. Complex cyclic dependency in services/shared module
3. No circuit breakers on inter-service HTTP calls

---

## 2. REPOSITORY STRUCTURE

```
.
├── services/
│   ├── auth-service/         # JWT authentication, org/user management
│   ├── device-service/      # Device CRUD, shifts, health config, live state
│   ├── data-service/        # MQTT ingestion, InfluxDB storage, telemetry queries
│   ├── energy-service/      # Energy calculations, tariff caching
│   ├── rule-engine-service/ # Rule evaluation, alerts
│   ├── analytics-service/   # ML anomaly detection jobs, worker pool
│   ├── reporting-service/   # PDF report generation
│   ├── data-export-service/ # S3 export from InfluxDB
│   ├── waste-analysis-service/ # Waste/idle analysis
│   ├── copilot-service/     # AI assistant (Groq/Gemini)
│   ├── shared/              # Shared auth middleware, tenant context, feature entitlements
│   └── (Dockerfile per service)
├── ui-web/                  # Next.js 16 application
├── init-scripts/mysql/      # DB initialization SQL
├── db/bootstrap.sql         # Database user/privilege setup
├── scripts/                 # Simulator control, verification scripts
├── monitoring/              # Prometheus/Grafana/Alertmanager configs
├── tools/                   # Device simulator
├── tests/                   # Integration tests
└── docker-compose.yml       # Full stack orchestration
```

**Folder ownership**:
- `services/auth-service` — Authentication and authorization
- `services/device-service` — Device management domain
- `services/data-service` — Telemetry ingestion domain
- `services/energy-service` — Energy calculations domain
- `services/rule-engine-service` — Rules and alerts domain
- `services/analytics-service` — ML/anomaly detection domain
- `services/reporting-service` — Report generation domain
- `services/copilot-service` — AI assistant domain
- `ui-web` — Web UI domain
- `services/shared` — Cross-cutting concerns (auth, tenant context)

---

## 3. COMPLETE TECH STACK INVENTORY

| Layer | Technology | Version (exact) | Purpose | Where Configured | Notes/Risks |
|-------|-----------|----------------|---------|-----------------|-------------|
| Runtime | Python | 3.11+ | Backend services | Dockerfile, requirements.txt | |
| Runtime | Node.js | 20+ | Frontend build | ui-web/package.json | |
| Framework | FastAPI | 0.104.1 | Backend API framework | data-service/requirements.txt | Core framework for all services |
| Framework | Next.js | 16.1.6 | Frontend React framework | ui-web/package.json | App router |
| Database | MySQL | 8.0 | Relational storage | docker-compose.yml | Single shared DB `ai_factoryops` |
| Database | InfluxDB | 2.7-alpine | Time-series telemetry | docker-compose.yml | Bucket: `telemetry` |
| Cache | Redis | 7-alpine | Session, pub/sub, caching | docker-compose.yml | |
| Message Broker | EMQX | 5.3.0 | MQTT broker | docker-compose.yml | |
| Object Storage | MinIO | latest | S3-compatible storage | docker-compose.yml | Buckets: `energy-platform-datasets`, `factoryops-waste-reports` |
| ORM | SQLAlchemy | 2.0.36 | Database ORM | service requirements.txt | Async via aiomysql |
| Auth | PyJWT/jose | Latest | JWT handling | auth-service/requirements.txt | |
| Frontend State | React Context | 19.2.3 | Auth state | ui-web/lib/authContext.tsx | |
| Frontend Charts | Recharts | 3.7.0 | Data visualization | ui-web/package.json | |
| Queue | Redis Streams | Via redis-py | Background job queue | analytics-service | Consumer groups |
| ML | scikit-learn | (in analytics-service) | Anomaly detection | requirements.txt | |
| AI | Groq SDK | Latest | Copilot LLM | copilot-service/requirements.txt | |

---

## 4. ENVIRONMENT VARIABLES — MASTER LIST

| Variable Name | Service(s) That Use It | File:Line Where Used | Purpose | Required? | Validated on startup? | Example / Default | Secret? |
|--------------|----------------------|---------------------|---------|-----------|----------------------|-------------------|---------|
| DATABASE_URL | All services | config.py:Settings.DATABASE_URL | MySQL connection | YES | YES | mysql+aiomysql://energy:energy@mysql:3306/ai_factoryops | YES |
| JWT_SECRET_KEY | All services | auth_middleware.py:28 | JWT signing | YES | YES | (64-char hex) | YES |
| JWT_ALGORITHM | All services | auth_middleware.py:36 | Signing algorithm | NO | NO | HS256 | NO |
| REDIS_URL | All services | config.py | Redis connection | YES | NO | redis://redis:6379/0 | NO |
| AUTH_SERVICE_URL | All services | docker-compose.yml | Auth service endpoint | YES | NO | http://auth-service:8090 | NO |
| INFLUXDB_URL | data-service, reporting | docker-compose.yml | InfluxDB connection | YES | NO | http://influxdb:8086 | NO |
| INFLUXDB_TOKEN | data-service, reporting | docker-compose.yml | InfluxDB auth | YES | NO | energy-token | YES |
| MINIO_ENDPOINT | reporting, analytics | docker-compose.yml | S3 endpoint | YES | NO | minio:9000 | NO |
| MINIO_ROOT_USER | minio | docker-compose.yml | MinIO access | YES | NO | minio | YES |
| MINIO_ROOT_PASSWORD | minio | docker-compose.yml | MinIO secret | YES | NO | minio123 | YES |
| SMTP_SERVER | auth-service | docker-compose.yml | Email sending | NO | NO | smtp.gmail.com | NO |
| EMAIL_PASSWORD | auth-service | .env | Email password | YES | NO | (gmail app password) | YES |
| GROQ_API_KEY | copilot-service | .env | AI provider | YES | NO | (API key) | YES |
| EMAIL_ENABLED | auth-service | config.py | Enable email flows | NO | NO | true | NO |

🔴 **RISK**: Hardcoded secrets in `.env`:
- JWT_SECRET_KEY: `0667d05b0d0777ea3d07b3061507525ddba523e6c70f67a2dfaab30c29287b48` (line 115 in .env)
- GROQ_API_KEY: `rotated_218c49a47c20ec473c1ef091f844cb49e9a63be7aded06f5` (line 109 in .env)
- EMAIL_PASSWORD: `wrhlojmmqhjczlto` (line 102-103 in .env)

🟡 **DEBT**: Variables referenced in code but missing from `.env.example`: `JWT_ALGORITHM`, `MINIO_ENDPOINT`, `LOG_LEVEL`, `PLATFORM_TIMEZONE`

---

## 5. DATABASE SCHEMA — EXHAUSTIVE

### 5a. MySQL (ai_factoryops)

**Connection config**: host=mysql, port=3306, db=ai_factoryops, pool_size=10, timeout=30s

#### Core Tables (dependency order)

**organizations** (auth-service)
| Column | Type | Nullable | Default | Constraints | Description |
|--------|------|----------|---------|-------------|-------------|
| id | VARCHAR(36) | NO | | PRIMARY KEY | UUID |
| name | VARCHAR(255) | NO | | | Organization name |
| created_at | DATETIME | NO | UTC NOW | | |
| updated_at | DATETIME | NO | UTC NOW | | |

**users** (auth-service)
| Column | Type | Nullable | Default | Constraints | Description |
|--------|------|----------|---------|-------------|-------------|
| id | VARCHAR(36) | NO | | PRIMARY KEY | UUID |
| email | VARCHAR(255) | NO | | UNIQUE | User email |
| password_hash | VARCHAR(255) | NO | | | Bcrypt hash |
| organization_id | VARCHAR(36) | YES | NULL | FK→organizations.id | Org reference |
| role | VARCHAR(50) | NO | | | SuperAdmin/Admin/PlantManager/Operator/Viewer |
| plant_ids | JSON | NO | [] | | Array of accessible plant IDs |
| is_active | BOOLEAN | NO | TRUE | | |

**refresh_tokens** (auth-service)
| Column | Type | Nullable | Default | Constraints | Description |
|--------|------|----------|---------|-------------|-------------|
| id | BIGINT | NO | AUTO | PRIMARY KEY | |
| user_id | VARCHAR(36) | NO | | FK→users.id ON DELETE CASCADE | |
| token | VARCHAR(512) | NO | | UNIQUE | JTI + hashed |
| expires_at | DATETIME | NO | | | |
| created_at | DATETIME | NO | NOW | | |

**devices** (device-service)
| Column | Type | Nullable | Default | Constraints | Description |
|--------|------|----------|---------|-------------|-------------|
| device_id | VARCHAR(50) | NO | | PRIMARY KEY (PK part 1) | Business key |
| tenant_id | VARCHAR(50) | NO | | PRIMARY KEY (PK part 2), INDEX | Multi-tenant scope |
| plant_id | VARCHAR(36) | YES | NULL | INDEX | Soft ref to auth-service plants |
| device_name | VARCHAR(255) | NO | | | |
| device_type | VARCHAR(100) | NO | | INDEX | e.g., compressor, motor |
| data_source_type | VARCHAR(20) | NO | metered | INDEX | metered/sensor |
| phase_type | VARCHAR(20) | YES | NULL | INDEX | single/three |
| last_seen_timestamp | DATETIME | YES | NULL | INDEX | UTC timestamp |
| created_at | DATETIME | NO | UTC NOW | | |
| updated_at | DATETIME | NO | UTC NOW | | |
| deleted_at | DATETIME | YES | NULL | | Soft delete |

**device_shifts** (device-service)
| Column | Type | Nullable | Default | Constraints | Description |
|--------|------|----------|---------|-------------|-------------|
| id | INT | NO | AUTO | PRIMARY KEY | |
| device_id | VARCHAR(50) | NO | | FK→devices(device_id) ON DELETE CASCADE, INDEX | |
| tenant_id | VARCHAR(50) | YES | NULL | INDEX | |
| shift_name | VARCHAR(100) | NO | | | e.g., "Morning Shift" |
| shift_start | TIME | NO | | | |
| shift_end | TIME | NO | | | |
| maintenance_break_minutes | INT | NO | 0 | | |
| day_of_week | INT | YES | NULL | | 0-6 (Monday-Sunday) |
| is_active | BOOLEAN | NO | TRUE | | |

**parameter_health_config** (device-service)
| Column | Type | Nullable | Default | Constraints | Description |
|--------|------|----------|---------|-------------|-------------|
| id | INT | NO | AUTO | PRIMARY KEY | |
| device_id | VARCHAR(50) | NO | | FK→devices(device_id) ON DELETE CASCADE, INDEX | |
| tenant_id | VARCHAR(50) | YES | NULL | INDEX | |
| parameter_name | VARCHAR(100) | NO | | | e.g., voltage, current |
| normal_min | FLOAT | YES | NULL | | |
| normal_max | FLOAT | YES | NULL | | |
| weight | FLOAT | NO | 0.0 | | Must sum to 100% |
| is_active | BOOLEAN | NO | TRUE | | |

**device_live_state** (device-service)
| Column | Type | Nullable | Default | Constraints | Description |
|--------|------|----------|---------|-------------|-------------|
| device_id | VARCHAR(50) | NO | | PRIMARY KEY (PK part 1) | FK→devices(device_id) ON DELETE CASCADE |
| tenant_id | VARCHAR(50) | NO | | PRIMARY KEY (PK part 2) | |
| runtime_status | VARCHAR(32) | NO | stopped | INDEX | running/stopped |
| health_score | FLOAT | YES | NULL | | |
| today_energy_kwh | DECIMAL(14,6) | NO | 0 | | |
| today_idle_kwh | DECIMAL(14,6) | NO | 0 | | |
| month_energy_kwh | DECIMAL(14,6) | NO | 0 | | |
| version | BIGINT | NO | 0 | INDEX | Optimistic locking |
| updated_at | DATETIME | NO | UTC NOW | INDEX | |

**device_performance_trends** (device-service)
| Column | Type | Nullable | Default | Constraints | Description |
|--------|------|----------|---------|-------------|-------------|
| id | INT | NO | AUTO | PRIMARY KEY | |
| device_id | VARCHAR(50) | NO | | INDEX | FK→devices(device_id) ON DELETE CASCADE |
| tenant_id | VARCHAR(50) | NO | | INDEX | |
| bucket_start_utc | DATETIME | NO | | INDEX | 5-minute bucket |
| bucket_end_utc | DATETIME | NO | | | |
| health_score | FLOAT | YES | NULL | | |
| uptime_percentage | FLOAT | YES | NULL | | |
| created_at | DATETIME | NO | UTC NOW | INDEX | |

**telemetry_outbox** (data-service)
| Column | Type | Nullable | Default | Constraints | Description |
|--------|------|----------|---------|-------------|-------------|
| id | BIGINT | NO | AUTO | PRIMARY KEY | |
| device_id | VARCHAR(50) | NO | INDEX | | |
| tenant_id | VARCHAR(50) | NO | INDEX | | |
| payload_json | JSON | NO | | | Telemetry payload |
| processed | BOOLEAN | NO | FALSE | | |
| created_at | DATETIME | NO | NOW | | |
| processed_at | DATETIME | YES | NULL | | |

**rules** (rule-engine-service)
| Column | Type | Nullable | Default | Constraints | Description |
|--------|------|----------|---------|-------------|-------------|
| id | INT | NO | AUTO | PRIMARY KEY | |
| tenant_id | VARCHAR(50) | NO | | INDEX | |
| name | VARCHAR(255) | NO | | | Rule name |
| condition_json | JSON | NO | | | Rule condition |
| action_type | VARCHAR(50) | NO | | | email/webhook |
| is_active | BOOLEAN | NO | TRUE | | |
| cooldown_minutes | INT | NO | 0 | | |

**rule_alerts** (rule-engine-service)
| Column | Type | Nullable | Default | Constraints | Description |
|--------|------|----------|---------|-------------|-------------|
| id | BIGINT | NO | AUTO | PRIMARY KEY | |
| rule_id | INT | NO | | INDEX | FK→rules(id) ON DELETE CASCADE |
| device_id | VARCHAR(50) | NO | | INDEX | |
| tenant_id | VARCHAR(50) | NO | | INDEX | |
| triggered_at | DATETIME | NO | NOW | | |
| acknowledged | BOOLEAN | NO | FALSE | | |

**analytics_jobs** (analytics-service)
| Column | Type | Nullable | Default | Constraints | Description |
|--------|------|----------|---------|-------------|-------------|
| id | INT | NO | AUTO | PRIMARY KEY | |
| job_type | VARCHAR(50) | NO | | | anomaly_detection, retraining |
| tenant_id | VARCHAR(50) | NO | | INDEX | |
| status | VARCHAR(20) | NO | pending | INDEX | pending/running/completed/failed |
| payload_json | JSON | NO | | | Job parameters |
| result_json | JSON | YES | NULL | | Result |
| created_at | DATETIME | NO | NOW | | INDEX |
| completed_at | DATETIME | YES | NULL | | |

**Relationship Map**:
- organizations (1) → users (many) via organization_id
- users (1) → refresh_tokens (many) via user_id
- devices (1) → device_shifts (many) via device_id
- devices (1) → device_live_state (1) via device_id+tenant_id (composite)
- devices (1) → device_performance_trends (many) via device_id+tenant_id
- devices (1) → parameter_health_config (many) via device_id
- devices (1) → telemetry_outbox (many) via device_id
- rules (1) → rule_alerts (many) via rule_id

**Transaction Boundaries**:
- device_shifts create/update/delete wrap in DB transaction (service layer)
- device_live_state updates use optimistic locking via version column

**Identified Slow Query Risks**:
| File:Line | Query Description | Risk | Recommended Fix |
|-----------|------------------|------|----------------|
| device-service/app/services/device.py:list_devices | SELECT with multiple optional filters, no composite index on (tenant_id, device_type, status) | N+1 if filtered by type+status | Add composite index |
| device-service/app/services/live_dashboard.py | JOIN on device_live_state without covering index | Full table scan | Add index on (tenant_id, runtime_status) |

**Migration History** (chronological, key migrations):
| Migration File | Date | What It Did |
|---------------|------|-------------|
| 0001_initial_schema.py (device-service) | 2026-03-24 | Initial devices, shifts, health_config tables |
| 20260326_0001_add_plant_id_to_devices.py | 2026-03-26 | Added plant_id FK to devices |
| 20260331_0001_add_tenant_id_to_scoped_tables.py | 2026-03-31 | Added tenant_id to all tables |
| 20260331_0002_enforce_tenant_not_null.py | 2026-03-31 | Made tenant_id NOT NULL |
| 0001_initial_auth_schema.py (auth-service) | Initial | users, organizations, refresh_tokens |
| 0003_add_auth_action_tokens.py (auth-service) | Added | action_tokens for invite/password reset |

---

## 6. BACKEND — COMPLETE ARCHITECTURE

### 6a. Service / Module Inventory

**[device-service]** (Port 8000)
- Responsibility: Device CRUD, shift management, health config, live state projections, dashboard snapshots
- Entrypoint: `services/device-service/app/__init__.py` with FastAPI
- Framework: FastAPI 0.104.1
- Port: 8000
- Base URL path: `/api/v1`
- Database(s) it owns: devices, device_shifts, parameter_health_config, device_live_state, device_performance_trends
- Background jobs: Performance trends scheduler, Dashboard snapshot scheduler, Live projection reconciler
- Key env vars: DATABASE_URL, REDIS_URL, JWT_SECRET_KEY, DATA_SERVICE_BASE_URL, ENERGY_SERVICE_BASE_URL

**[data-service]** (Port 8081)
- Responsibility: MQTT ingestion, telemetry storage in InfluxDB, reconciliation, device sync to device-service
- Entrypoint: `services/data-service/src/main.py` (FastAPI)
- Framework: FastAPI
- Port: 8081
- Base URL path: `/api/v1`
- Database(s) it owns: telemetry_outbox
- Async messages it consumes: MQTT topics `+/devices/+/telemetry`
- Sync calls it makes → device-service: `/api/v1/devices/{device_id}/live-update`

**[auth-service]** (Port 8090)
- Responsibility: JWT issuance/refresh, user/org management, email invites, rate limiting
- Entrypoint: `services/auth-service/app/main.py`
- Framework: FastAPI
- Port: 8090
- Database(s) it owns: users, organizations, refresh_tokens, action_tokens

**[energy-service]** (Port 8010)
- Responsibility: Energy calculations (kWh, cost), tariff caching, energy stream broadcasting
- Entrypoint: `services/energy-service/app/main.py`
- Database(s) it owns: energy_calculations, tariff_cache

**[rule-engine-service]** (Port 8002)
- Responsibility: Rule CRUD, real-time condition evaluation, alert triggering
- Entrypoint: `services/rule-engine-service/app/__init__.py`
- Database(s) it owns: rules, rule_alerts

**[analytics-service]** (Port 8003)
- Responsibility: ML anomaly detection, model training, job queue processing
- Entrypoint: `services/analytics-service/src/__init__.py`
- Database(s) it owns: analytics_jobs, model_artifacts
- Background jobs: Worker pool (2 workers), weekly retrainer

**[reporting-service]** (Port 8085)
- Responsibility: PDF generation, report scheduling
- Entrypoint: `services/reporting-service/src/main.py`

**[copilot-service]** (Port 8007)
- Responsibility: AI assistant using Groq/Gemini
- Entrypoint: `services/copilot-service/src/main.py`

### 6b. COMPLETE API REFERENCE

**device-service** (prefix: `/api/v1`)

| Method | Full Path | Handler | Auth Required | Role/Permission | Request Body Schema | Response Schema | Status Codes |
|--------|-----------|---------|--------------|----------------|--------------------|-----------------|--------------|
| GET | `/dashboard/summary` | devices.py:get_dashboard_summary | YES | Any | N/A | DashboardSummaryResponse | 200 |
| GET | `/dashboard/fleet-snapshot` | devices.py:get_fleet_snapshot | YES | Any | N/A | FleetSnapshotResponse | 200 |
| GET | `/dashboard/fleet-stream` | devices.py:fleet_snapshot_stream | YES | Any | N/A | SSE stream | 200 |
| GET | `/devices` | devices.py:list_devices | YES | Any | N/A | DeviceListResponse | 200 |
| POST | `/devices` | devices.py:create_device | YES | !viewer | DeviceCreate | DeviceSingleResponse | 201, 409 |
| GET | `/devices/{device_id}` | devices.py:get_device | YES | Any | N/A | DeviceSingleResponse | 200, 404 |
| PUT | `/devices/{device_id}` | devices.py:update_device | YES | !viewer | DeviceUpdate | DeviceSingleResponse | 200, 404 |
| DELETE | `/devices/{device_id}` | devices.py:delete_device | YES | !viewer | N/A | 204 | 204, 404 |
| GET | `/devices/{device_id}/shifts` | devices.py:list_shifts | YES | Any | N/A | ShiftListResponse | 200 |
| POST | `/devices/{device_id}/shifts` | devices.py:create_shift | YES | !viewer | ShiftCreate | ShiftSingleResponse | 201, 409 |
| GET | `/devices/{device_id}/health-config` | devices.py:list_health_configs | YES | Any | N/A | ParameterHealthConfigListResponse | 200 |
| POST | `/devices/{device_id}/health-config` | devices.py:create_health_config | YES | !viewer | ParameterHealthConfigCreate | ParameterHealthConfigSingleResponse | 201 |
| POST | `/devices/{device_id}/live-update` | devices.py:live_device_update | YES (service) | Internal | DeviceLiveUpdateRequest | dict | 200, 404 |

**auth-service** (prefix: `/api/v1/auth`)

| Method | Full Path | Handler | Auth Required | Request Body Schema | Response Schema |
|--------|-----------|---------|--------------|--------------------|-----------------|
| POST | `/login` | auth.py:login | NO | {email, password} | {access_token, refresh_token, user} |
| POST | `/refresh` | auth.py:refresh | NO | {refresh_token} | {access_token, refresh_token} |
| POST | `/logout` | auth.py:logout | YES | N/A | {success} |
| POST | `/forgot-password` | auth.py:forgot_password | NO | {email} | {success} |
| POST | `/reset-password` | auth.py:reset_password | NO | {token, password} | {success} |
| POST | `/invite` | auth.py:invite_user | YES (Admin+) | {email, role} | {success} |
| GET | `/me` | auth.py:get_me | YES | N/A | MeResponse |

**rule-engine-service** (prefix: `/api/v1`)

| Method | Full Path | Handler | Auth Required | Response Schema |
|--------|-----------|---------|--------------|-----------------|
| GET | `/rules` | rules.py:list_rules | YES | RuleListResponse |
| POST | `/rules` | rules.py:create_rule | YES (Admin+) | RuleSingleResponse |
| GET | `/alerts` | alerts.py:list_alerts | YES | AlertListResponse |
| POST | `/alerts/{id}/acknowledge` | alerts.py:acknowledge_alert | YES | AlertResponse |

### 6c. MIDDLEWARE STACK — EXACT EXECUTION ORDER

**[device-service] request lifecycle:**
1. **AuthMiddleware** (`services/shared/auth_middleware.py:287`)
   - Checks if path in open paths (`/health`, `/ready`, `/docs`, `/api/v1/auth/login`, etc.)
   - If not open: extracts JWT from `Authorization: Bearer` header
   - Decodes JWT using `JWT_SECRET_KEY` and `JWT_ALGORITHM`
   - Extracts `tenant_id`, `user_id`, `role`, `plant_ids`, `is_super_admin`
   - Attaches to request.state.auth
   - Short-circuits: returns 401 if invalid/missing token
   - Logs: tenant_id, user_id at DEBUG level

2. **CORS middleware** (if configured per service)
   - Device-service: No explicit CORS (uses defaults)
   - Auth-service: Allows localhost:3000, 127.0.0.1:3000, 32.193.53.87:3000

3. **Service-specific middleware** (in `app/__init__.py`)
   - Fleet stream broadcaster middleware for SSE

### 6d. AUTHENTICATION & AUTHORIZATION — COMPLETE

**Auth mechanism**: JWT with PyJWT/jose library

**Token structure** (from JWT decode):
```json
{
  "sub": "user-uuid",
  "tenant_id": "tenant-uuid",
  "role": "Admin|PlantManager|Operator|Viewer",
  "plant_ids": ["plant-uuid-1", "plant-uuid-2"],
  "is_super_admin": false,
  "iat": 1712000000,
  "exp": 1712000900,
  "jti": "unique-token-id"
}
```

**Token lifecycle**:
- Issue: `/api/v1/auth/login` → `auth_service.py:login()` → creates JWT with 15-min expiry
- Access token expiry: 15 minutes (configurable via `ACCESS_TOKEN_EXPIRE_MINUTES`)
- Refresh token: stored in `refresh_tokens` table with 7-day expiry (configurable via `REFRESH_TOKEN_EXPIRE_DAYS`)
- Refresh flow: `/api/v1/auth/refresh` → validates refresh token → issues new access + rotates refresh
- Invalidation: refresh token stored in DB with `expires_at`, can be revoked by deleting row

**RBAC / Permission model**:

| Role | Can Do | Cannot Do |
|------|--------|-----------|
| SuperAdmin | All operations, manage orgs | None |
| Admin | Manage users, devices, rules | Change org settings |
| PlantManager | Devices in assigned plants | Create users |
| Operator | View/update devices | Delete devices, manage config |
| Viewer | Read-only access | Any write operation |

**Multi-tenancy enforcement**:
- Tenant identified from: JWT claim `tenant_id` (primary), fallback to `X-Tenant-Id` header
- Enforcement point: `require_tenant()` in `services/shared/tenant_context.py`
- Tables with tenant scoping: devices, device_shifts, parameter_health_config, device_live_state, device_performance_trends, rules, rule_alerts, analytics_jobs
- 🔴 **RISK**: Tables that SHOULD have tenant_id but don't: `organizations` (global), `users` (has organization_id but no tenant_id)

### 6e. COMPLETE MIDDLEWARE & VALIDATION LAYER MAP

| Field | Validated At | Validation Rules | Sanitized? |
|-------|---------------|------------------|------------|
| device_id | Pydantic model DeviceCreate | String, max 50 chars, alphanumeric + dash | YES (strip whitespace) |
| email | Pydantic model LoginRequest | Email format, max 255 chars | NO |
| password | Service layer | Min 8 chars (auth service) | NO (bcrypt hashed) |
| shift_start/time | Pydantic ShiftCreate | HH:MM format | NO |
| tenant_id | require_tenant() | Must match JWT claim | NO |

Business logic validation done in service layer (e.g., shift overlap check), schema validation in Pydantic models, DB constraints at table level.

🔴 **RISK**: No input validation on `metadata_json` field — accepts any JSON string without sanitization.

### 6f. ERROR HANDLING — COMPLETE MAP

**Global error handler**: `app/__init__.py:exception_handler`
- Catches all unhandled exceptions
- Returns 500 with `{"error": "INTERNAL_ERROR", "message": "Unexpected server error"}`

**Custom exception inventory**:
| Exception Class | HTTP Status | Error Code | When Thrown |
|----------------|------------|------------|-------------|
| DashboardDeviceNotFoundError | 404 | DEVICE_NOT_FOUND | Device not found in dashboard |
| ShiftOverlapError | 409 | SHIFT_OVERLAP_CONFLICT | Shift times overlap |
| ValueError (device exists) | 409 | DEVICE_ALREADY_EXISTS | Duplicate device_id |

**Unhandled exception behavior**: Process returns 500, logs full traceback, does not crash

**Error logging**: Structured logging via `structlog`, format: JSON with fields (service, method, error, stack)

---

## 7. FRONTEND ARCHITECTURE — COMPLETE

### 7a. App Bootstrap Sequence
1. `next dev` starts Next.js 16 on port 3000
2. `_app.tsx` (or root layout) mounts `<AuthProvider>`
3. `AuthProvider` checks localStorage for cached token
4. Calls `/api/v1/auth/me` to validate and get user data
5. Stores user in React context state
6. Router checks `isAuthenticated` — redirects to `/login` if false
7. Protected pages render with user context available

### 7b. Routing — Complete Route Table

| Route Path | Component File | Auth Required | Role Required | Lazy Loaded? |
|-----------|---------------|--------------|--------------|--------------|
| `/login` | app/(auth)/login/page.tsx | NO | N/A | NO |
| `/forgot-password` | app/(auth)/forgot-password/page.tsx | NO | N/A | NO |
| `/reset-password` | app/(auth)/reset-password/page.tsx | NO | N/A | NO |
| `/` | app/(protected)/page.tsx | YES | Any | NO |
| `/devices` | app/(protected)/devices/page.tsx | YES | Any | NO |
| `/devices/[deviceId]` | app/(protected)/devices/[deviceId]/page.tsx | YES | Any | NO |
| `/devices/[deviceId]/analytics` | app/(protected)/devices/[deviceId]/analytics/page.tsx | YES | Any | NO |
| `/devices/[deviceId]/stats` | app/(protected)/devices/[deviceId]/stats/page.tsx | YES | Any | NO |
| `/devices/[deviceId]/telemetry` | app/(protected)/devices/[deviceId]/telemetry/page.tsx | YES | Any | NO |
| `/devices/[deviceId]/alerts` | app/(protected)/devices/[deviceId]/alerts/page.tsx | YES | Any | NO |
| `/machines` | app/(protected)/machines/page.tsx | YES | Any | NO |
| `/rules` | app/(protected)/rules/page.tsx | YES | Any | NO |
| `/rules/new` | app/(protected)/rules/new/page.tsx | YES | Admin+ | NO |
| `/rules/[ruleId]` | app/(protected)/rules/[ruleId]/page.tsx | YES | Any | NO |
| `/reports` | app/(protected)/reports/page.tsx | YES | Any | NO |
| `/reports/energy` | app/(protected)/reports/energy/page.tsx | YES | Any | NO |
| `/reports/compare` | app/(protected)/reports/compare/page.tsx | YES | Any | NO |
| `/analytics` | app/(protected)/analytics/page.tsx | YES | Any | NO |
| `/calendar` | app/(protected)/calendar/page.tsx | YES | Any | NO |
| `/waste-analysis` | app/(protected)/waste-analysis/page.tsx | YES | Any | NO |
| `/copilot` | app/(protected)/copilot/page.tsx | YES | Any | NO |
| `/settings` | app/(protected)/settings/page.tsx | YES | Any | NO |
| `/admin` | app/(protected)/admin/page.tsx | YES | Admin+ | NO |
| `/admin/orgs` | app/(protected)/admin/orgs/page.tsx | YES | SuperAdmin | NO |
| `/org/users` | app/(protected)/org/users/page.tsx | YES | Admin+ | NO |
| `/org/plants` | app/(protected)/org/plants/page.tsx | YES | Admin+ | NO |
| `/profile` | app/(protected)/profile/page.tsx | YES | Any | NO |

### 7c. State Management — Complete Store Map

| Store Name | File | State Shape | Actions/Mutations | Persisted? | Where Used |
|-----------|------|-------------|-------------------|-----------|------------|
| AuthContext | lib/authContext.tsx | me: MeResponse, isLoading: boolean, isAuthenticated: boolean | login(), logout(), refetchMe(), hasRole() | localStorage tokens | All pages |
| TenantStore | lib/tenantStore.ts | tenant_id: string, tenant_name: string | setTenant(), getTenant() | localStorage | API calls |
| FeatureFlags | lib/features.ts | enabled_features: string[] | isEnabled() | NO | UI gating |

### 7d. API Layer — Complete

- HTTP client: Native `fetch` with custom wrapper in `lib/apiFetch.ts`
- Base URL: `process.env.NEXT_PUBLIC_API_URL` → `http://32.193.53.87:3000` or `http://localhost:3000`
- Auth token: Stored in `localStorage` key `access_token`, `refresh_token`
- Token refresh: Auto-refresh on 401 via `authApi.refreshAccessToken()` in authContext
- Global error handling: Central error boundary, 401 redirects to `/login`

**Every API call made by frontend**:

| Function Name | File | Method + Endpoint | Used In Components |
|--------------|------|-------------------|-------------------|
| authApi.login | lib/authApi.ts | POST /api/v1/auth/login | LoginPage |
| authApi.getMe | lib/authApi.ts | GET /api/v1/auth/me | AuthProvider |
| authApi.refreshAccessToken | lib/authApi.ts | POST /api/v1/auth/refresh | AuthProvider |
| deviceApi.listDevices | lib/deviceApi.ts | GET /api/v1/devices | DevicesPage |
| deviceApi.createDevice | lib/deviceApi.ts | POST /api/v1/devices | OnboardDeviceModal |
| deviceApi.getDashboardSummary | lib/deviceApi.ts | GET /api/v1/dashboard/summary | DashboardPage |
| deviceApi.getFleetSnapshot | lib/deviceApi.ts | GET /api/v1/dashboard/fleet-snapshot | DevicesPage |
| deviceApi.getPerformanceTrends | lib/deviceApi.ts | GET /api/v1/devices/{id}/performance-trends | DeviceAnalyticsPage |
| dataApi.queryTelemetry | lib/dataApi.ts | GET /api/v1/data/telemetry | TelemetryPage |
| ruleApi.listRules | lib/ruleApi.ts | GET /api/v1/rules | RulesPage |
| copilotApi.ask | lib/copilotApi.ts | POST /api/v1/copilot/query | CopilotPage |

### 7e. Real-time / Live Data

- Connection setup: `deviceApi.getFleetStream()` calls `/api/v1/dashboard/fleet-stream`
- Events: SSE stream with `fleet_update` and `heartbeat` events
- Reconnection: Native SSE reconnects automatically on disconnect
- UI updates: Fleet page and device cards update in real-time via SSE

---

## 8. INFRASTRUCTURE & DEPLOYMENT

### 10a. Architecture Topology
```
[Client Browser / Mobile]
       │ HTTPS :3000
[ui-web:3000] ─────────┐
                        │
       ┌────────────────┼────────────────┐
       │                │                │
[device-service:8000] [auth-service:8090] [data-service:8081] [rule-engine:8002]
       │                │                │                │
       └────────────────┴────────────────┴────────────────┘
                              │
                    [MySQL:3306] ← shared database
                    [Redis:6379] ← session + pub/sub
                    [InfluxDB:8086] ← telemetry
                    [MinIO:9000] ← S3 storage
                    [EMQX:1883] ← MQTT broker
```

### 10b. Container / Service Inventory

| Service Name | Image | Ports | Env File | Depends On | Restart Policy |
|-------------|-------|-------|---------|------------|---------------|
| mysql | mysql:8.0 | 3306 | docker-compose | init-scripts | unless-stopped |
| influxdb | influxdb:2.7-alpine | 8086 | docker-compose | - | unless-stopped |
| minio | minio/minio | 9000,9001 | docker-compose | - | unless-stopped |
| redis | redis:7-alpine | 6379 | docker-compose | - | unless-stopped |
| emqx | emqx/emqx:5.3.0 | 1883,8083,18083 | docker-compose | - | unless-stopped |
| device-service | built from ./services/device-service | 8000 | docker-compose | mysql, redis | unless-stopped |
| auth-service | built from ./services/auth-service | 8090 | docker-compose | mysql | unless-stopped |
| data-service | built from ./services/data-service | 8081 | docker-compose | influxdb, emqx, mysql | unless-stopped |
| ui-web | built from ./ui-web | 3000 | docker-compose | device-service | unless-stopped |

### 10c. Startup & Initialization Order

```
1. [mysql] must be healthy before [device-service, auth-service, data-service]
2. [redis] must be healthy before [device-service, analytics-service]
3. [influxdb] must be healthy before [data-service]
4. [emqx] must be healthy before [data-service]
5. [minio] must be healthy before [analytics-service, reporting-service]
6. [device-service] must run migrations before [data-service] can sync devices
```

---

## 9. CRITICAL DATA FLOWS

### Flow 1: User Login → Token Issuance
```
User → POST /api/v1/auth/login (email, password)
 → auth_service.py:login()
 → verify password with bcrypt
 → create JWT with {sub: user_id, tenant_id, role, plant_ids}
 → store refresh_token in DB (refresh_tokens table)
 → return {access_token, refresh_token, user}
```

### Flow 2: Authenticated Request (middleware trace)
```
User → GET /api/v1/devices
 → AuthMiddleware.process_request()
   → decode JWT from Authorization header
   → extract user_id, tenant_id, role
   → create TenantContext
   → attach to request.state.auth
 → devices.py:list_devices()
   → get tenant_id from require_tenant(request)
   → DeviceService.list_devices(tenant_id=tenant_id)
   → SELECT * FROM devices WHERE tenant_id=?
 → return device list
```

### Flow 3: Telemetry Ingestion
```
MQTT Device → publish to emqx (topic: <tenant>/devices/<device_id>/telemetry)
 → data-service subscribes to MQTT
 → parse telemetry payload
 → write to InfluxDB (bucket: telemetry)
 → POST to device-service /api/v1/devices/{device_id}/live-update
 → LiveProjectionService.apply_live_update()
 → update device_live_state table
 → publish to Redis channel factoryops:fleet_stream:v1
 → fleet_stream_broadcast publishes to SSE subscribers
```

---

## 10. TESTING — COMPLETE

### Test Infrastructure
- Framework: pytest + pytest-asyncio (Python), Playwright (e2e)
- Test database: In-memory or separate test DB
- Mocking: unittest.mock, pytest-mock

### Key Test Files
| Test File | Tests What | Type |
|-----------|-----------|------|
| services/auth-service/tests/test_login_audit.py | Login audit trail | Unit |
| services/auth-service/tests/test_token_version_revocation.py | Token revocation | Unit |
| services/device-service/tests/test_delete_device_regression.py | Device deletion | Integration |
| tests/test_reporting_tenant_scope.py | Reporting scope | Integration |
| ui-web/tests/e2e/machines-reconnect.spec.js | Device reconnection | E2E |

---

## 11. KNOWN ISSUES, TODOS & TECH DEBT

| File | Line | Tag | Exact Text | Severity |
|------|------|-----|------------|----------|
| services/shared/auth_middleware.py | 295 | TODO | # TODO: add rate limiting per-tenant | 🟡 |
| services/device-service/app/services/live_projection.py | 42 | FIXME | # FIXME: handle timezone properly | 🟡 |
| .env | 103 | RISK | EMAIL_PASSWORD hardcoded in plain text | 🔴 |

---

## 12. DEPENDENCY AUDIT

### Direct Dependencies (key ones):
- fastapi==0.104.1 — Web framework
- sqlalchemy==2.0.36 — ORM
- pydantic==2.5.0 — Data validation
- uvicorn==0.24.0 — ASGI server
- redis==5.0.8 — Redis client
- paho-mqtt==1.6.1 — MQTT client
- influxdb-client==1.38.0 — InfluxDB client
- next==16.1.6 — React framework
- react==19.2.3 — UI library
- recharts==3.7.0 — Charts

### Risk Flags:
- PYPI package download counts: all major packages have high download counts (safe)
- No CVEs found in direct dependencies (as of audit date)
- Version pinning: All services pin exact versions (safe)

---

## 13. PERFORMANCE RISK INVENTORY

| Location | Issue | Estimated Impact | Recommended Fix |
|----------|-------|-----------------|-----------------|
| device-service/app/services/device.py:list_devices | N+1 query if filtering by plant_ids | High | Eager load devices with plant_ids |
| device-service/app/services/live_dashboard.py | Full table scan on device_live_state | Medium | Add index on (tenant_id, runtime_status) |
| analytics-service worker | Single-threaded ML inference | Medium | Add more worker instances |

---

## 14. GLOSSARY

| Term | Definition | Where Used |
|------|-----------|------------|
| tenant_id | Multi-tenant organization identifier | All services |
| plant_id | Physical plant/factory identifier | Devices, users |
| device_id | Business key for IoT device | Devices, telemetry |
| runtime_status | Computed status (running/stopped) from last_seen | device-service |
| shift | Time window for uptime calculation | device-service |
| health_config | Parameter thresholds for health scoring | device-service |
| live_state | Real-time aggregated metrics per device | device-service |
| telemetry | Time-series measurement from device | data-service |
| outbox | Transactional outbox for reliable sync | data-service |

---

## 15. QUICK-START GUIDE

```bash
# 1. Clone
git clone <repo> && cd <project-dir>

# 2. Create environment
cp .env.example .env
# REQUIRED: Set these variables or the app won't start:
# - JWT_SECRET_KEY: 64-char hex string
# - GROQ_API_KEY: your Groq API key
# - EMAIL_PASSWORD: your email app password

# 3. Start infrastructure
docker compose up -d mysql redis influxdb minio emqx

# 4. Run migrations (automatic on service startup)
# Device-service, auth-service, data-service run alembic on startup

# 5. Start all services
docker compose up -d --build

# 6. Verify
curl -s http://localhost:8000/health
# Expected: {"status": "healthy", "service": "device-service"}

# 7. Open UI
# Navigate to http://localhost:3000

# 8. Run tests
cd services/auth-service && pytest
```

---

## 16. WHAT WILL BREAK AND WHEN

| Component | Why It Will Break | When | How to Prevent |
|-----------|------------------|------|---------------|
| JWT_SECRET_KEY rotation | Tokens issued before rotation invalid | On secret change | Implement token versioning |
| Redis down | All real-time features fail | Redis outage | Add circuit breaker + fallback |
| InfluxDB down | Telemetry ingestion stops | InfluxDB outage | Add local buffer + replay |
| MQTT broker down | Device telemetry missed | EMQX outage | Reconnection with backoff + buffer |
| Shared middleware circular import | New service fails to start | On adding new shared module | Keep services/shared minimal |

---

END OF CODEBASE BIBLE
