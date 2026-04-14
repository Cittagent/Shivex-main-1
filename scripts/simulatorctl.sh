#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/simulatorctl.sh start [--tenant-id <TENANT_ID>] <DEVICE_ID> [PUBLISH_INTERVAL]
  ./scripts/simulatorctl.sh stop [--tenant-id <TENANT_ID>] <DEVICE_ID>
  ./scripts/simulatorctl.sh restart [--tenant-id <TENANT_ID>] <DEVICE_ID> [PUBLISH_INTERVAL]
  ./scripts/simulatorctl.sh status [--tenant-id <TENANT_ID>] [DEVICE_ID]
  ./scripts/simulatorctl.sh logs [--tenant-id <TENANT_ID>] <DEVICE_ID>
  ./scripts/simulatorctl.sh list
  ./scripts/simulatorctl.sh purge [--tenant-id <TENANT_ID>]

Examples:
  ./scripts/simulatorctl.sh start COMPRESSOR-001
  ./scripts/simulatorctl.sh start --tenant-id SH00000001 COMPRESSOR-001
  ./scripts/simulatorctl.sh start COMPRESSOR-002 2
  ./scripts/simulatorctl.sh stop COMPRESSOR-001
  ./scripts/simulatorctl.sh logs COMPRESSOR-002
  ./scripts/simulatorctl.sh purge
EOF
}

sanitize_identity_component() {
  local raw="$1"
  printf '%s' "${raw}" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9_.-' '-' | sed 's/^-//; s/-$//'
}

tenant_scope() {
  echo "${TENANT_ID:-}"
}

urlencode() {
  python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$1"
}

container_name_for_device() {
  local tenant_id="$1"
  local device_id="$2"
  local safe_tenant
  local safe_id
  safe_tenant="$(sanitize_identity_component "${tenant_id}")"
  safe_id="$(sanitize_identity_component "${device_id}")"
  echo "telemetry-simulator-${safe_tenant}-${safe_id}"
}

image_name() {
  cd "${ROOT_DIR}"
  local project
  project="$(docker compose config 2>/dev/null | sed -n 's/^name: //p' | head -n 1)"
  if [[ -z "${project}" ]]; then
    project="$(basename "${ROOT_DIR}" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9' '-')"
  fi
  echo "${project}-telemetry-simulator"
}

device_service_url() {
  echo "${DEVICE_SERVICE_URL:-http://localhost:8000}"
}

parse_simulator_args() {
  local allow_missing_device_id="${1:-false}"
  shift || true

  PARSED_TENANT_ID="$(tenant_scope)"
  PARSED_DEVICE_ID=""
  PARSED_INTERVAL=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --tenant-id|-t)
        [[ $# -ge 2 ]] || { echo "Missing value for $1"; return 1; }
        PARSED_TENANT_ID="$2"
        shift 2
        ;;
      --tenant-id=*|-t=*)
        PARSED_TENANT_ID="${1#*=}"
        shift
        ;;
      --)
        shift
        while [[ $# -gt 0 ]]; do
          if [[ -z "${PARSED_DEVICE_ID}" ]]; then
            PARSED_DEVICE_ID="$1"
          elif [[ -z "${PARSED_INTERVAL}" ]]; then
            PARSED_INTERVAL="$1"
          else
            echo "Unexpected extra argument: $1"
            return 1
          fi
          shift
        done
        break
        ;;
      -*)
        echo "Unknown option: $1"
        return 1
        ;;
      *)
        if [[ -z "${PARSED_DEVICE_ID}" ]]; then
          PARSED_DEVICE_ID="$1"
        elif [[ -z "${PARSED_INTERVAL}" ]]; then
          PARSED_INTERVAL="$1"
        else
          echo "Unexpected extra argument: $1"
          return 1
        fi
        shift
        ;;
    esac
  done

  if [[ -z "${PARSED_DEVICE_ID}" && "${allow_missing_device_id}" != "true" ]]; then
    echo "Missing DEVICE_ID"
    return 1
  fi
}

