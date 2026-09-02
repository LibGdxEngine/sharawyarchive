"""``manage.py smart_label "<question>"`` — candidate segments for labelling the golden set.

Retrieval only, so it runs with or without a provider key; prints the
segments behind the fused candidates once each, with the passage that put
them there, so a labeller can pick ``expected_segment_ids`` quickly.
"""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from corpus.arabic import normalize_light
from search.smart import passages, retrieval

EXCERPT_CHARS = 220


class Command(BaseCommand):
    help = "List the segments retrieval finds for a question, for golden-set labelling."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("question")
        parser.add_argument("-k", type=int, default=retrieval.FUSED_LIMIT)
        parser.add_argument("--no-llm", action="store_true", help="lexical retrieval only")
        parser.add_argument("--json", action="store_true", dest="as_json")

    def handle(self, *args: Any, **options: Any) -> None:
        result = retrieval.retrieve(
            options["question"], None, use_llm=not options["no_llm"], limit=options["k"]
        )
        rows = passages.hydrate([candidate.passage_id for candidate in result.candidates])
        segments: list[dict[str, Any]] = []
        seen: set[int] = set()
        for rank, row in enumerate(rows, start=1):
            if row.segment_id in seen:
                continue
            seen.add(row.segment_id)
            segments.append(
                {
                    "rank": rank,
                    "segment_id": row.segment_id,
                    "title": row.segment.title,
                    "surah": row.surah,
                    "ayah_start": row.ayah_start,
                    "ayah_end": row.ayah_end,
                    "passage_id": row.pk,
                    "start_ms": int(row.start_ms),
                    "excerpt": normalize_light(row.text)[:EXCERPT_CHARS],
                }
            )
        if options["as_json"]:
            self.stdout.write(
                json.dumps(
                    {"question": options["question"], "segments": segments},
                    ensure_ascii=False,
                    indent=1,
                )
            )
            return
        for warning in result.warnings:
            self.stderr.write(f"warning: {warning}")
        for item in segments:
            place = f"سورة {item['surah']} {item['ayah_start']}–{item['ayah_end']}"
            self.stdout.write(
                f"{item['rank']:>2}. segment {item['segment_id']} · {item['title']} · {place}\n"
                f"    {item['excerpt']}"
            )
        self.stdout.write(
            f"\n{len(segments)} segments — paste the right ids into "
            f"expected_segment_ids of search/smart/eval/golden.jsonl"
        )
