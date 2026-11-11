#!/usr/bin/env bash
# Back up PostgreSQL and uploaded screenshots.
# Usage: ./backup.sh            (keeps 7 days by default)
#        KEEP_DAYS=30 ./backup.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/min-ledger}"
BACKUP_DIR="${BACKUP_DIR:-${APP_DIR}/backups}"
KEEP_DAYS="${KEEP_DAYS:-7}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"

cd "$APP_DIR"

if [ ! -f .env ]; then
  echo "missing ${APP_DIR}/.env" >&2
  exit 1
fi

get_env() {
  # tolerate a UTF-8 BOM and CRLF line endings
  tr -d '\357\273\277' < .env | grep -E "^$1=" | tail -n 1 | cut -d= -f2- | tr -d '\r' || true
}
POSTGRES_USER="${POSTGRES_USER:-$(get_env POSTGRES_USER)}"
POSTGRES_DB="${POSTGRES_DB:-$(get_env POSTGRES_DB)}"
POSTGRES_USER="${POSTGRES_USER:-ledger}"
POSTGRES_DB="${POSTGRES_DB:-ledger}"

compose() {
  docker compose -f "$COMPOSE_FILE" "$@"
}

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
DB_FILE="${BACKUP_DIR}/db-${STAMP}.sql.gz"
UPLOADS_FILE="${BACKUP_DIR}/uploads-${STAMP}.tar.gz"

echo "==> dumping database"
if ! compose exec -T db pg_dump -U "${POSTGRES_USER}" "${POSTGRES_DB}" | gzip > "$DB_FILE"; then
  rm -f "$DB_FILE"
  echo "!! database dump failed" >&2
  exit 1
fi

echo "==> archiving uploads"
if ! compose exec -T backend tar czf - -C /app/data/uploads . > "$UPLOADS_FILE"; then
  rm -f "$UPLOADS_FILE" "$DB_FILE"
  echo "!! uploads archive failed" >&2
  exit 1
fi

echo "==> pruning backups older than ${KEEP_DAYS} days"
find "$BACKUP_DIR" -type f -mtime +"${KEEP_DAYS}" -delete

ls -lh "$BACKUP_DIR" | tail -n 5
echo "==> backup done: ${BACKUP_DIR}"
