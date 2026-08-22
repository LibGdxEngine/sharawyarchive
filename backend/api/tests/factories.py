"""Shared fixtures for the API suite.

One small archive stands in for the whole corpus: a surah, a couple of segments
with machine transcripts and chunks, and the audio asset behind them. Every app
that exercises an endpoint imports these fixtures into its own ``conftest.py``
rather than rebuilding the graph.

``AudioAsset.storage_key`` is the key the API really serves
(``corpus.storage.audio_key`` of the asset's hash). It used to be an unrelated
``ingest/original-….wav`` path, which quietly made every "no raw key in the
payload" assertion vacuous: the string being searched for was one no serializer
could have emitted even if it wanted to. Those assertions only mean something
when the raw key and the served key are the same string.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from corpus.arabic import normalize_for_index
from corpus.models import (
    AudioAsset,
    Chunk,
    ChunkTopic,
    Segment,
    SegmentKind,
    Source,
    Topic,
    Transcript,
    TranscriptWord,
)
from corpus.storage import audio_key
from quran.models import Ayah, Surah

AYAH_TEXTS = [
    'بِسْمِ ٱللَّهِ ٱلرَّحْمَـٰنِ ٱلرَّحِيمِ',
    'ٱلْحَمْدُ لِلَّهِ رَبِّ ٱلْعَـٰلَمِينَ',
    'ٱلرَّحْمَـٰنِ ٱلرَّحِيمِ',
]

WORD_TEXTS = [
    'الحمد', 'لله', 'رب', 'العالمين', 'الرحمن', 'الرحيم', 'مالك', 'يوم', 'الدين', 'إياك',
    'نعبد', 'وإياك', 'نستعين', 'اهدنا', 'الصراط', 'المستقيم', 'صراط', 'الذين', 'أنعمت', 'عليهم',
]

CHUNK_TEXTS = [
    'الصَّبْرُ عِنْدَ الصَّدْمَةِ الْأُولَى',
    'الرَّحْمَةُ فِي قُلُوبِ الْمُؤْمِنِينَ',
    'الْعِلْمُ نُورٌ يَهْدِي الْقَلْبَ',
]

OTHER_CHUNK_TEXTS = [
    'التَّوْبَةُ النَّصُوحُ بَابُهَا مَفْتُوحٌ',
    'الزَّكَاةُ طُهْرَةٌ لِلْمَالِ',
]

WORD_MS = 400
CHUNK_MS = 30_000
SEGMENT_MS = 600_000


@dataclass(frozen=True)
class Archive:
    """A surah, two segments over it, and everything hanging off them."""

    surah: Surah
    ayahs: list[Ayah]
    source: Source
    audio: AudioAsset
    segment: Segment
    """Covers ayahs 1-2, has a 20-word transcript and three chunks."""
    other: Segment
    """Covers ayah 1 only; exists so coverage counts have a second thing to
    point at."""
    transcript: Transcript
    words: list[TranscriptWord] = field(default_factory=list)
    chunks: list[Chunk] = field(default_factory=list)
    other_chunks: list[Chunk] = field(default_factory=list)


def clear_quran() -> None:
    """Start from an empty Quran.

    ``quran/tests/test_import_quran.py`` commits a full Tanzil import for the
    whole session, so anything collected after it inherits 114 surahs and 6236
    ayahs. These endpoint tests assert on whole-table shapes (the surah list,
    a surah's page count), so they wipe first. The delete runs inside the
    test's own transaction, which rolls back and puts the corpus straight
    back for whoever runs next.
    """
    Surah.objects.all().delete()


def make_surah(
    number: int = 2,
    *,
    ayah_count: int = 3,
    name_ar: str = 'البقرة',
    name_en: str = 'Al-Baqarah',
) -> tuple[Surah, list[Ayah]]:
    """A surah with ``ayah_count`` verses; texts cycle through :data:`AYAH_TEXTS`."""
    surah = Surah.objects.create(
        number=number,
        name_ar=name_ar,
        name_ar_plain=normalize_for_index(name_ar),
        name_en=name_en,
        ayah_count=ayah_count,
        revelation_place='madinah',
        order_revealed=87,
    )
    ayahs = Ayah.objects.bulk_create(
        Ayah(
            surah=surah,
            number=index + 1,
            text_uthmani=AYAH_TEXTS[index % len(AYAH_TEXTS)],
            text_imlaei=AYAH_TEXTS[index % len(AYAH_TEXTS)],
            text_normalized=normalize_for_index(AYAH_TEXTS[index % len(AYAH_TEXTS)]),
            juz=1,
            hizb=1,
            page=index // 10 + 1,
            sajda=False,
        )
        for index in range(ayah_count)
    )
    return surah, ayahs


def make_audio_asset() -> AudioAsset:
    digest = uuid.uuid4().hex * 2
    return AudioAsset.objects.create(
        storage_key=audio_key(digest),
        duration_ms=SEGMENT_MS,
        mime='audio/ogg',
        bitrate=64_000,
        sample_rate=48_000,
        sha256=digest,
        size_bytes=2_400_000,
    )


def make_segment(
    source: Source,
    audio: AudioAsset,
    *,
    surah: Surah,
    ayah_start: int,
    ayah_end: int,
    title: str,
    ordinal: int = 0,
) -> Segment:
    return Segment.objects.create(
        source=source,
        kind=SegmentKind.KHAWATIR,
        surah=surah,
        ayah_start=ayah_start,
        ayah_end=ayah_end,
        audio=audio,
        ordinal=ordinal,
        duration_ms=SEGMENT_MS,
        title=title,
    )


def make_transcript(
    segment: Segment, *, words: list[str] = WORD_TEXTS, version: int = 2
) -> tuple[Transcript, list[TranscriptWord]]:
    raw_text = ' '.join(words)
    transcript = Transcript.objects.create(
        segment=segment,
        engine='whisper-large-v3',
        engine_version='3.0',
        raw_text=raw_text,
        text_normalized=normalize_for_index(raw_text),
        word_count=len(words),
        version=version,
    )
    rows = TranscriptWord.objects.bulk_create(
        TranscriptWord(
            transcript=transcript,
            idx=index,
            text=text,
            start_ms=index * WORD_MS,
            end_ms=(index + 1) * WORD_MS,
            confidence=0.9876543 if index % 5 else None,
        )
        for index, text in enumerate(words)
    )
    return transcript, rows


def make_chunks(transcript: Transcript, texts: list[str]) -> list[Chunk]:
    return Chunk.objects.bulk_create(
        Chunk(
            transcript=transcript,
            idx=index,
            text=text,
            text_normalized=normalize_for_index(text),
            start_ms=index * CHUNK_MS,
            end_ms=(index + 1) * CHUNK_MS,
        )
        for index, text in enumerate(texts)
    )


def build_archive() -> Archive:
    clear_quran()
    surah, ayahs = make_surah()
    source = Source.objects.create(title='التلفزيون المصري', kind='tv')
    audio = make_audio_asset()
    segment = make_segment(
        source,
        audio,
        surah=surah,
        ayah_start=1,
        ayah_end=2,
        title='خواطر البقرة ١-٢',
        ordinal=3,
    )
    other = make_segment(
        source,
        make_audio_asset(),
        surah=surah,
        ayah_start=1,
        ayah_end=1,
        title='خواطر البقرة ١',
        ordinal=4,
    )
    transcript, words = make_transcript(segment)
    other_transcript, _ = make_transcript(other, words=WORD_TEXTS[:5], version=1)
    return Archive(
        surah=surah,
        ayahs=ayahs,
        source=source,
        audio=audio,
        segment=segment,
        other=other,
        transcript=transcript,
        words=words,
        chunks=make_chunks(transcript, CHUNK_TEXTS),
        other_chunks=make_chunks(other_transcript, OTHER_CHUNK_TEXTS),
    )


def make_topic(
    chunks: list[Chunk],
    *,
    slug: str = 'sabr',
    name_ar: str = 'الصبر',
    is_published: bool = True,
) -> Topic:
    """A topic over ``chunks``, scored best-first in the order given."""
    topic = Topic.objects.create(
        slug=slug,
        name_ar=name_ar,
        description_ar='ما قاله الشيخ عن الصبر',
        is_published=is_published,
    )
    ChunkTopic.objects.bulk_create(
        ChunkTopic(chunk=chunk, topic=topic, score=1.0 - index / 10)
        for index, chunk in enumerate(chunks)
    )
    return topic


@pytest.fixture
def archive(db: None) -> Archive:
    return build_archive()


@pytest.fixture
def api() -> APIClient:
    return APIClient()


@pytest.fixture(autouse=True)
def reset_throttles() -> Iterator[None]:
    """Throttle history lives in the default cache, which outlives a test."""
    cache.clear()
    yield
    cache.clear()
