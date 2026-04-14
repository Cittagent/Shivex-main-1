#!/bin/bash
set -e

echo "[auth-service] Running migration guard..."
python scripts/migration_guard.py

LOG_LEVEL_LOWER="$(printf '%s' "${LOG_LEVEL:-info}" | tr '[:upper:]' '[:lower:]')"
echo "[auth-service] Starting Uvicorn on ${SERVICE_HOST:-0.0.0.0}:${SERVICE_PORT:-8090}..."
exec uvicorn app.main:app \
    --host "${SERVICE_HOST:-0.0.0.0}" \
    --port "${SERVICE_PORT:-8090}" \
    --log-level "${LOG_LEVEL_LOWER}"
