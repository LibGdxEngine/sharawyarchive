"""``manage.py smart_eval --stage retrieval`` — score retrieval against the golden set.

Later phases add ``rerank`` and ``full``; asking for them now fails loudly.
Reports are JSON with ids and numbers only (no passage text), meant to be
committed under ``docs/smart-search/eval-<date>.json``.
"""

from __future__ import annotations

import json
import subprocess
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from search.models import Passage
from search.smart import retrieval
from search.smart.eval import GOLDEN_PATH, GoldenError, RetrievalResult, load_golden
from search.smart.eval import metrics as m


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False
        ).stdout.strip()
    except OSError:
        return ""


class Command(BaseCommand):
    help = "Evaluate smart search against search/smart/eval/golden.jsonl."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--stage", choices=["retrieval", "rerank", "full"], default="retrieval")
        parser.add_argument("--golden", type=Path, default=GOLDEN_PATH)
        parser.add_argument("--limit", type=int)
        parser.add_argument("--out", type=Path, help="write the JSON report here")
        parser.add_argument("-k", type=int, default=retrieval.FUSED_LIMIT)
        parser.add_argument("--no-llm", action="store_true", help="lexical retrieval only")

    def handle(self, *args: Any, **options: Any) -> None:
        if options["stage"] != "retrieval":
            raise CommandError(f"--stage {options['stage']} arrives with a later phase")
        try:
            items = load_golden(options["golden"])
        except (OSError, GoldenError) as error:
            raise CommandError(str(error)) from error
        labelled = [item for item in items if item.labelled]
        if options["limit"]:
            labelled = labelled[: options["limit"]]
        if not labelled:
            raise CommandError("no labelled items (every item lacks expected_segment_ids)")

        k = options["k"]
        results: list[RetrievalResult] = []
        for item in labelled:
            started = time.monotonic()
            result = RetrievalResult(id=item.id)
            try:
                found = retrieval.retrieve(
                    item.question, None, use_llm=not options["no_llm"], limit=k
                )
                segment_of = dict(
                    Passage.objects.filter(
                        pk__in=[candidate.passage_id for candidate in found.candidates]
                    ).values_list("pk", "segment_id")
                )
                ranked: list[int] = []
                for candidate in found.candidates:
                    segment_id = segment_of.get(candidate.passage_id)
                    if segment_id is not None and segment_id not in ranked:
                        ranked.append(segment_id)
                result.ranked_segment_ids = ranked
                result.hit_rank = m.first_hit_rank(ranked, item.expected_segment_ids)
                if found.usage and found.usage.cost_usd is not None:
                    result.cost_usd = str(found.usage.cost_usd)
            except Exception as error:  # noqa: BLE001 — one bad item must not sink the report
                result.error = f"{type(error).__name__}: {error}"
            result.latency_ms = int((time.monotonic() - started) * 1000)
            results.append(result)

        recall = m.mean(
            [1.0 if r.hit_rank is not None and r.hit_rank <= k else 0.0 for r in results]
        )
        mrr = m.mean([0.0 if r.hit_rank is None else 1.0 / r.hit_rank for r in results])
        latencies = [float(r.latency_ms) for r in results]
        report = {
            "run": {
                "date": datetime.now(UTC).isoformat(timespec="seconds"),
                "git_sha": _git_sha(),
                "stage": "retrieval",
                "k": k,
                "llm": not options["no_llm"],
                "embedding_model": settings.SMART_EMBEDDING_MODEL,
                "n": len(results),
            },
            "summary": {
                f"recall_at_{k}": round(recall, 4),
                "mrr": round(mrr, 4),
                "latency_ms": {
                    "p50": m.percentile(latencies, 50),
                    "p95": m.percentile(latencies, 95),
                },
                "cost_usd": str(sum(Decimal(r.cost_usd) for r in results)),
                "errors": sum(1 for r in results if r.error),
            },
            "items": [
                {
                    "id": r.id,
                    "hit_rank": r.hit_rank,
                    "ranked_segment_ids": r.ranked_segment_ids[:k],
                    "latency_ms": r.latency_ms,
                    "error": r.error,
                }
                for r in results
            ],
        }
        if options["out"]:
            options["out"].write_text(
                json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
            )
        self.stdout.write(
            f"retrieval: n={len(results)} recall@{k}={recall:.3f} mrr={mrr:.3f} "
            f"p95={report['summary']['latency_ms']['p95']:.0f}ms "
            f"errors={report['summary']['errors']}"
        )
