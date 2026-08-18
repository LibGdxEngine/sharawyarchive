# API Contract (frozen — backend and frontend both implement exactly this)

All timestamps are integer **milliseconds**. All list endpoints are JSON. Base path `/api/`.

## GET /api/surahs/
`[{ "number": 1, "name_ar": "الفاتحة", "name_ar_plain": "الفاتحه", "name_en": "Al-Fatihah", "ayah_count": 7, "revelation_place": "makkah", "segment_count": 3 }]`

## GET /api/surahs/{n}/?page=1
```json
{ "number": 2, "name_ar": "...", "name_en": "...", "ayah_count": 286, "revelation_place": "madinah",
  "ayahs": { "count": 286, "page": 1, "page_size": 20,
    "results": [{ "number": 1, "text_uthmani": "...", "juz": 1, "page": 2, "sajda": false, "segment_count": 2 }] } }
```

## GET /api/ayahs/{surah}/{ayah}/
```json
{ "surah": 2, "number": 255, "text_uthmani": "...", "text_imlaei": "...", "juz": 3, "page": 42,
  "segments": [{ "id": 17, "kind": "khawatir", "title": "...", "ayah_start": 250, "ayah_end": 260, "duration_ms": 2400000 }] }
```

## GET /api/segments/{id}/
```json
{ "id": 17, "kind": "khawatir", "title": "...", "surah": 2, "ayah_start": 250, "ayah_end": 260,
  "duration_ms": 2400000, "ordinal": 3,
  "audio_url": "https://... (presigned, 6h)", "waveform_url": "https://... (presigned, 6h)",
  "source": { "title": "...", "kind": "tv" },
  "transcript_version": 2, "is_human_reviewed": false }
```
Never expose raw storage keys.

## GET /api/segments/{id}/transcript/
Headers: `Cache-Control: public, max-age=31536000, immutable`. Content-addressed by `?v=<version>`.
```json
{ "version": 2, "engine": "whisper-large-v3", "is_human_reviewed": false,
  "words": [{ "i": 0, "t": "بسم", "s": 120, "e": 480, "c": 0.97 }] }
```

## GET /api/search/?q=&mode=hybrid|lexical|semantic&kind=&surah=&page=1
Headers: `Cache-Control: no-store`.
```json
{ "query": "...", "mode": "hybrid",
  "ayah_matches": [{ "surah": 2, "number": 255, "text_uthmani": "...", "surah_name_ar": "البقرة" }],
  "results": [{ "chunk_id": 9, "segment_id": 17, "segment_title": "...", "surah": 2,
                 "ayah_start": 250, "ayah_end": 260, "kind": "khawatir",
                 "text": "...", "start_ms": 125300, "end_ms": 152000 }],
  "page": 1, "total": 42 }
```

## GET /api/topics/  → `[{ "slug": "sabr", "name_ar": "الصبر", "description_ar": "...", "chunk_count": 12 }]`
## GET /api/topics/{slug}/ → topic + `"chunks": [<search result shape>]`
Only `is_published=True` topics ever appear.

## GET /api/segments/{id}/related/ → `[<search result shape>]` (embedding NN, same segment excluded)

## POST /api/corrections/  (throttle 10/hour/IP)
Body `{ "chunk_id": 9, "word_start": 4, "word_end": 6, "suggested_text": "..." }` → 201 `{ "id": 1, "status": "pending" }`

## POST /api/clips/  (throttle 5/hour/IP)
Body `{ "segment_id": 17, "start_ms": 125000, "end_ms": 155000, "preset": "night" }`
→ 202 `{ "id": "uuid", "status": "queued" }` (400 if span <15000ms or >60000ms)
## GET /api/clips/{id}/ → `{ "id": "uuid", "status": "queued|rendering|done|failed", "video_url": "https://...|null" }`

## Health
`GET /healthz` → 200 `{"status":"ok"}` (liveness, no deps)
`GET /readyz` → 200/503 `{"db":true,"redis":true,"meilisearch":true}`

## Throttles
search 30/min anon; corrections 10/hour; clips 5/hour → 429 with `Retry-After`.

---

## Amendments (post-freeze, recorded here rather than silently drifting)

1. **`GET /api/segments/{id}/chunks/`** (added for the corrections UI):
   `[{ "chunk_id": 9, "start_ms": 0, "end_ms": 25000, "word_start": 0, "word_end": 41 }]`
   ordered by chunk idx; `word_start`/`word_end` are inclusive transcript-wide
   `TranscriptWord.idx` values and are `null` for a chunk whose span holds no words.
   Immutable cache headers (content changes only with transcript version).
2. **Search pagination**: `page` is capped at 100 (400 beyond); for `semantic`
   and `hybrid` modes `total` is the size of the fused candidate pool (≤100),
   not a corpus-wide count.
3. **Clips**: there is deliberately no public `GET /api/clips/` listing; the
   pair is `POST /api/clips/` + `GET /api/clips/{id}/`. `POST` returns 200 with
   the existing clip (any status) on a cache hit, 202 on first creation.
4. **Segment detail caching**: `GET /api/segments/{id}/` sends
   `Cache-Control: private, max-age=300` (its presigned URLs expire in 6h and
   must not sit in shared caches for a year). Topics send `public, max-age=300`
   so publish/unpublish propagates.
5. **Surah detail ayahs** additionally carry `segments: [{id, kind, title}]`
   (max 5 inlined; `segment_count` stays uncapped) so the surah page needs no
   per-ayah fan-out.
