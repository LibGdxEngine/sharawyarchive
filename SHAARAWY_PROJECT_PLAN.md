# Sha'rawy Archive — Implementation Plan

**Stack:** Django (DRF) + PostgreSQL 16 (pgvector) + Celery/Redis + Meilisearch + Next.js (App Router) + Cloudflare R2

**Core thesis:** every other Sha'rawy site is a list of MP3 files. This one is *searchable audio* — you type a phrase and land on the exact second the Sheikh said it, with the words highlighting as he speaks.

R2 storage: S3 endpoint `https://6452da3166483560913682a6dd5a5b77.r2.cloudflarestorage.com`, bucket `shaarawy`.

---

## Phase 1 — Data model & Quran import

`backend/quran/models.py`
```
Surah(number PK, name_ar, name_ar_plain, name_en, ayah_count, revelation_place, order_revealed)
Ayah(id, surah FK, number, text_uthmani, text_imlaei, text_normalized,
     juz, hizb, page, sajda, UNIQUE(surah, number))
```

`backend/corpus/models.py`
```
Source(id, title, kind, description, rights_note)
AudioAsset(id, storage_key, duration_ms, mime, bitrate, sample_rate, sha256 UNIQUE, size_bytes)
Segment(id, source FK, kind[recitation|khawatir], surah FK, ayah_start, ayah_end,
        audio FK AudioAsset, ordinal, duration_ms, title,
        status[pending|transcribed|aligned|indexed|failed], INDEX(surah, ayah_start))
Transcript(id, segment O2O, engine, engine_version, language, raw_text, text_normalized,
           confidence, word_count, is_human_reviewed, version, created_at)
TranscriptWord(id, transcript FK, idx, text, start_ms, end_ms, confidence,
               UNIQUE(transcript, idx), INDEX(transcript, start_ms))
Chunk(id, transcript FK, idx, text, text_normalized, start_ms, end_ms,
      embedding vector(1024) NULL, INDEX(transcript, idx))
```

`backend/corpus/arabic.py` — the single normalization utility. Exact spec:
```
1. NFC normalize
2. strip tatweel U+0640
3. strip harakat U+064B–U+0652, U+0670, U+06D6–U+06ED (Quranic annotation marks)
4. أ إ آ ٱ ٲ ٳ → ا
5. ة → ه        (search index only)
6. ى → ي        (search index only)
7. ؤ → و ,  ئ → ي   (search index only)
8. collapse whitespace, strip Arabic-Indic digit variants → ASCII digits
```
Entry points: `normalize_for_index(s)` (all steps), `normalize_light(s)` (steps 1–3, display fallback).
Unit-test both against a fixture file of ≥50 tricky pairs.

Management command `import_quran` — Tanzil uthmani + imlaei text → Surah/Ayah, `text_normalized` via `normalize_for_index`. Idempotent: 114 surahs / 6236 ayahs.

## Phase 2 — Ingestion pipeline (audio → words with timestamps)

`pipeline/` is a separate package with its own requirements (torch, faster-whisper, ctc-forced-aligner, ffmpeg-python). Django imports **nothing** from it; communication via DB + Celery queue (`pipeline`).

Stages (each a resumable Celery task): `ingest` (walk folder, parse filename → surah/ayah range, sha256, ffprobe duration → AudioAsset, Segment), `transcode` (ffmpeg → Opus 32kbps mono + waveform peaks JSON → object storage), `transcribe` (ASR → Transcript), `align` (forced alignment → TranscriptWord), `chunk` (20–45s chunks on pause boundaries → Chunk), `embed` (multilingual-e5-large, 1024-dim; `query: `/`passage: ` prefixes), `index` (→ Meilisearch).

- Filename parser in `pipeline/parsers.py`, config-driven regex list, `--dry-run` prints parsed results.
- Chunking: split where gap(word[i].end_ms, word[i+1].start_ms) > 400ms AND chunk ≥20s; max 45s; never mid-ayah for recitation.
- Idempotency: every stage checks `Segment.status` + sha256; full re-run on completed corpus is a fast no-op.
- Failures: `status=failed` + traceback in `PipelineRun`; never abort the batch.
- `--limit N` / `--surah N` on every stage.

## Phase 3 — Search

