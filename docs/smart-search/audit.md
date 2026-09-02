# Smart search — Phase 0 audit (2026-09-02)

Read-only audit of the repository and the running production stack, answering the Phase 0 questions of
the two-mode search plan (exact «بحث دقيق» + smart «بحث ذكي»). No functional change ships with this
document. Decisions taken by the owner on the basis of this audit are recorded at the end.

## 1. Headline findings

1. **No embeddings exist.** The `Chunk.embedding` column (multilingual-e5-large, 1024 dims, HNSW cosine)
   and every embedding code path were removed on 2026-08-21 (`corpus/migrations/0003_remove_chunk_embedding.py`,
   commit `f84e673`, API contract amendment 6). pgvector 0.8.6 is still installed on the production
   Postgres and is still created by `corpus/migrations/0001`. Nothing embeds queries today.
2. **Chunks are small silence units, not fixed windows.** `pipeline/chunking.py` splits at a >400 ms gap
   once ≥20 s are covered and hard-splits at 45 s, with zero overlap. Production has 102,655 chunks,
   average 22 s / 43 words (p90 55 words, max 535), p50 16 chunks per transcript (max 305).
3. **Production is gunicorn sync WSGI with 2 workers** (`docker-compose.prod.shared.yml`, `--timeout 60`).
   `core/asgi.py` exists but nothing runs it. A 15–40 s smart request would pin half the site's capacity.
4. **The API is fully anonymous.** `accounts` is an empty placeholder, no auth is exposed to the frontend,
   production has 0 Django users. Rate limits are per IP, counted in Redis.
5. **The Postgres `arabic` text-search config exists but does not strip the و/ف clitics** (verified live:
   `والصبر` stays `والصبر`, so `الصبر` does not match it). Clitic-robust lexical recall has to come from our
   own light stemmer.
6. **Every khawatir segment carries surah + ayah range** (4,357 of 4,357). All segments are `khawatir`.

## 2. Audit questions and answers

