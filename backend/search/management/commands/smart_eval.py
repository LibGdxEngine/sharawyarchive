"""``manage.py smart_eval --stage retrieval|rerank|full`` — score against the golden set.

``retrieval`` measures where the expected segment first appears in the fused
candidate list (recall@k, MRR); ``rerank`` runs the reranker on top and
measures the same over what the generator would read (recall@8); ``full``
runs the whole pipeline — abstention accuracy, citation validity, latency and
cost per query, and with ``--judge`` a frontier model's faithfulness verdict
per sentence — and prints the ship gates. Reports are JSON with ids and
numbers only (no passage text), meant to be committed under
``docs/smart-search/eval-<date>.json``.
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
from search.smart import context, pipeline, rerank, retrieval
from search.smart.eval import (
    GOLDEN_PATH,
    FullResult,
    GoldenError,
    GoldenItem,
    RetrievalResult,
    load_golden,
)
from search.smart.eval import metrics as m
from search.smart.eval import report as rep
from search.smart.schemas import RerankedPassage


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False
        ).stdout.strip()
    except OSError:
        return ""


def _segments_of(passage_ids: list[int]) -> list[int]:
    """Segment ids behind ``passage_ids`` in the same order, each once."""
    segment_of = dict(
        Passage.objects.filter(pk__in=passage_ids).values_list("pk", "segment_id")
    )
    ranked: list[int] = []
    for passage_id in passage_ids:
        segment_id = segment_of.get(passage_id)
        if segment_id is not None and segment_id not in ranked:
            ranked.append(segment_id)
    return ranked


class Command(BaseCommand):
    help = "Evaluate smart search against search/smart/eval/golden.jsonl."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--stage", choices=["retrieval", "rerank", "full"], default="retrieval")
        parser.add_argument("--golden", type=Path, default=GOLDEN_PATH)
        parser.add_argument("--limit", type=int)
        parser.add_argument("--out", type=Path, help="write the JSON report here")
        parser.add_argument("-k", type=int, default=retrieval.FUSED_LIMIT)
        parser.add_argument(
            "--no-llm", action="store_true", help="lexical retrieval only, fused order for rerank"
        )
        parser.add_argument(
            "--judge", action="store_true", help="full stage: judge every answer's sentences"
        )

    def handle(self, *args: Any, **options: Any) -> None:
        stage = options["stage"]
        try:
            items = load_golden(options["golden"])
        except (OSError, GoldenError) as error:
            raise CommandError(str(error)) from error
        if stage == "full":
            self._full(items, options)
            return
        labelled = [item for item in items if item.labelled]
        if options["limit"]:
            labelled = labelled[: options["limit"]]
        if not labelled:
            raise CommandError("no labelled items (every item lacks expected_segment_ids)")

        k = options["k"] if stage == "retrieval" else rerank.TOP_N
        use_llm = not options["no_llm"]
        reranker: rerank.Reranker = (
            rerank.LLMListwiseReranker() if use_llm else rerank.NoopReranker()
        )
        results: list[RetrievalResult] = []
        for item in labelled:
            started = time.monotonic()
            result = RetrievalResult(id=item.id)
            try:
                found = retrieval.retrieve(item.question, None, use_llm=use_llm)
                cost = found.usage.cost_usd if found.usage else None
                ranked = _segments_of([candidate.passage_id for candidate in found.candidates])
                result.retrieval_hit_rank = m.first_hit_rank(ranked, item.expected_segment_ids)
                if stage == "rerank":
                    outcome = reranker.rerank(item.question, found.candidates)
                    ranked = _segments_of([row.passage_id for row in outcome.passages])
                    for usage in outcome.usage:
                        if usage.cost_usd is not None:
                            cost = (cost or Decimal("0")) + usage.cost_usd
                    result.weak_evidence = outcome.weak_evidence
                result.ranked_segment_ids = ranked
                result.hit_rank = m.first_hit_rank(ranked, item.expected_segment_ids)
                if cost is not None:
                    result.cost_usd = str(cost)
            except Exception as error:  # noqa: BLE001 — one bad item must not sink the report
                result.error = f"{type(error).__name__}: {error}"
            result.latency_ms = int((time.monotonic() - started) * 1000)
            results.append(result)

        recall = m.mean(
            [1.0 if r.hit_rank is not None and r.hit_rank <= k else 0.0 for r in results]
        )
        mrr = m.mean([0.0 if r.hit_rank is None else 1.0 / r.hit_rank for r in results])
        latencies = [float(r.latency_ms) for r in results]
        summary: dict[str, Any] = {
            f"recall_at_{k}": round(recall, 4),
            "mrr": round(mrr, 4),
            "latency_ms": {
                "p50": m.percentile(latencies, 50),
                "p95": m.percentile(latencies, 95),
            },
            "cost_usd": str(sum(Decimal(r.cost_usd) for r in results)),
            "errors": sum(1 for r in results if r.error),
        }
        if stage == "rerank":
            summary["weak_evidence"] = sum(1 for r in results if r.weak_evidence)
        report = {
            "run": {
                "date": datetime.now(UTC).isoformat(timespec="seconds"),
                "git_sha": _git_sha(),
                "stage": stage,
                "k": k,
                "llm": use_llm,
                "embedding_model": settings.SMART_EMBEDDING_MODEL,
                "rerank_model": settings.SMART_RERANK_MODEL if stage == "rerank" else None,
                "n": len(results),
            },
            "summary": summary,
            "items": [
                {
                    "id": r.id,
                    "hit_rank": r.hit_rank,
                    "retrieval_hit_rank": r.retrieval_hit_rank,
                    "ranked_segment_ids": r.ranked_segment_ids[:k],
                    "weak_evidence": r.weak_evidence,
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
            f"{stage}: n={len(results)} recall@{k}={recall:.3f} mrr={mrr:.3f} "
            f"p95={summary['latency_ms']['p95']:.0f}ms errors={summary['errors']}"
        )

    # --- full pipeline ------------------------------------------------------------

    def _full(self, items: list[GoldenItem], options: dict[str, Any]) -> None:
        if options["limit"]:
            items = items[: options["limit"]]
        if not items:
            raise CommandError("the golden file has no items")
        use_llm = not options["no_llm"]
        if options["judge"] and not use_llm:
            raise CommandError("--judge needs the provider (drop --no-llm)")
        from search.smart.eval.judge import judge

        results: list[FullResult] = []
        for item in items:
            result = FullResult(id=item.id, expected_status=item.expected_status)
            started = time.monotonic()
            try:
                response = pipeline.run_smart_search(
                    item.question, run=pipeline.RunContext(debug=True, use_llm=use_llm)
                )
                debug = response.debug or {}
                result.status = response.status
                result.ranked_segment_ids = _segments_of(
                    [row.passage_id for row in response.passages]
                )
                result.hit_rank = (
                    m.first_hit_rank(result.ranked_segment_ids, item.expected_segment_ids)
                    if item.labelled
                    else None
                )
                result.citations = len(response.citations)
                result.citations_dropped = sum(
                    1 for note in debug.get("verify", []) if str(note).startswith("citation:")
                )
                result.cost_usd = str(debug.get("cost_usd", "0"))
                if options["judge"] and response.answer_md and response.passages:
                    windows = context.assemble(
                        [
                            RerankedPassage(passage_id=row.passage_id, score=0, rrf=0.0)
                            for row in response.passages
                        ]
                    )
                    verdict, usage = judge(item.question, windows, response.answer_md)
                    result.judged = True
                    result.sentences = len(verdict.sentences)
                    result.unsupported = verdict.unsupported
                    result.contradicted = verdict.contradicted
                    result.cost_usd = str(Decimal(result.cost_usd) + (usage.cost_usd or 0))
            except Exception as error:  # noqa: BLE001 — one bad item must not sink the report
                result.error = f"{type(error).__name__}: {error}"
            result.latency_ms = int((time.monotonic() - started) * 1000)
            results.append(result)

        summary = rep.summarize(results, k=rerank.TOP_N)
        verdicts = rep.gates(summary)
        report = {
            "run": {
                "date": datetime.now(UTC).isoformat(timespec="seconds"),
                "git_sha": _git_sha(),
                "stage": "full",
                "k": rerank.TOP_N,
                "llm": use_llm,
                "judge": bool(options["judge"]),
                "models": {
                    "planner": settings.SMART_PLANNER_MODEL,
                    "rerank": settings.SMART_RERANK_MODEL,
                    "generator": settings.SMART_GENERATOR_MODEL,
                    "embedding": settings.SMART_EMBEDDING_MODEL,
                    "judge": settings.SMART_JUDGE_MODEL if options["judge"] else None,
                },
                "n": len(results),
            },
            "summary": summary,
            "gates": verdicts,
            "items": [
                {
                    "id": r.id,
                    "expected_status": r.expected_status,
                    "status": r.status,
                    "hit_rank": r.hit_rank,
                    "ranked_segment_ids": r.ranked_segment_ids[: rerank.TOP_N],
                    "citations": r.citations,
                    "citations_dropped": r.citations_dropped,
                    "sentences": r.sentences,
                    "unsupported": r.unsupported,
                    "contradicted": r.contradicted,
                    "latency_ms": r.latency_ms,
                    "cost_usd": r.cost_usd,
                    "error": r.error,
                }
                for r in results
            ],
        }
        if options["out"]:
            options["out"].write_text(
                json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
            )
        passed = [name for name, ok in verdicts.items() if ok]
        failed = [name for name, ok in verdicts.items() if ok is False]
        unknown = [name for name, ok in verdicts.items() if ok is None]
        self.stdout.write(
            f"full: n={len(results)} errors={summary['errors']} "
            f"recall@{rerank.TOP_N}={summary[f'recall_at_{rerank.TOP_N}']} "
            f"abstention={summary['abstention_accuracy']} "
            f"citation_validity={summary['citation_validity']} "
            f"unsupported={summary['unsupported_ratio']} "
            f"p95={summary['latency_ms']['p95']:.0f}ms cost/query={summary['cost_per_query_usd']}"
        )
        self.stdout.write(
            f"gates: passed {passed or '-'} · failed {failed or '-'} · no data {unknown or '-'}"
        )
