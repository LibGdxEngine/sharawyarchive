"""``manage.py build_passages`` — (re)build the smart-search passages over the chunks.

Idempotent and resumable: a transcript whose passages already hash the same
is skipped, changed text is rebuilt with its still-valid embeddings carried
over, and an interrupted run simply continues where it stopped.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from search.smart import passages

PROGRESS_EVERY = 200


class Command(BaseCommand):
    help = "Build or refresh smart-search passages (150–300-word windows over the chunks)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--transcript", type=int, action="append", help="only this transcript id"
        )
        parser.add_argument("--segment", type=int, action="append", help="only this segment id")
        parser.add_argument("--limit", type=int, help="stop after this many transcripts")
        parser.add_argument(
            "--rebuild", action="store_true", help="rewrite even unchanged transcripts"
        )
        parser.add_argument("--dry-run", action="store_true", help="plan and report, write nothing")
        parser.add_argument("--min-words", type=int, default=passages.MIN_WORDS)
        parser.add_argument("--max-words", type=int, default=passages.MAX_WORDS)

    def handle(self, *args: Any, **options: Any) -> None:
        queryset = passages.transcripts_with_chunks()
        if options["transcript"]:
            queryset = queryset.filter(pk__in=options["transcript"])
        if options["segment"]:
            queryset = queryset.filter(segment_id__in=options["segment"])
        if options["limit"]:
            queryset = queryset[: options["limit"]]

        total = passages.BuildStats()
        for count, transcript in enumerate(queryset.iterator(chunk_size=100), start=1):
            total += passages.build_for_transcript(
                transcript,
                dry_run=options["dry_run"],
                force=options["rebuild"],
                min_words=options["min_words"],
                max_words=options["max_words"],
            )
            if count % PROGRESS_EVERY == 0:
                self.stdout.write(f"… {count} transcripts")
        mode = "would write" if options["dry_run"] else "wrote"
        self.stdout.write(
            f"passages: {mode} {total.created} (deleted {total.deleted}, unchanged "
            f"{total.unchanged}, embeddings carried {total.carried}) over "
            f"{total.transcripts} transcripts"
        )
