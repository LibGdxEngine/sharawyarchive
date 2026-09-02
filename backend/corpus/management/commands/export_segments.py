"""Export the segment mapping — segments plus their source and audio rows — as JSON.

The counterpart of ``import_segments``: together they move a corpus mapping
between databases without re-running the pipeline. Audio bytes never travel,
only the rows pointing at them, so a mapping is only meaningful against object
storage that already holds those keys (``import_segments --verify-r2`` checks).

Nothing here writes to the database.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from corpus.models import Segment, SegmentKind


def serialize(segment: Segment) -> dict[str, Any]:
    """One segment as the JSON record ``import_segments`` reads back."""
    source = segment.source
    audio = segment.audio
    return {
        "source": {
            "title": source.title,
            "kind": source.kind,
            "description": source.description,
            "rights_note": source.rights_note,
        },
        "kind": segment.kind,
        "surah": segment.surah_id,
        "ayah_start": segment.ayah_start,
        "ayah_end": segment.ayah_end,
        "ordinal": segment.ordinal,
        "duration_ms": segment.duration_ms,
        "title": segment.title,
        "status": segment.status,
        "audio": {
            "sha256": audio.sha256,
            "storage_key": audio.storage_key,
            "duration_ms": audio.duration_ms,
            "mime": audio.mime,
            "bitrate": audio.bitrate,
            "sample_rate": audio.sample_rate,
            "size_bytes": audio.size_bytes,
        },
    }


class Command(BaseCommand):
    help = "Export Segment rows, with their Source and AudioAsset rows, to a JSON file."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("output", help="Path of the JSON file to write.")
        parser.add_argument(
            "--kind",
            choices=SegmentKind.values,
            default=None,
            help="Only export segments of this kind.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        segments = Segment.objects.select_related("source", "audio").order_by(
            "source_id", "ordinal", "id"
        )
        if options["kind"]:
            segments = segments.filter(kind=options["kind"])

        data = [serialize(segment) for segment in segments]
        output = Path(options["output"])
        try:
            output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            raise CommandError(f"could not write {output}: {exc}") from exc

        self.stdout.write(self.style.SUCCESS(f"wrote {len(data)} segments to {output}"))