| Question | Answer |
|---|---|
| `Chunk` schema | `corpus.Chunk` = `transcript` FK, `idx`, `text` (display, diacritics kept), `text_normalized`, `start_ms`, `end_ms` (`backend/corpus/models.py:157`). No segment FK, no word-index range, no tsvector, no embedding, no header, no content hash. Unique on (transcript, idx). |
| Word ↔ chunk mapping | A word belongs to the chunk whose `[start_ms, end_ms)` contains `word.start_ms` (`corpus/corrections.py:97`, `word_range_in_span`). Word indices are transcript-wide `TranscriptWord.idx`; an approved unequal-count correction renumbers them, so ms spans are the stable key. |
| Chunking policy | Silence-gap based (see §1). Idempotent by existence check per transcript, not by content hash. Chunk text is literally the words joined by single spaces. |
| Embedding model + dimensions | None today (historically `intfloat/multilingual-e5-large`, 1024 dims, `passage:`/`query:` prefixes, HNSW m=16 ef_construction=64 cosine). No `EMBEDDING_*`, OpenAI, OpenRouter or Cohere-embedding settings exist; `CO_API_KEY` is ASR-only. |
| Meilisearch settings | v1.15. Index `chunks`: one document per chunk (`id, segment_id, segment_title, surah, ayah_start, ayah_end, kind, text, text_normalized, start_ms, end_ms`), searchable `text_normalized` only, `typoTolerance.minWordSizeForTypos` 4/8, ranking `words, proximity, typo, attribute, sort, exactness`, filterable `surah, kind, ayah_start, segment_id`, sortable `start_ms, surah`. Index `ayahs`: `text_normalized` + `text_imlaei_normalized`. Defined in `backend/search/services.py:95-132`; `manage.py index_chunks` upserts all chunks. |
| Hit → `TranscriptWord` / ms | A hit's `start_ms`/`end_ms` are the whole chunk's span copied from the document. `search/matching.py` computes the matched token offset (`PhraseMatch.start`) but `services._verify` discards it, so exact hits deep-link to the chunk start (≈22 s window), not the matched word. Word indices come from a separate `GET /api/segments/{id}/chunks/`. |
| Exact search today | Strict phrase since 2026-09-02 (commit `c6438f2`, amendment 12): Meilisearch is a candidate generator (pool 1000, `matchingStrategy: all`); the verifier requires every query word consecutively and in order, typo budget 0/1/2 at 1–3/4–7/8+ letters, first letter fixed (`الله` never matches `بالله`). Quotes typed by the reader are stripped (no-op). Params `q, kind, surah, page`; page size fixed at 10; `total` exact over the pool. No `phrase` or `mode` param. |
| `/listen` deep link | `/listen/{segmentId}?t=<ms>` — integer milliseconds, autoplays; no end parameter. The player is a Zustand store (`frontend/src/lib/audio-store.ts`: `load(track, {startMs, autoplay})`, `seekMs`, `play/pause`), mounted in the root layout; range playback exists as `components/clip/useRangePlayback.ts`. |
| WSGI vs ASGI in prod | WSGI (`gunicorn core.wsgi:application --workers 2 --timeout 60`, sync workers). Caddy (owned by the co-tenant ilmshamela stack) proxies `/api/*` to `backend:8000`; `GZipMiddleware` is first in the middleware chain. |
| Throttling | `ScopedRateThrottle` per view: `search 30/min`, `corrections 10/hour`, `clips 5/hour`; counters in Redis (`CACHE_REDIS_URL`, db 2); `NUM_PROXIES=1`; client IP via `api/ip.py`. |
| `accounts` / sessions | Empty app (one-line `models.py`, no migrations); default `auth.User`; only `/admin/` sessions; `is_staff` unused outside the admin. No per-user quota is possible today. |
| Khawatir surah/ayah ranges | Yes — `Segment.surah` FK + `ayah_start`/`ayah_end`, populated for 100 % of production segments. |
| `pg_ts_config` has `arabic`? | Yes (PostgreSQL 16.15, Snowball). Verified live: `to_tsvector('arabic', 'والصبر عند الصدمة الاولي')` → `'والصبر' 'عند' 'صدم' 'اول'` — `ال` and `ة` handled, `وال` not; no stop-word list. |
| Host capacity | Shared 2-CPU VPS, 7.9 GB RAM (~3.7 GB available; the co-tenant runs Elasticsearch), 44 GB disk free. Production DB 910 MB (`corpus_transcriptword` 759 MB, `corpus_chunk` 94 MB). Postgres defaults: `maintenance_work_mem=64MB`, `shared_buffers=128MB`, `max_connections=100`. |
| Prod image versions | Python 3.12, Django 5.2.17 (`GeneratedField` available), DRF 3.18, drf-spectacular 0.30, psycopg 3.3.5, pgvector-python 0.5.0, meilisearch 0.43, gunicorn 26. Absent: `openai`, `httpx` (only transitively), `tenacity`, `rapidfuzz`, `respx`. |
| Tests | pytest-django against a real Postgres + real Meilisearch (per-test index prefix) + real Redis (autouse `reset_throttles` flushes the cache). Shared factories in `backend/api/tests/factories.py`. No HTTP-mocking library. No CI. This host has no venv or system Django: run the backend suite in a throwaway Docker network (see README). Frontend: vitest 3 + happy-dom, zero component tests, no fetch mocking, no markdown renderer; `src/types/models.ts` is hand-written and the generated `src/types/api.ts` is imported by nothing. |
| Frontend search flow | `app/(site)/search/page.tsx` is an async server component (`force-dynamic`) that calls `search()` server-side and renders `components/ChunkResultList.tsx` (client; `/listen/{segment_id}?t={start_ms}` links and an in-place «تشغيل من هنا»). Machine-transcript marker is the constant `MACHINE_TRANSCRIPT_NOTE`. Canonical Quran text renders through `.quran-text` (AmiriQuran) in `AyahCard` / `SegmentAyahText`, fetched from `GET /api/ayahs/{surah}/{ayah}/`. Tailwind v4, no UI library, no icon library. |

## 3. Corpus numbers (production, 2026-09-02)

| Item | Value |
|---|---|
| Sources | 1 («تفسير الشعراوي — المجموعة الكاملة») |
| Segments | 4,357 (4,347 `indexed`, 10 `failed`), all `khawatir`, all with surah + ayah range; avg 9 min, max ~2 h |
| Transcripts | 4,353, engine `cohere-transcribe` / `cohere-transcribe-arabic-07-2026`, 4.47 M words |
| Chunks | 102,655; avg 22 s / 43 words / 216 chars; p90 55 words; max 535 words; p50 16 per transcript, p90 53, max 305 |
| Meilisearch | `chunks` 102,655 documents; `ayahs` 12,472 documents (see §7) |

## 4. Model and provider verification (openrouter.ai, 2026-09-02)

