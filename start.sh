#!/bin/sh
set -e

PORT="${PORT:-10000}"

if [ "$SERVICE_TYPE" = "worker" ]; then
  echo "Starting ARQ worker service..."
  echo "Binding HTTP dummy health listener on port ${PORT} for Render..."
  python -m http.server "${PORT}" &
  HTTP_PID=$!

  cleanup() {
    echo "Stopping worker processes..."
    kill "${HTTP_PID}" 2>/dev/null || true
  }
  trap cleanup INT TERM EXIT

  echo "Running ARQ worker..."
  exec python -m arq app.workers.settings.WorkerSettings
else
  echo "Starting FastAPI server on port ${PORT}..."
  exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}"
fi