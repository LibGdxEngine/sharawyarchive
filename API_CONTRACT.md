# API Contract (frozen — backend and frontend both implement exactly this)

All timestamps are integer **milliseconds**. All list endpoints are JSON. Base path `/api/`.

## GET /api/surahs/
`[{ "number": 1, "name_ar": "الفاتحة", "name_ar_plain": "الفاتحه", "name_en": "Al-Fatihah", "ayah_count": 7, "revelation_place": "makkah", "segment_count": 3, "juz_start": 1, "juz_end": 1, "page_start": 1, "page_end": 1 }]`

## GET /api/quran/locate/?page=1
`{ "surah": 1, "number": 1, "surah_name_ar": "الفاتحة", "juz": 1, "page": 1 }`

Exactly one of `?page=` or `?juz=`. Answers the first ayah of that mushaf page
or juz; `404` when there is no such page or juz.

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

## GET /api/search/?q=&kind=&surah=&page=1
Headers: `Cache-Control: no-store`.
```json
{ "query": "...",
  "ayah_matches": [{ "surah": 2, "number": 255, "text_uthmani": "...", "surah_name_ar": "البقرة" }],
  "results": [{ "chunk_id": 9, "segment_id": 17, "segment_title": "...", "surah": 2,
                 "ayah_start": 250, "ayah_end": 260, "kind": "khawatir",
                 "text": "...", "start_ms": 125300, "end_ms": 152000 }],
  "page": 1, "total": 42 }
```

## GET /api/search/suggest/?q= → `["...", "..."]` (autocomplete snippets)
Headers: `Cache-Control: no-store`. Empty list under 2 normalized characters.

## GET /api/topics/  → `[{ "slug": "sabr", "name_ar": "الصبر", "description_ar": "...", "chunk_count": 12 }]`
## GET /api/topics/{slug}/ → topic + `"chunks": [<search result shape>]`
Only `is_published=True` topics ever appear.

## POST /api/corrections/  (throttle 10/hour/IP)
Body `{ "chunk_id": 9, "word_start": 4, "word_end": 6, "suggested_text": "..." }` → 201 `{ "id": 1, "status": "pending" }`

## POST /api/clips/  (throttle 5/hour/IP)
Body `{ "segment_id": 17, "start_ms": 125000, "end_ms": 155000, "preset": "night", "output": "video" }`
→ 202 `{ "id": "uuid", "status": "queued" }` (400 if span <1000ms or runs past the segment)
## GET /api/clips/{id}/ → `{ "id": "uuid", "status": "queued|rendering|done|failed", "output": "video|audio", "video_url": "https://...|null", "audio_url": "https://...|null" }`
(plus `media_url`, `download_url`, `download_filename` — amendment 11)
## GET /api/clips/{id}/media/ → 302 to the clip object, played inline
## GET /api/clips/{id}/download/ → 302 to the clip object, saved as an attachment

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
   `Cache-Control: public, max-age=300` (the URL carries no version and an
   approved correction can renumber word indices).
2. **Search pagination**: `page` is capped at 100 (400 beyond); `total` is
   Meilisearch's estimate of the matching document count.
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
6. **Semantic similarity removed** (2026-08-21): the `mode=` search param
   (`semantic`/`hybrid`) and the `mode` response field are gone — search is
   lexical only, and an incoming `mode=` is ignored like any unknown query
   param. `GET /api/segments/{id}/related/` is removed (404). Chunk embeddings
   are no longer stored. `GET /api/search/suggest/` documented above.
7. **Unaligned transcripts are invisible** (2026-08-21): a transcript whose
   align stage has not produced word rows 404s on
   `GET /api/segments/{id}/transcript/` (never `200` with `words: []` — that
   would be cached as "no text" for a year), and the segment detail reports
   `transcript_version: null` for it. The align stage bumps
   `Transcript.version` when it writes words, so clients always fetch a `?v=`
   that did not exist while the transcript was word-less.
8. **`kind` scopes content, not just chunks** (2026-08-21): `GET /api/search/`
   with `kind=recitation` returns canonical mushaf text only (`ayah_matches` +
   `verse_matches`; `results` is always `[]`, `total` `0`) and no ASR output;
   `kind=khawatir` returns machine transcripts only (`results`; `ayah_matches`
   and `verse_matches` are always `[]`); omitting `kind` returns both as before.
   Canonical text and ASR output never share one `kind`.
9. **Clips can be any length and either audio or video** (2026-08-21): the
   15–60 s span is gone — a clip may run from one second up to the end of its
   segment. `POST /api/clips/` accepts `output: "video" | "audio"` (default
   `video`). A video card now renders an animated waveform (driven by the
   audio) behind the karaoke subtitles instead of a flat colour. An audio clip
   is AAC in an `m4a` container with the clipped machine transcript embedded
   as lyrics metadata. `GET /api/clips/{id}/` answers with both
   `video_url`/`audio_url`, exactly one non-null for a finished job.
