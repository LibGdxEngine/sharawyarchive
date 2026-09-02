"""Dump Segment rows (with their Source and AudioAsset) to a JSON list.

The inverse of ``import_segments``: the two round-trip the ayah↔audio mapping
between environments (e.g. dev → prod) without touching the audio objects
themselves, which travel separately in the R2/S3 bucket.

Each record carries the segment's fields plus a nested ``source`` and ``audio``
object. ``surah`` is the surah *number* (``Surah`` is keyed by it), so the
importer resolves it against whatever Quran text is already loaded — Quran data
is never carried in this file (``CLAUDE.md`` rule 1).
"""

from __future__ import annotations

import json
import sys
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from corpus.models import Segment, SegmentKind


def serialize_segment(segment: Segment) -> dict[str, Any]:
    audio = segment.audio
    return {
        "source": {
            "title": segment.source.title,
            "kind": segment.source.kind,
            "description": segment.source.description,
            "rights_note": segment.source.rights_note,
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
    help = "Export Segment/Source/AudioAsset rows to a JSON list (round-trips with import_segments)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--output",
            default="-",
            help="Destination file, or '-' for stdout (default).",
        )
        parser.add_argument(
            "--source", default=None, help="Only segments filed under this Source title."
        )
        parser.add_argument(
            "--kind",
            default=None,
            choices=SegmentKind.values,
            help="Only segments of this kind.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        qs = Segment.objects.select_related("source", "audio", "surah").order_by(
            "source_id", "ordinal", "id"
        )
        if options["source"] is not None:
            qs = qs.filter(source__title=options["source"])
        if options["kind"] is not None:
            qs = qs.filter(kind=options["kind"])

        data = [serialize_segment(seg) for seg in qs.iterator()]
        payload = json.dumps(data, ensure_ascii=False, indent=1)

        if options["output"] == "-":
            sys.stdout.write(payload)
            sys.stdout.write("\n")
        else:
            with open(options["output"], "w", encoding="utf-8") as fh:
                fh.write(payload)
            self.stdout.write(
                self.style.SUCCESS(f"exported {len(data)} segments to {options['output']}")
            )
