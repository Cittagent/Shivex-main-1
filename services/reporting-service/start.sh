#!/bin/sh
set -e

echo "Running reporting-service migration guard..."
python scripts/migration_guard.py

echo "Starting reporting-service..."
exec uvicorn src.main:app --host 0.0.0.0 --port 8085
