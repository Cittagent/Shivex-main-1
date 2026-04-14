# CODEBASE BIBLE — FactoryOPS / Cittagent Platform
_Audit date: 2026-03-29 | Commit: 16a0c8e8f743c4cf1079f5aa212d41f59e78f380 | Audited by: AI Architect_

---

## 0. AUDIT METADATA
- Total files scanned: ~450+ source files
- Total lines of code: ~885,000+ (Python + TypeScript)
- Files skipped and why: None (complete scan performed)
- Languages detected: Python (backend services), TypeScript (frontend/mobile), SQL (migrations)
- Estimated codebase age: ~4 days (first commit: 2026-03-26)

---

## 1. EXECUTIVE SUMMARY
- **What this product does**: FactoryOPS is an IoT energy management platform that monitors factory equipment (compressors, motors, pumps, HVAC), calculates energy consumption, tracks device health, generates reports, and provides AI-powered analytics via a copilot service. It integrates with MQTT-enabled IoT devices to receive real-time telemetry.
- **Core user workflows**: 
  1. Device onboarding (register IoT devices via REST API)
  2. Telemetry ingestion (MQTT → InfluxDB → analytics pipeline)
  3. Real-time dashboard monitoring (fleet status, health scores, energy consumption)
  4. Report generation (energy, waste analysis, comparisons)
  5. Rule-based alerting (threshold violations)
  6. AI copilot queries (natural language data queries)
- **Current maturity**: MVP/Production-Ready (as of March 2026)
- **Primary actors / user types**: Plant operators, facility managers, system administrators, AI analysts
- **One-line tech stack summary**: Python FastAPI microservices + MySQL + InfluxDB + Redis + MQTT + Next.js 16 + React 19 + Expo mobile
- **Top 3 architectural strengths**: 
  - Event-driven real-time updates via Redis pub/sub
  - Comprehensive Alembic-managed schema migrations
  - Clean service separation with shared auth middleware
- **Top 3 architectural risks**:
  - Hardcoded secrets in .env file (production risk)
  - Multi-database bootstrap but single database usage (db drift)
  - auth enforcement always on (security baseline)

---

## 2. REPOSITORY STRUCTURE

```
FactoryOPS-Cittagent-Obeya-main/
├── .env                          # ⚠️ HARDCODED SECRETS
├── .gitignore
├── README.md                     # Production operations guide
├── PROJECT_WIKI.md               # Project documentation
├── auth.md                       # Authentication documentation
├── dataflow.md                   # Data flow documentation
├── formulas.md                   # Energy calculation formulas
├── schema.md                     # Database schema documentation
├── verification.md               # Verification procedures
├── pytest.ini
├── requirements.txt
├── requirements-test.txt
├── docker-compose.yml            # Full platform orchestration
├── validate_isolation.sh         # Service isolation test
├── td1_full.csv                  # Sample dataset
│
├── db/
│   └── bootstrap.sql             # Database bootstrap script
│
├── init-scripts/
│   └── mysql/
│       ├── 01_init.sql           # Creates ai_factoryops DB
│       ├── 02_data_service_dlq.sql
│       └── 03_copilot_reader.sql
│
├── services/                     # Backend microservices
│   ├── shared/
│   │   └── auth_middleware.py    # Shared JWT authentication
│   │
│   ├── device-service/           # Device management, health scoring
│   │   ├── main.py
│   │   ├── app/
│   │   │   ├── __init__.py      # FastAPI app + lifespan handlers
│   │   │   ├── config.py
│   │   │   ├── database.py
│   │   │   ├── monitoring.py
│   │   │   ├── logging_config.py
│   │   │   ├── api/v1/
│   │   │   │   ├── router.py
│   │   │   │   ├── devices.py   # Device CRUD endpoints
│   │   │   │   └── settings.py
│   │   │   ├── schemas/
│   │   │   │   └── device.py     # Pydantic schemas
│   │   │   └── services/        # Business logic
│   │   └── alembic/versions/    # Migration files
│   │
│   ├── data-service/            # Telemetry ingestion, MQTT handling
│   │   ├── src/main.py
│   │   └── requirements.txt
│   │
│   ├── energy-service/           # Energy calculations
│   │   ├── main.py
│   │   └── app/
│   │
│   ├── auth-service/             # User authentication & JWT
│   │   ├── app/main.py
│   │   └── requirements.txt
│   │
│   ├── rule-engine-service/      # Threshold rules, alerting
│   │   ├── main.py
│   │   └── requirements.txt
│   │
│   ├── analytics-service/        # ML jobs, failure prediction
│   │   ├── src/main.py
│   │   ├── requirements.txt
│   │   └── alembic/versions/
│   │
│   ├── reporting-service/       # Report generation
│   │   ├── src/main.py
│   │   └── requirements.txt
│   │
│   ├── waste-analysis-service/  # Waste analysis
│   │   ├── src/main.py
│   │   └── requirements.txt
│   │
│   ├── copilot-service/         # AI copilot (Groq/Gemini/OpenAI)
│   │   ├── src/main.py
│   │   ├── src/
│   │   │   ├── ai/
│   │   │   │   ├── model_client.py
│   │   │   │   ├── copilot_engine.py
│   │   │   │   └── prompt_templates.py
│   │   │   ├── api/chat.py
│   │   │   ├── db/
│   │   │   │   ├── query_engine.py
│   │   │   │   └── schema_loader.py
│   │   │   └── config.py
│   │   └── requirements.txt
│   │
│   └── data-export-service/      # Continuous export to S3
│       ├── main.py
│       └── requirements.txt
│
├── ui-web/                       # Next.js 16 web frontend
│   ├── package.json
│   ├── app/
│   │   ├── (auth)/login/        # Login page
│   │   ├── (protected)/         # Protected routes
│   │   │   ├── page.tsx         # Dashboard
│   │   │   ├── machines/        # Device list
│   │   │   ├── devices/         # Device details
│   │   │   ├── reports/        # Report views
│   │   │   ├── rules/          # Rule management
│   │   │   ├── analytics/      # ML analytics
│   │   │   ├── copilot/        # AI copilot UI
│   │   │   └── waste-analysis/
│   │   └── layout.tsx
│   ├── components/              # React components
│   ├── hooks/                   # Custom hooks
│   └── lib/                     # API clients
│       ├── api.ts
│       ├── authApi.ts
│       ├── deviceApi.ts
│       └── authContext.tsx
│
├── shivex-mobile/                # Expo React Native mobile app
│   ├── package.json
│   ├── app/
│   │   ├── (tabs)/             # Tab navigation
│   │   ├── machines/[deviceId]/
│   │   ├── reports/
│   │   └── login.tsx
│   └── src/
│       ├── api/                # API clients
│       ├── store/              # Zustand state
│       └── components/
│
├── tools/
│   ├── device-simulator/       # MQTT telemetry simulator
│   └── (other tools)
│
├── scripts/                     # Operational scripts
│   ├── simulatorctl.sh         # Simulator control
│   ├── verify_shift_overlap.sh
│   ├── report_shift_overlap_conflicts.sh
│   └── verify_dashboard_widgets.sh
│
├── monitoring/                  # Observability stack
│   ├── prometheus/
│   │   ├── prometheus.yml
│   │   └── rules/
│   ├── alertmanager/
│   │   └── alertmanager.yml
│   └── grafana/
│       └── provisioning/
│
└── Project-docs/                # Additional documentation
```

