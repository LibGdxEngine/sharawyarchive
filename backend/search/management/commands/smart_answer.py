"""``manage.py smart_answer "<question>"`` — run the whole pipeline and print the JSON."""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from search.smart import pipeline, retrieval


class Command(BaseCommand):
    help = "Answer a question with smart search and print the response as JSON."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("question")
        parser.add_argument("--surah", type=int)
        parser.add_argument("--source", type=int, dest="source_id")
        parser.add_argument("--debug", action="store_true", help="include the debug block")
        parser.add_argument("--no-llm", action="store_true", help="no provider calls at all")

    def handle(self, *args: Any, **options: Any) -> None:
        response = pipeline.run_smart_search(
            options["question"],
            filters=retrieval.Filters(surah=options["surah"], source_id=options["source_id"]),
            run=pipeline.RunContext(debug=options["debug"], use_llm=not options["no_llm"]),
        )
        # mode="json": the debug block carries Decimal costs, which json.dumps refuses.
        self.stdout.write(
            json.dumps(response.model_dump(mode="json"), ensure_ascii=False, indent=1)
        )
