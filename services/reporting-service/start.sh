#!/bin/sh
set -e

echo "Running reporting-service migration guard..."
python scripts/migration_guard.py

echo "Starting reporting-service..."
if [ "${APP_ROLE:-api}" = "worker" ]; then
  exec python -m src.worker_main
fi

exec uvicorn src.main:app --host 0.0.0.0 --port 8085
