# Phase 2 — Retrieval (2026-09-02)

Branch `smart/phase-2-retrieval`, stacked on Phase 1. Still nothing user-visible: the tables are
empty until the corpus jobs below run, and no endpoint exists yet.

## What landed

- **Light stemmer** (`corpus/arabic.py`): `light_stem()` strips one clitic prefix
  (`وال بال فال كال لل ال`, and a lone `و/ب/ف/ك/ل` only when the article follows: بالله → الله;
  a bare letter is too often a radical — وحده, كتاب — to strip alone) and
  one suffix (`ها هم كم نا ات ون ين`), only while ≥ 3 letters remain, so كتاب stays كتاب and الله
  stays الله. `stem_text()` stems every token and drops a curated `STOP_WORDS` set (index form).
  Postgres' Snowball `arabic` was verified not to strip clitics, so the index uses the `simple`
  config over our own stems on both sides.
- **`search.Passage`** (migration `0002_passage`): the retrieval unit — a 150–300-word window of
  consecutive chunks of one transcript, cut at the widest silence gap, one-chunk overlap between
  neighbours, tiny tails folded back. Denormalised `segment`, `surah`, `ayah_start/end` for filters;
  `header` («title — سورة X: الآيات a–b — source»), `text`, `text_normalized`, `text_stem`;
  `tsv` is a persisted `GeneratedField` (`to_tsvector('simple', text_stem)`) under a GIN index;
  `embedding` is `halfvec(1024)` under an HNSW cosine index; `content_hash`, `embedded_hash`,
  `embedding_model` («model@dims») make every job idempotent. `Chunk` is untouched.
- **Builder** (`search/smart/passages.py`): pure `plan_windows()` plus `build_for_transcript()`,
  which skips a transcript whose `(ordinal, hash)` list is unchanged, otherwise rewrites its
  passages carrying over any embedding whose hash still matches. `corpus.corrections.approve()`
  now queues `refresh_for_chunks()` next to the Meilisearch reindex, so an approved correction
  rewrites the covering passage and its hash (the next embed run re-embeds exactly that).
- **Retrieval** (`search/smart/retrieval.py`): lexical (all-stems `&` first, then any-stem `|`,
  `ts_rank_cd`), semantic (`CosineDistance` inside `hnsw_scan()`, which raises `hnsw.ef_search` and
  turns on `iterative_scan = relaxed_order` so filtered scans cannot underfetch; rows from another
  model tag never take part), ayah-anchored (segments covering the planner's `ayah_refs`, ordered by
  similarity), fused by reciprocal rank with the reader's own question weighted ×2 and a total
  deterministic order. Query vectors carry the Qwen instruction prefix; one embed call per request.
  An embedding failure degrades to lexical-only and is recorded as a warning, never raised.
- **Commands**: `build_passages [--transcript|--segment|--limit|--rebuild|--dry-run]`,
  `embed_passages [--batch-size 48|--limit|--transcript|--force|--max-cost-usd 2|--dry-run]`
  (stale = missing vector, hash mismatch, or other model; hash-guarded writes per batch; a failing
  batch is skipped and picked up next run), `smart_retrieve "<q>" [--surah|--source|-k|--no-llm|--json]`,
  `smart_eval --stage retrieval [--golden|--limit|--out|-k|--no-llm]` over
  `search/smart/eval/golden.jsonl` (three placeholder items; reports carry ids and numbers only).
- **Tests** (`search/tests/test_smart_passages.py`, `test_smart_retrieval.py`,
  `test_smart_commands.py`, plus the stemmer table in `corpus/tests/test_arabic.py`): planner
  shapes, build idempotency and embedding carry-over, the correction hook (on-commit callbacks
  executed), clitic recall (الصبر finds بالصبر), stop-word-only queries, filters, HNSW GUCs and
  clamping, ayah anchoring, RRF arithmetic and tie-breaks, degraded retrieval, and every command's
  output and resumability against a respx-faked provider. Backend suite: 832 passed.

## Design notes

- The planner absorbs the transcript's last chunk only while it stays within `max_words`;
  otherwise the tail becomes its own window (and merges back if it is under half `min_words`).
- `header` is part of both the hash and the embedded text: a retitled segment re-embeds.
- `embed_passages` embeds `header + "\n" + normalize_light(text)` (letters intact, harakat removed:
  fewer tokens, same words readers type).
- Sizing: ~25–30k passages × 1024 fp16 ≈ 55 MB plus a small HNSW graph; embedding the corpus is
  ≈ $0.15 at qwen3-embedding-8b prices, capped by `--max-cost-usd`.

## Production rollout (after merge)

See `DEPLOY.md` §6b. Deploy (the migration creates empty tables, flag stays off), then in a
throwaway runner: `build_passages`, `embed_passages --dry-run`, `embed_passages`. Verify with
`smart_retrieve "ما رأي الشيخ في نجاة والدي النبي" --json` and an `EXPLAIN` that names
`passage_embedding_hnsw`.
