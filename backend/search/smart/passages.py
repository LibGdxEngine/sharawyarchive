"""Building the retrieval unit — :class:`search.models.Passage` — over the chunks.

A passage is a window of consecutive :class:`corpus.Chunk` rows of one
transcript, 150–300 words long, closed at the largest silence gap the window
can reach, with a one-chunk overlap between neighbours so that no thought is
cut at a boundary without also appearing whole in the next window. Chunks stay
untouched: they remain the unit of exact search, corrections and clips.

Everything is idempotent by content hash. Rebuilding a transcript whose
passages hash the same is a no-op; when the text did change, embeddings whose
hash still matches are carried over to the new rows so only changed text is
re-embedded (CLAUDE.md rule 6).
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

from django.db import transaction
from django.db.models import QuerySet

from corpus.arabic import normalize_for_index, stem_text
from corpus.models import Chunk, Segment, Transcript
from search.models import Passage

__all__ = [
    "MAX_WORDS",
    "MIN_WORDS",
    "BuildStats",
    "ChunkInfo",
    "Window",
    "build_for_transcript",
    "content_hash",
    "header_for",
    "hydrate",
    "plan_windows",
    "refresh_for_chunks",
    "transcripts_with_chunks",
]

MIN_WORDS = 150
MAX_WORDS = 300
OVERLAP_CHUNKS = 1
TAIL_MERGE_FRACTION = 0.5
"""A final window shorter than this fraction of ``min_words`` is folded into the one before."""


@dataclass(frozen=True)
class ChunkInfo:
    """What the planner needs to know about one chunk."""

    idx: int
    start_ms: int
    end_ms: int
    words: int


@dataclass(frozen=True)
class Window:
    """Inclusive positions into the chunk sequence handed to :func:`plan_windows`."""

    first: int
    last: int


@dataclass
class BuildStats:
    transcripts: int = 0
    created: int = 0
    deleted: int = 0
    unchanged: int = 0
    carried: int = 0
    """Embeddings copied from the old rows because the text did not change."""

    def __iadd__(self, other: BuildStats) -> BuildStats:
        self.transcripts += other.transcripts
        self.created += other.created
        self.deleted += other.deleted
        self.unchanged += other.unchanged
        self.carried += other.carried
        return self


def plan_windows(
    chunks: Sequence[ChunkInfo],
    *,
    min_words: int = MIN_WORDS,
    max_words: int = MAX_WORDS,
    overlap_chunks: int = OVERLAP_CHUNKS,
) -> list[Window]:
    """Cut ``chunks`` (in transcript order) into passage windows.

    A window grows until it holds ``min_words``; from there every chunk edge
    up to ``max_words`` is a candidate boundary and the one with the widest
    silence gap wins. The next window starts ``overlap_chunks`` before the
    boundary (never before the previous window's own first chunk). A single
    chunk longer than ``max_words`` is a window of its own. A final window
    shorter than half ``min_words`` is folded into the one before it.
    """
    count = len(chunks)
    if count == 0:
        return []
    windows: list[Window] = []
    first = 0
    while first < count:
        words = 0
        best: int | None = None
        best_gap = -1
        for position in range(first, count):
            words += chunks[position].words
            if words < min_words:
                continue
            if position == count - 1:
                # The end of the transcript closes the window — unless taking
                # the last chunk would overshoot max_words while an earlier
                # edge already qualified; then the tail becomes its own window.
                if best is None or words <= max_words:
                    best = position
                break
            gap = chunks[position + 1].start_ms - chunks[position].end_ms
            if gap > best_gap:
                best, best_gap = position, gap
            if words >= max_words:
                break
        if best is None:  # the transcript ended before min_words was reached
            best = count - 1
        windows.append(Window(first, best))
        if best >= count - 1:
            break
        next_first = best - overlap_chunks + 1
        first = next_first if next_first > first else best + 1

    if len(windows) >= 2:
        previous, tail = windows[-2], windows[-1]
        own = chunks[previous.last + 1 : tail.last + 1]
        if sum(chunk.words for chunk in own) < min_words * TAIL_MERGE_FRACTION:
            windows[-2] = Window(previous.first, tail.last)
            windows.pop()
    return windows


def header_for(segment: Segment) -> str:
    """The metadata line embedded and shown with every passage of ``segment``."""
    parts = [segment.title.strip() or f"مقطع {segment.pk}"]
    if segment.surah_id is not None:
        label = f"سورة {segment.surah.name_ar}"
        if segment.ayah_start is not None and segment.ayah_end is not None:
            label += f": الآيات {segment.ayah_start}–{segment.ayah_end}"
        parts.append(label)
    parts.append(segment.source.title)
    return " — ".join(parts)[:300]


def content_hash(header: str, text_normalized: str) -> str:
    return hashlib.sha256(f"{header}\n{text_normalized}".encode()).hexdigest()


def _plan(transcript: Transcript, chunks: Sequence[Chunk], **planner: int) -> list[Passage]:
    segment = transcript.segment
    header = header_for(segment)
    infos = [
        ChunkInfo(
            idx=chunk.idx,
            start_ms=int(chunk.start_ms),
            end_ms=int(chunk.end_ms),
            words=len(chunk.text_normalized.split()),
        )
        for chunk in chunks
    ]
    planned: list[Passage] = []
    for ordinal, window in enumerate(plan_windows(infos, **planner)):
        members = chunks[window.first : window.last + 1]
        text = " ".join(chunk.text for chunk in members)
        text_normalized = " ".join(chunk.text_normalized for chunk in members)
        planned.append(
            Passage(
                transcript=transcript,
                segment=segment,
                surah=segment.surah_id,
                ayah_start=segment.ayah_start,
                ayah_end=segment.ayah_end,
                ordinal=ordinal,
                chunk_idx_start=members[0].idx,
                chunk_idx_end=members[-1].idx,
                start_ms=int(members[0].start_ms),
                end_ms=int(members[-1].end_ms),
                word_count=sum(len(chunk.text_normalized.split()) for chunk in members),
                header=header,
                text=text,
                text_normalized=text_normalized,
                text_stem=stem_text(normalize_for_index(header) + " " + text_normalized),
                content_hash=content_hash(header, text_normalized),
            )
        )
    return planned


def build_for_transcript(
    transcript: Transcript,
    *,
    dry_run: bool = False,
    force: bool = False,
    min_words: int = MIN_WORDS,
    max_words: int = MAX_WORDS,
) -> BuildStats:
    """Create, refresh or leave alone the passages of one transcript.

    ``transcript`` should come with ``segment__surah`` and ``segment__source``
    selected. Nothing is written when the planned ``(ordinal, content_hash)``
    list equals what is stored, unless ``force`` is set.
    """
    stats = BuildStats(transcripts=1)
    chunks = list(transcript.chunks.order_by("idx"))
    planned = _plan(transcript, chunks, min_words=min_words, max_words=max_words) if chunks else []
    existing = list(transcript.passages.order_by("ordinal"))
    same = [(row.ordinal, row.content_hash) for row in existing] == [
        (row.ordinal, row.content_hash) for row in planned
    ]
    if same and not force:
        stats.unchanged = len(existing)
        return stats

    carry = {
        row.embedded_hash: row
        for row in existing
        if row.embedding is not None and row.embedded_hash
    }
    for row in planned:
        old = carry.get(row.content_hash)
        if old is not None:
            row.embedding = old.embedding
            row.embedding_model = old.embedding_model
            row.embedded_hash = old.embedded_hash
            row.embedded_at = old.embedded_at
            stats.carried += 1
    stats.created = len(planned)
    stats.deleted = len(existing)
    if dry_run:
        return stats
    with transaction.atomic():
        transcript.passages.all().delete()
        Passage.objects.bulk_create(planned, batch_size=500)
    return stats


def transcripts_with_chunks() -> QuerySet[Transcript]:
    """Every transcript that has chunks, with what the builder needs preloaded."""
    return (
        Transcript.objects.filter(chunks__isnull=False)
        .distinct()
        .select_related("segment__surah", "segment__source")
        .order_by("pk")
    )


def refresh_for_chunks(chunk_ids: Sequence[int]) -> BuildStats:
    """Rebuild the passages of every transcript owning one of ``chunk_ids``.

    Called after a correction is approved: the chunk text changed, so the
    covering passages' text and hash change with it and the next
    ``embed_passages`` run re-embeds exactly those.
    """
    stats = BuildStats()
    transcript_ids = (
        Chunk.objects.filter(pk__in=list(chunk_ids))
        .values_list("transcript_id", flat=True)
        .distinct()
    )
    for transcript in transcripts_with_chunks().filter(pk__in=list(transcript_ids)):
        stats += build_for_transcript(transcript)
    return stats


def hydrate(passage_ids: Sequence[int]) -> list[Passage]:
    """The passages for ``passage_ids`` in the same order, segment and surah preloaded."""
    rows = {
        row.pk: row
        for row in Passage.objects.filter(pk__in=list(passage_ids)).select_related(
            "segment__surah", "segment__source"
        )
    }
    return [rows[pk] for pk in passage_ids if pk in rows]
