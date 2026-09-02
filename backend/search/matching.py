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

__all__ = [
    "ONE_TYPO_MIN_LETTERS",
    "PhraseMatch",
    "TWO_TYPOS_MIN_LETTERS",
    "edit_distance",
    "phrase_match",
    "tokenize",
    "typo_budget",
    "typo_cost",
]

ONE_TYPO_MIN_LETTERS = 4
"""Query words of this many letters or more may carry one edit."""

TWO_TYPOS_MIN_LETTERS = 8
"""Query words of this many letters or more may carry two edits."""

_WORD_RE = re.compile(r"\w+")


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


@dataclass(frozen=True)
class PhraseMatch:
    """Where a query phrase sits in a document and how many edits it took."""

    typos: int
    start: int


def phrase_match(query_tokens: Sequence[str], doc_text: str) -> PhraseMatch | None:
    """Best contiguous, in-order occurrence of ``query_tokens`` in ``doc_text``.

    Slides a window the length of the query over the document's tokens; every
    position must fit its word's typo budget. The window with the fewest total
    edits wins, the earliest on a tie. ``None`` when nothing fits or the query
    is empty.
    """
    if not query_tokens:
        return None
    doc_tokens = tokenize(doc_text)
    width = len(query_tokens)
    best: PhraseMatch | None = None
    for start in range(len(doc_tokens) - width + 1):
        total = 0
        for offset, word in enumerate(query_tokens):
            cost = typo_cost(word, doc_tokens[start + offset])
            if cost is None:
                break
            total += cost
            if best is not None and total >= best.typos:
                break
        else:
            best = PhraseMatch(typos=total, start=start)
            if total == 0:
                break
    return best
