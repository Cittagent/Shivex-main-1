#!/bin/sh
set -e

echo "Running waste-analysis-service migration guard..."
python scripts/migration_guard.py

echo "Starting waste-analysis-service..."
exec uvicorn src.main:app --host 0.0.0.0 --port 8087
