# Deploying the Sha'rawy Archive

Cold deploy on a clean Linux host with Docker + Compose v2 and the `aws` CLI.

## 1. Prepare

```bash
git clone <repo> /srv/shaarawy && cd /srv/shaarawy
cp .env.prod .env            # then edit every value marked change-me
```

Required values in `.env`:
- `SECRET_KEY`, `DB_PASSWORD`, `MEILI_MASTER_KEY` — long random strings.
- `AUDIO_S3_*` — Cloudflare R2 credentials for bucket `shaarawy`
  (endpoint `https://6452da3166483560913682a6dd5a5b77.r2.cloudflarestorage.com`).
- `DOMAIN_NAME`, `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`,
  `NEXT_PUBLIC_API_URL` — your domain. `DOMAIN_NAME` is scheme-prefixed
  (`https://example.com`); `SITE_BASE_URL` and `NEXT_PUBLIC_SITE_URL` default to
  it, so set them only if the public origin differs.
- `ASR_BACKEND=faster-whisper` and `EMBEDDING_BACKEND=e5` — **required.** Django's
  built-in defaults are `stub`, and the stub engines *fabricate* transcript text
  and embeddings. A production stack left on `stub` silently fills the archive
  with invented speech attributed to the Sheikh. Keep `ALLOW_STUB_ENGINES` empty;
  set it to `true` only for a throwaway staging smoke test.
- Behind Cloudflare's proxy set `SECURE_SSL_REDIRECT=False` (Cloudflare terminates TLS).

## 2. Start

```bash
docker compose -f docker-compose.prod.yml --env-file .env up -d --build
```

`entrypoint.sh` waits for Postgres, migrates (incl. `CREATE EXTENSION vector`),
and collects static files. Caddy answers on 80/443 and provisions certificates
for `DOMAIN_NAME` automatically.

## 3. Seed data

```bash
docker compose -f docker-compose.prod.yml exec backend python manage.py import_quran
```

Audio ingestion runs from a (GPU) worker host with `pipeline/requirements.txt`
installed, pointed at this stack's Redis and Postgres:

```bash
export ASR_BACKEND=faster-whisper EMBEDDING_BACKEND=e5   # never "stub" — see below
celery -A pipeline.celery_app worker -Q pipeline   # long-running worker
python -m pipeline.run --folder /data/mp3s --source-title "خواطر التلفزيون المصري" --kind khawatir
```

**Production ingest must run with `ASR_BACKEND=faster-whisper`** (and
`EMBEDDING_BACKEND=e5`). The `stub` backends exist for the test suite only: their
output is *fabricated* text, not a transcription of the audio. Ingesting with
them writes invented words into `Transcript` rows that the UI then presents as
the Sheikh's speech. If you suspect a batch ran on stubs, delete those
transcripts and re-ingest — there is no way to tell stub text apart downstream.

## 4. Verify

```bash
curl -fsS https://$DOMAIN/healthz     # liveness: {"status":"ok"}
curl -fsS https://$DOMAIN/readyz      # readiness: db/redis/meilisearch all true
curl -fsS "https://$DOMAIN/api/surahs/" | head -c 200
```

## 5. Backups

Nightly cron on the host:

```cron
15 3 * * * cd /srv/shaarawy && set -a && . ./.env && set +a && ./scripts/backup.sh docker-compose.prod.yml >> /var/log/shaarawy-backup.log 2>&1
```

Backups are `pg_dump --format=custom` uploads to `s3://$AUDIO_S3_BUCKET/backups/postgres/`,
pruned after `BACKUP_KEEP_DAYS` (default 30).

**Verify a restore** (throwaway database — this is the test that matters):

```bash
./scripts/restore.sh backups/postgres/<latest>.dump restore_check docker-compose.prod.yml
# prints surahs=114 / ayahs=6236 on success
docker compose -f docker-compose.prod.yml exec db psql -U $DB_USER -d postgres -c "DROP DATABASE restore_check;"
```

The raw source audio is irreplaceable — keep an independent copy outside R2
(cold storage / offline drive), not just the transcoded Opus derivatives.

## 6. Updating

```bash
git pull
docker compose -f docker-compose.prod.yml --env-file .env up -d --build
```

Migrations run on container start. Meilisearch reindexing is only needed when
chunk data changes (`python manage.py shell` → `search.services.ensure_chunks_index()`
+ reindex, or re-run the pipeline `index` stage).

## 7. Observability

### Sentry

Set `SENTRY_DSN` in `.env` to your project DSN.  The backend initialises Sentry
(Django + Celery integrations) automatically on startup when the variable is
non-empty.  Leave it unset or empty to disable — no import errors occur either
way.  Optionally set `SENTRY_TRACES_SAMPLE_RATE` (float 0–1, default 0) for
performance tracing.

```env
SENTRY_DSN=https://<key>@o<org>.ingest.sentry.io/<project>
SENTRY_TRACES_SAMPLE_RATE=0.1
```

### Structured JSON logs

In production every Django/Celery log line is a single-line JSON object:

```json
{"timestamp":"2024-01-15T12:34:56.789123+00:00","level":"INFO","logger":"django.request","message":"GET /healthz 200"}
```

Tail them with:

```bash
docker compose -f docker-compose.prod.yml logs -f backend
```

Parse and filter with `jq`:

```bash
docker compose -f docker-compose.prod.yml logs backend | jq 'select(.level=="ERROR")'
```

### Health probes

| Endpoint | Purpose | Expected response |
|---|---|---|
| `GET /healthz` | Liveness — process is up | `{"status":"ok"}` HTTP 200 |
| `GET /readyz` | Readiness — db/redis/meilisearch | `{"db":true,"redis":true,"meilisearch":true}` HTTP 200 |

Use these as Docker/Kubernetes health-check targets.

### Sitemap

```
https://$DOMAIN/sitemap.xml           # index → two child sitemaps
https://$DOMAIN/sitemap-quran.xml     # 114 surahs + 6 236 ayahs
https://$DOMAIN/sitemap-segments.xml  # indexed audio segments
```

Submit `https://$DOMAIN/sitemap.xml` to Google Search Console.

These are Django views (`backend/core/sitemaps.py`), not Next.js routes — Caddy
routes `/sitemap.xml` and `/sitemap-*.xml` to the backend ahead of the catch-all
frontend proxy. Compose derives `SITE_BASE_URL` from `DOMAIN_NAME`; override it
in `.env` only when the public origin differs from the Caddy site address.