10. **A video clip may not exceed 5 minutes** (2026-08-28): this narrows
    amendment 9, which removed every ceiling. `POST /api/clips/` answers 400 on
    `end_ms - start_ms > 300000` when `output` is `video`. The reason is
    capacity, not policy: a video card is a 1080×1920 H.264 encode with an
    animated `showwaves` layer under burned-in subtitles, and the render queue
    is two workers on a shared two-core host, so an 84-minute request would
    hold both of them for hours. **Audio clips keep amendment 9's freedom** —
    an AAC transcode is close to free — so a whole segment can still be
    exported as `output: "audio"`.
11. **Stable clip file addresses** (2026-08-28): `GET /api/clips/{id}/` gains
    three fields, all `null` until `status` is `done`:
    * `media_url` — `https://<site>/api/clips/{id}/media/`, the clip played
      inline, whichever output the job produced;
    * `download_url` — `https://<site>/api/clips/{id}/download/`, the same
      bytes saved to disk;
    * `download_filename` — the Arabic name the browser will save it under,
      e.g. `أرشيف-الشعراوي-الفاتحة-1-7-02.05-02.35.mp4`.

    Both routes answer `302` to a freshly presigned object URL with
    `Cache-Control: private, max-age=300`, and `404` while the clip is not
    rendered. They exist because the presigned `video_url`/`audio_url` cannot
    do two things a shared link needs: they die in six hours (these re-sign per
    request, so an OpenGraph card still resolves next week), and HTML ignores
    the `download` attribute across origins (the attachment disposition is
    *signed into* the redirect target instead). `video_url`/`audio_url` stay,
    unchanged, for direct playback.

    Both URLs name the public site (`SITE_BASE_URL`), never the caller's host —
    the frontend renders the clip page server-side against the cluster-internal
    API address, which must not reach a browser.
12. **Strict phrase search** (2026-09-02): `GET /api/search/` matches the
   query as a phrase. Every query word must occur in the chunk (or verse)
   **consecutively and in the same order**; each word may differ from the
   text by a typo budget set by its length after normalization — 1–3 letters
   exact, 4–7 letters one edit, 8 or more letters two edits (an edit is an
   inserted, missing, wrong or transposed letter; the first letter must
   always match, so `الله` never matches `بالله`). Prefix matching of the
   last word is gone: `الص` finds nothing, `الصبر عند الصدم` still finds
   `الصبر عند الصدمة` (one missing letter). `verse_matches` matches either the
   Uthmani or the imlaei spelling (`السماوات` finds `ٱلسَّمَـٰوَٰتِ`). `total`
   is now the exact number of verified chunks, computed over Meilisearch's
   first 1000 candidates (a lower bound only for phrases with more than 1000
   candidates); it is identical on every page. This supersedes the "estimate"
   wording of amendment 2. `GET /api/search/suggest/` stays prefix-based but
   returns only snippets that contain every typed word, cut on a word
   boundary so a clicked suggestion always matches itself.
13. **Browsing the index by juz and page** (2026-09-02): `GET /api/surahs/`
    gains four fields — `juz_start`, `juz_end`, `page_start`, `page_end` — the
    inclusive juz and Madani-mushaf-page span each surah occupies, aggregated
    from its ayahs. They come from the Tanzil import like every other verse
    fact (rule 1); ASR never touches them. They ride along on the existing
    single query so the `/surahs` index can filter by juz or page without a
    request per surah, and `segment_count` is now counted `DISTINCT` — joining
    the ayah table beside the segment table otherwise multiplies it by
    `ayah_count`.

    A new `GET /api/quran/locate/` takes **exactly one** of `?page=` (Madani
    mushaf) or `?juz=` and answers the first ayah of it:
    `{ "surah", "number", "surah_name_ar", "juz", "page" }`. It is the reverse
    of `Ayah.page`/`Ayah.juz`, which nothing else exposed, and exists so the
    index can turn a typed "صفحة ٦٠٤" or "جزء ٣٠" into
    `/surah/{surah}?ayah={number}`. Giving both parameters, or neither, is a
    `400`; a well-formed page or juz that is past the end of the mushaf is a
    `404`, not an empty `200`. Both endpoints stay
    `public, max-age=31536000, immutable`.
14. **Stem matches and quotes in exact search** (2026-09-02): below amendment
    12's typo tiers, `GET /api/search/` now accepts a word whose *light stem*
    equals the query word's — one clitic prefix (`وال بال فال كال لل ال`, or a
    lone `و/ب/ف/ك/ل` before `ال`) and one suffix (`ها هم كم نا ات ون ين`)
    removed, at least three letters kept. So `الصبر` finds `بالصبر` and
    `والصبر`, `مؤمن` finds `المؤمنين`, and `الله` finds `بالله` — flipping
    amendment 12's example. Stem matches rank **after** every exact and typo
    match of the same query, then by Meilisearch's order; the 4/8 typo
    thresholds and the first-letter rule are unchanged. Wrapping words in
    quotes (`"…"`, `«…»` or `“…”`) makes them strict: no typos, no stems, so
    `"الله"` finds only `الله`. Quotes were previously stripped and ignored.
    `verse_matches` follows the same rules over the mushaf text. `total`
    still counts verified chunks, now over up to two Meilisearch pools
    (raw and stemmed words, 1000 each).
