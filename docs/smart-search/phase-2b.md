# Phase 2b — Exact-mode tweaks (2026-09-02)

Branch `smart/phase-2b-exact-mode`, stacked on Phase 2. A small change to «بحث دقيق» that reuses the
Phase 2 stemmer; API_CONTRACT.md amendment 14.

## What changed

- **Stem tier in the verifier** (`search/matching.py`): a document word whose light stem equals the
  query word's (`بالصبر` for `الصبر`, `المومنين` for `مؤمن`, `بالله` for `الله`) now matches, counted
  in `PhraseMatch.stems` and ranked after every typo match (`_verify` sorts by stems, then typos, then
  Meilisearch rank). The typo tiers are tried first, so a stem match never hides a cheaper typo match.
  Thresholds stay 4/8 and the first-letter rule of the typo tier is untouched.
- **Quotes** (`matching.parse_query`): words inside `"…"`, `«…»` or `“…”` are *strict* — no typos, no
  stems. Parsed on the raw query before normalization; an unclosed quote is punctuation.
- **`text_stem` in the chunk index** (`search/services.py`): every chunk document carries the light
  stem of each word (no stop-word removal — exact search keeps every slot), and
  `searchableAttributes` is `["text_normalized", "text_stem"]`. When stemming changes any unquoted
  query word, `lexical_search` runs a second Meilisearch query with the stemmed words and appends its
  new candidates behind the raw pool. Without it a chunk that only says `بالصبر` was never a candidate
  for `الصبر`: Meilisearch tokenizes the clitic as part of the word.
- The verse index is unchanged (no `text_stem`), but its verifier applies the same quote rule and
  stem tier over the candidates Meilisearch already returns.
- **Stemmer fix** (`corpus/arabic.py`): a bare `و` is no longer stripped on its own (وحده stayed
  وحده in the index but became حده in `text_stem`); like `ب/ف/ك/ل` it is a clitic only before `ال`.

## Production

`ensure_chunks_index()` reapplies the settings on the next `index_chunks` run; **prod needs one
`manage.py index_chunks` after this deploy** so every document gains `text_stem`. Until then the
stemmed second query finds nothing extra and search behaves exactly as before.

## Tests

`test_matching.py` (stem tier, strict words, ranking by stems then typos, `parse_query` with all
three quote styles, `stem_words`), `test_meili.py` (attribute list, `text_stem` in the document,
`الله` ↔ `بالله`, the clitic-only chunk reached by `الصبر`/`صبر` and ranked last, quoted words exact,
typo matches above stem matches), `corpus/tests/test_arabic.py` (وحده, والله).
