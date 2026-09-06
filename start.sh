#!/bin/sh
set -e

echo "Starting ARQ background worker..."
python -m arq app.workers.settings.WorkerSettings &

echo "Starting Uvicorn API server on port ${PORT:-10000}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-10000}"