device_is_onboarded() {
  local tenant_id="$1"
  local device_id="$2"
  local url
  url="$(device_service_url)"
  curl -fsS \
    -H "X-Internal-Service: telemetry-simulator" \
    -H "X-Tenant-Id: ${tenant_id}" \
    "${url%/}/api/v1/devices/${device_id}" >/dev/null 2>&1
}

list_onboarded_devices() {
  local tenant_id="$1"
  local url
  url="$(device_service_url)"
  curl -fsS \
    -H "X-Internal-Service: telemetry-simulator" \
    -H "X-Tenant-Id: ${tenant_id}" \
    "${url%/}/api/v1/devices" 2>/dev/null \
    | python3 -c 'import json,sys
try:
    payload = json.load(sys.stdin)
except Exception:
    sys.exit(0)
items = payload.get("data", []) if isinstance(payload, dict) else []
for item in items:
    device_id = item.get("device_id")
    if device_id:
        print(device_id)'
}

network_name() {
  cd "${ROOT_DIR}"
  local project
  project="$(docker compose config 2>/dev/null | sed -n 's/^name: //p' | head -n 1)"
  if [[ -z "${project}" ]]; then
    project="$(basename "${ROOT_DIR}" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9' '-')"
  fi
  echo "${project}_energy-net"
}

ensure_image_built() {
  cd "${ROOT_DIR}"
  docker compose build telemetry-simulator >/dev/null
}

start_simulator() {
  local tenant_id="$1"
  local device_id="$2"
  local interval="${3:-5}"
  tenant_id="${tenant_id:-SH00000001}"
  local container_name
  local image
  local network

  container_name="$(container_name_for_device "${tenant_id}" "${device_id}")"
  image="$(image_name)"
  network="$(network_name)"

  if docker ps -a --format '{{.Names}}' | grep -Fxq "${container_name}"; then
    if docker ps --format '{{.Names}}' | grep -Fxq "${container_name}"; then
      echo "Simulator already running for ${tenant_id}/${device_id} (${container_name})"
      return 0
    fi
    docker start "${container_name}" >/dev/null
    docker update --restart unless-stopped "${container_name}" >/dev/null
    echo "Simulator restarted for ${tenant_id}/${device_id} (${container_name})"
    return 0
  fi

  if ! device_is_onboarded "${tenant_id}" "${device_id}"; then
    echo "Device ${tenant_id}/${device_id} is not onboarded in device-service."
    echo "Available onboarded devices:"
    list_onboarded_devices "${tenant_id}" | sed 's/^/  - /'
    return 1
  fi

  ensure_image_built
  if ! docker network inspect "${network}" >/dev/null 2>&1; then
    echo "Docker network ${network} is missing. Start the platform first: docker compose up -d"
    return 1
  fi

  docker run -d \
    --name "${container_name}" \
    --network "${network}" \
    --restart unless-stopped \
    --label "factoryops.tenant_id=${tenant_id}" \
    --label "factoryops.device_id=${device_id}" \
    -e DEVICE_ID="${device_id}" \
    -e TENANT_ID="${tenant_id}" \
    -e PUBLISH_INTERVAL="${interval}" \
    -e MQTT_BROKER_HOST="emqx" \
    -e MQTT_BROKER_PORT="1883" \
    -e DEVICE_SERVICE_URL="http://device-service:8000" \
    "${image}" >/dev/null

  echo "Simulator started for ${tenant_id}/${device_id} (${container_name})"
}

stop_simulator() {
  local tenant_id="$1"
  local device_id="$2"
  tenant_id="${tenant_id:-SH00000001}"
  local container_name
  container_name="$(container_name_for_device "${tenant_id}" "${device_id}")"

  if ! docker ps -a --format '{{.Names}}' | grep -Fxq "${container_name}"; then
    echo "No simulator container found for ${tenant_id}/${device_id}"
    return 0
  fi

  docker stop "${container_name}" >/dev/null || true
  echo "Simulator stopped for ${tenant_id}/${device_id} (${container_name})"
}

