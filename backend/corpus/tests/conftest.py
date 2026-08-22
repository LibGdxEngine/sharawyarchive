"""Fixtures for the corpus suite.

The shared API graph comes from ``api.tests.factories`` and is re-exported
below. On top of it this module builds one thing the endpoint fixtures cannot:
a transcript whose word timings and chunk spans actually line up, which is what
the correction and chunk-span tests are about. Its segment has no surah, so it
never collides with the Quran import that ``quran/tests`` commits for the
session.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from meilisearch.errors import MeilisearchApiError
from pytest_django.fixtures import Settings

from api.tests.factories import (  # noqa: F401
    api,
    archive,
    make_audio_asset,
    reset_throttles,
)
from corpus.arabic import normalize_for_index
from corpus.models import (
    Chunk,
    Correction,
    Segment,
    SegmentKind,
    Source,
    Transcript,
    TranscriptWord,
)
from search import services

WORD_STEP_MS = 1_000
"""One word per second, so a word index is readable straight off a timestamp."""

WORD_LENGTH_MS = 900
"""Leaves a 100 ms gap, the way an aligner would."""

WORDS_PER_CHUNK = 10

ALIGNED_WORDS = [
    # chunk 0 — الصبر
    "الصبر", "عند", "الصدمة", "الأولى", "هو", "الصبر", "الحقيقي", "الذي",
    "يرفع", "الدرجات",
    # chunk 1 — الرحمة
    "والرحمة", "في", "قلوب", "المؤمنين", "نور", "يهدي", "إلى", "طريق",
    "الحق", "دائما",
    # chunk 2 — العلم
    "والعلم", "نور", "يهدي", "القلب", "إلى", "معرفة", "الخالق", "سبحانه",
    "وتعالى", "أبدا",
]


@dataclass(frozen=True)
class Passages:
    """One segment whose 30 words fall neatly into three 10-word chunks."""

    segment: Segment
    transcript: Transcript
    chunks: list[Chunk]

    def words(self) -> list[TranscriptWord]:
        return list(self.transcript.words.order_by("idx"))

    def reload(self, chunk: Chunk) -> Chunk:
        return Chunk.objects.get(pk=chunk.pk)


def build_passages() -> Passages:
    source = Source.objects.create(title="التلفزيون المصري", kind="tv")
    segment = Segment.objects.create(
        source=source,
        kind=SegmentKind.KHAWATIR,
        audio=make_audio_asset(),
        ordinal=1,
        duration_ms=len(ALIGNED_WORDS) * WORD_STEP_MS,
        title="خواطر مرتبة",
    )
    raw_text = " ".join(ALIGNED_WORDS)
    transcript = Transcript.objects.create(
        segment=segment,
        engine="whisper-large-v3",
        engine_version="3.0",
        raw_text=raw_text,
        text_normalized=normalize_for_index(raw_text),
        word_count=len(ALIGNED_WORDS),
        version=1,
    )
    TranscriptWord.objects.bulk_create(
        TranscriptWord(
            transcript=transcript,
            idx=index,
            text=text,
            start_ms=index * WORD_STEP_MS,
            end_ms=index * WORD_STEP_MS + WORD_LENGTH_MS,
            confidence=0.9,
        )
        for index, text in enumerate(ALIGNED_WORDS)
    )
    chunks = []
    for index in range(len(ALIGNED_WORDS) // WORDS_PER_CHUNK):
        first = index * WORDS_PER_CHUNK
        text = " ".join(ALIGNED_WORDS[first : first + WORDS_PER_CHUNK])
        chunks.append(
            Chunk(
                transcript=transcript,
                idx=index,
                text=text,
                text_normalized=normalize_for_index(text),
                start_ms=first * WORD_STEP_MS,
                end_ms=(first + WORDS_PER_CHUNK - 1) * WORD_STEP_MS + WORD_LENGTH_MS,
            )
        )
    Chunk.objects.bulk_create(chunks)
    return Passages(segment=segment, transcript=transcript, chunks=chunks)


def make_correction(
    passages: Passages,
    word_start: int,
    word_end: int,
    text: str,
    *,
    chunk: Chunk | None = None,
) -> Correction:
    """A pending correction, filed against the chunk ``word_start`` falls in."""
    chunk = chunk or next(
        (
            candidate
            for candidate in passages.chunks
            if candidate.start_ms <= word_start * WORD_STEP_MS < candidate.end_ms
        ),
        passages.chunks[1],
    )
    return Correction.objects.create(
        chunk=chunk,
        word_start=word_start,
        word_end=word_end,
        suggested_text=text,
        submitted_ip="127.0.0.1",
    )


@pytest.fixture
def passages(db: None) -> Passages:
    return build_passages()


@pytest.fixture
def meili_prefix(settings: Settings) -> Iterator[str]:
    """A private Meilisearch index for one test, dropped on teardown."""
    settings.MEILI_INDEX_PREFIX = f"test_corpus_{uuid.uuid4().hex[:8]}_"
    yield settings.MEILI_INDEX_PREFIX
    client = services.meili_client()
    try:
        client.wait_for_task(
            client.delete_index(services.chunks_index_name()).task_uid,
            timeout_in_ms=services.TASK_TIMEOUT_MS,
        )
    except MeilisearchApiError as error:  # the index was never created
        if error.code != "index_not_found":
            raise


@pytest.fixture
def indexed_passages(meili_prefix: str, passages: Passages) -> Passages:
    services.ensure_chunks_index()
    services.index_chunks(passages.chunks)
    return passages
