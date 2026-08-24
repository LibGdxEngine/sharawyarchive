#!/usr/bin/env bash
# Run the ingestion pipeline from the host against the docker-compose services.
#
# Usage: scripts/pipeline_local.sh --folder "data/CD-1/001 alfat7a" --surah 1 --until index
#
# CO_API_KEY comes from the gitignored .env.local; DB/Meili/MinIO endpoints come
# from pipeline.django_setup defaults + .env.dev (already localhost). Must run
# from the repo root: ingest records relative local paths.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a
[ -f .env.local ] && source .env.local
set +a
# .env.local also carries the R2 keys under AUDIO_S3_*, which local MinIO
# rejects. A dev run writes to MinIO (sync_storage_to_r2 pushes to R2 later);
# PIPELINE_STORAGE=r2 keeps the sourced R2 credentials and endpoint instead.
if [ "${PIPELINE_STORAGE:-minio}" != r2 ]; then
  export AUDIO_S3_ENDPOINT_URL=http://localhost:9000 \
    AUDIO_S3_ACCESS_KEY_ID=minioadmin AUDIO_S3_SECRET_ACCESS_KEY=minioadmin
  unset AUDIO_PUBLIC_ENDPOINT_URL
else
  : "${AUDIO_S3_ENDPOINT_URL:?PIPELINE_STORAGE=r2 needs AUDIO_S3_ENDPOINT_URL}"
fi
export ASR_BACKEND="${ASR_BACKEND:-cohere}" ALIGNER_BACKEND="${ALIGNER_BACKEND:-ctc}"
exec .venv/bin/python -m pipeline.run \
  --source-title "تفسير الشعراوي — المجموعة الكاملة" --kind khawatir "$@"
