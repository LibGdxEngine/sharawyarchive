"""Import a segment mapping produced by ``export_segments``.

Every row is keyed on a natural key — a source by ``(title, kind)``, an audio
asset by its content hash, a segment by ``(audio, source, ordinal)`` — so a
second run of the same file adds nothing (project rule 6). Matched rows are
reconciled rather than left alone: like ``import_quran``, this command uses
``update_or_create``, so re-importing a corrected file repairs drift (a stale
``AudioAsset.storage_key`` pointing at the wrong R2 object, say) instead of
silently keeping the old value.

Each record is imported in its own transaction, so one malformed record is
counted as a failure and skipped rather than taking the whole file with it.
Only the up-front checks (unreadable file, unknown surah) abort the run. That
per-record transaction also bounds what ``--dry-run`` can tell you: each
record's rollback happens before the next record runs, so a dry run cannot see
one record deduplicating onto a Source or AudioAsset an earlier record in the
same file would have written, and may count as created what a real run would
reuse.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import DatabaseError, transaction

from corpus import storage
from corpus.models import AudioAsset, Segment, Source
from quran.models import Surah


@dataclass
class Tally:
    """Row-level outcome counters for the segments in one file."""

    created: int = 0
    updated: int = 0
    failed: int = 0

    def line(self) -> str:
        return f"created {self.created}, updated {self.updated}, failed {self.failed}"


def _load(path: Path) -> list[Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CommandError(f"could not read {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CommandError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise CommandError(f"{path} must hold a list of records, got {type(data).__name__}")
    return data


def _referenced_surahs(records: list[Any]) -> set[int]:
    """Surah numbers the file points at.

    Deliberately forgiving: this runs before any per-record error handling
    exists, so a record shaped wrongly is left for the import loop to fail on.
    """
    numbers: set[int] = set()
    for record in records:
        number = record.get("surah") if isinstance(record, dict) else None
        if isinstance(number, int) and not isinstance(number, bool):
            numbers.add(number)
    return numbers


def _sha256_of(record: Any) -> str:
    audio = record.get("audio") if isinstance(record, dict) else None
    sha256 = audio.get("sha256") if isinstance(audio, dict) else None
    return sha256 if isinstance(sha256, str) else "unknown sha256"


class Command(BaseCommand):
    help = "Import a segment mapping written by export_segments."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("input", help="Path of the JSON file to read.")
        parser.add_argument(
            "--verify-r2",
            action="store_true",
            help="Report audio and waveform keys missing from object storage. Never blocks a row.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Validate and tally without writing anything. Each record rolls back "
                "before the next one runs, so the tally cannot show two records in this "
                "file deduplicating onto one Source or AudioAsset the way a real run would."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        path = Path(options["input"])
        records = _load(path)

        wanted = _referenced_surahs(records)
        known = set(Surah.objects.filter(pk__in=wanted).values_list("number", flat=True))
        missing_surahs = sorted(wanted - known)
        if missing_surahs:
            raise CommandError(
                f"surahs not in this database: {missing_surahs}. "
                "Run manage.py import_quran first."
            )

        tally = Tally()
        missing_keys: list[str] = []
        failures: list[str] = []
        for index, record in enumerate(records):
            try:
                with transaction.atomic():
                    created = self._import_record(
                        record, verify_r2=options["verify_r2"], missing_keys=missing_keys
                    )
                    if options["dry_run"]:
                        transaction.set_rollback(True)
            except (KeyError, TypeError, ValueError, LookupError, DatabaseError) as exc:
                # A malformed record or a rejected write must not stop the file.
                tally.failed += 1
                failures.append(f"record {index} ({_sha256_of(record)}): {exc}")
                continue
            if created:
                tally.created += 1
            else:
                tally.updated += 1

        self.stdout.write(tally.line())
        for key in missing_keys:
            self.stdout.write(self.style.WARNING(f"missing in object storage: {key}"))
        for failure in failures:
            self.stdout.write(self.style.ERROR(f"failed: {failure}"))

        if tally.failed:
            self.stdout.write(
                self.style.ERROR(f"{tally.failed} of {len(records)} records failed to import")
            )
        elif options["dry_run"]:
            self.stdout.write(
                self.style.SUCCESS(f"dry run: {len(records)} records validated, nothing written")
            )
        else:
            self.stdout.write(self.style.SUCCESS(f"imported {len(records)} records from {path}"))

    def _import_record(
        self, record: Any, *, verify_r2: bool, missing_keys: list[str]
    ) -> bool:
        """Write one record's rows, reconciling any that already exist.

        Returns whether the segment was new.
        """
        source_data = record["source"]
        audio_data = record["audio"]

        source, _ = Source.objects.update_or_create(
            title=source_data["title"],
            kind=source_data["kind"],
            defaults={
                "description": source_data.get("description", ""),
                "rights_note": source_data.get("rights_note", ""),
            },
        )
        asset, _ = AudioAsset.objects.update_or_create(
            sha256=audio_data["sha256"],
            defaults={
                "storage_key": audio_data["storage_key"],
                "duration_ms": audio_data["duration_ms"],
                "mime": audio_data["mime"],
                "bitrate": audio_data.get("bitrate"),
                "sample_rate": audio_data.get("sample_rate"),
                "size_bytes": audio_data["size_bytes"],
            },
        )
        if verify_r2:
            for key in (asset.storage_key, storage.waveform_key(asset.sha256)):
                if not storage.object_exists(key):
                    missing_keys.append(key)

        number = record["surah"]
        surah = None if number is None else Surah.objects.filter(pk=number).first()
        # ``audio`` alone is not a natural key: Segment.audio is a plain FK, so one
        # asset can legitimately back several segments. Ordinal within a source is
        # what actually identifies the segment.
        _, created = Segment.objects.update_or_create(
            audio=asset,
            source=source,
            ordinal=record["ordinal"],
            defaults={
                "kind": record["kind"],
                "surah": surah,
                "ayah_start": record["ayah_start"],
                "ayah_end": record["ayah_end"],
                "duration_ms": record["duration_ms"],
                "title": record["title"],
                "status": record["status"],
            },
        )
        return bool(created)
