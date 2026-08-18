"""Import the canonical Quran text from the cached Tanzil files.

Project rule 1: this command is the only writer of ``quran.Surah`` and
``quran.Ayah``. Re-running it is a no-op — rows are keyed on their natural keys
and skipped entirely when nothing changed.
"""

from __future__ import annotations

import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from corpus.arabic import normalize_for_index
from quran import tanzil
from quran.models import Ayah, Surah


@dataclass
class Tally:
    """Row-level outcome counters for one model."""

    created: int = 0
    updated: int = 0
    unchanged: int = 0

    def __iadd__(self, other: Tally) -> Tally:
        self.created += other.created
        self.updated += other.updated
        self.unchanged += other.unchanged
        return self

    def line(self) -> str:
        return f"created {self.created}, updated {self.updated}, unchanged {self.unchanged}"


def _download_missing(paths: list[Path]) -> list[Path]:
    fetched: list[Path] = []
    for path in paths:
        if path.exists():
            continue
        url = tanzil.TANZIL_URLS[path]
        path.parent.mkdir(parents=True, exist_ok=True)
        # The URL is a fixed https constant from tanzil.TANZIL_URLS, never user input.
        with urllib.request.urlopen(url, timeout=120) as response:
            path.write_bytes(response.read())
        fetched.append(path)
    return fetched


class Command(BaseCommand):
    help = "Import Surah and Ayah rows from the cached Tanzil files in quran/data/."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--flush",
            action="store_true",
            help="Delete every Surah and Ayah row before importing.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        paths = [tanzil.UTHMANI_PATH, tanzil.SIMPLE_PATH, tanzil.METADATA_PATH]
        try:
            for path in _download_missing(paths):
                self.stdout.write(f"downloaded {path.name}")
        except OSError as exc:
            raise CommandError(f"could not download Tanzil sources: {exc}") from exc

        try:
            metadata = tanzil.parse_metadata(tanzil.METADATA_PATH.read_text(encoding="utf-8"))
            uthmani = tanzil.parse_ayah_lines(tanzil.UTHMANI_PATH.read_text(encoding="utf-8"))
            imlaei = tanzil.parse_ayah_lines(tanzil.SIMPLE_PATH.read_text(encoding="utf-8"))
            tanzil.validate_full_quran(metadata, uthmani)
            tanzil.check_ayah_counts(metadata, uthmani)
            uthmani, uthmani_stripped = tanzil.strip_sura_bismillah(uthmani)
            imlaei, imlaei_stripped = tanzil.strip_sura_bismillah(imlaei)
        except (OSError, tanzil.TanzilParseError) as exc:
            raise CommandError(str(exc)) from exc

        expected = tanzil.BISMILLAH_PREFIXED_SURAH_COUNT
        if uthmani_stripped != expected or imlaei_stripped != expected:
            raise CommandError(
                f"expected {expected} inlined sura-opening basmalas, found "
                f"{uthmani_stripped} (uthmani) and {imlaei_stripped} (imlaei)"
            )

        imlaei_by_key = {line.key: line.text for line in imlaei}
        missing = [line.key for line in uthmani if line.key not in imlaei_by_key]
        if missing:
            raise CommandError(
                f"{len(missing)} ayahs missing from the imlaei text, e.g. {missing[:3]}"
            )

        with transaction.atomic():
            if options["flush"]:
                deleted_ayahs, _ = Ayah.objects.all().delete()
                deleted_surahs, _ = Surah.objects.all().delete()
                self.stdout.write(f"flushed {deleted_ayahs} ayah rows, {deleted_surahs} surah rows")

            surah_tally = self._import_surahs(metadata)
            ayah_tally = self._import_ayahs(metadata, uthmani, imlaei_by_key)

        total = Tally()
        total += surah_tally
        total += ayah_tally

        self.stdout.write(f"surahs: {surah_tally.line()}")
        self.stdout.write(f"ayahs: {ayah_tally.line()}")
        self.stdout.write(total.line())
        self.stdout.write(
            self.style.SUCCESS(f"{Surah.objects.count()} surahs, {Ayah.objects.count()} ayahs")
        )

    def _import_surahs(self, metadata: tanzil.QuranMetadata) -> Tally:
        existing = {surah.number: surah for surah in Surah.objects.all()}
        tally = Tally()
        for sura in metadata.suras:
            fields = {
                "name_ar": sura.name_ar,
                "name_ar_plain": normalize_for_index(sura.name_ar),
                "name_en": sura.name_en,
                "ayah_count": sura.ayah_count,
                "revelation_place": sura.revelation_place,
                "order_revealed": sura.order_revealed,
            }
            current = existing.get(sura.number)
            if current is not None and _matches(current, fields):
                tally.unchanged += 1
                continue
            _, created = Surah.objects.update_or_create(number=sura.number, defaults=fields)
            if created:
                tally.created += 1
            else:
                tally.updated += 1
        return tally

    def _import_ayahs(
        self,
        metadata: tanzil.QuranMetadata,
        uthmani: list[tanzil.AyahLine],
        imlaei_by_key: dict[tuple[int, int], str],
    ) -> Tally:
        existing = {(ayah.surah_id, ayah.number): ayah for ayah in Ayah.objects.all()}
        tally = Tally()
        for line in uthmani:
            fields = {
                "text_uthmani": line.text,
                "text_imlaei": imlaei_by_key[line.key],
                "text_normalized": normalize_for_index(line.text),
                "juz": metadata.juz.index_for(line.surah, line.ayah),
                "hizb": metadata.hizb_quarters.index_for(line.surah, line.ayah),
                "page": metadata.pages.index_for(line.surah, line.ayah),
                "sajda": line.key in metadata.sajdas,
            }
            current = existing.get(line.key)
            if current is not None and _matches(current, fields):
                tally.unchanged += 1
                continue
            _, created = Ayah.objects.update_or_create(
                surah_id=line.surah, number=line.ayah, defaults=fields
            )
            if created:
                tally.created += 1
            else:
                tally.updated += 1
        return tally


def _matches(instance: Surah | Ayah, fields: dict[str, Any]) -> bool:
    return all(getattr(instance, name) == value for name, value in fields.items())
