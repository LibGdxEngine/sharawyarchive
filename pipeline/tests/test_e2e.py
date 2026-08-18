"""End-to-end driver runs against the real database, ffmpeg and MinIO."""

from __future__ import annotations

import io
import json
import time
from pathlib import Path

import pytest
from corpus import storage
from corpus.arabic import normalize_for_index
from corpus.models import (
    AudioAsset,
    Chunk,
    PipelineRun,
    PipelineRunStatus,
    Segment,
    SegmentStatus,
    Transcript,
    TranscriptWord,
)
from django.conf import settings

from pipeline import run, stages

from .conftest import CORRUPTED, VALID_ONE, VALID_TWO, FakeSearchServices

SOURCE_TITLE = "Test khawatir tape"
HARAKA = "َ"  # ARABIC FATHA, present in the stub vocabulary
# The fixtures ask ffmpeg for 30s; mp3 framing rounds that up a little.
NOMINAL_MS = 30_000
DURATION_SLACK_MS = 500


def drive(folder: Path, **kwargs) -> tuple[run.Summary, str]:
    stdout = io.StringIO()
    summary = run.run_folder(
        folder=str(folder),
        source_title=SOURCE_TITLE,
        kind="khawatir",
        stdout=stdout,
        **kwargs,
    )
    return summary, stdout.getvalue()


@pytest.mark.django_db
def test_driver_takes_two_files_to_indexed_and_isolates_the_corrupted_one(
    audio_folder: Path, fake_search: FakeSearchServices
) -> None:
    summary, output = drive(audio_folder)

    assert (summary.processed, summary.skipped, summary.failed) == (2, 0, 0)
    assert "processed 2, skipped 0, failed 0" in output

    segments = list(Segment.objects.order_by("id"))
    assert [segment.status for segment in segments] == [SegmentStatus.INDEXED] * 2
    assert {segment.title for segment in segments} == {
        Path(VALID_ONE).stem,
        Path(VALID_TWO).stem,
    }
    assert all(segment.source.title == SOURCE_TITLE for segment in segments)
    assert all(
        NOMINAL_MS <= segment.duration_ms <= NOMINAL_MS + DURATION_SLACK_MS
        for segment in segments
    )

    # The corrupted file failed on its own, and the batch still completed.
    failures = PipelineRun.objects.filter(stage="ingest", status=PipelineRunStatus.FAILED)
    assert failures.count() == 1
    assert CORRUPTED in failures.get().detail
    batch = PipelineRun.objects.get(
        stage="ingest", segment__isnull=True, status=PipelineRunStatus.COMPLETED
    )
    assert json.loads(batch.detail)["accepted"] == 2
    assert json.loads(batch.detail)["failed"] == 1


@pytest.mark.django_db
def test_transcript_words_are_monotonic_integer_milliseconds(
    audio_folder: Path, fake_search: FakeSearchServices
) -> None:
    drive(audio_folder, limit=1)

    transcript = Transcript.objects.get()
    words = list(transcript.words.order_by("idx"))

    assert transcript.engine == "stub"
    assert transcript.language == "ar"
    assert transcript.word_count == len(words) == 50  # 30s at 600ms per stub word
    assert transcript.text_normalized == normalize_for_index(transcript.raw_text)
    assert [word.idx for word in words] == list(range(len(words)))
    assert all(isinstance(word.start_ms, int) and isinstance(word.end_ms, int) for word in words)
    assert all(word.end_ms > word.start_ms for word in words)
    assert all(
        earlier.end_ms <= later.start_ms
        for earlier, later in zip(words, words[1:], strict=False)
    )
    assert words[-1].end_ms <= transcript.segment.duration_ms


