"""Summaries and ship gates for ``smart_eval --stage full``. Pure functions."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from . import FullResult
from . import metrics as m

__all__ = ["GATES", "gates", "summarize"]

GATES: dict[str, tuple[str, float]] = {
    "recall_at_8": (">=", 0.80),
    "abstention_accuracy": (">=", 0.90),
    "citation_validity": (">=", 0.95),
    "unsupported_ratio": ("<=", 0.05),
    "latency_p95_ms": ("<=", 15_000),
}
"""What must hold before ``SMART_ENABLED`` goes on (docs/smart-search/phase-6.md)."""


def summarize(results: Sequence[FullResult], *, k: int = 8) -> dict[str, Any]:
    ok = [r for r in results if not r.error]
    labelled = [r for r in ok if r.expected_status != "not_found"]
    recall = m.mean([1.0 if r.hit_rank is not None and r.hit_rank <= k else 0.0 for r in labelled])
    pairs = [(r.expected_status, r.status) for r in ok]
    kept = sum(r.citations for r in ok)
    dropped = sum(r.citations_dropped for r in ok)
    judged = [r for r in ok if r.judged]
    sentences = sum(r.sentences for r in judged)
    latencies = [float(r.latency_ms) for r in ok]
    return {
        "n": len(results),
        "errors": len(results) - len(ok),
        "labelled": len(labelled),
        f"recall_at_{k}": round(recall, 4) if labelled else None,
        "mrr": round(m.mean([0.0 if r.hit_rank is None else 1.0 / r.hit_rank for r in labelled]), 4)
        if labelled
        else None,
        "abstention_accuracy": m.abstention_accuracy(pairs),
        "confusion": m.confusion(pairs),
        "citation_validity": round(kept / (kept + dropped), 4) if kept + dropped else None,
        "citations_per_answer": round(kept / len(ok), 2) if ok else None,
        "judged": len(judged),
        "unsupported_ratio": round(sum(r.unsupported for r in judged) / sentences, 4)
        if sentences
        else None,
        "contradicted": sum(r.contradicted for r in judged),
        "latency_ms": {
            "p50": m.percentile(latencies, 50),
            "p95": m.percentile(latencies, 95),
        },
        "cost_usd": str(sum((Decimal(r.cost_usd) for r in ok), Decimal("0"))),
        "cost_per_query_usd": str(
            (sum((Decimal(r.cost_usd) for r in ok), Decimal("0")) / len(ok)).quantize(
                Decimal("0.000001")
            )
        )
        if ok
        else None,
    }


def gates(summary: dict[str, Any]) -> dict[str, bool | None]:
    """Each gate's verdict; ``None`` when the summary has no number for it."""
    verdicts: dict[str, bool | None] = {}
    for name, (op, threshold) in GATES.items():
        value = summary["latency_ms"]["p95"] if name == "latency_p95_ms" else summary.get(name)
        if value is None:
            verdicts[name] = None
        elif op == ">=":
            verdicts[name] = float(value) >= threshold
        else:
            verdicts[name] = float(value) <= threshold
    return verdicts
