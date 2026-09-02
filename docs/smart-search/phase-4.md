# Phase 4 — Generate, verify, API (2026-09-02)

Branch `smart/phase-4-generate-verify-api`, stacked on Phase 3. The pipeline is complete and
reachable over HTTP, behind `SMART_ENABLED` (off by default). API_CONTRACT.md amendment 15.

## What landed

- **Generator** (`search/smart/generate.py`): strict `GeneratedAnswer` from the generator model
  (`reasoning.effort = medium`, 30 s); one regeneration when the first answer breaks the schema or is
  not Arabic (`is_arabic()`: ≥ 70 % of letters Arabic); a second failure raises.
- **Verifier** (`search/smart/verify.py`) — nothing the model wrote is shown unverified:
  * quotes: 3–60 words; located with `rapidfuzz.partial_ratio_alignment` at `SMART_QUOTE_MIN_SCORE`
    (90) in the passage's **TranscriptWord** rows (fetched by ms span with the chunk API's
    membership rule); the aligned characters map back to the first and last word, whose
    `start_ms`/`end_ms` become the citation's; spans over 5 min are dropped; `quote_display` is the
    display words of that span; `chunk_id` is the chunk containing `start_ms`;
  * markers: `[pN]` → the numbers of that passage's accepted citations (`[1][2]`), orphans stripped;
    a sentence left without a marker is dropped, except the one sentence of a `not_found` answer;
  * ayahs: every `[[ayah:S:A]]` must exist in `quran.Ayah` or it is removed; `ayah_refs` are hydrated
    from the mushaf (`surah_name_ar`, `text_uthmani`) — the model's text never reaches the output;
  * status: no surviving citation → `not_found` (with a fixed Arabic sentence when nothing
    supported remains); `answered` with most citations dropped → `partial`; empty or non-Arabic
    text → `VerifyError` (the request degrades). Every drop is a note for `debug` and the row.
- **Pipeline** (`search/smart/pipeline.py`): `run_smart_search(question, filters, run)` under a
  `Deadline(SMART_REQUEST_BUDGET_S = 40)`: cache lookup → plan → retrieve → rerank → context →
  generate (skipped under 8 s left) → verify. Planner/reranker failures are warnings; generation
  failure, `VerifyError`, deadline or daily budget → `degraded` with the passages kept (the budget
  case carries a short Arabic notice). Every request writes a `SmartQuery` row (cache hits get a
  fresh `query_id`); only `answered`/`partial`/`not_found` are cached. `RunContext.use_llm=False`
  runs with no provider at all (naive plan, lexical retrieval, fused order, no answer).
- **API** (`search/views.py`, `search/urls.py`, `api/serializers.py`): `POST /api/search/smart/`
  (503 when off; 400 on a bad body; `SmartRateThrottle` = `ScopedRateThrottle` with a hashed ident,
  scope `smart` 20/hour; the in-flight cap held for the whole request as a context manager →
  `Throttled(wait=10)`; `debug` only for `is_staff`; `Cache-Control: no-store`) and
  `POST /api/search/smart/{query_id}/feedback/` (scope `smart_feedback` 60/hour). Serializers exist
  so `make types` regenerates the frontend types in Phase 5.
- **Prod runtime**: gunicorn `--worker-class gthread --threads 8 --timeout 75 --graceful-timeout 60`
  in both compose files (2 workers on the shared host); `CONN_MAX_AGE = 60` +
  `CONN_HEALTH_CHECKS` in `prod.py`. Under gthread `--timeout` is a heartbeat, not a per-request
  kill; the pipeline `Deadline` is the real cap and every provider call carries a timeout.
- **`manage.py smart_answer "<question>" [--surah|--source|--debug|--no-llm]`** prints the response.
- **Tests**: `test_smart_verify.py` (ms resolution, typo-tolerant quotes, every rejection, markers,
  ayah placeholders against the mushaf, status downgrades, non-Arabic refusal),
  `test_smart_generate.py` (context rendering, both regeneration triggers, double failure),
  `test_smart_api.py` (a full answered request with ms-resolved citations and the `SmartQuery` row,
  cache hit with zero provider calls, staff-only debug, generator failure → degraded and uncached,
  nothing retrieved → not_found, 503/400/429 rate/429 in-flight, filters, feedback, the command).
  `api/tests/test_throttling.py` asserts the new scopes. Backend suite: 921 passed.

## Live check after deploy (flag still off)

`curl -X POST /api/search/smart/` → 503. `manage.py smart_answer "ما رأي الشيخ في نجاة والدي النبي"
--debug` in a throwaway runner once Phase 2's passages are built and embedded. Enable for a staff
smoke test only after the Phase 6 gates.
