"""Strict phrase verification for search hits.

Meilisearch is the candidate generator; this module is the gate. A candidate
survives only when every query word appears in the document **consecutively
and in order**, each within a typo budget that depends on the *query* word's
length::

    letters   edits allowed
    1-3       0   (exact)
    4-7       1
    8+        2

An edit is an insertion, deletion, substitution or adjacent transposition
(optimal string alignment distance). The first letter must always match:
Meilisearch charges a first-letter typo as two edits and, verified live on
v1.15, does not reliably retrieve such words at all, so tolerating them here
would only make results depend on which words the engine happened to return.

Below the typo tiers sits one more: a document word whose **light stem**
(:func:`corpus.arabic.light_stem`) equals the query word's — ``بالصبر`` for
``الصبر``, ``المومنين`` for ``مومن``. Such matches are counted separately and
rank after every typo match. Words the reader wrapped in quotes are *strict*:
no typos, no stems.

Everything here operates on ``corpus.arabic.normalize_for_index`` output —
both the query and the indexed ``text_normalized`` (CLAUDE.md rule 2). The
module is pure Python with no Django or Meilisearch imports so that it can be
unit-tested in isolation.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

from corpus.arabic import MIN_STEM_LETTERS, light_stem, normalize_for_index

__all__ = [
    "ONE_TYPO_MIN_LETTERS",
    "PhraseMatch",
    "QueryWord",
    "TWO_TYPOS_MIN_LETTERS",
    "edit_distance",
    "parse_query",
    "phrase_match",
    "stem_match",
    "stem_words",
    "tokenize",
    "typo_budget",
    "typo_cost",
    "word_cost",
]

ONE_TYPO_MIN_LETTERS = 4
"""Query words of this many letters or more may carry one edit."""

TWO_TYPOS_MIN_LETTERS = 8
"""Query words of this many letters or more may carry two edits."""

_WORD_RE = re.compile(r"\w+")

_QUOTED_RE = re.compile(r'"([^"]*)"|«([^»]*)»|“([^”]*)”')
"""A quoted span in a raw query: ASCII, guillemets or curly double quotes.
An unclosed quote is punctuation and is dropped by :func:`tokenize`."""


@dataclass(frozen=True)
class QueryWord:
    """One query word in index form; ``strict`` words match exactly."""

    text: str
    strict: bool = False


def parse_query(raw: str) -> list[QueryWord]:
    """The reader's query as index-form words, quoted words marked strict.

    ``الصبر "عند الصدمة"`` → ``الصبر`` (typos and stems allowed), ``عند`` and
    ``الصدمه`` (exact). The quotes are read before normalization, which is
    per-character and so unaffected by the split.
    """
    words: list[QueryWord] = []
    last = 0
    for match in _QUOTED_RE.finditer(raw):
        words.extend(QueryWord(t) for t in tokenize(normalize_for_index(raw[last : match.start()])))
        quoted = next(group for group in match.groups() if group is not None)
        words.extend(QueryWord(t, strict=True) for t in tokenize(normalize_for_index(quoted)))
        last = match.end()
    words.extend(QueryWord(t) for t in tokenize(normalize_for_index(raw[last:])))
    return words


def stem_words(normalized: str) -> str:
    """``normalized`` with every word light-stemmed, for the index's ``text_stem``.

    No stop words are dropped: exact search is a phrase search and every
    word, however small, keeps its slot.
    """
    return " ".join(light_stem(token) for token in tokenize(normalized))


def tokenize(normalized: str) -> list[str]:
    """Split already-normalized text into words.

    Runs of word characters are tokens; whitespace and punctuation are
    separators, which is how Meilisearch's tokenizer treats them too:
    ``"الصبر، عند"`` → ``["الصبر", "عند"]`` and ``"2:255"`` → ``["2", "255"]``.
    """
    return _WORD_RE.findall(normalized)


def typo_budget(word: str) -> int:
    """Edits allowed for a query word of this length."""
    letters = len(word)
    if letters >= TWO_TYPOS_MIN_LETTERS:
        return 2
    if letters >= ONE_TYPO_MIN_LETTERS:
        return 1
    return 0


def edit_distance(a: str, b: str, *, limit: int) -> int:
    """Optimal string alignment distance between ``a`` and ``b``, capped.

    Insertion, deletion, substitution and adjacent transposition each cost
    one. Returns ``limit + 1`` as soon as the distance is known to exceed
    ``limit`` (row minima never decrease, so a row whose minimum passes the
    limit ends the search early).
    """
    if a == b:
        return 0
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    len_b = len(b)
    two_back: list[int] | None = None
    previous = list(range(len_b + 1))
    for i in range(1, len(a) + 1):
        current = [i] + [0] * len_b
        char_a = a[i - 1]
        row_min = i
        for j in range(1, len_b + 1):
            char_b = b[j - 1]
            value = min(
                previous[j] + 1,  # delete from a
                current[j - 1] + 1,  # insert into a
                previous[j - 1] + (0 if char_a == char_b else 1),  # substitute
            )
            if (
                two_back is not None
                and j > 1
                and char_a == b[j - 2]
                and a[i - 2] == char_b
            ):
                value = min(value, two_back[j - 2] + 1)  # transpose
            current[j] = value
            if value < row_min:
                row_min = value
        if row_min > limit:
            return limit + 1
        two_back, previous = previous, current
    distance = previous[len_b]
    return distance if distance <= limit else limit + 1


@lru_cache(maxsize=1 << 16)
def typo_cost(query_word: str, doc_word: str) -> int | None:
    """Edits needed to read ``doc_word`` as ``query_word``, or ``None`` when
    that takes more than the query word's budget or changes its first letter.

    Cached because the same document words recur thousands of times across a
    candidate pool.
    """
    if query_word == doc_word:
        return 0
    budget = typo_budget(query_word)
    if budget == 0 or abs(len(query_word) - len(doc_word)) > budget:
        return None
    if query_word[0] != doc_word[0]:
        return None
    distance = edit_distance(query_word, doc_word, limit=budget)
    return distance if distance <= budget else None


@lru_cache(maxsize=1 << 16)
def stem_match(query_word: str, doc_word: str) -> bool:
    """Whether two different words share a light stem of usable length.

    ``الصبر`` / ``بالصبر`` / ``والصبر`` all stem to ``صبر``; ``الله`` and
    ``بالله`` both to ``الله``. Equal words are the typo tier's business.
    """
    if query_word == doc_word:
        return False
    stem = light_stem(query_word)
    return len(stem) >= MIN_STEM_LETTERS and stem == light_stem(doc_word)


def word_cost(word: QueryWord, doc_word: str) -> tuple[int, int] | None:
    """``(stems, typos)`` needed to read ``doc_word`` as ``word``, or ``None``.

    A strict word only matches itself. Otherwise the typo tiers are tried
    first and the stem tier only when they fail, so a stem match never hides
    a cheaper typo match.
    """
    if word.strict:
        return (0, 0) if word.text == doc_word else None
    cost = typo_cost(word.text, doc_word)
    if cost is not None:
        return (0, cost)
    if stem_match(word.text, doc_word):
        return (1, 0)
    return None


@dataclass(frozen=True)
class PhraseMatch:
    """Where a query phrase sits in a document and what it cost to read it there."""

    typos: int
    start: int
    stems: int = 0
    """Words matched through the stem tier only — ranked after every typo."""

    @property
    def cost(self) -> tuple[int, int]:
        return (self.stems, self.typos)


def phrase_match(query_tokens: Sequence[str | QueryWord], doc_text: str) -> PhraseMatch | None:
    """Best contiguous, in-order occurrence of ``query_tokens`` in ``doc_text``.

    Slides a window the length of the query over the document's tokens; every
    position must fit its word's typo budget or share its stem (strict words
    must be identical). The window with the fewest stem matches wins, then the
    fewest edits, then the earliest. ``None`` when nothing fits or the query is
    empty. Plain strings are non-strict words.
    """
    if not query_tokens:
        return None
    words = [word if isinstance(word, QueryWord) else QueryWord(word) for word in query_tokens]
    doc_tokens = tokenize(doc_text)
    width = len(words)
    best: PhraseMatch | None = None
    for start in range(len(doc_tokens) - width + 1):
        stems = typos = 0
        for offset, word in enumerate(words):
            cost = word_cost(word, doc_tokens[start + offset])
            if cost is None:
                break
            stems += cost[0]
            typos += cost[1]
            if best is not None and (stems, typos) >= best.cost:
                break
        else:
            best = PhraseMatch(typos=typos, start=start, stems=stems)
            if stems == 0 and typos == 0:
                break
    return best
