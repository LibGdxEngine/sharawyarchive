"""A failing segment must stay one failing segment."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from corpus.models import PipelineRun, PipelineRunStatus, Segment, SegmentStatus, Transcript

from pipeline import run, stages
from pipeline.engines import StubASR

from .conftest import VALID_TWO, FakeSearchServices

SOURCE_TITLE = "Failure isolation tape"
BOOM = "engine exploded on purpose"


class ExplodingASR:
    """The stub, except for one file it refuses to look at."""

    name = "stub"
    version = "1"

    def __init__(self, failing_name: str) -> None:
        self.failing_name = failing_name
        self._real = StubASR()

    def transcribe(self, audio_path: str, *, duration_ms: int):  # noqa: ANN201 - list[ASRWord]
        if self.failing_name in audio_path:
            raise RuntimeError(BOOM)
        return self._real.transcribe(audio_path, duration_ms=duration_ms)


@pytest.mark.django_db
def test_one_exploding_segment_does_not_stop_the_others(
    audio_folder: Path,
    fake_search: FakeSearchServices,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(stages, "get_asr_engine", lambda: ExplodingASR(VALID_TWO))

    stdout = io.StringIO()
    summary = run.run_folder(
        folder=str(audio_folder),
        source_title=SOURCE_TITLE,
        kind="khawatir",
        stdout=stdout,
    )

    assert (summary.processed, summary.skipped, summary.failed) == (1, 0, 1)
    assert "processed 1, skipped 0, failed 1" in stdout.getvalue()

    healthy = Segment.objects.exclude(title=Path(VALID_TWO).stem).get()
    broken = Segment.objects.get(title=Path(VALID_TWO).stem)
    assert healthy.status == SegmentStatus.INDEXED
    assert broken.status == SegmentStatus.FAILED

    failed_run = PipelineRun.objects.get(
        segment=broken, stage="transcribe", status=PipelineRunStatus.FAILED
    )
    assert BOOM in failed_run.detail
    assert "Traceback" in failed_run.detail

    # The broken segment stopped at transcribe; nothing downstream ran for it.
    assert not Transcript.objects.filter(segment=broken).exists()
    assert not PipelineRun.objects.filter(segment=broken, stage="align").exists()
    assert Transcript.objects.filter(segment=healthy).exists()
    assert len(fake_search.indexed) > 0


@pytest.mark.django_db
def test_a_failed_segment_is_retried_on_the_next_run(
    audio_folder: Path,
    fake_search: FakeSearchServices,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resumability: fix the cause, run again, the segment catches up."""
    monkeypatch.setattr(stages, "get_asr_engine", lambda: ExplodingASR(VALID_TWO))
    run.run_folder(
        folder=str(audio_folder),
        source_title=SOURCE_TITLE,
        kind="khawatir",
        stdout=io.StringIO(),
    )

    monkeypatch.setattr(stages, "get_asr_engine", StubASR)
    summary = run.run_folder(
        folder=str(audio_folder),
        source_title=SOURCE_TITLE,
        kind="khawatir",
        stdout=io.StringIO(),
    )

    assert (summary.processed, summary.skipped, summary.failed) == (1, 1, 0)
    assert Segment.objects.count() == 2
    assert set(Segment.objects.values_list("status", flat=True)) == {SegmentStatus.INDEXED}


@pytest.mark.django_db
def test_a_stage_never_raises_out_of_its_task() -> None:
    """A segment id that does not exist is a failed result, not an exception."""
    result = stages.do_chunk(999_999)

    assert result.ok is False
    assert result.skipped is False
    assert "no longer exists" in result.detail
    assert PipelineRun.objects.filter(status=PipelineRunStatus.FAILED).exists()
