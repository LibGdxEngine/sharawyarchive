"""Hand a folder of audio to the ingestion pipeline.

This command dispatches and returns; it does no work itself. Django must not
import ``pipeline`` (that package carries torch and friends), so the stage is
addressed **by task name** over the ``pipeline`` Celery queue — the routing
comes from ``CELERY_TASK_ROUTES = {'pipeline.*': {'queue': 'pipeline'}}`` in
``core/settings/base.py``.

Nothing happens until a pipeline worker is running::

    celery -A pipeline.celery_app worker -Q pipeline

For a synchronous run with no broker involved, use the pipeline's own driver
instead: ``python -m pipeline.run --folder ... --source-title ...``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from core.celery import app as celery_app
from corpus.models import SegmentKind

INGEST_TASK = "pipeline.ingest"


class Command(BaseCommand):
    help = "Dispatch pipeline.ingest for a folder of audio onto the 'pipeline' queue."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--folder", required=True, help="Folder of audio files (recursive).")
        parser.add_argument(
            "--source-title", required=True, help="Source row the segments are filed under."
        )
        parser.add_argument(
            "--kind",
            default=SegmentKind.KHAWATIR,
            choices=SegmentKind.values,
            help="Kind for files whose name does not imply one.",
        )
        parser.add_argument("--limit", type=int, default=None, help="Stop after N files.")
        parser.add_argument(
            "--surah", type=int, default=None, help="Only files parsed as this surah."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        folder = options["folder"]
        if not Path(folder).is_dir():
            raise CommandError(
                f"folder does not exist or is not a directory: {folder}"
            )
        result = celery_app.send_task(
            INGEST_TASK,
            kwargs={
                "folder": folder,
                "source_title": options["source_title"],
                "kind": options["kind"],
                "limit": options["limit"],
                "surah": options["surah"],
            },
        )
        self.stdout.write(f"dispatched {INGEST_TASK} as task {result.id}")
        self.stdout.write(
            "a pipeline worker must be consuming the 'pipeline' queue: "
            "celery -A pipeline.celery_app worker -Q pipeline"
        )
