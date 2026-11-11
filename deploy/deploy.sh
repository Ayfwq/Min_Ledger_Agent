#!/usr/bin/env bash
# Runs on the target server (invoked by GitHub Actions or manually).
# Usage: ./deploy.sh <image-tag>
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/min-ledger}"
TAG="${1:-latest}"
REGISTRY="${REGISTRY:-ghcr.io}"
IMAGE_OWNER="${IMAGE_OWNER:-ayfwq}"
HTTP_PORT="${HTTP_PORT:-80}"

cd "$APP_DIR"

BACKEND_IMAGE="${REGISTRY}/${IMAGE_OWNER}/min-ledger-backend:${TAG}"
WEB_IMAGE="${REGISTRY}/${IMAGE_OWNER}/min-ledger-web:${TAG}"
export BACKEND_IMAGE WEB_IMAGE

if [ ! -f .env ]; then
  echo "missing $APP_DIR/.env (copy deploy/.env.example and fill it in)" >&2
  exit 1
fi

echo "==> deploying tag: ${TAG}"

wait_health() {
  for _ in $(seq 1 "${HEALTH_ATTEMPTS:-40}"); do
    if curl -fsS "http://127.0.0.1:${HTTP_PORT}/api/v1/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 3
  done
  return 1
}

rollback() {
  echo "!! deployment unhealthy, attempting rollback" >&2
  docker compose logs --tail=120 backend >&2 || true

  if [ ! -f .last_good_tag ]; then
    echo "!! no previous good tag recorded; manual intervention required" >&2
    return 1
  fi

  PREV="$(cat .last_good_tag)"
  if [ -z "$PREV" ] || [ "$PREV" = "$TAG" ]; then
    echo "!! previous tag is '${PREV:-<empty>}', nothing to roll back to" >&2
    return 1
  fi

  echo "==> rolling back to ${PREV}"
  export BACKEND_IMAGE="${REGISTRY}/${IMAGE_OWNER}/min-ledger-backend:${PREV}"
  export WEB_IMAGE="${REGISTRY}/${IMAGE_OWNER}/min-ledger-web:${PREV}"
  if docker compose up -d --remove-orphans && wait_health; then
    echo "==> rollback healthy (${PREV})" >&2
    return 0
  fi
  echo "!! rollback also unhealthy" >&2
  return 1
}

echo "==> pulling images"
if [ "${SKIP_PULL:-0}" = "1" ]; then
  echo "==> SKIP_PULL=1, using local images"
else
  if ! docker compose pull; then
    echo "!! docker compose pull failed, keeping current containers" >&2
    exit 1
  fi
fi

echo "==> starting containers"
if ! docker compose up -d --remove-orphans; then
  rollback || true
  exit 1
fi

echo "==> waiting for health check"
if wait_health; then
  echo "$TAG" > .last_good_tag
  docker image prune -f >/dev/null 2>&1 || true
  echo "==> health: $(curl -fsS "http://127.0.0.1:${HTTP_PORT}/api/v1/health" || true)"
  echo "==> deploy succeeded (${TAG})"
  exit 0
fi

rollback || true
exit 1
