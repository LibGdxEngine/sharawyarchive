#!/usr/bin/env bash
# Upload the raw corpus MP3s to R2 from the host.
#
# Usage: scripts/upload_r2_local.sh [--dry-run|--limit N|--verify-only|...]
#
# R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY come from the gitignored .env.local.
# Must run from the repo root: the default --data-root and checkpoint/mapping
# paths are relative.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a
[ -f .env.local ] && source .env.local
set +a
exec .venv/bin/python -m pipeline.upload_r2 "$@"
