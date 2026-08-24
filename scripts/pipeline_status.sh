#!/usr/bin/env bash
# Progress of a corpus run, from the database (the log is not the source of truth).
#
# Usage: scripts/pipeline_status.sh [since-UTC-timestamp]
#   defaults to the start recorded by the last pipeline_corpus.sh launch
#   (.omc/logs/corpus-run-start.txt) or the last 24 hours.
set -euo pipefail
cd "$(dirname "$0")/.."
SINCE="${1:-$(cat .omc/logs/corpus-run-start.txt 2>/dev/null || date -u -d '-24 hours' +%FT%TZ)}"
psql() { docker compose exec -T db psql -U "${DB_USER:-postgres}" -d "${DB_NAME:-postgres}" -v ON_ERROR_STOP=1 "$@"; }

echo "since ${SINCE}  now $(date -u +%FT%TZ)  pipeline: $(pgrep -f 'python -m pipeline[.]run' >/dev/null && echo running || echo stopped)"
psql -tA -F ' ' <<SQL
SELECT 'segments:', string_agg(status||'='||n, '  ' ORDER BY status)
FROM (SELECT status, count(*) AS n FROM corpus_segment GROUP BY status) t;
SELECT 'this run:', 'done='||count(*),
       'audio_h='||round(sum(s.duration_ms)/3600000.0, 1),
       'wall_h='||round(extract(epoch FROM (now() - '${SINCE}'::timestamptz))/3600.0, 1),
       'ratio='||round(extract(epoch FROM (now() - '${SINCE}'::timestamptz)) / greatest(sum(s.duration_ms)/1000.0, 1), 2)
FROM corpus_pipelinerun p JOIN corpus_segment s ON s.id = p.segment_id
WHERE p.started_at > '${SINCE}' AND p.stage = 'index_segment' AND p.status = 'completed';
SELECT 'remaining:', 'pending='||count(*), 'audio_h='||round(coalesce(sum(duration_ms), 0)/3600000.0, 1)
FROM corpus_segment WHERE status IN ('pending', 'failed');
SELECT 'failures this run:', coalesce(string_agg(stage||'='||n, '  '), 'none')
FROM (SELECT stage, count(*) AS n FROM corpus_pipelinerun
      WHERE started_at > '${SINCE}' AND status = 'failed' GROUP BY stage) t;
SQL
echo "disk free: $(df -h --output=avail / | tail -1 | tr -d ' ')   AC: $(cat /sys/class/power_supply/ADP0/online 2>/dev/null || echo '?')"
