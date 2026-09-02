# Phase 7 — Streaming and production (2026-09-02)

Branch `smart/phase-7-streaming`, stacked on Phase 6. The smart endpoint can answer as server-sent
events, and the frontend can read them, behind a build flag that stays off until the edge is
confirmed to pass a stream through.

## What landed

- **Backend** (`search/views.py`, `search/smart/pipeline.py`): `POST /api/search/smart/` with
  `Accept: text/event-stream` answers `text/event-stream` (`Cache-Control: no-store`,
  `Content-Encoding: identity` so `GZipMiddleware` leaves the body alone, `X-Accel-Buffering: no`).
  The pipeline runs on a helper thread that feeds a queue (`RunContext.on_event`); the response
  generator relays `stage` events (`retrieve`, `rerank`, `generate`), one `passages` event as soon
  as the reranked passages are known (sources on screen within seconds), then `result` with the full
  verified response, or `error`. A `: ping` comment goes out every 10 s while a stage is still
  running. The in-flight slot is held until the stream ends (the 429 path is unchanged), a cache hit
  streams only `result`, and the thread closes its own database connection. **No token events**: the
  answer must pass the verifier before a quote is shown (rule 1), so the target is "first `passages`
  event ≤ 5 s", not "first token ≤ 4 s".
- **Frontend** (`src/lib/smart-transport.ts`): `parseSse()` (chunk boundaries, multi-line data,
  comments, CRLF) and `streamTransport()` — the same POST with `Accept: text/event-stream`; a plain
  JSON answer (proxy buffered, or an older backend) is handled exactly like the fetch transport; a
  stream that ends without `result` is a `network` error. `defaultTransport` is the streaming one
  when the build has `NEXT_PUBLIC_SMART_STREAMING=1`. `useSmartSearch` keeps `earlyPassages`, which
  `SmartResults` renders under the skeleton while the answer is being written. Components are
  otherwise unchanged.
- **Compose**: `NEXT_PUBLIC_SMART_STREAMING` as a frontend build arg and env (default `0`).
- **Tests**: backend — the event order and payloads through the DRF client
  (`transaction=True`, the worker thread needs committed rows), cache hit → `result` only, the
  concurrency cap on the streaming path; frontend — the SSE parser and every branch of the transport,
  early passages in the island.

## Turning it on (after the Phase 6 gates)

1. Spike through the live edge (the shared Caddy owned by the co-tenant stack):
   ```bash
   curl -sN -X POST https://<site>/api/search/smart/ -H 'Content-Type: application/json' \
     -H 'Accept: text/event-stream' -d '{"question":"ما رأي الشيخ في الصبر عند الصدمة"}'
   ```
   `stage:` lines must appear *before* `result` (Caddy's `reverse_proxy` flushes SSE immediately and
   `encode` skips a body that already declares `Content-Encoding`). If everything arrives at once, the
   edge buffers: leave the flag off — the transport already degrades to the one-piece answer — and
   fall back to job + poll (a Celery `smart` queue with `-P threads -c 4` as its own compose service
   via the `&backend` anchor, `POST → 202` + `GET /api/search/smart/{id}/`).
2. `NEXT_PUBLIC_SMART_STREAMING=1` in `.env.prod`, rebuild the frontend (`--build frontend`).
3. Watch the `SmartQuery` admin list (status, cost, latency, feedback) — the v1 dashboard — and the
   daily spend (`SMART_DAILY_BUDGET_USD`).

## Live smoke test (2026-09-02, real models, throwaway database, rolled back)

Twelve passages built from the search-suite fixture corpus, embedded through OpenRouter (568
tokens), then one `run_smart_search("ماذا قال الشيخ عن الصبر عند الصدمة الأولى؟")` with debug on:

- every stage answered in the strict schema on the first try — planner `google/gemini-3.1-flash-lite`
  (5 rewrites, e.g. «تفسير حديث إنما الصبر عند الصدمة الأولى»), reranker (same model), generator
  `google/gemini-3.8-flash`; no warnings, no verifier notes;
- status `not_found` with the model's honest sentence (the fixture chunks only *mention* the phrase),
  two citations both resolved to the exact words: 30 000–33 900 ms and 180 000–183 900 ms, listen URLs
  `/listen/1?t=30000` / `?t=180000`; three Arabic follow-ups; four passages returned;
- latency plan 1.3 s · retrieve 1.0 s · rerank 1.2 s · generate 5.9 s · total 9.4 s; cost $0.0075.
