#!/bin/sh
set -e

PORT="${PORT:-10000}"

echo "Starting FastAPI server on port ${PORT}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}"