@pytest.mark.django_db
def test_chunks_carry_display_text_and_a_normalized_form(
    audio_folder: Path, fake_search: FakeSearchServices
) -> None:
    drive(audio_folder, limit=1)

    chunks = list(Chunk.objects.order_by("idx"))
    assert chunks
    for chunk in chunks:
        assert chunk.text_normalized == normalize_for_index(chunk.text)
        assert HARAKA in chunk.text  # display text keeps its diacritics
        assert HARAKA not in chunk.text_normalized  # the index form drops them
        assert isinstance(chunk.start_ms, int) and isinstance(chunk.end_ms, int)
        assert chunk.end_ms > chunk.start_ms
        assert chunk.embedding is not None
        assert len(chunk.embedding) == 1024

    assert fake_search.ensure_calls == 1
    assert len(fake_search.indexed) == len(chunks)


@pytest.mark.django_db
def test_opus_and_waveform_land_in_object_storage(
    audio_folder: Path, fake_search: FakeSearchServices
) -> None:
    drive(audio_folder, limit=1)

    asset = AudioAsset.objects.get()
    assert asset.storage_key == storage.audio_key(asset.sha256)
    assert storage.object_exists(asset.storage_key)
    assert storage.object_exists(storage.waveform_key(asset.sha256))
    assert asset.bitrate == stages.OPUS_BITRATE
    assert asset.sample_rate == stages.OPUS_SAMPLE_RATE

    waveform = json.loads(
        storage.get_s3_client()
        .get_object(
            Bucket=settings.AUDIO_S3_BUCKET,
            Key=storage.waveform_key(asset.sha256),
        )["Body"]
        .read()
    )
    assert waveform["duration_ms"] == asset.duration_ms
    assert len(waveform["peaks"]) == stages.WAVEFORM_BUCKETS
    assert all(0.0 <= peak <= 1.0 for peak in waveform["peaks"])


@pytest.mark.django_db
def test_a_second_run_creates_nothing_and_reports_no_work(
    audio_folder: Path, fake_search: FakeSearchServices
) -> None:
    drive(audio_folder)
    before = {
        model.__name__: model.objects.count()
        for model in (Segment, AudioAsset, Transcript, TranscriptWord, Chunk)
    }

    started = time.monotonic()
    summary, output = drive(audio_folder)
    elapsed = time.monotonic() - started

    after = {
        model.__name__: model.objects.count()
        for model in (Segment, AudioAsset, Transcript, TranscriptWord, Chunk)
    }
    assert after == before
    assert (summary.processed, summary.skipped, summary.failed) == (0, 2, 0)
    assert "processed 0, skipped 2, failed 0" in output
    assert elapsed < 10, f"idempotent re-run took {elapsed:.1f}s"
    # Two calls from the first run and none from the second: an indexed segment
    # never reaches Meilisearch again.
    assert fake_search.ensure_calls == 2


@pytest.mark.django_db
def test_limit_and_surah_filter_which_files_are_ingested(audio_folder: Path) -> None:
    only_one = stages.do_ingest(str(audio_folder), SOURCE_TITLE, "khawatir", limit=1)
    assert len(only_one) == 1

    nothing = stages.do_ingest(str(audio_folder), SOURCE_TITLE, "khawatir", surah=3)
    assert nothing == []

    matching = stages.do_ingest(str(audio_folder), SOURCE_TITLE, "khawatir", surah=2)
    assert len(matching) == 2
    # The first file was already ingested above, so it comes back as existing.
    assert [item.created for item in matching] == [False, True]


@pytest.mark.django_db
def test_unparseable_filenames_are_skipped_not_failed(
    tmp_path: Path, fake_search: FakeSearchServices
) -> None:
    folder = tmp_path / "mixed"
    folder.mkdir()
    (folder / "random-podcast.mp3").write_bytes(b"")

    files = stages.do_ingest(str(folder), SOURCE_TITLE, "khawatir")

    assert files == []
    skipped = PipelineRun.objects.get(stage="ingest", status=PipelineRunStatus.SKIPPED)
    assert "unparseable filename" in skipped.detail
    assert not PipelineRun.objects.filter(status=PipelineRunStatus.FAILED).exists()
