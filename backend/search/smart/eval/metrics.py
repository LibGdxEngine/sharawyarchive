"""Pure ranking metrics for the evaluation harness."""

from __future__ import annotations

from collections.abc import Sequence

__all__ = ["first_hit_rank", "mean", "percentile", "recall_at_k", "reciprocal_rank"]


def first_hit_rank(ranked: Sequence[int], expected: Sequence[int]) -> int | None:
    """1-based rank of the first expected id in ``ranked``, or ``None``."""
    wanted = set(expected)
    for position, value in enumerate(ranked, start=1):
        if value in wanted:
            return position
    return None


def recall_at_k(ranked: Sequence[int], expected: Sequence[int], k: int) -> float:
    """1.0 when any expected id sits within the first ``k``, else 0.0."""
    rank = first_hit_rank(ranked[:k], expected)
    return 1.0 if rank is not None else 0.0


def reciprocal_rank(ranked: Sequence[int], expected: Sequence[int]) -> float:
    rank = first_hit_rank(ranked, expected)
    return 0.0 if rank is None else 1.0 / rank


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def percentile(values: Sequence[float], p: float) -> float:
    """Nearest-rank percentile (``p`` in 0..100) of ``values``; 0 when empty."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(p / 100.0 * len(ordered) + 0.5) - 1))
    return float(ordered[index])
