# FactoryOPS / Cittagent Platform

FactoryOPS is a multi-service industrial monitoring platform with:

- `ui-web` for the operator dashboard
- `device-service` for onboarding, shifts, health config, runtime state, and live projections
- `data-service` for MQTT ingestion and telemetry queries
- `analytics-service` for anomaly and failure jobs
- `rule-engine-service` for rules and alerts
- `reporting-service` for energy reports and PDFs
- `waste-analysis-service` for waste and idle analysis
- `copilot-service` for assistant-style queries
- `auth-service` for authentication and org/tenant scope
- supporting services like MySQL, Redis, InfluxDB, MinIO, EMQX, Prometheus, Grafana, and Mailpit

## What You Need

- Docker Engine with Docker Compose v2
- Access to the repository root
- Optional for local UI work: Node.js 20+
- Optional for simulator CLI testing: Python 3 and `mosquitto_pub`

Ports used by the default compose stack:

| Service | Port |
|---|---|
| UI | `3000` |
| Device Service | `8000` |
| Data Service | `8081` |
| Rule Engine Service | `8002` |
| Analytics Service | `8003` |
| Data Export Service | `8080` |
| Reporting Service | `8085` |
| Waste Analysis Service | `8087` |
| Copilot Service | `8007` |
| Energy Service | `8010` |
| Auth Service | `8090` |
| EMQX MQTT | `1883` |
| MySQL | `3306` |
| Redis | `6379` |
| InfluxDB | `8086` |
| MinIO API / Console | `9000` / `9001` |
| Mailpit SMTP / UI | `1025` / `8025` |
| Prometheus | `9090` |
| Alertmanager | `9093` |
| Grafana | `3001` |

## First-Time Setup

1. Create your environment file if you do not already have one.

```bash
cp .env.example .env
```

2. Fill in the values that matter for your environment.

At minimum, check:

- `MYSQL_USER`
- `MYSQL_PASSWORD`
- `MYSQL_DATABASE`
- `JWT_SECRET_KEY`
- `AUTH_SERVICE_URL`
- `MINIO_EXTERNAL_URL`
- email/SMTP settings if you want notifications

3. Start the full stack.

```bash
docker compose up -d --build
```

4. Confirm the services are healthy.

```bash
docker compose ps
curl -s http://localhost:8000/health
curl -s http://localhost:8081/api/v1/data/health
curl -s http://localhost:8002/health
curl -s http://localhost:8003/health
curl -s http://localhost:8085/health
curl -s http://localhost:8087/health
```

5. Open the UI.

```text
http://localhost:3000
```

## Pre-Production Validation

Use the single repo-native runner before deployment:

```bash
python3 scripts/preprod_validation.py --mode current-live
```

For credentials, modes, reset behavior, artifacts, and GO / NO-GO semantics, see [docs/preprod_validation.md](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/docs/preprod_validation.md).

## Device Onboarding

Onboarding is tenant-scoped and auth-aware.

- In normal usage, onboard devices from the UI after logging in.
- If you call the API directly, send a valid JWT in `Authorization: Bearer ...` and the tenant scope expected by the shared auth middleware.
- The middleware reads tenant scope from the authenticated org context, and also supports `X-Tenant-Id` / `X-Target-Tenant-Id` for the appropriate flows.

Device records live in `device-service` and require:

- `device_id`
- `device_name`
- `device_type`
- `data_source_type` set to `metered` or `sensor`
- optional metadata like `manufacturer`, `model`, `location`, `phase_type`, and `metadata_json`

Important behavior:

- `phase_type` is still accepted for backward compatibility.
- Runtime status starts as `stopped`.
- The device becomes `running` only after telemetry or a heartbeat arrives.
- `tenant_id` is assigned from the request context, not from the public create payload.

## Starting the Simulator

Use the simulator control script when you want one container per onboarded device.
It is the preferred path for onboarding demos and multi-device testing.

The script will:

- verify the device exists in `device-service`
- build the simulator image on first use
- attach the container to the compose network
- keep the container restarting with `unless-stopped`

### Start one simulator

```bash
./scripts/simulatorctl.sh start COMPRESSOR-001
```

### Start with a custom tenant

```bash
./scripts/simulatorctl.sh start --tenant-id ORG-123 COMPRESSOR-001
```

