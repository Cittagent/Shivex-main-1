# Device Simulator for Energy Intelligence Platform

Production-grade MQTT device simulator for generating realistic telemetry data.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run simulator
python main.py --device-id D1 --tenant-id SH00000001 --interval 5

# Same as above, using an explicit Shivex tenant ID
python main.py --device-id D1 --tenant-id SH00000001 --interval 5

# With custom broker
python main.py --device-id D1 --interval 5 --broker localhost --port 1883

# With fault injection
python main.py --device-id D1 --interval 5 --fault-mode overheating

# With fallback heartbeat (keeps runtime status alive during MQTT outages)
python main.py --device-id D1 --device-service-url http://localhost:8000 --heartbeat-interval 20
```

## CLI Options

- `--device-id`: Device identifier (required)
- `--tenant-id` / `--tenant-id`: Tenant identifier used in MQTT topic (default: `SH00000001`)
- `--interval`: Publish interval in seconds (default: 5)
- `--broker`: MQTT broker host (default: localhost)
- `--port`: MQTT broker port (default: 1883)
- `--fault-mode`: Fault injection mode - 'none', 'spike', 'drop', 'overheating' (default: none)
- `--log-level`: Logging level (default: INFO)
- `--device-service-url`: Device Service URL used for heartbeat fallback (default: `http://device-service:8000`)
- `--heartbeat-interval`: Heartbeat fallback interval in seconds (default: `20`)

Heartbeat fallback and onboarding checks are tenant-aware. The simulator publishes to:

```text
<tenant_id>/devices/<device_id>/telemetry
```

## CSV Replay

Replay an exported telemetry CSV through the same MQTT ingestion path:

```bash
python csv_replay.py \
  --csv /path/to/td00000001.csv \
  --device-id TD00000002 \
  --tenant-id SH00000001 \
  --broker localhost \
  --port 1883
```

The replay utility:

- skips Influx export metadata rows that begin with `#`
- preserves the original `_time` timestamp in each published payload
- sleeps for the original row-to-row gap before publishing the next sample
- publishes to `<tenant_id>/devices/<device_id>/telemetry`

To seed historical data quickly while keeping the original payload timestamps intact:

```bash
python csv_replay.py \
  --csv /path/to/td00000001.csv \
  --device-id TD00000002 \
  --tenant-id SH00000001 \
  --broker localhost \
  --port 1883 \
  --no-delay
```

## Telemetry Schema

```json
{
  "device_id": "D1",
  "timestamp": "2026-02-07T11:26:00Z",
  "schema_version": "v1",
  "voltage": 230.5,
  "current": 0.85,
  "power": 195.9,
  "temperature": 45.2
}
```

## Features

- Realistic time-series data generation with smooth variation and noise
- MQTT QoS 1 publishing with automatic reconnect
- Exponential backoff + jitter for reconnection (no retry cap)
- Buffered replay of telemetry after reconnect
- Heartbeat fallback to `device-service` during broker/session disruption
- Graceful shutdown handling
- Structured JSON logging
- Multiple fault injection modes
- Production-ready error handling
