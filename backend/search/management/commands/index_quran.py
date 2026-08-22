"""Index the canonical Quran text into the Meilisearch ``ayahs`` index.

The mushaf corpus is static (``manage.py import_quran`` is the only writer of
``quran.Ayah``), so this command runs on deploy and whenever a fresh
Meilisearch instance is attached. It is idempotent: documents are keyed by
Ayah id, so re-running overwrites rather than duplicates, and the whole run is
a single upsert sweep that can simply be repeated after an interruption.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from quran.models import Ayah
from search import services


class Command(BaseCommand):
    help = "Ensure the ayahs index exists and upsert every Ayah row into it."

    def handle(self, *args: Any, **options: Any) -> None:
        services.ensure_ayahs_index()
        indexed = services.index_ayahs(
            Ayah.objects.order_by("surah_id", "number").iterator(chunk_size=1000)
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"indexed {indexed} ayahs into {services.ayahs_index_name()}"
            )
        )
