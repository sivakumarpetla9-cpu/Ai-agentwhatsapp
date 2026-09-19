#!/bin/sh
set -e

echo "=== WhatsApp Dine-In Ordering Platform Production Startup ==="

# 1. Run database migrations
echo "Applying database migrations (alembic upgrade head)..."
alembic upgrade head

# 2. Start Uvicorn ASGI server with dynamic port
PORT_TO_BIND="${PORT:-8000}"
echo "Starting Uvicorn server on 0.0.0.0:${PORT_TO_BIND}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT_TO_BIND}"
