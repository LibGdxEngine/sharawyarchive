# Smart search («بحث ذكي») — working notes

Phase-by-phase documentation for the two-mode search work. One phase = one branch = one PR.

| Phase | Document | Branch |
|---|---|---|
| 0 — Audit | [audit.md](audit.md) | `smart/phase-0-audit` |
| 1 — Foundation (settings, OpenRouter client, schemas, prompts, `SmartQuery`) | [phase-1.md](phase-1.md) | `smart/phase-1-foundation` |
| 2 — Retrieval (`Passage` table, build/embed commands, hybrid retrieval) | [phase-2.md](phase-2.md) | `smart/phase-2-retrieval` |
| 2b — Exact-mode tweaks (`light_stem`, `text_stem`, quotes) | [phase-2b.md](phase-2b.md) | `smart/phase-2b-exact-mode` |
| 3 — Plan, rerank, context | `phase-3.md` | `smart/phase-3-plan-rerank-context` |
| 4 — Generate, verify, API | `phase-4.md` | `smart/phase-4-generate-verify-api` |
| 5 — Frontend | `phase-5.md` | `smart/phase-5-frontend` |
| 6 — Eval and tuning | `phase-6.md` + `eval-<YYYY-MM-DD>.json` | `smart/phase-6-eval` |
| 7 — Streaming and prod | `phase-7.md` | `smart/phase-7-streaming` |

Evaluation reports are committed here as `eval-<YYYY-MM-DD>[-label].json` (ids and numbers only, no
passage text) so regressions stay visible in diffs.

## Running the backend tests on the production host

The host has no virtualenv and no system Django, and the live stack must never be pointed at by tests.
Use a throwaway Docker network:

```bash
docker network create shaarawy_tmptest
docker run -d --name shaarawy_tmp_testdb --network shaarawy_tmptest \
  -e POSTGRES_PASSWORD=postgres -e POSTGRES_USER=postgres -e POSTGRES_DB=postgres pgvector/pgvector:pg16
docker run -d --name shaarawy_tmp_redis --network shaarawy_tmptest redis:7-alpine
docker run -d --name shaarawy_tmp_meili --network shaarawy_tmptest \
  -e MEILI_MASTER_KEY=devmasterkey -e MEILI_ENV=development getmeili/meilisearch:v1.15

docker build -t shaarawy-tmp-test -f - backend <<'DOCKERFILE'
FROM sharawyarchive-backend
USER root
COPY requirements.txt requirements-dev.txt /tmp/req/
RUN pip install --no-cache-dir -r /tmp/req/requirements-dev.txt
DOCKERFILE

docker run --rm --network shaarawy_tmptest -v "$PWD/backend:/app" -w /app --entrypoint /bin/sh \
  -e DJANGO_SETTINGS_MODULE=core.settings.dev \
  -e DB_HOST=shaarawy_tmp_testdb -e DB_PORT=5432 -e DB_NAME=postgres -e DB_USER=postgres -e DB_PASSWORD=postgres \
  -e CACHE_REDIS_URL=redis://shaarawy_tmp_redis:6379/2 \
  -e MEILI_URL=http://shaarawy_tmp_meili:7700 -e MEILI_MASTER_KEY=devmasterkey \
  shaarawy-tmp-test -c "python -m pytest search corpus api quran -q"
```

`--entrypoint /bin/sh` is required (the image entrypoint migrates and runs `index_quran`). The `clips`
suite additionally needs ffmpeg + MinIO. Frontend checks run natively: `npm run test -- --run`,
`npx tsc --noEmit`, `npm run lint`, `npm run build`.
