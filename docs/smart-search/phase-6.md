# Phase 6 — Eval and tuning (2026-09-02, tooling landed; the run is pending)

Branch `smart/phase-6-eval`, stacked on Phase 5. This phase ships the harness; the numbers come
from running it against production data once Phases 2–4 are deployed and the passages are built and
embedded. `SMART_ENABLED` stays off until the gates below pass.

## Tooling

- **Golden set** `search/smart/eval/golden.jsonl`: one object per line —
  `{ "id", "question", "expected_segment_ids": [Segment ids], "expected_status":
  "answered"|"partial"|"not_found", "tags": [...], "notes": "" }`. An abstention item has
  `expected_status: "not_found"` and no ids. Target 60–100 items written by the owner: real
  questions readers ask (opinions, tafseer of a phrase, stories, literal phrases) plus 10–15
  abstention cases (personal rulings, off-corpus topics). Three placeholders are committed.
- **`manage.py smart_label "<question>" [-k 40] [--no-llm] [--json]`** — retrieval only; lists the
  segments behind the fused candidates once each with title, surah/ayahs and an excerpt, so
  `expected_segment_ids` can be picked in seconds.
- **`manage.py smart_eval --stage retrieval|rerank|full [--golden path] [--limit N] [--out
  report.json] [-k] [--no-llm] [--judge]`**:
  * `retrieval` — recall@k and MRR of the expected segment over the fused list;
  * `rerank` — the same over the top 8 the generator would read (`retrieval_hit_rank` kept);
  * `full` — the whole pipeline per item: status vs expected (abstention accuracy + confusion
    matrix), citation validity (quotes the verifier kept ÷ quotes the generator wrote), citations
    per answer, latency p50/p95, cost per query; with `--judge` a frontier model
    (`SMART_JUDGE_MODEL`, default `google/gemini-3.8-flash`, budget check off) marks every sentence
    supported / unsupported / contradicted (`search/smart/eval/judge.py`, prompt `judge.v1.md`).
    The report ends with the gates.
- **Report** (`search/smart/eval/report.py`): `summarize()` and `gates()` are pure and tested.
  Reports carry ids and numbers only; commit them as `docs/smart-search/eval-<YYYY-MM-DD>[-label].json`.

## Ship gates (`report.GATES`)

| Gate | Threshold |
|---|---|
| recall@8 (expected segment among the passages read) | ≥ 0.80 |
| abstention accuracy (`not_found` exactly when expected) | ≥ 0.90 |
| citation validity | ≥ 0.95 |
| unsupported sentences (judge) | ≤ 5 % |
| latency p95 | ≤ 15 s |

## Running it (after the Phase 2 rollout)

```bash
# label
docker run --rm ... --entrypoint python sharawyarchive-backend manage.py smart_label "ما رأي الشيخ في نجاة والدي النبي"
# measure
docker run --rm ... manage.py smart_eval --stage retrieval --out docs/smart-search/eval-<date>-retrieval.json
docker run --rm ... manage.py smart_eval --stage full --judge --out docs/smart-search/eval-<date>.json
```

Tuning knobs, in the order to try them: the stop-word list and `light_stem` (lexical recall),
`SMART_QUOTE_MIN_SCORE` (citation validity vs. recall of colloquial quotes), reranker `KEEP_SCORE`
and `TOP_N`, the context word budget, and the prompts (bump `PROMPT_VERSION` so the cache and the
reports stay comparable).
