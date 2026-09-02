# Phase 1 — Foundation (2026-09-02)

Branch `smart/phase-1-foundation`, stacked on the Phase 0 audit. Nothing user-visible changes: no
endpoint exists yet and `SMART_ENABLED` defaults to off.

## What landed

- **Dependencies** (`backend/requirements.txt`): `openai`, `pydantic`, `tenacity`, `rapidfuzz`;
  `respx` in `requirements-dev.txt` to fake the provider in tests.
- **Settings** (`backend/core/settings/base.py`): `SMART_ENABLED`, `OPENROUTER_API_KEY`,
  `OPENROUTER_BASE_URL`, `SMART_PLANNER_MODEL` / `SMART_RERANK_MODEL` (`google/gemini-3.1-flash-lite`),
  `SMART_GENERATOR_MODEL` (`google/gemini-3.8-flash`), `SMART_EMBEDDING_MODEL`
  (`qwen/qwen3-embedding-8b`) + `SMART_EMBEDDING_DIMENSIONS` (1024), `SMART_DAILY_BUDGET_USD` (5),
  `SMART_MAX_INFLIGHT` (3), `SMART_REQUEST_BUDGET_S` (40), per-stage timeouts, cache TTL, quote score,
  and a fallback price table. Production refuses to boot with the flag on and no key.
  `docker-compose.prod.yml` passes the variables through; `DEPLOY.md` lists them.
- **`backend/search/smart/`**: `schemas.py` (stage contracts; `strict_json_schema()` closes every
  object for strict structured output), `llm.py` (`chat_json`, `embed`, `Deadline`, tenacity retries
  with the SDK's own retries disabled, usage + cost from OpenRouter's `usage.cost`, daily-budget check
  before every call, Matryoshka truncation fallback), `prompts/` (`planner`, `reranker`, `generator`,
  `judge` at `PROMPT_VERSION = "v1"`), `cache.py` (response keys carrying prompt version + embedding
  tag, daily-salted `ip_hash`), `budget.py` (micro-USD spend counter in the Django cache; in-flight
  cap as a Redis sorted set acquired by one Lua script, self-healing through 90 s leases).
- **`search.SmartQuery`** (`backend/search/models.py`, migration `0001_smartquery`): one row per
  request with plan, candidates, reranked list, verified answer, models, usage, cost, per-stage
  latency, cache flag, error and reader feedback. Read-only admin at `/admin/search/smartquery/`.
- **Tests** (`backend/search/tests/test_smart_*.py`, fakes in `openrouter_fakes.py`, fixtures
  `smart_settings` / `openrouter` / `fast_retries` in the search conftest): wire format of a strict
  JSON-schema call, retry on 429/5xx/timeouts only, no retry on 4xx, schema violations, fenced JSON,
  price-table fallback, budget refusal, deadline short-circuit, embedding truncation and the
  `dimensions`-rejected fallback, cache keys, hashing, spend cap, in-flight slots, model round trip,
  prompt loading. No test calls the provider.

## Live smoke test (real key, 2026-09-02, ≈ $0.0006 total)

- `POST /embeddings` with `qwen/qwen3-embedding-8b` **forwards `dimensions=1024`** (1024 components
  back; 4096 without the parameter), so the client-side truncation is a fallback only. `usage.cost`
  is returned when `usage: {include: true}` is sent.
- Planner call on `google/gemini-3.1-flash-lite` with strict `json_schema`, `provider.require_parameters`
  and `reasoning.effort = minimal`: 1,066 prompt / 153 completion tokens, $0.000496, 1.7 s; the
  answer validated against `QueryPlan` on the first try.

## Notes

- The field is `SmartQuery.models_used`, not `models`: a field named `models` would shadow
  `django.db.models` inside the class body.
- Throttle scopes for the endpoint arrive with the endpoint (Phase 4), so the contract test that
  asserts the exact rates dict stays truthful until then.
- Both caps live in the cache's Redis database, which the autouse `reset_throttles` fixture flushes
  between tests.

Next: Phase 2 — `Passage` table over the existing chunks, light stemmer, build/embed commands,
hybrid retrieval.
