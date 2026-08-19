"""The audio-first ingest path: ``--until transcode`` and readable titles.

This is how the real 11-CD corpus lands (user decision: ingest now, transcribe
later): segments become playable immediately and stay ``pending`` until a real
ASR engine is configured.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from corpus import storage
from corpus.models import Segment, SegmentStatus, Transcript
from quran.models import Surah

from pipeline import run

from .conftest import synthesize_audio

SOURCE_TITLE = "تفسير — اختبار"


def _drive(folder: Path, **kwargs) -> tuple[run.Summary, str]:
    stdout = io.StringIO()
    summary = run.run_folder(
        folder=str(folder), source_title=SOURCE_TITLE, kind="khawatir", stdout=stdout, **kwargs
    )
    return summary, stdout.getvalue()


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


@pytest.mark.django_db
def test_until_transcode_leaves_segments_pending_and_playable(
    tmp_path: Path, baqarah: Surah
) -> None:
    folder = tmp_path / "cd"
    folder.mkdir()
    synthesize_audio(folder / "002_001_005.mp3", seconds=25)

    summary, output = _drive(folder, until="transcode")

    assert (summary.processed, summary.failed) == (1, 0)
    assert "transcribe" not in output  # the chain really stopped at transcode
    segment = Segment.objects.get()
    assert segment.status == SegmentStatus.PENDING
    assert not Transcript.objects.filter(segment=segment).exists()
    assert storage.object_exists(storage.audio_key(segment.audio.sha256))
    assert storage.object_exists(storage.waveform_key(segment.audio.sha256))

    # A later full run resumes: transcode skips, nothing was lost.
    summary_again, output_again = _drive(folder, until="transcode")
    assert (summary_again.processed, summary_again.skipped) == (0, 1)
    assert "transcode skipped" in output_again


@pytest.mark.django_db
def test_ingest_composes_arabic_titles_from_the_parsed_reference(
    tmp_path: Path, baqarah: Surah
) -> None:
    folder = tmp_path / "cd"
    folder.mkdir()
    synthesize_audio(folder / "002_001_005.mp3", seconds=2, frequency=440)
    synthesize_audio(folder / "002_007_007.mp3", seconds=2, frequency=523)

    _drive(folder, until="transcode")

    titles = set(Segment.objects.values_list("title", flat=True))
    assert titles == {
        "تفسير سورة البقرة — الآيات 1–5",
        "تفسير سورة البقرة — الآية 7",
    }


@pytest.mark.django_db
def test_title_falls_back_to_the_stem_when_the_surah_is_not_imported(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "cd"
    folder.mkdir()
    synthesize_audio(folder / "099_001_002.mp3", seconds=2)

    _drive(folder, until="transcode")

    assert Segment.objects.get().title == "099_001_002"


def test_until_rejects_an_unknown_stage() -> None:
    with pytest.raises(ValueError, match="until must be one of"):
        run.process_segment(1, "/nowhere.mp3", until="publish")
