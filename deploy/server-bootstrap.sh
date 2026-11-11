#!/usr/bin/env bash
# One-time server preparation. Run as root (or a user with sudo).
#
#   scp deploy/server-bootstrap.sh deploy/.env.example user@server:/tmp/
#   ssh user@server 'sudo bash /tmp/server-bootstrap.sh'
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/min-ledger}"
HTTP_PORT="${HTTP_PORT:-80}"
ENV_TEMPLATE="${ENV_TEMPLATE:-/tmp/.env.example}"

if ! command -v docker >/dev/null 2>&1; then
  echo "==> installing docker"
  curl -fsSL https://get.docker.com | sh
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "==> installing docker compose plugin"
  apt-get update
  apt-get install -y docker-compose-plugin
fi

# Allow the (sudo) login user to run docker without sudo.
if [ -n "${SUDO_USER:-}" ] && [ "${SUDO_USER}" != "root" ]; then
  if ! id -nG "${SUDO_USER}" | grep -qw docker; then
    usermod -aG docker "${SUDO_USER}"
    echo "==> added ${SUDO_USER} to the docker group (re-login to take effect)"
  fi
fi

echo "==> creating ${APP_DIR}"
mkdir -p "${APP_DIR}"

if [ ! -f "${APP_DIR}/.env" ]; then
  if [ -f "${ENV_TEMPLATE}" ]; then
    cp "${ENV_TEMPLATE}" "${APP_DIR}/.env"
    echo "==> .env created from ${ENV_TEMPLATE}"
  else
    cat > "${APP_DIR}/.env" <<'EOF'
POSTGRES_USER=ledger
POSTGRES_PASSWORD=change-me
POSTGRES_DB=ledger
HTTP_PORT=80
SILICONFLOW_API_KEY=
SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1
LLM_TEXT_MODEL=deepseek-ai/DeepSeek-V3.2
LLM_VISION_MODEL=Qwen/Qwen3-VL-32B-Instruct
APP_ENV=prod
APP_PASSWORD=
ALLOWED_ORIGINS=
WORKER_ENABLED=true
TIMEZONE=Asia/Shanghai
EOF
    echo "==> .env created with placeholders"
  fi
fi

chmod 600 "${APP_DIR}/.env" || true

if command -v ufw >/dev/null 2>&1; then
  ufw allow "${HTTP_PORT}/tcp" || true
  ufw allow 443/tcp || true
fi

cat <<EOF

Done. Next steps:
  1. edit ${APP_DIR}/.env (database password, SiliconFlow key, access password)
  2. add GitHub secrets: SSH_HOST / SSH_USER / SSH_KEY (or SSH_PASSWORD) / SSH_PORT
  3. push to main (or run the Deploy workflow manually)

EOF