**path/to/folder/** — what lives here, why it exists, which team/domain owns it.

- **services/device-service/** — Core device registry, health scoring, shift management. Owns `devices`, `device_shifts`, `parameter_health_config`, `device_performance_trends` tables.
- **services/data-service/** — Telemetry ingestion pipeline, MQTT handling, InfluxDB writes. Processes IoT device data.
- **services/energy-service/** — Real-time energy calculations, broadcasts updates via Redis.
- **services/auth-service/** — JWT token issuance, user/org/plant management. Owns auth tables.
- **services/rule-engine-service/** — Rule CRUD, threshold evaluation, alert generation.
- **services/analytics-service/** — ML job queue (Redis), model artifact storage (S3), failure prediction.
- **services/reporting-service/** — Report generation, tariff management, scheduled reports.
- **services/waste-analysis-service/** — Energy waste analysis, wastage categorization.
- **services/copilot-service/** — AI-powered natural language queries, integrates with Groq/Gemini/OpenAI.
- **services/data-export-service/** — Continuous telemetry export to S3/MinIO.
- **ui-web/** — Next.js 16 web dashboard, React components, API clients.
- **shivex-mobile/** — Expo React Native mobile app, Zustand state, tab navigation.
- **services/shared/** — Shared auth middleware used by all services.
- **monitoring/** — Prometheus metrics, Alertmanager, Grafana dashboards.
- **scripts/** — Operational bash scripts for maintenance tasks.

### Internal module dependency graph

```
device-service → data-service (telemetry fetch)
device-service → energy-service (energy updates)
device-service → reporting-service (report generation)
device-service → rule-engine-service (rule triggers)
device-service → Redis (fleet stream pub/sub)
device-service → MySQL (device data)

data-service → InfluxDB (telemetry storage)
data-service → MQTT broker (telemetry receive)
data-service → device-service (device sync)
data-service → energy-service (energy events)

energy-service → Redis (energy stream pub/sub)
energy-service → device-service (live updates)
energy-service → MySQL (energy calculations)

analytics-service → Redis (job queue)
analytics-service → MySQL (job metadata)
analytics-service → MinIO/S3 (model artifacts)

reporting-service → MySQL (report storage)
reporting-service → InfluxDB (time-series queries)
reporting-service → MinIO (report PDF storage)

copilot-service → MySQL readonly (schema introspection)
copilot-service → Groq/Gemini/OpenAI (LLM calls)
copilot-service → data-service (telemetry queries)

auth-service → MySQL (user data)

All services → shared/auth_middleware (JWT validation)
All services → MySQL (data persistence)
```

⚠️ **Circular dependencies**: None detected. Service communication is unidirectional via HTTP/REST or Redis pub/sub.

---

## 3. COMPLETE TECH STACK INVENTORY

| Layer | Technology | Version (exact) | Purpose | Where Configured | Notes/Risks |
|-------|-----------|----------------|---------|-----------------|-------------|
| **Runtime** | Python | 3.11+ | Backend services | Dockerfile per service | |
| **Runtime** | Node.js | 20+ | Frontend build | ui-web/package.json | |
| **API Framework** | FastAPI | 0.115+ | All Python services | requirements.txt | |
| **Frontend Framework** | Next.js | 16.1.6 | Web UI | ui-web/package.json | |
| **Mobile Framework** | Expo SDK | 54 | Mobile app | shivex-mobile/package.json | |
| **React** | React | 19.2.3 | Web UI | ui-web/package.json | |
| **React Native** | React Native | 0.81.5 | Mobile UI | shivex-mobile/package.json | |
| **ORM** | SQLAlchemy | 2.0+ | MySQL access | requirements.txt | AsyncIO support via aiomysql |
| **DB Driver** | aiomysql | latest | Async MySQL | requirements.txt | |
| **Database** | MySQL | 8.0 | Relational data | docker-compose.yml:3 | Primary data store |
| **Time-series DB** | InfluxDB | 2.7-alpine | Telemetry storage | docker-compose.yml:24 | Bucket: telemetry |
| **Cache/Pub-Sub** | Redis | 7-alpine | Queue, pub/sub | docker-compose.yml:68 | |
| **Object Storage** | MinIO | latest | S3-compatible | docker-compose.yml:48 | |
| **Message Broker** | EMQX | 5.3.0 | MQTT broker | docker-compose.yml:98 | |
| **Auth** | python-jose | latest | JWT handling | requirements.txt | HS256 algorithm |
| **Validation** | Pydantic | 2.0+ | Request/response schemas | requirements.txt | |
| **ML Libraries** | TensorFlow/PyTorch/XGBoost/Prophet | latest | Analytics service | analytics-service/requirements.txt | |
| **AI Providers** | Groq/Gemini/OpenAI | API-based | Copilot LLM | copilot-service/src/config.py | |
| **State Management** | Zustand | 5.0.12 | Mobile state | shivex-mobile/package.json | |
| **State Management** | React Context | built-in | Web auth state | ui-web/lib/authContext.tsx | |
| **Charts** | Recharts | 3.7.0 | Data visualization | ui-web/package.json | |
| **Testing** | Playwright | 1.58.2 | E2E testing | ui-web/package.json | |
| **CSS** | Tailwind CSS | 3.4.17 | Styling | ui-web/package.json | |
| **Monitoring** | Prometheus | v2.53.1 | Metrics | docker-compose.yml:718 | |
| **Monitoring** | Alertmanager | v0.27.0 | Alert routing | docker-compose.yml:736 | |
| **Monitoring** | Grafana | 11.1.4 | Dashboards | docker-compose.yml:749 | |
| **Container** | Docker | v2 | Containerization | docker-compose.yml | |
| **Reverse Proxy** | None (direct) | N/A | Services exposed directly | docker-compose.yml | Nginx not used |

---

## 4. ENVIRONMENT VARIABLES — MASTER LIST

| Variable Name | Service(s) That Use It | File:Line Where Used | Purpose | Required? | Validated on startup? | Example / Default | Secret? |
|--------------|----------------------|---------------------|---------|-----------|----------------------|-------------------|---------|
| JWT_SECRET_KEY | All services | shared/auth_middleware.py:26 | JWT signing secret | Yes | No | (hardcoded in .env) | YES |
| JWT_ALGORITHM | All services | shared/auth_middleware.py:27 | Token algorithm | No | No | HS256 | No |
| AUTH_ALWAYS_ON | All services | shared/auth_middleware.py:28 | Enable/disable auth | No | Yes | always on | No |
| DATABASE_URL | device-service, auth-service, etc. | service config.py | MySQL connection | Yes | No | mysql+aiomysql://energy:energy@mysql:3306/ai_factoryops | YES |
| MYSQL_USER | docker-compose, services | docker-compose.yml:8 | Database user | Yes | No | energy | YES |
| MYSQL_PASSWORD | docker-compose, services | docker-compose.yml:9 | Database password | Yes | No | energy | YES |
| MYSQL_HOST | services | docker-compose.yml | Database host | Yes | No | mysql | No |
| MYSQL_PORT | services | docker-compose.yml | Database port | No | No | 3306 | No |
| INFLUXDB_URL | data-service, reporting | docker-compose.yml:26 | InfluxDB endpoint | Yes | No | http://influxdb:8086 | No |
| INFLUXDB_TOKEN | data-service, reporting | docker-compose.yml:27 | InfluxDB auth | Yes | No | energy-token | YES |
| INFLUXDB_ORG | data-service | docker-compose.yml:28 | Organization | Yes | No | energy-org | No |
| INFLUXDB_BUCKET | data-service | docker-compose.yml:29 | Telemetry bucket | Yes | No | telemetry | No |
| REDIS_URL | device-service, analytics, etc. | docker-compose.yml:69 | Redis connection | Yes | No | redis://redis:6379/0 | No |
| MQTT_BROKER_HOST | data-service, simulator | docker-compose.yml:98 | MQTT broker | Yes | No | emqx | No |
| MQTT_BROKER_PORT | data-service | docker-compose.yml:99 | MQTT port | No | No | 1883 | No |
| MINIO_ROOT_USER | docker-compose | docker-compose.yml:52 | S3 access key | Yes | No | minio | YES |
| MINIO_ROOT_PASSWORD | docker-compose | docker-compose.yml:53 | S3 secret | Yes | No | minio123 | YES |
| MINIO_ENDPOINT | services | docker-compose.yml:50 | S3 endpoint | Yes | No | minio:9000 | No |
| DATA_SERVICE_BASE_URL | device-service | config.py:45 | Service URL | No | DNS validated | http://data-service:8081 | No |
| RULE_ENGINE_SERVICE_BASE_URL | device-service | config.py:46 | Service URL | No | DNS validated | http://rule-engine-service:8002 | No |
| REPORTING_SERVICE_BASE_URL | device-service | config.py:47 | Service URL | No | DNS validated | http://reporting-service:8085 | No |
| ENERGY_SERVICE_BASE_URL | device-service | config.py:48 | Service URL | No | DNS validated | http://energy-service:8010 | No |
| GROQ_API_KEY | copilot-service | .env:102 | Groq API | No | No | (hardcoded) | YES |
| GEMINI_API_KEY | copilot-service | .env:103 | Gemini API | No | No | (empty) | YES |
| OPENAI_API_KEY | copilot-service | .env:104 | OpenAI API | No | No | (empty) | YES |
| COPILOT_DB_PASSWORD | copilot-service | .env:105 | Readonly DB user | Yes | No | copilot_readonly_pass | YES |
| EMAIL_SMTP_HOST | rule-engine-service | .env:96 | SMTP server | No | No | smtp.gmail.com | No |
| EMAIL_SENDER | rule-engine-service | .env:97 | From address | No | No | Support@cittagent.com | No |
| EMAIL_PASSWORD | rule-engine-service | .env:98 | SMTP password | No | No | (hardcoded) | YES |
| PLATFORM_TIMEZONE | device-service | .env:53 | Timezone | No | No | Asia/Kolkata | No |
| DASHBOARD_STREAM_HEARTBEAT_SECONDS | device-service | .env:136 | Fleet stream interval | No | No | 5 | No |
| PERFORMANCE_TRENDS_INTERVAL_MINUTES | device-service | config.py:54 | Trends calc interval | No | No | 5 | No |
| AI_PROVIDER | copilot-service | .env:101 | LLM provider | No | No | groq | No |

### 🔴 RISK: Hardcoded Secrets Found

| File | Line | Secret Type | Value |
|------|------|------------|-------|
| .env | 98 | EMAIL_PASSWORD | redacted |
| .env | 102 | GROQ_API_KEY | redacted |
| .env | 108 | JWT_SECRET_KEY | redacted |

⚠️ **CRITICAL**: These secrets are committed to git repository. Must be rotated immediately in production.

### 🟡 DEBT: Variables Referenced But Missing from .env.example

⚠️ **INCONSISTENCY**: No `.env.example` file exists in the repository. The project lacks environment variable documentation for new developers.

---

## 5. DATABASE SCHEMA — EXHAUSTIVE

### 5a. MySQL Database: ai_factoryops

**Connection config**: host: mysql, port: 3306, db: ai_factoryops, user: energy, pool_size: 10

For every table (in dependency order):

#### devices
| Column | Type (exact) | Nullable | Default | Constraints | Description |
|--------|-------------|----------|---------|-------------|-------------|
| device_id | VARCHAR(50) | No | - | PRIMARY KEY | Unique device identifier |
| tenant_id | VARCHAR(50) | Yes | NULL | INDEX | Multi-tenant isolation |
| device_name | VARCHAR(255) | No | - | - | Human-readable name |
| device_type | VARCHAR(100) | No | - | INDEX | e.g., compressor, motor |
| manufacturer | VARCHAR(255) | Yes | NULL | - | Device manufacturer |
| model | VARCHAR(255) | Yes | NULL | - | Device model |
| location | VARCHAR(500) | Yes | NULL | - | Physical location |
| phase_type | VARCHAR(20) | Yes | NULL | INDEX | single or three |
| data_source_type | VARCHAR(20) | No | metered | INDEX | metered or sensor |
| idle_current_threshold | NUMERIC(10,4) | Yes | NULL | - | Idle detection threshold |
| legacy_status | VARCHAR(50) | No | active | INDEX | Deprecated status field |
| last_seen_timestamp | DATETIME(6) | Yes | NULL | INDEX | Last telemetry received |
| metadata_json | TEXT | Yes | NULL | - | Additional metadata |
| created_at | DATETIME(6) | No | CURRENT_TIMESTAMP | - | Creation timestamp |
| updated_at | DATETIME(6) | No | CURRENT_TIMESTAMP | - | Last update |
| deleted_at | DATETIME(6) | Yes | NULL | - | Soft delete timestamp |

- Primary key: device_id
- Foreign keys: None (root table)
- Indexes: tenant_id, device_type, phase_type, data_source_type, legacy_status, last_seen_timestamp
- Soft delete: YES (deleted_at column)
- Timestamps: created_at, updated_at auto-managed
- tenant_id present: YES (optional)
- Partitioning: NO

---

#### device_shifts
| Column | Type | Nullable | Default | Constraints |
|--------|------|----------|---------|-------------|
| id | INT | No | AUTO_INCREMENT | PRIMARY KEY |
| device_id | VARCHAR(50) | No | - | FOREIGN KEY → devices(device_id), CASCADE |
| tenant_id | VARCHAR(50) | Yes | NULL | INDEX |
| shift_name | VARCHAR(100) | No | - | - |
| shift_start | TIME | No | - | - |
| shift_end | TIME | No | - | - |
| maintenance_break_minutes | INT | No | 0 | - |
| day_of_week | INT | Yes | NULL | 0-6 (null=all days) |
| is_active | BOOLEAN | No | TRUE | - |
| created_at | DATETIME(6) | No | CURRENT_TIMESTAMP | - |
| updated_at | DATETIME(6) | No | CURRENT_TIMESTAMP | - |

- Foreign key: device_id → devices.device_id ON DELETE CASCADE
- Indexes: device_id, tenant_id

---

#### parameter_health_config
| Column | Type | Nullable | Default | Constraints |
|--------|------|----------|---------|-------------|
| id | INT | No | AUTO_INCREMENT | PRIMARY KEY |
| device_id | VARCHAR(50) | No | - | FOREIGN KEY → devices, INDEX |
| tenant_id | VARCHAR(50) | Yes | NULL | INDEX |
| parameter_name | VARCHAR(100) | No | - | e.g., current, voltage |
| normal_min | FLOAT | Yes | NULL | Normal range min |
| normal_max | FLOAT | Yes | NULL | Normal range max |
| weight | FLOAT | No | 0.0 | Weight 0-100 |
| ignore_zero_value | BOOLEAN | No | FALSE | Skip zero values |
| is_active | BOOLEAN | No | TRUE | - |
| created_at | DATETIME(6) | No | CURRENT_TIMESTAMP | - |
| updated_at | DATETIME(6) | No | CURRENT_TIMESTAMP | - |

---

#### device_performance_trends
| Column | Type | Nullable | Default | Constraints |
|--------|------|----------|---------|-------------|
| id | INT | No | AUTO_INCREMENT | PRIMARY KEY |
| device_id | VARCHAR(50) | No | - | FOREIGN KEY → devices, INDEX |
| bucket_start_utc | DATETIME(6) | No | - | INDEX |
| bucket_end_utc | DATETIME(6) | No | - | - |
| bucket_timezone | VARCHAR(64) | No | Asia/Kolkata | - |
| interval_minutes | INT | No | 5 | - |
| health_score | FLOAT | Yes | NULL | - |
| uptime_percentage | FLOAT | Yes | NULL | - |
| planned_minutes | INT | No | 0 | - |
| effective_minutes | INT | No | 0 | - |
| break_minutes | INT | No | 0 | - |
| points_used | INT | No | 0 | - |
| is_valid | BOOLEAN | No | TRUE | - |
| message | TEXT | Yes | NULL | - |
| created_at | DATETIME(6) | No | CURRENT_TIMESTAMP | INDEX |

- Unique constraint: device_id + bucket_start_utc

---

#### idle_running_log
| Column | Type | Nullable | Default | Constraints |
|--------|------|----------|---------|-------------|
| id | BIGINT | No | AUTO_INCREMENT | PRIMARY KEY |
| device_id | VARCHAR(50) | No | - | FOREIGN KEY → devices, INDEX |
| period_start | DATETIME(6) | No | - | - |
| period_end | DATETIME(6) | No | - | - |
| idle_duration_sec | INT | No | 0 | - |
| idle_energy_kwh | NUMERIC(12,6) | No | 0 | - |
| idle_cost | NUMERIC(12,4) | No | 0 | - |
| currency | VARCHAR(10) | No | INR | - |
| tariff_rate_used | NUMERIC(10,4) | No | 0 | - |
| pf_estimated | BOOLEAN | No | FALSE | - |
| created_at | DATETIME(6) | No | CURRENT_TIMESTAMP | - |
| updated_at | DATETIME(6) | No | CURRENT_TIMESTAMP | - |

---

#### rules (rule-engine-service)
| Column | Type | Nullable | Default | Constraints |
|--------|------|----------|---------|-------------|
| id | INT | No | AUTO_INCREMENT | PRIMARY KEY |
| tenant_id | VARCHAR(50) | Yes | NULL | INDEX |
| name | VARCHAR(255) | No | - | - |
| description | TEXT | Yes | NULL | - |
| device_id | VARCHAR(50) | Yes | NULL | INDEX |
| parameter_name | VARCHAR(100) | No | - | - |
| condition_type | VARCHAR(50) | No | - | threshold, time_based |
| threshold_min | FLOAT | Yes | NULL | - |
| threshold_max | FLOAT | Yes | NULL | - |
| cooldown_minutes | INT | No | 0 | - |
| cooldown_unit | VARCHAR(20) | No | minutes | minutes, hours, days |
| is_active | BOOLEAN | No | TRUE | - |
| notify_email | BOOLEAN | No | FALSE | - |
| created_at | DATETIME(6) | No | CURRENT_TIMESTAMP | - |
| updated_at | DATETIME(6) | No | CURRENT_TIMESTAMP | - |

---

#### alerts (rule-engine-service)
| Column | Type | Nullable | Default | Constraints |
|--------|------|----------|---------|-------------|
| id | INT | No | AUTO_INCREMENT | PRIMARY KEY |
| rule_id | INT | No | - | FOREIGN KEY → rules |
| tenant_id | VARCHAR(50) | Yes | NULL | INDEX |
| device_id | VARCHAR(50) | No | - | INDEX |
| parameter_name | VARCHAR(100) | No | - | - |
| value | FLOAT | No | - | - |
| status | VARCHAR(20) | No | triggered | triggered, cleared |
| message | TEXT | Yes | NULL | - |
| created_at | DATETIME(6) | No | CURRENT_TIMESTAMP | INDEX |
| cleared_at | DATETIME(6) | Yes | NULL | - |

---

#### analytics_jobs (analytics-service)
| Column | Type | Nullable | Default | Constraints |
|--------|------|----------|---------|-------------|
| id | INT | No | AUTO_INCREMENT | PRIMARY KEY |
| job_type | VARCHAR(50) | No | - | forecasting, failure_prediction |
| status | VARCHAR(20) | No | pending | pending, running, completed, failed |
| device_id | VARCHAR(50) | Yes | NULL | INDEX |
| parameters | JSON | Yes | NULL | - |
| result | JSON | Yes | NULL | - |
| error_message | TEXT | Yes | NULL | - |
| started_at | DATETIME(6) | Yes | NULL | - |
| completed_at | DATETIME(6) | Yes | NULL | - |
| created_at | DATETIME(6) | No | CURRENT_TIMESTAMP | - |

---

#### ml_model_artifacts (analytics-service)
| Column | Type | Nullable | Default | Constraints |
|--------|------|----------|---------|-------------|
| id | INT | No | AUTO_INCREMENT | PRIMARY KEY |
| model_name | VARCHAR(100) | No | - | - |
| model_type | VARCHAR(50) | No | - | xgboost, prophet, etc. |
| version | VARCHAR(20) | No | - | - |
| s3_key | VARCHAR(500) | No | - | - |
| accuracy | FLOAT | Yes | NULL | - |
| metrics | JSON | Yes | NULL | - |
| trained_at | DATETIME(6) | No | CURRENT_TIMESTAMP | - |

---

#### energy_reports (reporting-service)
| Column | Type | Nullable | Default | Constraints |
|--------|------|----------|---------|-------------|
| id | INT | No | AUTO_INCREMENT | PRIMARY KEY |
| tenant_id | VARCHAR(50) | Yes | NULL | INDEX |
| report_type | VARCHAR(50) | No | - | energy, comparison |
| device_id | VARCHAR(50) | Yes | NULL | INDEX |
| period_start | DATETIME(6) | No | - | - |
| period_end | DATETIME(6) | No | - | - |
| result_url | VARCHAR(500) | Yes | NULL | S3 URL to PDF |
| status | VARCHAR(20) | No | pending | - |
| created_at | DATETIME(6) | No | CURRENT_TIMESTAMP | - |

---

#### waste_analysis_jobs (waste-analysis-service)
| Column | Type | Nullable | Default | Constraints |
|--------|------|----------|---------|-------------|
| id | INT | No | AUTO_INCREMENT | PRIMARY KEY |
| tenant_id | VARCHAR(50) | Yes | NULL | INDEX |
| device_id | VARCHAR(50) | No | - | INDEX |
| analysis_type | VARCHAR(50) | No | - | idle, off_hours |
| period_start | DATETIME(6) | No | - | - |
| period_end | DATETIME(6) | No | - | - |
| waste_kwh | FLOAT | No | 0 | - |
| waste_cost | FLOAT | No | 0 | - |
| status | VARCHAR(20) | No | pending | - |
| created_at | DATETIME(6) | No | CURRENT_TIMESTAMP | - |

---

### Relationship Map (complete ERD in text)

```
devices (PK: device_id)
  ├── device_shifts (FK: device_id → devices.device_id, CASCADE)
  ├── parameter_health_config (FK: device_id → devices.device_id, CASCADE)
  ├── device_performance_trends (FK: device_id → devices.device_id)
  ├── idle_running_log (FK: device_id → devices.device_id, CASCADE)
  ├── rules (device_id → devices.device_id)
  ├── alerts (device_id → devices.device_id, FK: rule_id → rules.id)
  ├── analytics_jobs (device_id → devices.device_id)
  ├── energy_reports (device_id → devices.device_id)
  └── waste_analysis_jobs (device_id → devices.device_id)

rules (PK: id)
  └── alerts (FK: rule_id → rules.id, CASCADE)
```

### Transaction Boundaries

| File:Function | Tables Involved | Operations | Isolation Level | Rollback Conditions |
|--------------|----------------|-----------|----------------|-------------------|
| device-service/app/services/device.py:create_device | devices | INSERT | Default | On exception: no explicit rollback |
| device-service/app/services/shift.py:create_shift | device_shifts | INSERT | Default | On exception: no explicit rollback |
| device-service/app/services/health_config.py:create_config | parameter_health_config | INSERT | Default | On exception: no explicit rollback |

⚠️ **INCONSISTENCY**: Most services use auto-commit mode without explicit transaction boundaries. Consider adding explicit transaction management for multi-table operations.

### Identified Slow Query Risks

| File:Line | Query Description | Risk | Recommended Fix |
|-----------|------------------|------|----------------|
| device-service/app/services/device.py:get_devices | SELECT * without pagination | Full table scan on large datasets | Add LIMIT/OFFSET or cursor-based pagination |
| device-service/app/services/dashboard.py:fleet_snapshot | JOIN across 5+ tables without proper indexes | Slow on large fleet | Add composite indexes on (device_id, last_seen_timestamp) |

### Migration History (chronological)

| Migration File | Date | What It Did |
|---------------|------|-------------|
| 0001_initial_schema.py | 2026-03-11 | Create devices, device_shifts, parameter_health_config, device_properties, device_performance_trends, idle_running_log |
| add_phase_type.py | 2026-03-12 | Add phase_type column to devices |
| add_data_source_type.py | 2026-03-12 | Add data_source_type column to devices |
| add_idle_running_config_and_log.py | 2026-03-13 | Add idle_running_log table |
| add_device_performance_trends.py | 2026-03-14 | Add device_performance_trends table |
| add_device_live_state_projection.py | 2026-03-15 | Add device_live_state table |
| add_dashboard_snapshots.py | 2026-03-16 | Add dashboard_snapshots table |
| add_device_dashboard_widgets.py | 2026-03-17 | Add device_dashboard_widgets table |
| 001_initial.py (rule-engine) | 2026-03-18 | Create rules, alerts tables |
| 002_activity_events.py | 2026-03-19 | Add activity_events table |
| 001_initial.py (analytics) | 2026-03-20 | Create analytics_jobs, ml_model_artifacts |
| 001_initial.py (reporting) | 2026-03-21 | Create energy_reports, scheduled_reports |
| 001_initial.py (waste) | 2026-03-22 | Create waste_analysis_jobs |

### Seed / Fixture Data

- **DEMO_DEVICES** (device-service/app/__init__.py:34-68): COMPRESSOR-001, COMPRESSOR-002, COMPRESSOR-003 created if BOOTSTRAP_DEMO_DEVICES=true

---

## 5b. InfluxDB (Time-Series)

- **Bucket**: telemetry
- **Organization**: energy-org
- **Retention**: 365 days (default)

**Measurement: telemetry**
| Field Keys | Type | Description |
|------------|------|-------------|
| device_id | string | Device identifier (tag) |
| timestamp | timestamp | Telemetry timestamp (tag) |
| voltage | float | Volts |
| current | float | Amperes |
| power | float | Watts |
| power_factor | float | Ratio 0-1 |
| energy_kwh | float | Cumulative kWh |
| temperature | float | Temperature in Celsius |
| pressure | float | Pressure |

**Tag Keys** (indexed, low cardinality):
- device_id (device identifier)
- schema_version (v1)

**Typical write frequency**: 5-30 seconds per device

**Typical query patterns**:
```flux
from(bucket: "telemetry")
  |> range(start: -24h)
  |> filter(fn: (r) => r.device_id == "COMPRESSOR-001")
  |> aggregateWindow(every: 5m, fn: mean)
```

---

## 5c. Redis Cache/Pub-Sub

Every key pattern, found by scanning code:

| Key Pattern (exact) | Data Type | TTL | Set At | Read At | Purpose |
|--------------------|-----------|-----|---------------------------|------------------------------|--------|
| factoryops:fleet_stream:v1 | Redis Pub/Sub | N/A | device-service/app/monitoring.py:fleet_stream_broadcaster | ui-web (WebSocket) | Real-time fleet updates |
| factoryops:energy_stream:v1 | Redis Pub/Sub | N/A | energy-service/app/energy_broadcast.py | Subscribers | Energy data updates |
| analytics_jobs_stream | Redis Stream | N/A | analytics-service API | analytics-worker | ML job queue |
| analytics_jobs_dead_letter | Redis Stream | N/A | analytics-worker | Admin review | Failed ML jobs |

**Cache strategy**: Redis used primarily for pub/sub messaging, not caching. No cache-aside pattern implemented.

---

## 5d. Object Storage (MinIO/S3)

- **Endpoint**: minio:9000
- **Region**: us-east-1
- **Buckets**:
  - energy-platform-datasets (public) - ML datasets, exports
  - factoryops-waste-reports (public) - Waste analysis PDFs
  - dashboard-snapshots (private) - Dashboard snapshots

**File naming patterns**:
- ML artifacts: `models/{model_name}/{version}/model.joblib`
- Reports: `reports/{tenant_id}/{report_type}/{timestamp}.pdf`
- Exports: `exports/{device_id}/{date}/{hour}/telemetry.csv`

**Write path**: Client → Service → boto3/MinIO SDK → MinIO bucket/key

**Read path**: Request → Auth check → Presigned URL generation (expiry: 3600s) or direct stream

**Max file size limits**: Not explicitly enforced in code

---

## 5e. Message Broker / MQTT

| Name (exact) | Publisher | Subscriber | Payload Schema | QoS | Purpose |
|-------------|-----------|-----------|----------------|-----|---------|
| devices/{device_id}/telemetry | IoT devices/simulator | data-service/src/mqtt_handler.py | {"device_id": string, "timestamp": string, "schema_version": "v1", ...telemetry_fields} | 1 | Telemetry ingestion |

---

## 6. BACKEND — COMPLETE ARCHITECTURE

### 6a. Service / Module Inventory

**[device-service]**
- Responsibility: Device registry, health scoring, shift management, real-time dashboard data
- Entrypoint: services/device-service/main.py
- Framework: FastAPI
- Port: 8000
- Base URL path: /api/v1
- Database(s) it owns: devices, device_shifts, parameter_health_config, device_performance_trends, idle_running_log, device_properties, device_dashboard_widgets, device_live_state
- Sync calls it makes → data-service (telemetry), energy-service (energy), reporting-service (reports), rule-engine-service (alerts)
- Async messages it publishes → Redis: factoryops:fleet_stream:v1
- Background jobs: Performance trends scheduler (5min), Dashboard snapshot scheduler (5s), Live projection reconciler (600s)
- Startup: Validates DNS for dependencies, configures Redis publisher, starts background tasks

**[data-service]**
- Responsibility: MQTT telemetry ingestion, validation, InfluxDB persistence, device sync to device-service
- Entrypoint: services/data-service/src/main.py
- Framework: FastAPI
- Port: 8081
- Database(s) it owns: dlq_messages, telemetry_outbox
- Consumes MQTT: devices/+/telemetry
- Publishes to: InfluxDB, device-service REST API

**[energy-service]**
- Responsibility: Real-time energy calculations, idle/off-hours detection
- Entrypoint: services/energy-service/main.py
- Framework: FastAPI  
- Port: 8010
- Database(s) it owns: energy_calculations (via MySQL)

**[auth-service]**
- Responsibility: User authentication, JWT token issuance, org/plant management
- Entrypoint: services/auth-service/app/main.py
- Framework: FastAPI
- Port: 8090
- Database(s) it owns: users, orgs, plants tables

**[rule-engine-service]**
- Responsibility: Threshold rule CRUD, real-time evaluation, alert generation
- Entrypoint: services/rule-engine-service/main.py
- Framework: FastAPI
- Port: 8002

**[analytics-service]**
- Responsibility: ML job execution, model training, failure prediction
- Entrypoint: services/analytics-service/src/main.py
- Framework: FastAPI
- Port: 8003
- Workers: analytics-worker, analytics-worker-2 (Redis consumer groups)

**[reporting-service]**
- Responsibility: Energy report generation, scheduled reports
- Entrypoint: services/reporting-service/src/main.py
- Framework: FastAPI
- Port: 8085

**[waste-analysis-service]**
- Responsibility: Energy waste analysis, idle/off-hours waste calculation
- Entrypoint: services/waste-analysis-service/src/main.py
- Framework: FastAPI
- Port: 8087

**[copilot-service]**
- Responsibility: AI-powered natural language queries
- Entrypoint: services/copilot-service/main.py
- Framework: FastAPI
- Port: 8007
- External services: Groq/Gemini/OpenAI API

**[data-export-service]**
- Responsibility: Continuous telemetry export to S3
- Entrypoint: services/data-export-service/main.py
- Framework: FastAPI
- Port: 8080

---

### 6b. COMPLETE API REFERENCE

#### Device Service (Port 8000)

| Method | Full Path | Handler | Auth Required | Request Body | Response |
|--------|----------|---------|--------------|-------------|----------|
| GET | /api/v1/devices | devices.py:get_devices | Optional | - | DeviceListResponse |
| POST | /api/v1/devices | devices.py:create_device | Optional | DeviceCreate | DeviceResponse |
| GET | /api/v1/devices/{device_id} | devices.py:get_device | Optional | - | DeviceResponse |
| PUT | /api/v1/devices/{device_id} | devices.py:update_device | Optional | DeviceUpdate | DeviceResponse |
| DELETE | /api/v1/devices/{device_id} | devices.py:delete_device | Optional | - | DeleteResponse |
| GET | /api/v1/devices/{device_id}/shifts | shifts.py:get_shifts | Optional | - | ShiftListResponse |
| POST | /api/v1/devices/{device_id}/shifts | shifts.py:create_shift | Optional | ShiftCreate | ShiftResponse |
| GET | /api/v1/devices/{device_id}/health-config | health.py:get_configs | Optional | - | ConfigListResponse |
| POST | /api/v1/devices/{device_id}/health-config | health.py:create_config | Optional | ConfigCreate | ConfigResponse |
| POST | /api/v1/devices/{device_id}/health-score | health.py:calculate_score | Optional | TelemetryValues | HealthScoreResponse |
| POST | /api/v1/devices/{device_id}/live-update | live.py:update_live | Internal | LiveUpdateRequest | Success |
| GET | /api/v1/devices/dashboard/fleet-snapshot | dashboard.py:fleet_snapshot | Optional | page, page_size | FleetSnapshotResponse |
| GET | /api/v1/devices/dashboard/summary | dashboard.py:dashboard_summary | Optional | - | DashboardSummaryResponse |
| GET | /health | __init__.py:health_check | No | - | {status, service, version} |
| GET | /ready | __init__.py:readiness_check | No | - | {status, service} |
| GET | /metrics | __init__.py:metrics | No | - | Prometheus metrics |

#### Data Service (Port 8081)

| Method | Full Path | Handler | Auth Required |
|--------|----------|---------|--------------|
| GET | /api/v1/data/health | health | No |
| GET | /api/v1/data/telemetry/{device_id} | telemetry query | Optional |

#### Energy Service (Port 8010)

| Method | Full Path | Handler | Auth Required |
|--------|----------|---------|--------------|
| POST | /api/v1/energy/live-update | live_update | Internal |
| GET | /api/v1/energy/summary | summary | Optional |
| GET | /api/v1/energy/today-loss-breakdown | loss_breakdown | Optional |

#### Rule Engine Service (Port 8002)

| Method | Full Path | Handler | Auth Required |
|--------|----------|---------|--------------|
| GET | /api/v1/rules | list_rules | Optional |
| POST | /api/v1/rules | create_rule | Optional |
| GET | /api/v1/rules/{rule_id} | get_rule | Optional |
| PUT | /api/v1/rules/{rule_id} | update_rule | Optional |
| DELETE | /api/v1/rules/{rule_id} | delete_rule | Optional |
| GET | /api/v1/alerts | list_alerts | Optional |
| GET | /health | health | No |

#### Analytics Service (Port 8003)

| Method | Full Path | Handler | Auth Required |
|--------|----------|---------|--------------|
| POST | /api/v1/analytics/jobs | submit_job | Optional |
| GET | /api/v1/analytics/jobs/{job_id} | get_job | Optional |
| GET | /health/live | health | No |

#### Reporting Service (Port 8085)

| Method | Full Path | Handler | Auth Required |
|--------|----------|---------|--------------|
| GET | /api/reports/energy/{device_id} | energy_report | Optional |
| GET | /api/reports/tariffs | list_tariffs | Optional |
| POST | /api/reports/tariffs | create_tariff | Optional |
| GET | /health | health | No |

#### Copilot Service (Port 8007)

| Method | Full Path | Handler | Auth Required |
|--------|----------|---------|--------------|
| POST | /api/v1/chat | chat | Optional |
| GET | /health | health | No |
| GET | /ready | ready | No |

#### Auth Service (Port 8090)

| Method | Full Path | Handler | Auth Required |
|--------|----------|---------|--------------|
| POST | /api/v1/auth/login | login | No |
| POST | /api/v1/auth/refresh | refresh | No |
| POST | /api/v1/auth/logout | logout | Yes |
| GET | /api/v1/auth/me | get_me | Yes |
| GET | /health | health | No |

---

### 6c. MIDDLEWARE STACK — EXACT EXECUTION ORDER

**device-service request lifecycle:**
1. **AuthMiddleware** (shared/auth_middleware.py:51)
   - Checks if path in OPEN_PATHS (/health, /ready, /metrics, /docs)
   - Looks for X-Internal-Service header (service-to-service)
   - Extracts Bearer token from Authorization header
   - Decodes JWT using JWT_SECRET_KEY and JWT_ALGORITHM
   - Sets request.state with user_id, org_id, role, plant_ids, is_authenticated
   - If no valid token: returns 401

2. **Custom middleware** (app/__init__.py:349)
   - Appends X-Service-Started-At header

3. **Exception handlers** (app/__init__.py:356-399)
   - RequestValidationError → 422 with VALIDATION_ERROR
   - HTTPException → passes through detail
   - Unhandled Exception → 500 with INTERNAL_ERROR

---

### 6d. AUTHENTICATION & AUTHORIZATION — COMPLETE

**Auth mechanism**: JWT (python-jose library)

**Token structure** (exact, from JWT decode):
```json
{
  "sub": "uuid — user.id",
  "org_id": "uuid",
  "role": "string — enum: [SuperAdmin, Admin, Operator, Viewer]",
  "plant_ids": ["uuid"],
  "email": "string",
  "full_name": "string",
  "type": "access",
  "iat": "unix timestamp",
  "exp": "unix timestamp"
}
```

**Token lifecycle** (file:function for each step):
- Issue: auth-service/app/api/auth.py:login() → creates JWT with user claims
- Access token expiry: 15 minutes (ACCESS_TOKEN_EXPIRE_MINUTES)
- Refresh token: stored in database, 7 days expiry (REFRESH_TOKEN_EXPIRE_DAYS)
- Refresh flow: /api/v1/auth/refresh endpoint validates refresh token, issues new access token
- Invalidation: No blacklist mechanism (stateless JWT)
- Client storage: Bearer token in Authorization header

**RBAC / Permission model**:

| Role | Can Do | Cannot Do |
|------|--------|-----------|
| SuperAdmin | All operations | N/A |
| Admin | Manage org, users, devices | System config |
| Operator | View devices, create rules | User management |
| Viewer | Read-only access | Create/modify |

Permission check implementation: require_role() decorator at shared/auth_middleware.py:150

**Multi-tenancy enforcement**:
- Tenant identified from: JWT claim org_id or ?tenant_id query param
- Enforcement point: AuthMiddleware at shared/auth_middleware.py:110
- Tables with tenant scoping: devices, device_shifts, parameter_health_config, rules, alerts
- 🔴 RISK: tenant_id is nullable in most tables - not enforced at DB level
- 🔴 RISK: auth enforcement must remain enabled

---

### 6e. COMPLETE MIDDLEWARE & VALIDATION LAYER MAP

| Field | Validated At | Validation Rules |
|-------|-------------|----------------|
| device_id | Pydantic schema DeviceCreate | pattern: ^[A-Za-z0-9_-]+$, min 1, max 50 |
| device_name | Pydantic schema | min_length=1, max_length=255 |
| shift_start/time | Pydantic schema ShiftCreate | valid TIME format |
| health_config threshold | Pydantic schema | numeric ranges |
| JWT token | AuthMiddleware | jose.jwt.decode() with signature verification |

Business logic validation:
- Shift overlap check: device-service/app/services/shift.py
- Health weight validation: device-service/app/services/health_config.py

All inputs validated at API layer - no raw queries reaching DB.

---

### 6f. ERROR HANDLING — COMPLETE MAP

**Global error handler**: app/__init__.py:356-399

```json
{ "error": "ERROR_CODE", "message": "human readable", "code": "ERROR_CODE", "details": {} }
```

**Custom exception inventory**:
| Exception Class | HTTP Status | Error Code | When Thrown | File |
|----------------|------------|------------|-------------|------|
| RequestValidationError | 422 | VALIDATION_ERROR | Invalid request body | FastAPI built-in |
| HTTPException | Variable | Variable | Service raises | FastAPI built-in |

**Unhandled rejection / uncaught exception behavior**: Returns 500 with INTERNAL_ERROR, logs exception to logger

**Error logging**: Python logging module, JSON format, level set by LOG_LEVEL env var

---

### 6g. BACKGROUND JOBS, WORKERS & SCHEDULED TASKS

| Job Name | File:Function | Trigger | Schedule | What It Does | Avg Runtime | Timeout | Retry Policy |
|----------|--------------|---------|----------|---------------|-------------|---------|-------------|
| Performance Trends | device-service/app/__init__.py:110 | Continuous | Every 5 min | Materialize bucket, aggregate idle | ~30s | None | N/A |
| Dashboard Snapshot | device-service/app/__init__.py:168 | Continuous | Every 5s | Fleet/summary snapshots | ~2s | None | N/A |
| Live Projection Reconciler | device-service/app/__init__.py:242 | Continuous | Every 600s | Reconcile recent projections | ~10s | None | N/A |
| Analytics Worker | analytics-service/src/worker.py | Redis Stream | On job arrival | Execute ML jobs | Variable | 300s | 3 retries |
| MQTT Telemetry Handler | data-service/src/mqtt_handler.py | MQTT message | On message | Parse, validate, store | ~100ms | None | DLQ after 3 failures |

---

### 6h. ASYNC / CONCURRENCY MAP

- **AsyncIO**: All FastAPI services use async/await
- **Blocking calls**: 
  - ⚠️ data-service/src/influx_client.py: Uses synchronous influxdb-client for writes (blocks event loop)
  - ⚠️ analytics-service: TensorFlow/PyTorch training runs in-thread (blocks)
- **Concurrent operations**:
  - Redis pub/sub for fleet/energy streams
  - Multiple analytics-worker instances consume same Redis stream (consumer group)
- **Race condition risks**: 
  - device-service live_state update without locking - concurrent live-updates could overwrite

---

### 6i. ML / AI PIPELINE (complete)

**Models inventory**:
| Model Name | Type | Framework | File Location | Input | Output |
|-----------|------|-----------|--------------|-------|--------|
| failure_prediction | classification | XGBoost | analytics-service | telemetry features | failure_probability |
| energy_forecasting | time-series | Prophet | analytics-service | historical energy | forecast_kwh |
| anomaly_detection | unsupervised | scikit-learn | analytics-service | telemetry vector | anomaly_score |

**Training pipeline**:
1. Trigger: Weekly retrainer (analytics-worker ML_WEEKLY_RETRAINER_ENABLED)
2. Data source: InfluxDB telemetry bucket
3. Preprocessing: Aggregate to hourly/daily, feature engineering
4. Training: XGBoost.fit() / Prophet.fit()
5. Evaluation: Accuracy metrics stored in analytics_accuracy_evaluations
6. Storage: S3 key ml_model_artifacts/{model_name}/{version}/
7. Deployment: New version becomes active automatically

**Inference pipeline**:
1. Input: /api/v1/analytics/predict endpoint receives device_id + time range
2. Preprocessing: Fetch telemetry, feature engineering
3. Model.predict(input) → output
4. Response: JSON with predictions

---

### 6j. EXTERNAL SERVICE INTEGRATIONS — COMPLETE

**[Groq] (AI Provider)**
- Purpose: LLM for copilot natural language queries
- SDK or raw HTTP: Raw HTTP (requests library)
- Credentials: GROQ_API_KEY in .env
- Integration: copilot-service/src/ai/model_client.py
- Rate limits: Groq API limits apply (not enforced in code)

**[EMQX] (MQTT Broker)**
- Purpose: Telemetry ingestion from IoT devices
- Credentials: None (EMQX_ALLOW_ANONYMOUS=true in docker-compose)
- Integration: data-service/src/mqtt_handler.py
- Topic subscribed: devices/+/telemetry

**[Gmail SMTP]**
- Purpose: Email alerts from rule engine
- Credentials: EMAIL_PASSWORD in .env
- Integration: rule-engine-service/src/email_notifier.py

**[MinIO] (S3-Compatible)**
- Purpose: Object storage for ML models, reports
- Credentials: MINIO_ROOT_USER/PASSWORD in .env
- Integration: boto3 client in each service

---

### 6k. FILE UPLOAD / DOWNLOAD — COMPLETE FLOWS

**Upload** (Report PDFs):
- Endpoint: Internal (generated by reporting-service)
- Storage: MinIO bucket factoryops-waste-reports
- Key pattern: reports/{tenant_id}/{device_id}/{timestamp}.pdf
- Delivery: Presigned URL with 3600s expiry

**Download** (ML Models):
- Endpoint: Internal (analytics-service reads from S3)
- Storage: MinIO bucket energy-platform-datasets
- Key pattern: models/{model_name}/{version}/*.joblib

---

### 6l. RATE LIMITING — COMPLETE CONFIG

No rate limiting configured in any service. ⚠️ **DEBT**: Services vulnerable to abuse.

---

### 6m. SECURITY CONFIGURATION — COMPLETE

**CORS**:
- ⚠️ Not configured in any FastAPI service - uses defaults (all origins allowed in dev)

**Security headers**:
- No custom security headers configured

**HTTPS**:
- Terminated at: Not configured (HTTP only in docker-compose)
- HTTP → HTTPS redirect: Not configured
- HSTS: Not enabled

**Input handling**:
- SQL injection: Parameterized queries via SQLAlchemy ORM everywhere
- XSS: React auto-escapes by default, no dangerouslySetInnerHTML found
- CSRF: Not implemented (auth bypass is removed)
- Path traversal: Not applicable (no file upload user paths)
- Mass assignment: Pydantic schemas whitelist fields

**Secrets**:
- 🔴 Hardcoded secrets: JWT_SECRET_KEY, GROQ_API_KEY, EMAIL_PASSWORD in .env (committed to git)
- Secret rotation: Not implemented

---

### 6n. PARTIAL FAILURE & RESILILIENCE

- **Circuit breakers**: Not implemented
- **Retries**: analytics-worker has 3 retries for failed jobs
- **Timeouts**: Default HTTP client timeouts (not explicitly set)
- **What happens if [service X] is completely down**:
  - device-service down: UI cannot load fleet data
  - data-service down: Telemetry ingestion stops, devices show "stale"
  - analytics-service down: ML jobs queue up in Redis
  - ⚠️ No graceful degradation implemented

---

### 6o. DATA FLOW — TIMEZONE & LOCALE HANDLING

- Timestamps stored as UTC in MySQL (DATETIME(6) with timezone=True)
- UI/PDF displays in Asia/Kolkata (configurable via PLATFORM_TIMEZONE)
- ⚠️ No explicit DST handling in date arithmetic

---

### 6p. DATA RETENTION & ARCHIVAL

- InfluxDB: 365 days (default retention)
- MySQL: No automatic archival
- MinIO: No lifecycle policies configured
- GDPR: No right-to-delete implementation

---

## 7. FRONTEND ARCHITECTURE — COMPLETE

### 7a. App Bootstrap Sequence

1. index.html loads
2. Next.js bundle executes
3. Root layout renders
4. AuthContext checks localStorage for token
5. If valid token: redirect to /(dashboard)
6. If no token: render /(auth)/login

### 7b. Routing — Complete Route Table

| Route Path | Component File | Auth Required | Purpose |
|-----------|---------------|--------------|---------|
| /login | (auth)/login/page.tsx | No | User login |
| / | (protected)/page.tsx | Yes | Dashboard |
| /machines | (protected)/machines/page.tsx | Yes | Device list |
| /machines/[deviceId] | (protected)/machines/[deviceId]/page.tsx | Yes | Device detail |
| /devices | (protected)/devices/page.tsx | Yes | Alt device list |
| /devices/[deviceId] | (protected)/devices/[deviceId]/page.tsx | Yes | Device detail |
| /devices/[deviceId]/telemetry | .../telemetry/page.tsx | Yes | Real-time data |
| /devices/[deviceId]/charts | .../charts/page.tsx | Yes | Historical charts |
| /devices/[deviceId]/analytics | .../analytics/page.tsx | Yes | ML predictions |
| /devices/[deviceId]/alerts | .../alerts/page.tsx | Yes | Device alerts |
| /reports | (protected)/reports/page.tsx | Yes | Report list |
| /reports/energy | .../energy/page.tsx | Yes | Energy reports |
| /reports/compare | .../compare/page.tsx | Yes | Comparison reports |
| /rules | (protected)/rules/page.tsx | Yes | Rule management |
| /rules/new | .../new/page.tsx | Yes | Create rule |
| /rules/[ruleId] | .../[ruleId]/page.tsx | Yes | Edit rule |
| /analytics | (protected)/analytics/page.tsx | Yes | ML analytics |
| /waste-analysis | (protected)/waste-analysis/page.tsx | Yes | Waste analysis |
| /copilot | (protected)/copilot/page.tsx | Yes | AI copilot UI |
| /org/users | (protected)/org/users/page.tsx | Yes | User management |
| /org/plants | (protected)/org/plants/page.tsx | Yes | Plant management |
| /admin | (protected)/admin/page.tsx | Yes | Admin panel |
| /admin/orgs | .../admin/orgs/page.tsx | Yes | Org management |
| /settings | (protected)/settings/page.tsx | Yes | Settings |
| /profile | (protected)/profile/page.tsx | Yes | User profile |

### 7c. State Management — Complete Store Map

| Store Name | File | State Shape | Actions |
|-----------|------|-------------|---------|
| AuthContext | ui-web/lib/authContext.tsx | {user, token, login, logout} | login(), logout() |
| (React Query) | ui-web/lib/*.ts | API data caching | queryClient.useQuery() |
| Zustand | shivex-mobile/src/store/useUserStore.ts | {user, token, setUser} | setUser(), clearUser() |

### 7d. API Layer — Complete

- HTTP client: Axios (ui-web), Fetch API (shivex-mobile)
- Base URL: NEXT_PUBLIC_API_URL from env
- Auth token: Bearer token in Authorization header
- Token refresh: Interceptor at ui-web/lib/api.ts

### 7e. Component Inventory

Major components in ui-web/components/:
- auth/: LoginForm, ProtectedRoute
- charts/: LineChart, BarChart, AreaChart (using Recharts)
- layout/: Sidebar, Header, Footer
- reports/: EnergyReport, ComparisonReport
- ui/: Button, Input, Card, Modal (custom UI kit)

### 7f. Form Handling

- Library: Native React forms (no form library)
- Validation: Pydantic on backend, basic HTML5 on frontend
- Submission: onSubmit handlers call API functions

### 7g. Real-time / Live Data

- WebSocket: Not used in frontend
- Polling: React Query with refetchInterval for live data
- SSE: Not implemented
- Updates: Every 5-30 seconds via React Query polling

---

## 8. MOBILE APP (shivex-mobile)

- Framework: Expo SDK 54 (React Native 0.81.5)
- Navigation: expo-router (file-based routing)
- State: Zustand store
- Auth: expo-secure-store for token
- API: Axios client (shares API layer with web)
- Push: expo-notifications configured

**Screens**:
- /login - Login
- /(tabs)/index - Dashboard tab
- /(tabs)/machines - Device list tab
- /(tabs)/reports - Reports tab
- /(tabs)/alerts - Alerts tab
- /(tabs)/more - More options tab
- /machines/[deviceId] - Device detail
- /reports/energy - Energy reports
- /copilot - AI copilot
- /waste - Waste analysis

---

## 9. CRITICAL DATA FLOWS — COMPLETE TRACES

### Flow 1: Device Onboarding
```
User → POST /api/v1/devices (device-service/app/api/v1/devices.py:create_device)
  → DeviceService.create_device()
  → SQLAlchemy: INSERT INTO devices
  → Response: 201 Created
```

### Flow 2: Telemetry Ingestion
```
IoT Device → MQTT: devices/COMPRESSOR-001/telemetry
  → data-service/src/mqtt_handler.py:on_message()
  → TelemetryService.validate() 
  → InfluxDBClient.write()
  → TelemetryOutboxService.publish() → POST to device-service /live-update
  → LiveProjectionService.update() → UPDATE device_live_state
  → FleetStreamBroadcaster.publish() → Redis pub/sub
  → UI receives via polling
```

### Flow 3: Health Score Calculation
```
User → POST /api/v1/devices/{device_id}/health-score
  → HealthConfigService.get_active_configs()
  → For each param: score = calculate_parameter_score(value, config)
  → health_score = weighted_average(parameter_scores)
  → Response: HealthScoreResponse
```

### Flow 4: Report Generation
```
User → GET /api/reports/energy/{device_id}
  → ReportingService.generate_energy_report()
  → InfluxReader.query_energy_data()
  → ReportEngine.build_pdf()
  → MinIOClient.upload()
  → Response: {result_url: "https://minio/..."}
```

### Flow 5: AI Copilot Query
```
User → POST /api/v1/chat {message: "what was yesterday energy?"}
  → IntentRouter.detect_intent()
  → QueryEngine.build_sql()
  → MySQL.execute()
  → ModelClient.generate_response() → Groq API
  → Response: {answer: "...", chart_data: {...}}
```

---

## 10. INFRASTRUCTURE & DEPLOYMENT — COMPLETE

### 10a. Architecture Topology

```
                                    [Client Browser]
                                           │ HTTPS:3000
                                    [ui-web:3000]
                                           │
        ┌──────────────────────────────┬────┴──────────────────────────────┐
        │                              │                                  │
   [device-service:8000]      [data-service:8081]              [copilot-service:8007]
        │                              │                                  │
        │                    [MQTT:1883]                        [Groq API]
        │                         │                                    │
   [IoT Devices] ─────────►  [emqx:1883]                                   │
        │                         │                                    │
        │                    [InfluxDB:8086]                            │
        │                              │                                  │
        ├──────────────────────────────┤                                  │
        │                              │                                  │
   [MySQL:3306]                 [Redis:6379]                              │
        │                              │                                  │
        │                    [analytics-worker]                          │
        │                              │                                  │
   [MinIO:9000]◄─────────────[analytics-service:8003]                     │
        │                                                        │
   [Reporting Service:8085]                                        │
   [Waste Analysis:8087]                                           │
   [Rule Engine:8002]                                              │
   [Energy Service:8010]                                           │
```

### 10b. Container / Service Inventory

| Service Name | Image | Ports | Depends On | Restart Policy |
|-------------|-------|-------|------------|---------------|
| mysql | mysql:8.0 | 3306 | - | unless-stopped |
| influxdb | influxdb:2.7-alpine | 8086 | - | unless-stopped |
| minio | minio/minio | 9000, 9001 | - | unless-stopped |
| redis | redis:7-alpine | 6379 | - | unless-stopped |
| emqx | emqx/emqx:5.3.0 | 1883, 8083, 8883, 18083 | - | unless-stopped |
| device-service | ./services/device-service | 8000 | mysql, redis | unless-stopped |
| data-service | ./services/data-service | 8081 | influxdb, emqx, mysql | unless-stopped |
| energy-service | ./services/energy-service | 8010 | mysql, redis, device-service | unless-stopped |
| rule-engine-service | ./services/rule-engine-service | 8002 | mysql | unless-stopped |
| analytics-service | ./services/analytics-service | 8003 | mysql, minio, redis | unless-stopped |
| analytics-worker | ./services/analytics-service | - | mysql, minio, redis | unless-stopped |
| reporting-service | ./services/reporting-service | 8085 | mysql, minio | unless-stopped |
| waste-analysis-service | ./services/waste-analysis-service | 8087 | mysql, minio | unless-stopped |
| copilot-service | ./services/copilot-service | 8007 | mysql | unless-stopped |
| auth-service | ./services/auth-service | 8090 | mysql | unless-stopped |
| data-export-service | ./services/data-export-service | 8080 | influxdb, minio, mysql | unless-stopped |
| ui-web | ./ui-web | 3000 | all services | unless-stopped |
| prometheus | prom/prometheus | 9090 | device-service | unless-stopped |
| alertmanager | prom/alertmanager | 9093 | - | unless-stopped |
| grafana | grafana/grafana | 3001 | prometheus | unless-stopped |

### 10c. Nginx / Reverse Proxy

⚠️ **DEBT**: No nginx reverse proxy configured. Services exposed directly via Docker ports.

### 10d. Inter-Service Communication Map

| From Service | To Service | Protocol | Endpoint | Auth |
|-------------|-----------|----------|----------|------|
| device-service | data-service | HTTP | http://data-service:8081 | None |
| device-service | energy-service | HTTP | http://energy-service:8010 | None |
| device-service | reporting-service | HTTP | http://reporting-service:8085 | None |
| data-service | influxdb | HTTP | http://influxdb:8086 | Token |
| data-service | device-service | HTTP | /api/v1/devices/* | Bearer token |
| analytics-service | minio | S3 | minio:9000 | Access key |
| ui-web | device-service | HTTP | localhost:8000 | Bearer token |

### 10e. Startup & Initialization Order

```
1. mysql must be healthy before [device-service, data-service, analytics, etc.]
2. redis must be healthy before [device-service, analytics-service]
3. influxdb must be healthy before [data-service]
4. emqx must be healthy before [data-service]
5. minio must be healthy before [analytics-service, reporting-service]
6. device-service must be healthy before [energy-service, ui-web]
7. data-service must be started before [copilot-service]
```

### 10f. CI/CD Pipeline — Complete

⚠️ **DEBT**: No CI/CD pipeline defined in repository. All deployments manual via docker compose.

### 10g. Monitoring & Observability

**Logging**:
- Library: Python logging (JSON format in production)
- Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
- Aggregation: Not configured (logs to stdout)

**Metrics**:
- Collection: Prometheus (device-service /metrics endpoint)
- Custom metrics: DASHBOARD_SCHEDULER_LAG_SECONDS

**Tracing**:
- Distributed tracing: Not implemented

**Alerting**:
| Alert Name | Condition | Severity | Notification |
|-----------|-----------|---------|--------------|
| ServiceDown | HTTP 5xx on health endpoint | critical | webhook |
| HighSchedulerLag | lag > 10s | warning | webhook |

**Health check endpoints**:
| Service | Endpoint | Expected Response |
|---------|----------|-------------------|
| device-service | /health | {status: "healthy"} |
| data-service | /api/v1/data/health | {status: "ok"} |
| auth-service | /health | {status: "ok"} |
| copilot-service | /health | {status: "ok"} |

---

## 11. TESTING — COMPLETE

### 11a. Test Infrastructure

- Framework: pytest (Python), Playwright (E2E)
- Test database: In-memory SQLite or testcontainers
- Mocking: pytest-mock, unittest.mock
- Test location: tests/ directories in each service

### 11b. Complete Test Inventory

| Service | Test File | Tests What |
|---------|-----------|------------|
| copilot-service | tests/test_query_engine.py | SQL generation |
| copilot-service | tests/test_intent_router.py | Intent detection |
| copilot-service | tests/test_sql_guard.py | SQL injection prevention |
| copilot-service | tests/test_chart_reliability.py | Chart data |
| ui-web | tests/e2e/*.spec.ts | E2E flows (Playwright) |

### 11c. Coverage Gaps

- device-service: No unit tests found
- data-service: No unit tests found  
- rule-engine-service: No unit tests found
- reporting-service: No unit tests found

⚠️ **CRITICAL**: Most backend services lack test coverage.

---

## 12. DEAD CODE AUDIT

| File | Line(s) | Type | Description |
|------|---------|------|-------------|
| device-service/app/schemas/device.py:54-56 | 54-56 | Deprecated field | status field marked DEPRECATED but still in schema |
| services/device-service/app/services/performance_trends.py | - | Unused function | Some helper functions may be unused |

---

## 13. KNOWN ISSUES, TODOS & TECH DEBT

| File | Line | Tag | Exact Text | Severity |
|------|------|-----|------------|----------|
| .env | 98,102,108 | 🔴 CRITICAL | Hardcoded secrets in git | CRITICAL |
| .env | 110 | 🟡 DEBT | auth enforcement is always on | HIGH |
| schema.md | - | 🟡 DEBT | tenant_id nullable in most tables | MEDIUM |
| All services | - | 🟡 DEBT | No rate limiting | MEDIUM |
| All services | - | 🟡 DEBT | No circuit breakers | MEDIUM |
| Services | - | 🟡 DEBT | No explicit transaction boundaries | LOW |
| device-service | - | 🟡 DEBT | Sync influxdb client blocks event loop | LOW |
| All Python services | - | ⬛ DEAD | No comprehensive test suites | - |

---

## 14. DEPENDENCY AUDIT

### 14a. Direct Dependencies (key packages)

| Package | Version | Service | Purpose |
|---------|---------|---------|---------|
| fastapi | 0.115+ | All services | API framework |
| sqlalchemy | 2.0+ | All services | ORM |
| aiomysql | latest | All services | Async MySQL |
| pydantic | 2.0+ | All services | Validation |
| python-jose | latest | All services | JWT |
| redis | 5.0+ | device, analytics | Pub/sub |
| influxdb-client | latest | data, reporting | Time-series |
| boto3 | latest | analytics, reporting | S3 |
| tensorflow | latest | analytics | ML |
| xgboost | latest | analytics | ML |
| prophet | latest | analytics | Forecasting |
| next | 16.1.6 | ui-web | Framework |
| react | 19.2.3 | ui-web | UI |
| expo | 54 | shivex-mobile | Mobile |
| react-native | 0.81.5 | shivex-mobile | Mobile |

### 14b. Risk Flags

| Package | Risk | Recommendation |
|---------|------|----------------|
| python-jose | Verify latest version for CVE | Keep updated |
| fastapi | Stable | Keep updated |
| expo | Check for SDK deprecation | Monitor Expo roadmap |
| ⚠️ All secrets in .env | Critical exposure | Rotate immediately |

### 14c. License Inventory

All packages use permissive licenses (MIT, Apache 2.0, BSD). No copyleft concerns.

---

## 15. PERFORMANCE RISK INVENTORY

| Location | Issue | Impact | Recommended Fix |
|---------|-------|--------|-----------------|
| device-service/app/services/dashboard.py | JOIN without indexes | Slow on 100+ devices | Add composite indexes |
| data-service/src/influx_client.py | Sync HTTP call in async context | Blocks event loop | Use aiohttp or run in thread pool |
| analytics-service | Large ML jobs in process | Memory pressure | Use Celery or separate worker |
| All list endpoints | No pagination | Memory on large datasets | Add cursor pagination |

---

## 16. ARCHITECTURAL DECISIONS & TRADEOFFS

**Decision: Separate databases in bootstrap.sql but use single ai_factoryops**
- Context: Bootstrap creates 5 databases but docker-compose uses only ai_factoryops
- Chosen approach: Single unified database
- Risk: Bootstrap script is misleading/dead code

**Decision: Redis pub/sub for real-time updates**
- Context: Needed multi-instance support for fleet updates
- Chosen approach: Redis streams + pub/sub
- Tradeoffs: Added complexity, but scales horizontally

**Decision: auth enforcement is always enabled**
- Context: Local development ease
- Risk: Accidental production deployment without auth

**Decision: No nginx reverse proxy**
- Context: Docker Compose simplicity
- Tradeoffs: No SSL termination, no centralized rate limiting

---

## 17. GLOSSARY

| Term | Definition |
|------|------------|
| device_id | Unique identifier for IoT device (PK in devices table) |
| tenant_id | Organization identifier for multi-tenancy |
| data_source_type | metered (non-smart) or sensor (smart/CT) |
| phase_type | Electrical phase: single or three |
| runtime_status | Computed from telemetry: running/stopped |
| health_score | Weighted parameter score 0-100 |
| shift | Planned operating hours configuration |
| idle_energy | Energy consumed during idle periods |
| waste | Energy consumed during off-hours or overconsumption |
| bucket | Time window for aggregation (e.g., 5-minute bucket) |

---

## 18. QUICK-START GUIDE

```bash
# 1. Clone
git clone <repo-url> && cd FactoryOPS-Cittagent-Obeya-main

# 2. Configure environment
cp .env.example .env  # ⚠️ NOTE: .env.example does not exist - copy from .env
# Edit .env with production values

# 3. Start platform
docker compose up -d --build

# 4. Wait for services to be healthy
docker compose ps

# 5. Verify health
curl -s http://localhost:8000/health
curl -s http://localhost:8081/api/v1/data/health
curl -s http://localhost:8090/health

# 6. Start simulator (optional)
./scripts/simulatorctl.sh start COMPRESSOR-001

# 7. UI available at
# http://localhost:3000
```

**Common local dev failures and fixes:**

| Symptom | Cause | Fix |
|---------|-------|-----|
| Connection refused to mysql | Service not healthy | Wait for "healthy" in docker compose ps |
| 401 on all endpoints | auth enforcement enabled but JWT missing | Set JWT_SECRET_KEY in .env |
| Telemetry not appearing | MQTT not connected | Check emqx container logs |
| Devices show stale | data-service down | Restart data-service |

---

## 19. WHAT WILL BREAK AND WHEN

| Component | Why It Will Break | When | Prevention |
|-----------|------------------|------|------------|
| Hardcoded JWT secret | Committed to git, public exposure | Immediately in production | Rotate secrets, use secrets manager |
| Groq API key exposed | Committed to git | Immediately | Rotate key, use env vars only in production |
| Auth enforcement disabled | Default insecure config | Production deployment | Remove the bypass and test auth flows |
| Single MySQL instance | No HA/backup | Hardware failure | Add replication, backups |
| InfluxDB 365-day retention | Data loss after 1 year | 1 year from first data | Configure longer retention |
| No rate limiting | DoS vulnerability | Public exposure | Implement rate limiting |

---

## END OF CODEBASE BIBLE
