#!/bin/sh
set -e

echo "Running energy-service migration guard..."
python scripts/migration_guard.py

echo "Starting energy-service..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8010