| Role | Slug | Price (per M tokens) | Notes |
|---|---|---|---|
| Planner / reranker | `google/gemini-3.1-flash-lite` | $0.25 in / $1.50 out | 1 M context, JSON-schema structured outputs, thinking levels minimal…high |
| Generator | `google/gemini-3.8-flash` | $0.75 in / $3.75 out | 1 M context, structured outputs, reasoning |
| Embeddings | `qwen/qwen3-embedding-8b` | $0.01 | 32k input, native 4096 dims with Matryoshka (32–4096); served by Nebius / DeepInfra / SiliconFlow; MTEB multilingual 70.58 |
| Embeddings (fallback) | `qwen/qwen3-embedding-0.6b` | — | native 1024 dims, MTEB multilingual 64.33 |

OpenRouter's embeddings endpoint is `POST /api/v1/embeddings`; whether it forwards a `dimensions`
parameter is not documented, so the client must verify the returned length and otherwise truncate to
1024 and L2-normalise (valid for Matryoshka-trained models) — identically for documents and queries.
Chat requests can ask for `usage: {include: true}` to get the exact cost per call.

Whole-corpus embedding estimate: 4.47 M words × ~2.5 tokens × ~1.2 overlap + headers ≈ 14 M tokens ≈ **$0.15**.

## 5. Recommendations

1. **Retrieval unit: a new `search.Passage` table over the existing chunks** (≈25–30k rows of 150–300
   words, one-chunk overlap, boundaries at the largest silence gap), leaving `Chunk` untouched. Chunk ids
   are referenced by Meilisearch documents, submitted corrections and clips; re-chunking would break them,
   and embedding all 102k chunks (fp32 ≈ 420 MB + graph) does not fit a 64 MB `maintenance_work_mem`
   build on this host. Store vectors as `halfvec(1024)` (≈55 MB + ~5 MB graph).
2. **Embeddings: `qwen/qwen3-embedding-8b` via OpenRouter at 1024 dims** (open weights → reproducible if
   the vendor retires it; cost ≈ $0.15 for the corpus). Record the model tag on every row.
3. **Lexical channel: our own `light_stem()` + Postgres `simple` config**, not Snowball `arabic`, because
   the latter leaves `وال`/`و`/`ف` clitics in place. Stem query and index with the same function.
4. **Exact mode:** add `light_stem()` to `corpus/arabic.py`, a `text_stem` Meilisearch attribute, and a
   third verifier tier (stem-equal, ranked below exact and typo matches). Keep the 4/8 thresholds that the
   verifier and Meilisearch already share. Quoted input turns the typo budget off. This flips amendment
   12's example: `الله` will match `بالله`, ranked last.
5. **Runtime before public exposure:** switch gunicorn to `gthread` workers (2 × 8 threads) and cap
   in-flight smart requests (Redis), so smart-mode latency never blocks exact search or playback.
6. **Streaming (Phase 7):** SSE is feasible under WSGI gthread (`Content-Encoding: identity` bypasses
   `GZipMiddleware`; Caddy flushes `text/event-stream`), but stream stage/passage events only — the
   answer is strict JSON and must pass the verifier before it is shown.

## 6. Decisions taken by the owner (2026-09-02)

- Push the two local production commits to origin before branching (done; master is in sync).
- Retrieval unit: new `Passage` table; `Chunk` untouched.
- Embeddings: `qwen/qwen3-embedding-8b` via OpenRouter, 1024 dims.
- Exact mode: stem tier in the verifier, thresholds stay 4/8, quotes = zero typos.
- Access: anonymous, 20 requests/hour per IP, daily spend cap $5.
- Answers: Arabic only in v1 (English questions still get Arabic rewrites and an Arabic answer).
- The OpenRouter key lives only in the gitignored env files (`OPENROUTER_API_KEY`).

## 7. Asides noticed during the audit (not in scope)

- The `ayahs` Meilisearch index holds 12,472 documents for 6,236 ayahs: an earlier import used different
  ids and `index_quran` upserts without deleting, so half the documents are stale duplicates. Harmless
  for correctness (both copies carry the same text) but worth a one-off index reset.
- `PhraseMatch.start` is computed and discarded; using it would let exact hits deep-link to the matched
  word rather than the chunk start.
- `frontend/src/types/api.ts` (generated by `make types`) is imported by nothing; the hand-written
  `src/types/models.ts` is the live contract and can drift silently.
- `djangorestframework-simplejwt` is installed but unused.
- The API contract file is edited by several workstreams; amendment numbers are assigned at merge time.

## 8. What Phase 1 starts from

Foundation (no data changes): `openai`/`pydantic`/`tenacity`/`rapidfuzz`/`respx` dependencies, `SMART_*`
settings and the feature flag (off by default), the `search.smart` package (schemas, OpenRouter client,
versioned prompts, cache/budget helpers), the `SmartQuery` model as the first migration of the `search`
app, and respx-based tests that never call the provider.
