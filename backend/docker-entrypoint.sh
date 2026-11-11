#!/bin/sh
set -eu

echo "[entrypoint] running database migrations"
alembic upgrade head

echo "[entrypoint] starting api"
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --workers "${WEB_WORKERS:-1}" \
    --proxy-headers \
    --forwarded-allow-ips='*'