- Lexical: Meili index `chunks`: docs `{id, segment_id, surah, ayah_start, ayah_end, kind, text, text_normalized, start_ms, end_ms}`; searchable `text_normalized` only; filterable `surah, kind, ayah_start`; sortable `surah, start_ms`. Queries pass through `normalize_for_index`.
- Semantic: pgvector HNSW on `Chunk.embedding`, cosine. Same e5 model for queries (with prefixes).
- Hybrid: RRF k=60 behind `?mode=lexical|semantic|hybrid`, default hybrid.
- Ayah lookup: parse `2:255`, `البقرة 255`, `آية الكرسي` → direct Ayah hit above chunk results.
- `backend/search/services.py` holds ranking; views thin.

## Phase 4 — API

```
GET  /api/surahs/                          list + ayah counts
GET  /api/surahs/{n}/                      surah + ayahs (paginated by 20)
GET  /api/ayahs/{surah}/{ayah}/            ayah + segments covering it
GET  /api/segments/{id}/                   metadata + signed audio url + waveform url
GET  /api/segments/{id}/transcript/        full word array [{i,t,s,e,c}] — compact keys
GET  /api/search/?q=&mode=&kind=&surah=&page=
GET  /api/topics/  /api/topics/{slug}/
POST /api/corrections/                     {chunk_id, word_start, word_end, suggested_text}
GET  /api/clips/{id}/  POST /api/clips/    clip render jobs
```
- Compact transcript keys, integer ms, gzip.
- `Cache-Control: public, max-age=31536000, immutable` on transcripts + ayah text; search `no-store`.
- Signed R2 URLs, 6h TTL, per request. Throttle: search 30/min anon, corrections 10/hour, clips 5/hour.
- drf-spectacular schema; frontend types generated (`make types`).

## Phase 5 — Frontend player

Design (record in `frontend/DESIGN.md` first): Uthmani face for ayah text (self-hosted, next/font/local) + modern Arabic UI face (IBM Plex Sans Arabic / Almarai); the contrast is the identity. Restraint: reading column + audio state only; no cards/shadows/gradient hero; no cream-paper-terracotta. Keyboard focus visible, prefers-reduced-motion respected, works at 360px.

Architecture:
- One global `<audio>` in root layout, owned by Zustand store; survives route changes.
- Highlight loop: requestAnimationFrame + binary search of word array for currentTime*1000; bail early if unchanged.
- Virtualize transcript (@tanstack/react-virtual). Auto-scroll active line to 40% viewport; disable on user scroll; "back to current" affordance.
- Click word → seek. Media Session API. Deep links `?t=<ms>`; share writes position into URL.
- Speed 0.75/1/1.25/1.5, sleep timer, per-segment position in localStorage.

Pages: `/` (search-first landing), `/surah/[n]`, `/listen/[segmentId]`, `/search?q=` (in-place play), `/topics`, `/topics/[slug]`.

## Phase 6 — Corrections & review

Permanent machine-transcript marker. Select words → suggest correction → POST /api/corrections/ (no account, IP rate-limited). Admin review queue side-by-side + play range; approve → TranscriptWord update, Transcript.version bump, re-chunk/embed/index affected chunks only. `is_human_reviewed` surfaces subtly.

## Phase 7 — Topics & discovery

Cluster chunk embeddings (HDBSCAN), label clusters via LLM (10 central chunks). `Topic(slug, name_ar, description_ar, is_published=False until reviewed)` + `ChunkTopic(chunk, topic, score)`. Related passages: embedding NN excluding same segment.

## Phase 8 — Clip cards

Waveform drag handles 15–60s (hard cap 60), 3 presets, preview. Celery+ffmpeg: ASS subtitles with per-word `\k` karaoke, 1080×1920, H.264+AAC, audio via -ss/-to. Share page `/clip/[id]` with OG video tags + download. Attribution mark. Cache by (segment_id, start_ms, end_ms, preset).

## Phase 9 — Offline & PWA

Serwist/Workbox: precache shell; transcripts SWR; ayah text cache-first. Save-for-offline per segment (Opus + transcript in Cache Storage, usage indicator, per-item delete). Media Session background audio. Install prompt, maskable icons, Arabic manifest.

## Phase 10 — Production

Compose: web, worker, beat, postgres, redis, meilisearch, caddy. R2 for audio (zero egress). Sentry both sides; structured logging; /healthz + /readyz. Nightly pg_dump to R2 with tested restore. Plausible analytics, query log without PII. SEO: per-ayah/segment metadata, sitemap.xml (6236 ayahs).

## Risks

- ASR error in religious text → Quran text never from ASR; permanent marker; corrections from day one.
- Rights on TV khawatir → `Source.rights_note`, verify before promotion.
- Auto topics unreviewed → `is_published` gate.
- GPU cost → WER checkpoint on one surah first; `--limit`/`--surah` everywhere.
- Storage/egress → Opus 32kbps mono, R2.
