"""``manage.py embed_passages`` — embed every passage whose vector is missing or stale.

Resumable by construction: a passage is selected while its ``embedded_hash``
differs from its ``content_hash`` (or its vector came from another model),
and each batch is written as soon as it returns. A batch that keeps failing
is skipped and logged; the next run picks it up.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from corpus.arabic import normalize_light
from search.models import Passage
from search.smart import embedding_model_tag, llm

BATCH_SIZE = 48
TOKENS_PER_WORD = 2.5
"""Rough Arabic tokenisation rate, for the --dry-run estimate only."""
PROGRESS_EVERY = 20


def embedding_text(header: str, text: str) -> str:
    """What gets embedded: the metadata line, then the text without harakat.

    Readers type without vowel marks and the marks cost tokens, so the
    letters-only form (:func:`corpus.arabic.normalize_light`) is what the
    model sees on both sides.
    """
    return f"{header}\n{normalize_light(text)}"


class Command(BaseCommand):
    help = "Embed smart-search passages through OpenRouter (missing or stale vectors only)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
        parser.add_argument("--limit", type=int, help="embed at most this many passages")
        parser.add_argument("--transcript", type=int, action="append")
        parser.add_argument("--force", action="store_true", help="re-embed up-to-date rows too")
        parser.add_argument("--max-cost-usd", type=Decimal, default=Decimal("2"))
        parser.add_argument("--dry-run", action="store_true", help="count and estimate, no calls")

    def handle(self, *args: Any, **options: Any) -> None:
        tag = embedding_model_tag()
        queryset = Passage.objects.order_by("pk")
        if not options["force"]:
            queryset = queryset.filter(
                Q(embedding__isnull=True)
                | ~Q(embedded_hash=F("content_hash"))
                | ~Q(embedding_model=tag)
            )
        if options["transcript"]:
            queryset = queryset.filter(transcript_id__in=options["transcript"])
        ids = list(queryset.values_list("pk", flat=True))
        if options["limit"]:
            ids = ids[: options["limit"]]

        if options["dry_run"]:
            words = sum(
                Passage.objects.filter(pk__in=ids).values_list("word_count", flat=True)
            )
            tokens = int(words * TOKENS_PER_WORD) + len(ids) * 30
            self.stdout.write(
                f"would embed {len(ids)} passages with {tag}: ≈{tokens:,} tokens"
            )
            return

        batch_size = max(1, options["batch_size"])
        embedded = failed = batches = tokens = 0
        cost = Decimal("0")
        for start in range(0, len(ids), batch_size):
            batch_ids = ids[start : start + batch_size]
            rows = list(
                Passage.objects.filter(pk__in=batch_ids)
                .order_by("pk")
                .values("id", "header", "text", "content_hash")
            )
            texts = [embedding_text(row["header"], row["text"]) for row in rows]
            try:
                vectors, usage = llm.embed(texts)
            except llm.LLMError as error:
                failed += len(rows)
                self.stderr.write(f"batch at {batch_ids[0]} failed, skipped: {error}")
                continue
            now = timezone.now()
            with transaction.atomic():
                for row, vector in zip(rows, vectors, strict=True):
                    # The hash guard leaves alone a passage whose text changed mid-run.
                    Passage.objects.filter(pk=row["id"], content_hash=row["content_hash"]).update(
                        embedding=vector,
                        embedding_model=tag,
                        embedded_hash=row["content_hash"],
                        embedded_at=now,
                    )
            embedded += len(rows)
            batches += 1
            tokens += usage.prompt_tokens
            cost += usage.cost_usd or Decimal("0")
            if batches % PROGRESS_EVERY == 0:
                self.stdout.write(f"… {embedded} passages, {tokens:,} tokens, ${cost:.4f}")
            if cost > options["max_cost_usd"]:
                self.stderr.write(f"stopping: cost ${cost:.4f} exceeds --max-cost-usd")
                break
        self.stdout.write(
            f"embedded {embedded} passages in {batches} batches with {tag}: "
            f"{tokens:,} tokens, ${cost:.4f}; failed {failed}"
        )
