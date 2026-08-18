"""Cluster chunk embeddings into candidate topics.

Offline and safe to re-run: everything it creates is unpublished, so a bad run
is invisible to readers and ``--rebuild`` throws it away::

    python manage.py build_topics --rebuild

The clustering and labelling live in :mod:`corpus.topics`; this command is the
operator's handle on them.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from corpus.topics import MIN_CHUNKS, NotEnoughChunks, build_topics


class Command(BaseCommand):
    help = "Cluster chunk embeddings into unpublished candidate topics."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--min-chunks",
            type=int,
            default=MIN_CHUNKS,
            help=f"Refuse to cluster fewer embedded chunks than this (default {MIN_CHUNKS}).",
        )
        parser.add_argument(
            "--rebuild",
            action="store_true",
            help="Delete the existing auto-* topics first. Hand-made topics are left alone.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            result = build_topics(
                min_chunks=options["min_chunks"], rebuild=options["rebuild"]
            )
        except NotEnoughChunks as error:
            raise CommandError(str(error)) from error

        if result.topics_deleted:
            self.stdout.write(f"deleted {result.topics_deleted} previous auto topic(s)")
        self.stdout.write(
            f"{result.algorithm} over {result.chunks_considered} embedded chunks "
            f"-> {len(result.topics)} topic(s), {result.chunks_clustered} passage(s) "
            f"assigned, labelled by {result.labeler}"
        )
        for topic in result.topics:
            self.stdout.write(f"  {topic.slug}\t{topic.name_ar}")
        self.stdout.write(
            self.style.WARNING(
                "every topic is unpublished: review the labels in the admin and "
                "publish the ones that hold up"
            )
        )
