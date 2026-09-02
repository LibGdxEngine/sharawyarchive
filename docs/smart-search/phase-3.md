# Phase 3 — Plan, rerank, context (2026-09-02)

Branch `smart/phase-3-plan-rerank-context`, stacked on Phase 2b. Three more stages of the pipeline,
all advisory: each one degrades to something that still works rather than failing the request.

## What landed

- **Planner** (`search/smart/planner.py`): `plan(question, deadline)` asks the planner model (strict
  `QueryPlan` schema, `reasoning.effort = minimal`, 8 s) and returns a `PlanResult`. `tidy_plan()`
  dedupes rewrites in index form and drops the question itself (cap 5), caps keywords (8), keeps only
  `ayah_refs` that exist in the canonical `quran.Ayah` table, and discards an impossible
  `surah_hint`. Any `LLMError` (provider, schema, budget, deadline) → `naive_plan()` — the question
  as the only query — with `warning = "planner: …"`; retrieval never waits on a plan.
- **Reranker** (`search/smart/rerank.py`): `Reranker` protocol; `LLMListwiseReranker` renders
  candidates as `<c id="17">header\ntext≤220 words</c>`, scores them 0–3 in batches of 20 (two
  threads), keeps score ≥ 2 ordered by (score, rrf), top 8. Fewer than two survivors → the fused top 3
  is passed on with `weak_evidence=True`. Unknown ids and out-of-range scores are ignored. A failed
  batch → fused order with `warning = "rerank: …"`; under 20 s of request budget the stage is
  `skipped`. `NoopReranker` = fused order (tests, `--no-llm`).
- **Context** (`search/smart/context.py`): `assemble(reranked)` widens each seed by one passage on
  either side in its transcript, merges overlapping windows of one transcript, rebuilds the text from
  the underlying chunks (so the one-chunk passage overlap is never rendered twice), trims a window to
  450 words around its seed, spends a 3,600-word budget in rerank order, and returns the survivors in
  corpus order as `p1…pN` with their chunk-index and millisecond spans. `render()` emits
  `<passage id="p1" segment_id title surah ayahs start_ms end_ms>` blocks with `normalize_light()`
  text (letters intact, harakat removed: fewer tokens, steadier verbatim quotes).
- **`smart_eval --stage rerank`**: retrieval → reranker → recall@8 / MRR over what the generator
  would read; reports carry `retrieval_hit_rank` next to `hit_rank` and the count of weak-evidence
  items. `--no-llm` uses `NoopReranker`.
- **Tests**: `test_smart_planner.py` (tidying, validation against the mushaf, every fallback),
  `test_smart_rerank.py` (rendering cap, ordering, batching and top-8, weak evidence, ignored ids,
  fallback, deadline skip, noop), `test_smart_context.py` (widening, merging, ordering and ids,
  trimming, budget, rendering), plus the rerank stage of `smart_eval`. Backend suite: 883 passed.

## Failure policy (recorded for Phase 4)

Planner failure and reranker failure/skip are each a `debug.warnings` entry; neither alone makes the
response `degraded`. Only generation failing to produce a verified answer does.
