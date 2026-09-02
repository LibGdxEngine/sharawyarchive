"""``manage.py smart_retrieve "<question>"`` — show what hybrid retrieval returns.

A debugging aid: prints every channel's ranked ids and the fused list with
segment, time span and an excerpt. ``--no-llm`` skips the embedding call
(lexical only), which also makes the command work without a provider key.
"""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from corpus.arabic import normalize_light
from search.smart import passages, retrieval

EXCERPT_CHARS = 120


class Command(BaseCommand):
    help = "Print the retrieval candidates for a question (smart search, no answer)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("question")
        parser.add_argument("--surah", type=int)
        parser.add_argument("--source", type=int, dest="source_id")
        parser.add_argument("-k", type=int, default=20, help="how many fused candidates to show")
        parser.add_argument("--no-llm", action="store_true", help="lexical channel only")
        parser.add_argument("--json", action="store_true", dest="as_json")

    def handle(self, *args: Any, **options: Any) -> None:
        filters = retrieval.Filters(surah=options["surah"], source_id=options["source_id"])
        result = retrieval.retrieve(
            options["question"],
            None,
            filters=filters,
            use_llm=not options["no_llm"],
            limit=options["k"],
        )
        rows = passages.hydrate([candidate.passage_id for candidate in result.candidates])
        by_id = {row.pk: row for row in rows}

        if options["as_json"]:
            payload = {
                "queries": result.queries,
                "warnings": result.warnings,
                "lists": [
                    {"name": lst.name, "weight": lst.weight, "ids": lst.ids}
                    for lst in result.lists
                ],
                "candidates": [
                    {
                        "rank": rank,
                        "passage_id": candidate.passage_id,
                        "segment_id": by_id[candidate.passage_id].segment_id,
                        "start_ms": by_id[candidate.passage_id].start_ms,
                        "end_ms": by_id[candidate.passage_id].end_ms,
                        "rrf": round(candidate.rrf, 6),
                        "channels": candidate.channel_ranks,
                    }
                    for rank, candidate in enumerate(result.candidates, start=1)
                    if candidate.passage_id in by_id
                ],
            }
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=1))
            return

        for warning in result.warnings:
            self.stderr.write(f"warning: {warning}")
        for lst in result.lists:
            shown = ", ".join(str(pid) for pid in lst.ids[:10])
            self.stdout.write(f"[{lst.name} ×{lst.weight:g}] {len(lst.ids)} hits: {shown}")
        self.stdout.write("")
        for rank, candidate in enumerate(result.candidates, start=1):
            row = by_id.get(candidate.passage_id)
            if row is None:
                continue
            channels = " ".join(
                f"{name}#{position}" for name, position in candidate.channel_ranks.items()
            )
            excerpt = normalize_light(row.text)[:EXCERPT_CHARS]
            self.stdout.write(
                f"{rank:>2}. passage {row.pk} · segment {row.segment_id} · {row.header}\n"
                f"    {row.start_ms}–{row.end_ms} ms · rrf {candidate.rrf:.4f} · {channels}\n"
                f"    {excerpt}…"
            )
