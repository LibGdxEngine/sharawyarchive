# Sha'rawy Archive

Searchable archive of Sheikh Mohamed Metwally Al-Sha'rawy's Quran recitation and
khawatir (commentary), with word-level audio/text alignment.

## Layout
- `backend/`  Django 5 + DRF. App per domain: `quran`, `corpus`, `search`, `clips`, `accounts`.
- `frontend/` Next.js App Router, TypeScript, Tailwind, RTL-first.
- `pipeline/` Standalone ASR + alignment workers (heavy deps, not imported by Django).

## Non-negotiable rules
1. **Quran text NEVER comes from ASR output.** Ayah text is imported from Tanzil/QUL
   only. ASR output is stored exclusively on the `Transcript` model and is always
   rendered with a "machine transcript" marker in the UI.
2. All Arabic search/compare goes through `corpus.arabic.normalize_for_index()`
   (or `normalize_light()` for display fallback). Never compare raw Arabic
   strings. Display text keeps full diacritics; index text is normalized.
3. `dir="rtl"` and `lang="ar"` at the document level. No per-component RTL hacks.
4. Audio URLs are always presigned/CDN URLs generated server-side. No bucket paths in
   the API response.
5. Timestamps are integer **milliseconds** everywhere. Never floats, never seconds.
6. Any script that touches thousands of files must be idempotent and resumable
   (checkpoint by content hash, skip completed rows).

## Commands
- `make dev` — docker compose up (postgres+pgvector, redis, meilisearch, minio)
- `make be` / `make fe` — run backend / frontend
- `make test` — pytest + vitest
- `make lint` — ruff + mypy + eslint + tsc
- `make types` — regenerate frontend API types from the OpenAPI schema

## Storage
- Production audio lives in Cloudflare R2, bucket `shaarawy`
  (S3 endpoint `https://6452da3166483560913682a6dd5a5b77.r2.cloudflarestorage.com`).
  Credentials via `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` env vars.
- Local dev uses MinIO with the same S3 client code (`AUDIO_S3_ENDPOINT_URL`).

## Style
- Python: ruff, type hints on all public functions, no bare `except`.
- TS: strict mode, no `any`, server components by default (`"use client"` only when needed).
- Conventional commits. One phase = one PR.
