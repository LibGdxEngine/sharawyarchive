"""Transcribe audio that already lives in object storage, end to end.

``python -m pipeline.run_storage [--surah N] [--limit N] [--dry-run]``

The sibling :mod:`pipeline.run` ingests a folder of *local* files. This driver
is for the other case: the Opus masters are already in R2 (imported straight
into the database, e.g. by ``manage.py import_segments``) but were never
transcribed. It enumerates the segments that still need work, pulls each one's
object down to a temp file by its ``sha256`` key, and runs the same
``do_transcribe`` → ``do_align`` stages the folder driver uses.

Only those two stages run: the audio in storage *is* the Opus master, so there
is nothing to transcode, and its waveform was uploaded alongside it. What lands
is one ``Transcript`` plus its ``TranscriptWord`` rows per segment — which is
all the site needs to show the machine transcript under each ayah.

Idempotent and resumable (project rule 6): a fully-aligned segment is skipped at
the query, so it is never re-downloaded, and a segment left half-done (transcript
but no words) is picked up and only its missing stage runs. Re-running over a
finished corpus selects nothing and exits in seconds; an interrupted run resumes
where it stopped.

A real ASR engine has to be configured (``ASR_BACKEND=cohere`` + ``CO_API_KEY``);
the stub is refused, exactly as in the folder driver.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import traceback
from collections.abc import Iterable
from typing import TextIO

from pipeline import run, stages
from pipeline.django_setup import setup_django

setup_django()

from corpus import storage
from corpus.models import PipelineRun, PipelineRunStatus, Segment, SegmentStatus
from django.utils import timezone

# A segment in either of these states is done as far as this driver cares
# (aligned words exist), so it is filtered out before any download happens.
DONE_STATES = (SegmentStatus.ALIGNED, SegmentStatus.INDEXED)

DOWNLOAD = "download"


def pending_segments(
    surah: int | None = None, limit: int | None = None
) -> list[Segment]:
    """Segments still needing a transcript, oldest surah/ayah first.

    Excludes anything already aligned or indexed. ``pending``, ``transcribed``
    (transcript but no words yet) and ``failed`` (retry) are all included; the
    stage guards make picking up a half-done or previously failed segment safe.
    """
    query = Segment.objects.exclude(status__in=DONE_STATES).select_related("audio")
    if surah is not None:
        query = query.filter(surah_id=surah)
    query = query.order_by("surah_id", "ayah_start", "id")
    if limit is not None:
        query = query[:limit]
    return list(query)


def process_segment(segment_id: int, local_path: str) -> tuple[str, list[str]]:
    """Run transcribe then align for one segment, short-circuiting on failure."""
    notes: list[str] = []
    all_skipped = True
    for name, call in (
        ("transcribe", lambda: stages.do_transcribe(segment_id, local_path)),
        ("align", lambda: stages.do_align(segment_id, local_path)),
    ):
        result = call()
        if not result.ok:
            notes.append(f"{name} FAILED")
            return run.FAILED, notes
        notes.append(f"{name} {'skipped' if result.skipped else 'ok'}")
        all_skipped = all_skipped and result.skipped
    return (run.SKIPPED if all_skipped else run.PROCESSED), notes


def _record_download_failure(segment: Segment, key: str) -> None:
    """Account for a download that failed before any stage could run.

    Mirrors what the stages do on failure: a ``failed`` ``PipelineRun`` with the
    traceback, and the segment marked ``failed`` so a later run retries it.
    """
    PipelineRun.objects.create(
        stage=DOWNLOAD,
        segment=segment,
        status=PipelineRunStatus.FAILED,
        detail=f"{key}\n{traceback.format_exc()}",
        finished_at=timezone.now(),
    )
    Segment.objects.filter(pk=segment.pk).update(status=SegmentStatus.FAILED)


def transcribe_segment(segment: Segment) -> tuple[str, list[str]]:
    """Fetch one segment's audio from storage and drive it through the stages."""
    key = storage.audio_key(segment.audio.sha256)
    with tempfile.TemporaryDirectory(prefix="shaarawy-r2-") as tmpdir:
        local_path = os.path.join(tmpdir, f"{segment.audio.sha256}.opus")
        try:
            storage.download_file(key, local_path)
        except Exception:
            _record_download_failure(segment, key)
            return run.FAILED, [f"download FAILED: {key}"]
        return process_segment(segment.pk, local_path)


def run_storage(
    surah: int | None = None,
    limit: int | None = None,
    stdout: TextIO = sys.stdout,
) -> run.Summary:
    """Transcribe every pending segment, reporting one line each."""
    segments = pending_segments(surah=surah, limit=limit)
    print(f"{len(segments)} segment(s) to transcribe", file=stdout)

    summary = run.Summary()
    total = len(segments)
    for position, segment in enumerate(segments, start=1):
        outcome, notes = transcribe_segment(segment)
        summary.record(outcome)
        print(
            f"[{position}/{total}] segment {segment.pk} "
            f"{segment.surah_id}:{segment.ayah_start}-{segment.ayah_end} "
            f"{segment.title}: {', '.join(notes)} -> {outcome}",
            file=stdout,
        )
    print(summary.line(), file=stdout)
    return summary


def _print_dry_run(segments: Iterable[Segment], stdout: TextIO) -> None:
    count = 0
    for segment in segments:
        count += 1
        print(
            f"segment {segment.pk}\t{segment.surah_id}:"
            f"{segment.ayah_start}-{segment.ayah_end}\t{segment.title}",
            file=stdout,
        )
    print(f"{count} segment(s) would be transcribed", file=stdout)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.run_storage",
        description="Transcribe audio already in object storage (R2/MinIO).",
    )
    parser.add_argument("--surah", type=int, default=None, help="Only this surah.")
    parser.add_argument("--limit", type=int, default=None, help="Stop after N segments.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List the segments that would be transcribed and exit. Writes nothing.",
    )
    args = parser.parse_args(argv)

    if args.dry_run:
        _print_dry_run(pending_segments(surah=args.surah, limit=args.limit), sys.stdout)
        return 0

    summary = run_storage(surah=args.surah, limit=args.limit)
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
