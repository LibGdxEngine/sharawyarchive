"""Stage 4 — the context window the generator reads.

Each reranked passage is widened by one passage on either side of it in its
transcript, overlapping windows of one transcript are merged, and the text is
rebuilt from the underlying chunks (so the one-chunk overlap between passages
is never rendered twice). Windows are capped in words and the whole context in
words too. Every window keeps its chunk-index and millisecond span, which is
what the verifier later uses to place a quoted span on the audio.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from corpus.arabic import normalize_light
from corpus.models import Chunk
from search.models import Passage

from .schemas import ContextPassage, RerankedPassage

__all__ = ["EXPAND_PASSAGES", "MAX_CONTEXT_WORDS", "MAX_PASSAGE_WORDS", "assemble", "render"]

EXPAND_PASSAGES = 1
MAX_PASSAGE_WORDS = 450
MAX_CONTEXT_WORDS = 3600
"""≈ 9k tokens of Arabic — what the generator can read comfortably in one go."""


@dataclass
class _Window:
    seed: Passage
    priority: int
    idx_start: int
    idx_end: int

    def overlaps(self, other: _Window) -> bool:
        return self.idx_start <= other.idx_end + 1 and other.idx_start <= self.idx_end + 1


def _windows(reranked: Sequence[RerankedPassage]) -> list[_Window]:
    """One window per seed passage, widened by its neighbours, merged per transcript."""
    ids = [row.passage_id for row in reranked]
    seeds = {
        row.pk: row
        for row in Passage.objects.filter(pk__in=ids).select_related("segment__surah")
    }
    windows: list[_Window] = []
    for priority, passage_id in enumerate(ids):
        seed = seeds.get(passage_id)
        if seed is None:
            continue
        neighbours = Passage.objects.filter(
            transcript_id=seed.transcript_id,
            ordinal__gte=seed.ordinal - EXPAND_PASSAGES,
            ordinal__lte=seed.ordinal + EXPAND_PASSAGES,
        ).values_list("chunk_idx_start", "chunk_idx_end")
        idx_start, idx_end = seed.chunk_idx_start, seed.chunk_idx_end
        for start, end in neighbours:
            idx_start, idx_end = min(idx_start, start), max(idx_end, end)
        window = _Window(seed, priority, idx_start, idx_end)
        for existing in windows:
            if existing.seed.transcript_id == seed.transcript_id and existing.overlaps(window):
                existing.idx_start = min(existing.idx_start, window.idx_start)
                existing.idx_end = max(existing.idx_end, window.idx_end)
                break
        else:
            windows.append(window)
    return windows


def _trim(chunks: list[Chunk], seed: Passage, limit: int) -> list[Chunk]:
    """Drop chunks from whichever end is farther from the seed until ``limit`` words remain."""
    words = [len(chunk.text.split()) for chunk in chunks]
    first, last = 0, len(chunks) - 1
    while last > first and sum(words[first : last + 1]) > limit:
        if chunks[first].idx < seed.chunk_idx_start:
            first += 1
        elif chunks[last].idx > seed.chunk_idx_end:
            last -= 1
        else:
            break  # the seed alone is over the limit: keep it whole
    return chunks[first : last + 1]


def assemble(reranked: Sequence[RerankedPassage]) -> list[ContextPassage]:
    """Context windows for ``reranked`` (best first), returned in corpus order.

    The word budget is spent in rerank order, so when it runs out it is the
    weakest windows that are dropped; the survivors are then ordered by
    segment and time and numbered ``p1``… in that order.
    """
    chosen: list[tuple[_Window, list[Chunk]]] = []
    budget = MAX_CONTEXT_WORDS
    for window in sorted(_windows(reranked), key=lambda w: w.priority):
        chunks = list(
            Chunk.objects.filter(
                transcript_id=window.seed.transcript_id,
                idx__gte=window.idx_start,
                idx__lte=window.idx_end,
            ).order_by("idx")
        )
        chunks = _trim(chunks, window.seed, MAX_PASSAGE_WORDS)
        if not chunks:
            continue
        words = sum(len(chunk.text.split()) for chunk in chunks)
        if words > budget:
            continue
        budget -= words
        chosen.append((window, chunks))

    chosen.sort(key=lambda item: (item[0].seed.segment_id, item[1][0].start_ms))
    passages: list[ContextPassage] = []
    for number, (window, chunks) in enumerate(chosen, start=1):
        segment = window.seed.segment
        passages.append(
            ContextPassage(
                id=f"p{number}",
                passage_ids=[window.seed.pk],
                transcript_id=window.seed.transcript_id,
                segment_id=segment.pk,
                segment_title=segment.title,
                surah=segment.surah_id,
                ayah_start=segment.ayah_start,
                ayah_end=segment.ayah_end,
                start_ms=int(chunks[0].start_ms),
                end_ms=int(chunks[-1].end_ms),
                chunk_idx_start=chunks[0].idx,
                chunk_idx_end=chunks[-1].idx,
                text=" ".join(chunk.text for chunk in chunks),
            )
        )
    return passages


def _attr(value: object) -> str:
    return str(value).replace('"', "”")


def render(passages: Sequence[ContextPassage]) -> str:
    """``<passage id="p1" …>`` blocks with the letters-only text the generator quotes from."""
    blocks = []
    for passage in passages:
        ayahs = (
            f"{passage.ayah_start}-{passage.ayah_end}"
            if passage.ayah_start is not None and passage.ayah_end is not None
            else ""
        )
        blocks.append(
            f'<passage id="{passage.id}" segment_id="{passage.segment_id}" '
            f'title="{_attr(passage.segment_title)}" surah="{passage.surah or ""}" '
            f'ayahs="{ayahs}" start_ms="{passage.start_ms}" end_ms="{passage.end_ms}">\n'
            f"{normalize_light(passage.text)}\n</passage>"
        )
    return "\n\n".join(blocks)
