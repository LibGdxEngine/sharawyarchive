# أرشيف الشعراوي — Sha'rawy Archive

Searchable audio archive of Sheikh Mohamed Metwally El-Sha'rawy.  Type a
phrase, land on the exact second the Sheikh said it, and watch the words
highlight as he speaks.

---

## What it is

Every other Sha'rawy site is a list of MP3 files.  This one is *searchable
audio*: forced-aligned transcripts map each word to its millisecond position so
search results link directly to the audio moment, and a highlight loop drives
real-time word highlighting during playback.

Two content kinds:

- **Recitation** — Quran recitation with word-level Uthmani text displayed.
- **Khawatir** — sermon/commentary segments, fully indexed and searchable.

---

## Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 14 (App Router, TypeScript, Tailwind CSS v4) |
| Backend | Django 5 + Django REST Framework |
| Database | PostgreSQL 16 with pgvector (HNSW index for embeddings) |
| Search | Meilisearch (lexical) + pgvector cosine (semantic), RRF hybrid |
| Task queue | Celery + Redis |
| Object storage | Cloudflare R2 (zero egress), presigned URLs |
| Ingestion pipeline | faster-whisper ASR, CTC forced aligner, ffmpeg |
| Reverse proxy | Caddy (automatic HTTPS) |

---

## Repo layout

```text
shaarawy/
├── backend/
│   ├── core/           # Django project — settings, URLs, sitemaps, observability
│   ├── api/            # Health probes (/healthz, /readyz), OpenAPI schema
│   ├── quran/          # Canonical Quran text (Surah, Ayah) — read-only reference
│   ├── corpus/         # Audio corpus: Source, AudioAsset, Segment, Transcript, Chunk
│   ├── search/         # Hybrid search service (Meilisearch + pgvector + RRF)
│   ├── clips/          # Clip render jobs (Celery + ffmpeg + ASS karaoke)
│   ├── accounts/       # User accounts
│   ├── requirements.txt
│   └── manage.py
├── pipeline/           # Ingestion pipeline (GPU worker, not imported by Django)
│   ├── run.py          # Entry point: python -m pipeline.run
│   ├── parsers.py      # Filename → surah/ayah range parser
│   └── requirements.txt
├── frontend/           # Next.js app (App Router)
│   └── src/
│       └── app/        # Pages: /, /surah/[n], /listen/[id], /search, /topics
├── caddy/              # Caddyfile (prod) + Caddyfile.dev
├── scripts/            # backup.sh, restore.sh
├── docker-compose.yml          # Development stack
├── docker-compose.prod.yml     # Production stack
├── .env.dev            # Dev environment variables (checked in with safe defaults)
├── .env.prod           # Prod template — copy and edit every change-me value
├── Makefile
└── DEPLOY.md           # Cold-deploy runbook
```

---

## Quick start (development)

### Prerequisites

- Docker + Compose v2
- GNU Make

### 1. Start everything

```bash
make dev        # builds images, starts all services
```

Or step by step:

```bash
docker compose up -d --build
```

Services started: PostgreSQL, Redis, Meilisearch, MinIO, Django backend,
Celery worker, Next.js frontend, Caddy.

### 2. Create the venv and install dependencies (bare-metal runs)

```bash
python -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/pip install -r backend/requirements-dev.txt
```

### 3. Run migrations and seed Quran text

```bash
cd backend
../..venv/bin/python manage.py migrate
../..venv/bin/python manage.py import_quran   # idempotent; 114 surahs / 6 236 ayahs
```

### 4. Verify

```bash
curl http://localhost/healthz          # {"status":"ok"}
curl http://localhost/readyz           # {"db":true,"redis":true,"meilisearch":true}
curl http://localhost/api/surahs/ | head -c 200
```

### 5. Run the ingestion pipeline

```bash
# Start a pipeline worker (GPU or CPU host with pipeline/requirements.txt)
celery -A pipeline.celery_app worker -Q pipeline -l info

# Ingest a folder of MP3 files
python -m pipeline.run \
    --folder /data/mp3s \
    --source-title "خواطر التلفزيون المصري" \
    --kind khawatir

# Dry-run (parse filenames only, no DB writes)
python -m pipeline.run --folder /data/mp3s --dry-run
```

---

## Make targets

| Target | Description |
|---|---|
| `make dev` | Start the development stack (builds if needed) |
| `make be` | Run the Django dev server outside Docker |
| `make fe` | Run the Next.js dev server outside Docker |
| `make migrate` | Apply Django migrations |
| `make import-quran` | Run `import_quran` management command |
| `make types` | Generate TypeScript types from the OpenAPI schema |
| `make test` | Run the full backend test suite |
| `make lint` | Run ruff on the backend |
| `make prod-build` | Build production Docker images |
| `make prod-up` | Start the production stack |
| `make logs` | Tail all service logs |
| `make createsuperuser` | Create a Django admin superuser |

---

## Testing

```bash
cd backend
DB_HOST=localhost DB_PORT=5432 DB_NAME=api_pg DB_USER=postgres DB_PASSWORD=postgres \
    ../.venv/bin/python -m pytest -q
```

The test suite covers: health probes, throttling, corpus/quran models, search
ranking, clip rendering, JSON log formatter, Sentry init, sitemap XML validity,
Arabic normalisation (≥50 fixture pairs).

---

## Non-negotiable rules

1. **Quran text never from ASR.** Every row in `quran.Ayah` is imported from
   Tanzil (`import_quran`) and treated as read-only.  Machine transcripts in
   `corpus.Transcript` always carry a "machine transcript" marker.

2. **Normalised search.** All search input and indexed text passes through
   `corpus.arabic.normalize_for_index` (NFC → strip harakat → hamza/alef
   unification → teh marbuta → alef maqsura → collapse whitespace).

3. **Integer milliseconds.** All durations, word offsets, and audio positions
   are stored and served as integer milliseconds.  Never floats, never seconds.

4. **Presigned URLs.** Raw R2 storage keys never leave the backend.  Audio and
   waveform URLs are presigned with a 6-hour TTL, generated per request.

---

## Deployment

See [DEPLOY.md](DEPLOY.md) for the full cold-deploy runbook including backups,
seed data, Sentry, and sitemap submission.
