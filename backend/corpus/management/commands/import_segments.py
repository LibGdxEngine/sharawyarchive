"""Import a JSON export of Segment/Source/AudioAsset rows (see export_segments).

Idempotent and resumable (``CLAUDE.md`` rule 6): audio is keyed by content hash
(``AudioAsset.sha256``) and a segment is keyed by its audio asset, so re-running
upserts rather than duplicating. The audio objects themselves are expected to be
in the bucket already; ``--verify-r2`` HEAD-checks each expected key.

Quran text is never created here — a record's ``surah`` is resolved against the
already-loaded ``quran.Surah`` table, and a record naming an absent surah is
counted as failed and skipped (rule 1).

Usage::

    python manage.py import_segments segments_export.json --dry-run --verify-r2 \\
        --exclude-samples --missing-manifest /tmp/missing_r2_keys.txt
    python manage.py import_segments segments_export.json --verify-r2 --exclude-samples
"""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from corpus.models import AudioAsset, Segment, Source
from corpus.storage import audio_key, object_exists, waveform_key
from quran.models import Surah

# Dev fixtures were filed under source titles containing this word ("sample").
SAMPLE_MARKER = "عينة"


def _source_title(record: dict[str, Any]) -> str:
    source = record.get("source")
    if isinstance(source, dict):
        return source.get("title", "")
    return source or ""


class Command(BaseCommand):
    help = "Import Segment/Source/AudioAsset rows from a JSON export (idempotent)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("path", help="Path to the JSON export.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Do everything in a transaction and roll it back; report the tally only.",
        )
        parser.add_argument(
            "--verify-r2",
            action="store_true",
            help="HEAD-check each audio + waveform key against object storage.",
        )
        parser.add_argument(
            "--exclude-samples",
            action="store_true",
            help=f"Skip records whose source title contains {SAMPLE_MARKER!r}.",
        )
        parser.add_argument(
            "--missing-manifest",
            default=None,
            help="With --verify-r2, write every missing storage key to this file.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            with open(options["path"], encoding="utf-8") as fh:
                records = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"cannot read export {options['path']}: {exc}") from exc
        if not isinstance(records, list):
            raise CommandError("export must be a JSON list of segment records")

        dry_run: bool = options["dry_run"]
        exclude_samples: bool = options["exclude_samples"]

        created = updated = skipped_samples = failed_no_surah = 0
        # Deduped audio keys of the records we actually imported, for --verify-r2.
        shas: list[str] = []

        with transaction.atomic():
            for record in records:
                if exclude_samples and SAMPLE_MARKER in _source_title(record):
                    skipped_samples += 1
                    continue

                surah_number = record.get("surah")
                surah = None
                if surah_number is not None:
                    surah = Surah.objects.filter(number=surah_number).first()
                    if surah is None:
                        failed_no_surah += 1
                        self.stderr.write(
                            self.style.WARNING(
                                f"no surah {surah_number} loaded — skipping "
                                f"{record.get('title', '<untitled>')!r}"
                            )
                        )
                        continue

                source = record.get("source")
                source_title = _source_title(record)
                source_kind = source.get("kind", "") if isinstance(source, dict) else record["kind"]
                source_obj, _ = Source.objects.get_or_create(
                    title=source_title,
                    kind=source_kind,
                    defaults={
                        "description": source.get("description", "")
                        if isinstance(source, dict)
                        else "",
                        "rights_note": source.get("rights_note", "")
                        if isinstance(source, dict)
                        else "",
                    },
                )

                audio = record["audio"]
                asset, _ = AudioAsset.objects.update_or_create(
                    sha256=audio["sha256"],
                    defaults={
                        "storage_key": audio["storage_key"],
                        "duration_ms": audio["duration_ms"],
                        "mime": audio["mime"],
                        "bitrate": audio.get("bitrate"),
                        "sample_rate": audio.get("sample_rate"),
                        "size_bytes": audio["size_bytes"],
                    },
                )

                _, was_created = Segment.objects.update_or_create(
                    audio=asset,
                    defaults={
                        "source": source_obj,
                        "kind": record["kind"],
                        "surah": surah,
                        "ayah_start": record.get("ayah_start"),
                        "ayah_end": record.get("ayah_end"),
                        "ordinal": record.get("ordinal", 0),
                        "duration_ms": record["duration_ms"],
                        "title": record.get("title", ""),
                        "status": record.get("status", "pending"),
                    },
                )
                if was_created:
                    created += 1
                else:
                    updated += 1
                shas.append(audio["sha256"])

                processed = created + updated
                if processed % 500 == 0:
                    self.stdout.write(f"...{processed} segments processed")

            if dry_run:
                transaction.set_rollback(True)

        verb = "would create" if dry_run else "created"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb} {created}, updated {updated}, "
                f"skipped {skipped_samples} sample(s), {failed_no_surah} failed (no surah)"
            )
        )

        if options["verify_r2"]:
            self._verify_r2(shas, options["missing_manifest"])

    def _verify_r2(self, shas: list[str], manifest_path: str | None) -> None:
        unique = sorted(set(shas))
        self.stdout.write(f"verifying {len(unique)} audio + waveform key(s) against storage...")
        missing_audio: list[str] = []
        missing_waveform: list[str] = []
        for i, sha in enumerate(unique, start=1):
            akey, wkey = audio_key(sha), waveform_key(sha)
            if not object_exists(akey):
                missing_audio.append(akey)
            if not object_exists(wkey):
                missing_waveform.append(wkey)
            if i % 500 == 0:
                self.stdout.write(f"...{i}/{len(unique)} verified")

        if manifest_path is not None:
            with open(manifest_path, "w", encoding="utf-8") as fh:
                for key in missing_audio + missing_waveform:
                    fh.write(f"{key}\n")
            self.stdout.write(
                f"wrote {len(missing_audio) + len(missing_waveform)} missing key(s) "
                f"to {manifest_path}"
            )

        style = self.style.ERROR if (missing_audio or missing_waveform) else self.style.SUCCESS
        self.stdout.write(
            style(
                f"R2 verify: {len(missing_audio)} audio and "
                f"{len(missing_waveform)} waveform key(s) missing "
                f"of {len(unique)} asset(s)"
            )
        )
