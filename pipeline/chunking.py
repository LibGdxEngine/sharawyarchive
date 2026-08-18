"""Turn a word stream into 20-45s retrievable passages.

Pure functions, no Django, no I/O — the rules from ``SHAARAWY_PROJECT_PLAN.md``
Phase 2 and nothing else:

* split at a word boundary when the gap to the next word exceeds ``gap_ms``
  **and** the chunk already covers ``min_ms``;
* split unconditionally once the chunk reaches ``max_ms``;
* for ``kind='recitation'`` with known ayah starts, splits may only happen at an
  ayah start — a chunk is allowed to run past ``max_ms`` rather than cut an ayah
  in half (project rule: never split mid-ayah).

The returned spans are contiguous and cover every input word exactly once.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

GAP_MS = 400
MIN_MS = 20_000
MAX_MS = 45_000

RECITATION = "recitation"


@dataclass(frozen=True)
class WordSpan:
    """One timed word. Milliseconds, always integers."""

    text: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class ChunkSpan:
    """A half-open word range ``[start_index, end_index)`` and its ms bounds."""

    start_index: int
    end_index: int
    start_ms: int
    end_ms: int

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms

    def words(self, words: Sequence[WordSpan]) -> Sequence[WordSpan]:
        return words[self.start_index : self.end_index]


def plan_chunks(
    words: Sequence[WordSpan],
    *,
    kind: str,
    ayah_starts: Iterable[int] | None = None,
    gap_ms: int = GAP_MS,
    min_ms: int = MIN_MS,
    max_ms: int = MAX_MS,
) -> list[ChunkSpan]:
    """Plan the chunk boundaries for ``words``.

    ``ayah_starts`` are word indices at which an ayah begins. They only
    constrain ``kind='recitation'``; for khawatir there are no ayah boundaries
    to respect and the argument is ignored.
    """
    if not words:
        return []

    restricted = kind == RECITATION and ayah_starts is not None
    allowed = set(ayah_starts) if restricted else set()

    chunks: list[ChunkSpan] = []
    start_index = 0
    start_ms = int(words[0].start_ms)

    for index in range(len(words) - 1):
        current = words[index]
        following = words[index + 1]
        covered = int(current.end_ms) - start_ms
        gap = int(following.start_ms) - int(current.end_ms)

        wants_split = (gap > gap_ms and covered >= min_ms) or covered >= max_ms
        if not wants_split:
            continue
        # A recitation chunk may only end where the next ayah begins.
        if restricted and (index + 1) not in allowed:
            continue

        chunks.append(
            ChunkSpan(
                start_index=start_index,
                end_index=index + 1,
                start_ms=start_ms,
                end_ms=int(current.end_ms),
            )
        )
        start_index = index + 1
        start_ms = int(following.start_ms)

    chunks.append(
        ChunkSpan(
            start_index=start_index,
            end_index=len(words),
            start_ms=start_ms,
            end_ms=int(words[-1].end_ms),
        )
    )
    return chunks