show_status() {
  local tenant_id="$1"
  local maybe_device_id="${2:-}"
  if [[ -n "${maybe_device_id}" ]]; then
    tenant_id="${tenant_id:-SH00000001}"
    local container_name
    container_name="$(container_name_for_device "${tenant_id}" "${maybe_device_id}")"
    docker ps -a \
      --filter "name=^/${container_name}$" \
      --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'
    return 0
  fi

  if [[ -n "${tenant_id}" ]]; then
    docker ps -a \
      --filter "label=factoryops.tenant_id=${tenant_id}" \
      --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'
  else
    docker ps -a \
      --filter "name=^/telemetry-simulator-" \
      --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'
  fi
}

show_logs() {
  local tenant_id="$1"
  local device_id="$2"
  local container_name
  container_name="$(container_name_for_device "${tenant_id}" "${device_id}")"
  docker logs -f "${container_name}"
}

list_simulators() {
  local tenant_id="${1:-}"
  if [[ -n "${tenant_id}" ]]; then
    docker ps -a \
      --filter "label=factoryops.tenant_id=${tenant_id}" \
      --format 'table {{.Names}}\t{{.Status}}\t{{.RunningFor}}'
  else
    docker ps -a \
      --filter "name=^/telemetry-simulator-" \
      --format 'table {{.Names}}\t{{.Status}}\t{{.RunningFor}}'
  fi
}

purge_simulators() {
  local tenant_id="${1:-}"
  local containers=""

  if [[ -n "${tenant_id}" ]]; then
    containers="$(docker ps -aq --filter "label=factoryops.tenant_id=${tenant_id}")"
  else
    containers="$(docker ps -aq --filter "name=^/telemetry-simulator-")"
  fi

  if [[ -z "${containers}" ]]; then
    if [[ -n "${tenant_id}" ]]; then
      echo "No simulator containers found for tenant ${tenant_id}"
    else
      echo "No simulator containers found"
    fi
    return 0
  fi

  docker rm -f ${containers} >/dev/null
  if [[ -n "${tenant_id}" ]]; then
    echo "Purged simulator containers for tenant ${tenant_id}"
  else
    echo "Purged all simulator containers"
  fi
}

main() {
  if [[ $# -lt 1 ]]; then
    usage
    exit 1
  fi

  local command="$1"
  shift
  local tenant_id
  local device_id
  local interval

  if [[ "${command}" == "list" ]]; then
    list_simulators "${TENANT_ID:-}"
    exit 0
  fi

  if [[ "${command}" == "purge" ]]; then
    if ! parse_simulator_args true "$@"; then
      usage
      exit 1
    fi
    purge_simulators "${PARSED_TENANT_ID}"
    exit 0
  fi

  if [[ "${command}" == "status" ]]; then
    if ! parse_simulator_args true "$@"; then
      usage
      exit 1
    fi
  else
    if ! parse_simulator_args false "$@"; then
      usage
      exit 1
    fi
  fi

  if [[ "${command}" != "status" && -z "${PARSED_TENANT_ID}" ]]; then
    PARSED_TENANT_ID="SH00000001"
  fi

  if [[ "${command}" == "status" && -z "${PARSED_TENANT_ID}" && -z "${PARSED_DEVICE_ID}" ]]; then
    tenant_id=""
  else
    tenant_id="${PARSED_TENANT_ID}"
  fi

  if [[ "${command}" != "status" && -z "${PARSED_DEVICE_ID}" ]]; then
    usage
    exit 1
  fi

  device_id="${PARSED_DEVICE_ID}"
  interval="${PARSED_INTERVAL:-5}"

  case "${command}" in
    start)
      start_simulator "${tenant_id}" "${device_id}" "${interval}"
      ;;
    stop)
      stop_simulator "${tenant_id}" "${device_id}"
      ;;
    restart)
      stop_simulator "${tenant_id}" "${device_id}"
      start_simulator "${tenant_id}" "${device_id}" "${interval}"
      ;;
    status)
      show_status "${tenant_id}" "${device_id}"
      ;;
    logs)
      show_logs "${tenant_id}" "${device_id}"
      ;;
    *)
      usage
      exit 1
      ;;
  esac
}

main "$@"