### Change the publish interval

```bash
./scripts/simulatorctl.sh start COMPRESSOR-001 2
```

### Other commands

```bash
./scripts/simulatorctl.sh list
./scripts/simulatorctl.sh status COMPRESSOR-001
./scripts/simulatorctl.sh logs COMPRESSOR-001
./scripts/simulatorctl.sh stop COMPRESSOR-001
./scripts/simulatorctl.sh restart COMPRESSOR-001
./scripts/simulatorctl.sh purge
```

Notes:

- If you omit `--tenant-id`, the script defaults to `SH00000001`.
- The simulator publishes to a tenant-prefixed topic.
- The data service expects tenant-prefixed telemetry topics.
- You must start the main compose stack first, because the script attaches to the compose network and talks to `device-service`.
- `docker compose down -v --remove-orphans` does not remove these standalone simulator containers. Use `./scripts/simulatorctl.sh purge`, or run `python3 scripts/preprod_validation.py --mode full-reset`, to get a truly clean local reset.

### Optional demo profile

If you just want the single compose-managed demo simulator, the stack also defines a `telemetry-simulator` service under the `demo` profile.

```bash
docker compose --profile demo up -d telemetry-simulator
```

That service uses the default device ID from the environment and is best for quick smoke tests, not for per-device simulation.

## Telemetry Contract

The simulator and firmware should publish JSON telemetry with numeric values only.

MQTT basics:

- Broker host in compose: `localhost` from the host, `emqx` inside containers
- Port: `1883`
- QoS: `1`
- Default subscription pattern in `data-service`: `devices/+/telemetry`
- Tenant-aware subscription also supported: `+/devices/+/telemetry`

Simulator topic format:

```text
<tenant_id>/devices/<device_id>/telemetry
```

Payload requirements:

- `device_id` must match the onboarded device
- `timestamp` must be UTC ISO-8601
- `schema_version` should be `v1`
- all measurement values must be numbers, not strings

Canonical field names:

- `voltage` in volts
- `current` in amperes
- `power` in watts
- `power_factor` from `0.0` to `1.0`
- `energy_kwh` as a cumulative meter reading when available

Common aliases accepted by the backend:

- current: `current_l1`, `current_l2`, `current_l3`, `phase_current`, `i_l1`
- voltage: `voltage_l1`, `voltage_l2`, `voltage_l3`, `v_l1`
- power factor: `pf`
- power: `active_power`, `kw`

Example payload:

```json
{
  "device_id": "COMPRESSOR-001",
  "timestamp": "2026-03-04T12:00:00Z",
  "schema_version": "v1",
  "voltage": 231.4,
  "current": 0.86,
  "power": 198.7,
  "power_factor": 0.98,
  "energy_kwh": 1245.337
}
```

## Simulator Reliability

The device simulator is designed to survive transient broker or session issues:

- reconnects with exponential backoff and jitter
- buffers telemetry while MQTT is unavailable
- flushes buffered messages after reconnect
- sends fallback heartbeats to `device-service` so runtime status can remain `running` while the simulator process is alive

## Verification

Useful checks after onboarding or telemetry changes:

```bash
./scripts/report_shift_overlap_conflicts.sh
```

For a manual telemetry smoke test, publish one sample message to the same topic your simulator uses:

```bash
mosquitto_pub -h localhost -p 1883 -t SH00000001/devices/COMPRESSOR-001/telemetry -m '{
  "device_id": "COMPRESSOR-001",
  "timestamp": "2026-03-04T12:00:00Z",
  "schema_version": "v1",
  "voltage": 230.8,
  "current": 0.88,
  "power": 203.0,
  "power_factor": 0.98
}'
```

After that, check the UI or your authenticated API client to confirm the device card and telemetry views update.

For the UI, run the hook-order and production build checks before shipping changes:

```bash
cd ui-web
npm run lint:hooks
npm run build
```

## Safety Notes

- Do not run `docker compose down -v` unless you intentionally want to remove the named volumes.
- The stack uses persistent volumes for MySQL, InfluxDB, MinIO, Prometheus, Alertmanager, and Grafana.
- If you change secrets or service URLs, keep `.env` and `docker-compose.yml` aligned.
- Migrations run automatically in the services that manage Alembic on startup.
