"""Applying a reader's correction to a machine transcript (Phase 6).

A :class:`~corpus.models.Correction` is a suggestion, never an edit: the POST
endpoint only queues it. Everything that turns one into corpus state lives
here, so :mod:`corpus.admin` stays a thin review screen.

Word offsets
------------
``Correction.word_start`` / ``word_end`` are **transcript-wide**
``TranscriptWord.idx`` values, inclusive on both ends — a one-word fix has
``word_start == word_end``. They are *not* offsets inside the chunk's text.
The chunk is carried alongside them because the reader selected the words in a
chunk (a search result or a player passage), and it is what bounds the range:
:func:`approve` refuses a range that reaches outside the chunk's own words, so
a submission can never rewrite a part of the transcript the submitter was not
looking at.

A chunk owns the words whose *start* falls in its half-open ``[start_ms,
end_ms)`` span — chunk spans are built from those same word timings by
``pipeline.chunking.plan_chunks``, so the two views agree by construction and
every word belongs to exactly one chunk. :func:`word_range_in_span` is the one
implementation of that rule; ``GET /api/segments/{id}/chunks/`` serves it to
the frontend so a selected word index maps back to the chunk it came from.

Approval
--------
:func:`approve` runs as one transaction:

1. the suggestion is split on whitespace into words;
2. the ``TranscriptWord`` rows in the range are replaced — texts in place when
   the word count matches (timings survive untouched), otherwise the range is
   deleted, the new words are spread evenly over the span the old ones covered
   and every following ``idx`` is renumbered;
3. the transcript's ``raw_text``/``text_normalized``/``word_count`` are
   recomputed, ``version`` is bumped and ``is_human_reviewed`` is set;
4. only the chunks whose span overlaps the edit are rebuilt and re-embedded.

The Meilisearch update is deliberately *not* part of that transaction:
reindexing a row that a later rollback would revert is worse than a search
index that lags by milliseconds, so it is queued with
``transaction.on_commit`` — which also does the right thing when an outer
atomic block (an admin action over several corrections) wraps the call.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from django.db import transaction
from django.db.models import F, Max

from .arabic import normalize_for_index
from .embeddings import get_embedder
from .models import Chunk, Correction, CorrectionStatus, Transcript, TranscriptWord

__all__ = [
    "ApprovalResult",
    "CorrectionError",
    "approve",
    "chunk_word_range",
    "original_text_for",
    "reject",
    "word_range_in_span",
    "word_span_ms",
]

logger = logging.getLogger(__name__)

MAX_WORD_CHARS = 100
"""Matches ``TranscriptWord.text``'s ``max_length``; the pipeline truncates the
same way rather than failing a whole transcript over one runaway token."""


class CorrectionError(ValueError):
    """A correction cannot be applied as submitted."""


@dataclass(frozen=True)
class ApprovalResult:
    """What one approval changed, for the admin message and the log."""

    correction_id: int
    transcript_id: int
    version: int
    """The transcript version *after* the bump."""
    words_replaced: int
    words_written: int
    chunk_ids: tuple[int, ...]
    """The chunks rebuilt, re-embedded and queued for reindexing."""
    reviewed_by: str


# --- Word ranges -------------------------------------------------------------


def word_range_in_span(
    words: Iterable[tuple[int, int]], start_ms: int, end_ms: int
) -> tuple[int, int] | None:
    """First and last word ``idx`` of ``[start_ms, end_ms)``, or ``None``.

    ``words`` are ``(idx, start_ms)`` pairs. Membership is by word *start* so
    that a word straddling a chunk edge lands in exactly one chunk. ``None``
    means the span holds no words at all, which only happens for a chunk that
    was not built from these words.
    """
    matched = [idx for idx, word_start in words if start_ms <= word_start < end_ms]
    if not matched:
        return None
    return min(matched), max(matched)


def chunk_word_range(chunk: Chunk) -> tuple[int, int] | None:
    """The transcript-wide ``idx`` range of the words inside ``chunk``."""
    return word_range_in_span(
        TranscriptWord.objects.filter(transcript_id=chunk.transcript_id).values_list(
            "idx", "start_ms"
        ),
        chunk.start_ms,
        chunk.end_ms,
    )


def _words_in(correction: Correction) -> list[TranscriptWord]:
    return list(
        TranscriptWord.objects.filter(
            transcript_id=correction.chunk.transcript_id,
            idx__gte=correction.word_start,
            idx__lte=correction.word_end,
        ).order_by("idx")
    )


def original_text_for(correction: Correction) -> str:
    """The transcript text the correction proposes to replace, as it stands now.

    Empty when the range no longer resolves to any word (the transcript was
    re-ingested under the submitter's feet), which the review screen renders as
    a dash rather than an error.
    """
    return " ".join(word.text for word in _words_in(correction))


def word_span_ms(correction: Correction) -> tuple[int, int] | None:
    """Audio span ``(start_ms, end_ms)`` of the corrected words, or ``None``.

    What the review screen's play link seeks to.
    """
    words = _words_in(correction)
    if not words:
        return None
    return int(words[0].start_ms), int(words[-1].end_ms)


# --- Applying an approval ----------------------------------------------------


def _boundaries(start_ms: int, end_ms: int, count: int) -> list[int]:
    """``count + 1`` integer millisecond marks spread evenly over the span.

    Integer arithmetic, so the marks are monotonic and the last one is exactly
    ``end_ms`` — the replacement words cover the old span and nothing else
    (project rule 5: milliseconds are integers, never floats).
    """
    span = end_ms - start_ms
    return [start_ms + (span * index) // count for index in range(count)] + [end_ms]


def _shift_tail(transcript: Transcript, *, after_idx: int, delta: int) -> None:
    """Renumber every word after ``after_idx`` by ``delta``.

    Two statements, not one: the ``(transcript, idx)`` unique constraint is
    checked per row, so ``idx = idx + 1`` collides with the rows it has not
    moved yet. Parking the tail above the current maximum first leaves every
    intermediate value free, and both updates are bulk.
    """
    if not delta:
        return
    tail = TranscriptWord.objects.filter(transcript=transcript, idx__gt=after_idx)
    park = int(
        TranscriptWord.objects.filter(transcript=transcript).aggregate(top=Max("idx"))["top"] or 0
    ) + 1
    if not tail.update(idx=F("idx") + park):
        return
    TranscriptWord.objects.filter(transcript=transcript, idx__gt=after_idx + park).update(
        idx=F("idx") - park + delta
    )


def _replace_words(
    transcript: Transcript,
    *,
    first_idx: int,
    old_words: Sequence[TranscriptWord],
    new_texts: Sequence[str],
) -> None:
    """Swap ``old_words`` for ``new_texts`` over the span the old ones covered."""
    if len(new_texts) == len(old_words):
        # Equal counts: the alignment still holds, so only the text changes.
        for word, text in zip(old_words, new_texts, strict=True):
            word.text = text[:MAX_WORD_CHARS]
        TranscriptWord.objects.bulk_update(old_words, ["text"])
        return

    start_ms, end_ms = int(old_words[0].start_ms), int(old_words[-1].end_ms)
    marks = _boundaries(start_ms, end_ms, len(new_texts))
    TranscriptWord.objects.filter(pk__in=[word.pk for word in old_words]).delete()
    _shift_tail(
        transcript,
        after_idx=first_idx + len(old_words) - 1,
        delta=len(new_texts) - len(old_words),
    )
    TranscriptWord.objects.bulk_create(
        [
            TranscriptWord(
                transcript=transcript,
                idx=first_idx + offset,
                text=text[:MAX_WORD_CHARS],
                start_ms=marks[offset],
                end_ms=marks[offset + 1],
                # No ASR confidence to inherit: a human wrote these words.
                confidence=None,
            )
            for offset, text in enumerate(new_texts)
        ]
    )


def _refresh_transcript(transcript: Transcript) -> None:
    """Recompute the derived text columns and bump the version."""
    texts = list(
        TranscriptWord.objects.filter(transcript=transcript)
        .order_by("idx")
        .values_list("text", flat=True)
    )
    transcript.raw_text = " ".join(texts)
    transcript.text_normalized = normalize_for_index(transcript.raw_text)
    transcript.word_count = len(texts)
    transcript.version += 1
    transcript.is_human_reviewed = True
    transcript.save(
        update_fields=[
            "raw_text",
            "text_normalized",
            "word_count",
            "version",
            "is_human_reviewed",
        ]
    )


def _rebuild_chunks(transcript: Transcript, *, start_ms: int, end_ms: int) -> list[Chunk]:
    """Rebuild the chunks overlapping ``[start_ms, end_ms]`` from the words.

    Chunk *spans* are left alone — the replacement words cover exactly the span
    the old ones did, so the boundaries planned at ingestion still hold and
    every chunk outside the edit stays byte-identical.
    """
    chunks = list(
        Chunk.objects.filter(
            transcript=transcript, start_ms__lte=end_ms, end_ms__gte=start_ms
        ).order_by("idx")
    )
    if not chunks:
        return []
    words = list(
        TranscriptWord.objects.filter(transcript=transcript)
        .order_by("idx")
        .values_list("start_ms", "text")
    )
    for chunk in chunks:
        text = " ".join(
            text for word_start, text in words if chunk.start_ms <= word_start < chunk.end_ms
        )
        chunk.text = text
        chunk.text_normalized = normalize_for_index(text)
    # The normalized form is embedded, exactly as the pipeline's embed stage
    # does, so corrected passages stay in the same space as the queries.
    vectors = get_embedder().embed_passages([chunk.text_normalized for chunk in chunks])
    for chunk, vector in zip(chunks, vectors, strict=True):
        chunk.embedding = vector
    Chunk.objects.bulk_update(chunks, ["text", "text_normalized", "embedding"])
    return chunks


def _reindex(chunk_ids: Sequence[int]) -> None:
    """Push the rebuilt chunks to Meilisearch. Imported late on purpose: it
    keeps the search client out of the admin's import graph and gives tests a
    single seam."""
    from search import services

    services.ensure_chunks_index()
    services.index_chunks(Chunk.objects.filter(pk__in=chunk_ids))


def _validate(correction: Correction, new_texts: Sequence[str]) -> list[TranscriptWord]:
    if correction.status != CorrectionStatus.PENDING:
        raise CorrectionError(f"correction {correction.pk} is already {correction.status}")
    if not new_texts:
        raise CorrectionError("suggested_text has no words")
    if correction.word_end < correction.word_start:
        raise CorrectionError("word_end comes before word_start")
    chunk_range = chunk_word_range(correction.chunk)
    if chunk_range is None:
        raise CorrectionError(f"chunk {correction.chunk_id} covers no transcript words")
    low, high = chunk_range
    if correction.word_start < low or correction.word_end > high:
        raise CorrectionError(
            f"words {correction.word_start}-{correction.word_end} fall outside "
            f"chunk {correction.chunk_id} (words {low}-{high})"
        )
    words = _words_in(correction)
    if len(words) != correction.word_end - correction.word_start + 1:
        raise CorrectionError(
            f"words {correction.word_start}-{correction.word_end} are not all present"
        )
    return words


@transaction.atomic
def approve(correction: Correction, *, reviewed_by: str = "") -> ApprovalResult:
    """Apply ``correction`` to its transcript and return what changed.

    ``reviewed_by`` is recorded in the log only: ``Correction`` has no reviewer
    column, and adding one is a migration this phase does not need.

    Raises :class:`CorrectionError` when the correction is not pending, has no
    words, or names a range outside its chunk.
    """
    new_texts = correction.suggested_text.split()
    old_words = _validate(correction, new_texts)
    # One approval at a time per transcript: the renumbering below reads the
    # word table and writes it back.
    transcript = Transcript.objects.select_for_update().get(
        pk=correction.chunk.transcript_id
    )
    start_ms, end_ms = int(old_words[0].start_ms), int(old_words[-1].end_ms)

    _replace_words(
        transcript,
        first_idx=correction.word_start,
        old_words=old_words,
        new_texts=new_texts,
    )
    _refresh_transcript(transcript)
    chunks = _rebuild_chunks(transcript, start_ms=start_ms, end_ms=end_ms)

    correction.status = CorrectionStatus.APPROVED
    correction.save(update_fields=["status"])

    chunk_ids = tuple(chunk.pk for chunk in chunks)
    if chunk_ids:
        transaction.on_commit(lambda: _reindex(chunk_ids))
    result = ApprovalResult(
        correction_id=correction.pk,
        transcript_id=transcript.pk,
        version=transcript.version,
        words_replaced=len(old_words),
        words_written=len(new_texts),
        chunk_ids=chunk_ids,
        reviewed_by=reviewed_by,
    )
    logger.info(
        "correction %s approved by %r: %s words -> %s, transcript %s now v%s, chunks %s rebuilt",
        result.correction_id,
        reviewed_by or "unknown",
        result.words_replaced,
        result.words_written,
        result.transcript_id,
        result.version,
        list(result.chunk_ids),
    )
    return result


def reject(correction: Correction) -> None:
    """Close ``correction`` without touching a single row of the corpus."""
    if correction.status != CorrectionStatus.PENDING:
        raise CorrectionError(f"correction {correction.pk} is already {correction.status}")
    correction.status = CorrectionStatus.REJECTED
    correction.save(update_fields=["status"])
