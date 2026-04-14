#!/bin/sh
set -e

echo "Running rule-engine migration guard..."
python scripts/migration_guard.py

echo "Starting rule-engine service..."
exec uvicorn app:app --host 0.0.0.0 --port 8002
