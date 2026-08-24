"""Rebuild the Meilisearch ``chunks`` index from the database.

The pipeline's ``index`` stage writes chunks as each segment is processed and
skips segments already marked ``indexed`` — so a database restored onto a fresh
Meilisearch instance (a production import of a dump, a rebuilt search volume)
ends up with indexed segments and an empty index. This command closes that gap.
It is idempotent: documents are keyed by Chunk id, so re-running overwrites
rather than duplicates, and an interrupted run can simply be repeated. It only
upserts — dropping stale documents is ``services.delete_segment_chunks``'s job.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from corpus.models import Chunk
from search import services

BATCH_SIZE = 1000
PROGRESS_EVERY = 10 * BATCH_SIZE


class Command(BaseCommand):
    help = "Ensure the chunks index exists and upsert every Chunk row into it."

    def handle(self, *args: Any, **options: Any) -> None:
        services.ensure_chunks_index()
        indexed = 0
        batch: list[Chunk] = []
        chunks = Chunk.objects.select_related("transcript__segment").order_by("pk")
        for chunk in chunks.iterator(chunk_size=BATCH_SIZE):
            batch.append(chunk)
            if len(batch) < BATCH_SIZE:
                continue
            indexed += services.index_chunks(batch)
            batch = []
            if indexed % PROGRESS_EVERY == 0:
                self.stdout.write(f"indexed {indexed} chunks...")
        indexed += services.index_chunks(batch)
        self.stdout.write(
            self.style.SUCCESS(f"indexed {indexed} chunks into {services.chunks_index_name()}")
        )
