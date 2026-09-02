"""The storage-sourced transcription driver: R2 in, transcript out.

``storage.download_file`` is faked to hand back a locally synthesized file, so
nothing touches the network. Transcription runs on the stub engines the suite
already opts into (``ALLOW_STUB_ENGINES=true`` in conftest).
"""

from __future__ import annotations

import io
import shutil
from pathlib import Path

import pytest
from corpus import storage
from corpus.models import (
    AudioAsset,
    Segment,
    SegmentStatus,
    Source,
    Transcript,
    TranscriptWord,
)
from quran.models import Surah

from pipeline import run_storage

from .conftest import synthesize_audio

# Arbitrary but valid 64-char hex; the object key is derived from it.
SHA = "a" * 64


@pytest.fixture
def baqarah(db: None) -> Surah:
    surah, _ = Surah.objects.update_or_create(
        number=2,
        defaults={
            "name_ar": "البقرة",
            "name_ar_plain": "البقره",
            "name_en": "Al-Baqarah",
            "ayah_count": 286,
            "revelation_place": "madinah",
            "order_revealed": 87,
        },
    )
    return surah


@pytest.fixture
def segment(baqarah: Surah) -> Segment:
    asset = AudioAsset.objects.create(
        storage_key=storage.audio_key(SHA),
        duration_ms=3000,
        mime="audio/opus",
        sha256=SHA,
        size_bytes=1234,
    )
    source = Source.objects.create(title="تفسير — اختبار", kind="khawatir")
    return Segment.objects.create(
        source=source,
        kind="khawatir",
        surah_id=2,
        ayah_start=1,
        ayah_end=5,
        audio=asset,
        duration_ms=3000,
        title="تفسير سورة البقرة — الآيات 1–5",
        status=SegmentStatus.PENDING,
    )


@pytest.fixture
def fake_download(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    """Replace the R2 fetch with a copy of a locally synthesized file.

    Returns the list of keys requested, so a test can assert the right object
    was pulled.
    """
    source_audio = synthesize_audio(tmp_path / "master.wav", seconds=3)
    keys: list[str] = []

    def _download(key: str, dest_path: str) -> None:
        keys.append(key)
        shutil.copy(source_audio, dest_path)

    monkeypatch.setattr(storage, "download_file", _download)
    return keys


@pytest.mark.django_db
def test_transcribes_a_segment_pulled_from_storage(
    segment: Segment, fake_download: list[str]
) -> None:
    summary = run_storage.run_storage(stdout=io.StringIO())

    assert (summary.processed, summary.skipped, summary.failed) == (1, 0, 0)
    # The object fetched was this segment's audio key, not something else.
    assert fake_download == [storage.audio_key(SHA)]

    transcript = Transcript.objects.get(segment=segment)
    assert transcript.raw_text.strip()
    assert transcript.text_normalized.strip()
    assert TranscriptWord.objects.filter(transcript=transcript).count() > 0

    segment.refresh_from_db()
    assert segment.status == SegmentStatus.ALIGNED


@pytest.mark.django_db
def test_a_finished_segment_is_never_re_fetched(
    segment: Segment, fake_download: list[str]
) -> None:
    run_storage.run_storage(stdout=io.StringIO())
    assert len(fake_download) == 1

    # Second pass: the aligned segment is filtered out at the query, so nothing
    # is downloaded and there is no work to do.
    again = run_storage.run_storage(stdout=io.StringIO())
    assert (again.processed, again.skipped, again.failed) == (0, 0, 0)
    assert len(fake_download) == 1  # not re-fetched


@pytest.mark.django_db
def test_surah_and_limit_filter_the_queue(segment: Segment, baqarah: Surah) -> None:
    # A second segment under a different surah that must be excluded by --surah.
    other_source = Source.objects.create(title="أخرى", kind="khawatir")
    Surah.objects.update_or_create(
        number=3,
        defaults={
            "name_ar": "آل عمران",
            "name_ar_plain": "ال عمران",
            "name_en": "Al Imran",
            "ayah_count": 200,
            "revelation_place": "madinah",
            "order_revealed": 89,
        },
    )
    other_asset = AudioAsset.objects.create(
        storage_key=storage.audio_key("b" * 64),
        duration_ms=3000,
        mime="audio/opus",
        sha256="b" * 64,
        size_bytes=1234,
    )
    Segment.objects.create(
        source=other_source,
        kind="khawatir",
        surah_id=3,
        ayah_start=1,
        ayah_end=2,
        audio=other_asset,
        duration_ms=3000,
        title="آل عمران",
        status=SegmentStatus.PENDING,
    )

    only_two = run_storage.pending_segments(surah=2)
    assert [s.pk for s in only_two] == [segment.pk]

    assert len(run_storage.pending_segments(limit=1)) == 1


@pytest.mark.django_db
def test_a_download_failure_is_non_fatal_and_recorded(
    segment: Segment, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(key: str, dest_path: str) -> None:
        raise OSError("R2 unreachable")

    monkeypatch.setattr(storage, "download_file", _boom)

    summary = run_storage.run_storage(stdout=io.StringIO())

    assert (summary.processed, summary.failed) == (0, 1)
    assert not Transcript.objects.filter(segment=segment).exists()
    segment.refresh_from_db()
    assert segment.status == SegmentStatus.FAILED
    # The failure is accounted for, with the key in the detail.
    failure = segment.pipeline_runs.get(stage=run_storage.DOWNLOAD)
    assert storage.audio_key(SHA) in failure.detail
