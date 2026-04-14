#!/bin/sh
set -e

echo "Running analytics-service migration guard..."
python scripts/migration_guard.py

echo "Starting analytics-service..."
if [ "${APP_ROLE:-api}" = "worker" ]; then
  exec python -m src.worker_main
fi

exec uvicorn src.main:app --host 0.0.0.0 --port 8003
