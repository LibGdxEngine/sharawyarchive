"""Fixtures for the search suite.

Three things need isolating. Meilisearch is a shared server, so every test that
touches it gets its own ``MEILI_INDEX_PREFIX`` and deletes the index afterwards.
The Quran rows are created per test rather than relying on a fully imported
corpus, so the suite runs against an empty database. And throttle history lives
in Redis now rather than in per-process memory, so it outlives not just a test
but the whole run — hence ``reset_throttles``, re-exported here so that this
suite's twenty-odd search requests cannot spend the 30/min budget of the next
run.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from meilisearch.errors import MeilisearchApiError
from pytest_django.fixtures import Settings

from api.tests.factories import reset_throttles  # noqa: F401
from corpus.arabic import normalize_for_index
from corpus.models import AudioAsset, Chunk, Segment, SegmentKind, Source, Transcript
from quran.models import Ayah, Surah
from search import services

KHAWATIR_TEXTS: list[str] = [
    "الْإِيمَانُ بِاللَّهِ وَحْدَهُ لَا شَرِيكَ لَهُ",
    "الصَّبْرُ عِنْدَ الصَّدْمَةِ الْأُولَى",
    "الرَّحْمَةُ فِي قُلُوبِ الْمُؤْمِنِينَ",
    "التَّوْبَةُ النَّصُوحُ بَابُهَا مَفْتُوحٌ",
    "الْعِلْمُ نُورٌ يَهْدِي الْقَلْبَ",
    "الزَّكَاةُ طُهْرَةٌ لِلْمَالِ",
]

RECITATION_TEXTS: list[str] = [
    "الصَّلَاةُ عِمَادُ الدِّينِ",
    "الْحَجُّ عَرَفَةُ وَالطَّوَافُ سَبْعًا",
    "الشُّكْرُ نِعْمَةٌ تَدُومُ",
    "الْيَقِينُ رَاحَةُ الْقَلْبِ",
]

CHUNK_MS = 30_000


@dataclass(frozen=True)
class CorpusFixture:
    """A tiny two-segment corpus: khawatir on surah 2, recitation on surah 3."""

    khawatir: Segment
    recitation: Segment
    chunks: list[Chunk]

    def chunk_for(self, text: str) -> Chunk:
        return next(chunk for chunk in self.chunks if chunk.text == text)


def _audio_asset() -> AudioAsset:
    digest = uuid.uuid4().hex * 2
    return AudioAsset.objects.create(
        storage_key=f"audio/{digest}.opus",
        duration_ms=600_000,
        mime="audio/ogg",
        sha256=digest,
        size_bytes=2_400_000,
    )


def _segment(source: Source, *, kind: str, surah: Surah, title: str) -> Segment:
    segment = Segment.objects.create(
        source=source,
        kind=kind,
        surah=surah,
        ayah_start=1,
        ayah_end=10,
        audio=_audio_asset(),
        duration_ms=600_000,
        title=title,
    )
    Transcript.objects.create(
        segment=segment,
        engine="stub",
        raw_text=title,
        text_normalized=normalize_for_index(title),
    )
    return segment


def _chunks(segment: Segment, texts: list[str]) -> list[Chunk]:
    return [
        Chunk.objects.create(
            transcript=segment.transcript,
            idx=idx,
            text=text,
            text_normalized=normalize_for_index(text),
            start_ms=idx * CHUNK_MS,
            end_ms=(idx + 1) * CHUNK_MS,
        )
        for idx, text in enumerate(texts)
    ]


@pytest.fixture
def quran_slice(db: None) -> dict[int, Surah]:
    """Surahs 2, 3 and 24 with the handful of ayahs the reference tests need."""
    surahs = {}
    for number, name_ar, name_en, ayah_count, place, revealed in (
        (2, "البقرة", "Al-Baqarah", 286, "madinah", 87),
        (3, "آل عمران", "Aal-Imran", 200, "madinah", 89),
        (24, "النور", "An-Nur", 64, "madinah", 102),
    ):
        # update_or_create: the quran app's session-scoped import fixture may
        # have already populated the full Quran in this test database.
        surahs[number], _ = Surah.objects.update_or_create(
            number=number,
            defaults={
                'name_ar': name_ar,
                'name_ar_plain': normalize_for_index(name_ar),
                'name_en': name_en,
                'ayah_count': ayah_count,
                'revelation_place': place,
                'order_revealed': revealed,
            },
        )
    for surah_number, ayah_number, text in (
        (2, 255, "ٱللَّهُ لَآ إِلَـٰهَ إِلَّا هُوَ ٱلْحَىُّ ٱلْقَيُّومُ"),
        (2, 282, "يَـٰٓأَيُّهَا ٱلَّذِينَ ءَامَنُوٓا۟ إِذَا تَدَايَنتُم بِدَيْنٍ"),
        (3, 61, "فَمَنْ حَآجَّكَ فِيهِ مِنۢ بَعْدِ مَا جَآءَكَ مِنَ ٱلْعِلْمِ"),
        (24, 35, "ٱللَّهُ نُورُ ٱلسَّمَـٰوَٰتِ وَٱلْأَرْضِ"),
    ):
        Ayah.objects.update_or_create(
            surah=surahs[surah_number],
            number=ayah_number,
            defaults={
                'text_uthmani': text,
                'text_imlaei': text,
                'text_normalized': normalize_for_index(text),
                'juz': 3,
                'hizb': 5,
                'page': 42,
            },
        )
    return surahs


@pytest.fixture
def corpus(quran_slice: dict[int, Surah]) -> CorpusFixture:
    source = Source.objects.create(title="التلفزيون المصري", kind="tv")
    khawatir = _segment(
        source, kind=SegmentKind.KHAWATIR, surah=quran_slice[2], title="خواطر البقرة"
    )
    recitation = _segment(
        source, kind=SegmentKind.RECITATION, surah=quran_slice[3], title="تلاوة آل عمران"
    )
    chunks = _chunks(khawatir, KHAWATIR_TEXTS) + _chunks(recitation, RECITATION_TEXTS)
    return CorpusFixture(khawatir=khawatir, recitation=recitation, chunks=chunks)


@pytest.fixture
def meili_prefix(settings: Settings) -> Iterator[str]:
    """Point Meilisearch at a private index name and drop it afterwards."""
    settings.MEILI_INDEX_PREFIX = f"test_{uuid.uuid4().hex[:8]}_"
    yield settings.MEILI_INDEX_PREFIX
    client = services.meili_client()
    for index_name in (services.chunks_index_name(), services.ayahs_index_name()):
        try:
            client.wait_for_task(
                client.delete_index(index_name).task_uid,
                timeout_in_ms=services.TASK_TIMEOUT_MS,
            )
        except MeilisearchApiError as error:  # index was never created
            if error.code != "index_not_found":
                raise


@pytest.fixture
def chunks_index(meili_prefix: str) -> str:
    services.ensure_chunks_index()
    return services.chunks_index_name()


@pytest.fixture
def ayahs_index(meili_prefix: str) -> str:
    services.ensure_ayahs_index()
    return services.ayahs_index_name()


@pytest.fixture
def indexed_quran(ayahs_index: str, quran_slice: dict[int, Surah]) -> None:
    """Index every Ayah row in the database — in this suite that is the handful
    ``quran_slice`` created, never the full 6236-ayah import."""
    services.index_ayahs(Ayah.objects.order_by("surah_id", "number"))


@pytest.fixture
def indexed_corpus(chunks_index: str, corpus: CorpusFixture) -> CorpusFixture:
    services.index_chunks(corpus.chunks)
    return corpus
