#!/usr/bin/env bash
# Restore a Postgres backup produced by scripts/backup.sh.
#
# Usage:
#   scripts/restore.sh <dump-file-or-s3-key> [target-db] [compose-file]
#
# Examples:
#   scripts/restore.sh backups/postgres/postgres-20260818T031500Z.dump           # fetch from S3, restore into $DB_NAME
#   scripts/restore.sh /tmp/x.dump restore_check docker-compose.yml              # local file into throwaway db
#
# Restoring into a throwaway database first (and checking row counts) is the
# supported way to verify a backup; see DEPLOY.md.
set -euo pipefail

SRC="${1:?usage: restore.sh <dump-file-or-s3-key> [target-db] [compose-file]}"
TARGET_DB="${2:-${DB_NAME:-postgres}}"
COMPOSE_FILE="${3:-docker-compose.prod.yml}"
DB_USER="${DB_USER:-postgres}"

DUMP="${SRC}"
if [[ ! -f "${SRC}" ]]; then
  ENDPOINT="${BACKUP_S3_ENDPOINT_URL:-${AUDIO_S3_ENDPOINT_URL:?set BACKUP_S3_ENDPOINT_URL}}"
  BUCKET="${BACKUP_S3_BUCKET:-${AUDIO_S3_BUCKET:-shaarawy}}"
  export AWS_ACCESS_KEY_ID="${BACKUP_S3_ACCESS_KEY_ID:-${AUDIO_S3_ACCESS_KEY_ID:?}}"
  export AWS_SECRET_ACCESS_KEY="${BACKUP_S3_SECRET_ACCESS_KEY:-${AUDIO_S3_SECRET_ACCESS_KEY:?}}"
  DUMP="/tmp/$(basename "${SRC}")"
  echo "[restore] fetch s3://${BUCKET}/${SRC}"
  aws s3 cp --endpoint-url "${ENDPOINT}" "s3://${BUCKET}/${SRC}" "${DUMP}" --only-show-errors
fi
test -s "${DUMP}"

echo "[restore] recreate database ${TARGET_DB}"
docker compose -f "${COMPOSE_FILE}" exec -T db \
  psql -U "${DB_USER}" -d postgres -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE IF EXISTS ${TARGET_DB} WITH (FORCE);" \
  -c "CREATE DATABASE ${TARGET_DB};"

echo "[restore] pg_restore into ${TARGET_DB}"
docker compose -f "${COMPOSE_FILE}" exec -T db \
  pg_restore -U "${DB_USER}" -d "${TARGET_DB}" --no-owner --exit-on-error < "${DUMP}"

echo "[restore] sanity"
docker compose -f "${COMPOSE_FILE}" exec -T db \
  psql -U "${DB_USER}" -d "${TARGET_DB}" -tAc \
  "SELECT 'surahs='||count(*) FROM quran_surah UNION ALL SELECT 'ayahs='||count(*) FROM quran_ayah;"
echo "[restore] done -> ${TARGET_DB}"
