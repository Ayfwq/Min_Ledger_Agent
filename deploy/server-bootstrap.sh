#!/usr/bin/env bash
# One-time server preparation. Run as root (or a user with sudo).
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/min-ledger}"
HTTP_PORT="${HTTP_PORT:-80}"

if ! command -v docker >/dev/null 2>&1; then
  echo "==> installing docker"
  curl -fsSL https://get.docker.com | sh
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "==> installing docker compose plugin"
  apt-get update
  apt-get install -y docker-compose-plugin
fi

echo "==> creating ${APP_DIR}"
mkdir -p "${APP_DIR}"
cd "${APP_DIR}"

if [ ! -f .env ]; then
  cp .env.example .env 2>/dev/null || true
  echo "!! please edit ${APP_DIR}/.env (database password, SiliconFlow key, access password)"
fi

if command -v ufw >/dev/null 2>&1; then
  ufw allow "${HTTP_PORT}/tcp" || true
  ufw allow 443/tcp || true
fi

cat <<EOF

Done. Next steps:
  1. edit ${APP_DIR}/.env
  2. configure GitHub secrets: SSH_HOST / SSH_USER / SSH_KEY / SSH_PORT
  3. push to main to trigger the deploy workflow

EOF
