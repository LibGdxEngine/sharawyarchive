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
export ASR_BACKEND="${ASR_BACKEND:-cohere}" ALIGNER_BACKEND="${ALIGNER_BACKEND:-ctc}"
exec .venv/bin/python -m pipeline.run \
  --source-title "تفسير الشعراوي — المجموعة الكاملة" --kind khawatir "$@"
