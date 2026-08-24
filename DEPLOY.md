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
- `ASR_BACKEND=cohere` — **required.** Django's built-in default is `stub`,
  and the stub engine *fabricates* transcript text. A production stack left on
  `stub` silently fills the archive with invented speech attributed to the
  Sheikh. Keep `ALLOW_STUB_ENGINES` empty; set it to `true` only for a
  throwaway staging smoke test.
- `CO_API_KEY` — Cohere API key for `ASR_BACKEND=cohere` (the default:
  `cohere-transcribe-arabic-07-2026`, Arabic-specialized, hosted — no GPU needed
  for transcription). `ASR_BACKEND=faster-whisper` is the offline/GPU
  alternative. Word-level timings always come from the local CTC aligner
  (`pipeline/requirements.txt`), whichever recognizer produces the text.
- Behind Cloudflare's proxy set `SECURE_SSL_REDIRECT=False` (Cloudflare terminates TLS).

## 2. Start

```bash
docker compose -f docker-compose.prod.yml --env-file .env up -d --build
```

`entrypoint.sh` waits for Postgres, migrates (incl. `CREATE EXTENSION vector`),
and collects static files. Caddy answers on 80/443 and provisions certificates
for `DOMAIN_NAME` automatically.

## 3. Seed data

If you were handed a corpus database dump (transcripts already made), skip
this section and follow §8 instead — the dump already contains the Quran text.

```bash
docker compose -f docker-compose.prod.yml exec backend python manage.py import_quran
docker compose -f docker-compose.prod.yml exec backend python manage.py index_quran   # idempotent; builds the full-text ayahs index
```

The `index_quran` step powers search over the mushaf itself (pasting a whole
ayah must find it). The backend entrypoint also runs it on every start, so it
self-heals an empty index — but run it explicitly here so search works without
waiting for a redeploy.

Audio ingestion runs from a (GPU) worker host with `pipeline/requirements.txt`
installed, pointed at this stack's Redis and Postgres:

```bash
export ASR_BACKEND=cohere CO_API_KEY=...   # never "stub" — see below
celery -A pipeline.celery_app worker -Q pipeline   # long-running worker
python -m pipeline.run --folder /data/mp3s --source-title "خواطر التلفزيون المصري" --kind khawatir
```

**Production ingest must run with `ASR_BACKEND=cohere`** (hosted, default) or
`faster-whisper` (local GPU). As a backstop,
`get_asr_engine()` itself refuses the stub without `ALLOW_STUB_ENGINES=true`,
even on a worker that booted with dev settings. The `stub` backends exist for the test suite only: their
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
chunk data changes or the search volume is rebuilt:
`python manage.py index_chunks` (idempotent upsert of every chunk row).

## 8. Import the corpus database dump

Use this instead of §3's ingestion when the corpus was transcribed elsewhere
(the dev workstation) and handed over as a Postgres dump produced by
`scripts/backup.sh`. The dump carries everything: Quran text, sources, audio
asset metadata, transcripts, word timings, chunks, topics, corrections and
accounts. It does **not** carry Meilisearch indexes or audio bytes — those are
rebuilt / already in R2 below.

Prerequisites: the stack is up per §1–2 (so `db` exists and migrations have
run once), `.env` holds the R2 credentials (`AUDIO_S3_*` — `restore.sh` falls
back to them, or set `BACKUP_S3_*` explicitly), and the `aws` CLI is installed.

```bash
cd /srv/shaarawy && set -a && . ./.env && set +a

# 1. Stop everything that holds a DB connection (Caddy can stay up).
docker compose -f docker-compose.prod.yml stop backend celery_worker celery_beat

# 2. Restore. The dump was taken from a dev database named "postgres"; the name
#    is irrelevant — restore.sh drops and recreates the target database, and
#    custom-format dumps are database-name-agnostic. DB_USER is POSTGRES_USER,
#    i.e. a superuser inside the pgvector image, so the dump's
#    CREATE EXTENSION vector restores without privilege errors.
DB_NAME="$DB_NAME" DB_USER="$DB_USER" \
  scripts/restore.sh backups/postgres/postgres-<STAMP>.dump "$DB_NAME" docker-compose.prod.yml
# (a local file path works too: scripts/restore.sh /path/to/postgres-<STAMP>.dump "$DB_NAME" docker-compose.prod.yml)

# 3. Bring the app back. entrypoint.sh runs migrate (expect "No migrations to
#    apply" — the dump and the checkout are the same commit) and index_quran.
docker compose -f docker-compose.prod.yml up -d

# 4. Rebuild search. Meilisearch starts empty and the pipeline's index stage
#    would skip these segments (they are already marked indexed).
docker compose -f docker-compose.prod.yml exec backend python manage.py index_quran
docker compose -f docker-compose.prod.yml exec backend python manage.py index_chunks
```

Audio needs no copying: the Opus derivatives and waveforms were pushed to R2
(`manage.py sync_storage_to_r2`) before the dump was taken, and the API signs
R2 URLs directly — just confirm `AUDIO_S3_BUCKET=shaarawy` and the R2 endpoint
in `.env`.

**Rotate the dev accounts.** The dump includes the dev workstation's Django
users (a superuser with a development password). Before exposing the site:

```bash
docker compose -f docker-compose.prod.yml exec backend python manage.py createsuperuser
docker compose -f docker-compose.prod.yml exec backend python manage.py shell -c \
  "from django.contrib.auth import get_user_model as g; U=g(); \
   print(U.objects.exclude(username='<new-superuser>').update(is_active=False), 'dev accounts deactivated')"
```

**Verify** (numbers in brackets are the dev-side counts recorded at dump time —
fill them in from the hand-over note):

```bash
curl -fsS https://$DOMAIN/healthz && curl -fsS https://$DOMAIN/readyz
docker compose -f docker-compose.prod.yml exec db psql -U "$DB_USER" -d "$DB_NAME" -tAc "
SELECT 'segments:'||status||'='||count(*) FROM corpus_segment GROUP BY status
UNION ALL SELECT 'transcripts='||count(*) FROM corpus_transcript
UNION ALL SELECT 'engine:'||engine||'='||count(*) FROM corpus_transcript GROUP BY engine
UNION ALL SELECT 'words='||count(*) FROM corpus_transcriptword
UNION ALL SELECT 'chunks='||count(*) FROM corpus_chunk
UNION ALL SELECT 'ayahs='||count(*) FROM quran_ayah;"
```

The `engine` line must show only `cohere-transcribe`; `ayahs=6236`. Then, in
the UI, search a phrase you know occurs in one segment, open it, play it and
confirm the word highlighting follows the audio (that proves both the R2
signing and the word timings survived the move).

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
