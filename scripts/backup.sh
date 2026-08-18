#!/usr/bin/env bash
# Nightly Postgres backup to S3-compatible storage (Cloudflare R2 in prod).
#
# Usage: scripts/backup.sh [compose-file]
# Env:   DB_NAME DB_USER (defaults postgres/postgres)
#        BACKUP_S3_ENDPOINT_URL BACKUP_S3_BUCKET BACKUP_S3_ACCESS_KEY_ID
#        BACKUP_S3_SECRET_ACCESS_KEY (falls back to AUDIO_S3_* when unset)
#        BACKUP_KEEP_DAYS (default 30)
#
# Cron example (nightly at 03:15):
#   15 3 * * * cd /srv/shaarawy && ./scripts/backup.sh docker-compose.prod.yml >> /var/log/shaarawy-backup.log 2>&1
set -euo pipefail

COMPOSE_FILE="${1:-docker-compose.prod.yml}"
DB_NAME="${DB_NAME:-postgres}"
DB_USER="${DB_USER:-postgres}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="/tmp/shaarawy-${DB_NAME}-${STAMP}.dump"

ENDPOINT="${BACKUP_S3_ENDPOINT_URL:-${AUDIO_S3_ENDPOINT_URL:?set BACKUP_S3_ENDPOINT_URL}}"
BUCKET="${BACKUP_S3_BUCKET:-${AUDIO_S3_BUCKET:-shaarawy}}"
export AWS_ACCESS_KEY_ID="${BACKUP_S3_ACCESS_KEY_ID:-${AUDIO_S3_ACCESS_KEY_ID:?set BACKUP_S3_ACCESS_KEY_ID}}"
export AWS_SECRET_ACCESS_KEY="${BACKUP_S3_SECRET_ACCESS_KEY:-${AUDIO_S3_SECRET_ACCESS_KEY:?set BACKUP_S3_SECRET_ACCESS_KEY}}"

echo "[backup] pg_dump ${DB_NAME} @ ${STAMP}"
docker compose -f "${COMPOSE_FILE}" exec -T db \
  pg_dump -U "${DB_USER}" -d "${DB_NAME}" --format=custom --no-owner > "${OUT}"
test -s "${OUT}"

KEY="backups/postgres/${DB_NAME}-${STAMP}.dump"
echo "[backup] upload s3://${BUCKET}/${KEY} ($(du -h "${OUT}" | cut -f1))"
aws s3 cp --endpoint-url "${ENDPOINT}" "${OUT}" "s3://${BUCKET}/${KEY}" --only-show-errors
rm -f "${OUT}"

# Prune backups older than BACKUP_KEEP_DAYS
KEEP_DAYS="${BACKUP_KEEP_DAYS:-30}"
CUTOFF="$(date -u -d "-${KEEP_DAYS} days" +%Y%m%dT%H%M%SZ)"
aws s3 ls --endpoint-url "${ENDPOINT}" "s3://${BUCKET}/backups/postgres/" | awk '{print $4}' | while read -r f; do
  ts="${f##*-}"; ts="${ts%.dump}"
  if [[ -n "${ts}" && "${ts}" < "${CUTOFF}" ]]; then
    echo "[backup] prune ${f}"
    aws s3 rm --endpoint-url "${ENDPOINT}" "s3://${BUCKET}/backups/postgres/${f}" --only-show-errors
  fi
done
echo "[backup] done"
