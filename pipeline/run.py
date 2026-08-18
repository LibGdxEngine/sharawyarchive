"""The one command: ingest a folder of audio, end to end, in this process.

``python -m pipeline.run --folder F --source-title T --kind khawatir``

It calls the same ``do_*`` functions the Celery tasks wrap, in order, one
segment at a time — no broker, no worker, nothing to babysit. A failing segment
is reported and the loop moves on; re-running over a finished corpus prints
``processed 0`` and exits in seconds.

Use ``manage.py run_pipeline`` instead when the work should go to the
``pipeline`` queue and be picked up by ``celery -A pipeline.celery_app worker``.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import TextIO

from pipeline import parsers, stages

PROCESSED = "processed"
SKIPPED = "skipped"
FAILED = "failed"


@dataclass
class Summary:
    """What the run did, per segment."""

    processed: int = 0
    skipped: int = 0
    failed: int = 0

    def record(self, outcome: str) -> None:
        setattr(self, outcome, getattr(self, outcome) + 1)

    def line(self) -> str:
        return f"processed {self.processed}, skipped {self.skipped}, failed {self.failed}"


def process_segment(segment_id: int, local_path: str) -> tuple[str, list[str]]:
    """Run every stage for one segment. Returns its outcome and stage notes."""
    steps = (
        ("transcode", lambda: stages.do_transcode(segment_id, local_path)),
        ("transcribe", lambda: stages.do_transcribe(segment_id, local_path)),
        ("align", lambda: stages.do_align(segment_id, local_path)),
        ("chunk", lambda: stages.do_chunk(segment_id)),
        ("embed", lambda: stages.do_embed(segment_id)),
        ("index", lambda: stages.do_index_segment(segment_id)),
    )
    notes: list[str] = []
    all_skipped = True
    for name, call in steps:
        result = call()
        if not result.ok:
            notes.append(f"{name} FAILED")
            return FAILED, notes
        notes.append(f"{name} {'skipped' if result.skipped else 'ok'}")
        all_skipped = all_skipped and result.skipped
    return (SKIPPED if all_skipped else PROCESSED), notes


def run_folder(
    folder: str,
    source_title: str,
    kind: str,
    limit: int | None = None,
    surah: int | None = None,
    stdout: TextIO = sys.stdout,
) -> Summary:
    """Ingest ``folder`` and drive every segment through the remaining stages."""
    files = stages.do_ingest(folder, source_title, kind, limit=limit, surah=surah)
    print(f"ingested {len(files)} file(s) from {folder}", file=stdout)

    summary = Summary()
    for position, item in enumerate(files, start=1):
        outcome, notes = process_segment(item.segment_id, item.local_path)
        summary.record(outcome)
        name = item.local_path.rsplit("/", 1)[-1]
        print(
            f"[{position}/{len(files)}] segment {item.segment_id} {name}: "
            f"{', '.join(notes)} -> {outcome}",
            file=stdout,
        )
    print(summary.line(), file=stdout)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.run",
        description="Ingest a folder of Sha'rawy audio into the archive.",
    )
    parser.add_argument("--folder", required=True, help="Folder of audio files (recursive).")
    parser.add_argument("--source-title", required=True, help="Source row to file these under.")
    parser.add_argument(
        "--kind",
        default="khawatir",
        choices=["khawatir", "recitation"],
        help="Kind for files whose name does not imply one (default: khawatir).",
    )
    parser.add_argument("--limit", type=int, default=None, help="Stop after N files.")
    parser.add_argument("--surah", type=int, default=None, help="Only files parsed as this surah.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print how the filenames parse and exit. Touches neither database nor storage.",
    )
    args = parser.parse_args(argv)

    if args.dry_run:
        return parsers.main([args.folder, "--dry-run"])

    summary = run_folder(
        folder=args.folder,
        source_title=args.source_title,
        kind=args.kind,
        limit=args.limit,
        surah=args.surah,
    )
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
