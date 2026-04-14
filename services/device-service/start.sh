#!/bin/sh
set -e

echo "Running device-service migration guard..."
python scripts/migration_guard.py

echo "Starting device-service..."
exec uvicorn app:app --host 0.0.0.0 --port 8000
