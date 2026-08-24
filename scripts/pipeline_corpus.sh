#!/usr/bin/env bash
# Run the full 11-CD corpus through the pipeline, one CD folder at a time.
#
# Usage: scripts/pipeline_corpus.sh [CD-folder ...]      (default: data/CD-1 … data/CD-11)
#   nohup scripts/pipeline_corpus.sh > corpus-run.log 2>&1 &
#
# Every stage is resumable (pipeline/stages.py: transcribe skips when a
# Transcript exists, align when words exist, …), so re-running this script is
# also the retry mechanism for segments that ended up `failed`. Each CD prints
# its own processed/skipped/failed summary line, which is the progress marker.
set -uo pipefail
cd "$(dirname "$0")/.."

folders=("$@")
if [ ${#folders[@]} -eq 0 ]; then
  for n in $(seq 1 11); do folders+=("data/CD-$n"); done
fi

rc=0
for folder in "${folders[@]}"; do
  echo "=== $folder start $(date -u +%FT%TZ) free=$(df -h --output=avail / | tail -1 | tr -d ' ')"
  scripts/pipeline_local.sh --folder "$folder" --until index || rc=1
  echo "=== $folder end   $(date -u +%FT%TZ)"
done
echo "=== all folders done $(date -u +%FT%TZ) rc=$rc"
exit $rc
