"""Stage 3 — listwise reranking of the fused candidates.

The retrieval channels are good at recall and poor at precision: forty
candidates come back for every question and most are tangential. A small
model reads them in batches, scores each 0–3 against the question, and the
generator only ever sees the few that score 2 or better. Like the planner it
is advisory — a failure or a tight deadline leaves the fused order in place.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Protocol

from django.conf import settings

from . import llm, prompts
from .schemas import Candidate, RerankedPassage, RerankResult, Usage

__all__ = [
    "BATCH_SIZE",
    "KEEP_SCORE",
    "MIN_DEADLINE_S",
    "TOP_N",
    "WEAK_TOP_N",
    "LLMListwiseReranker",
    "NoopReranker",
    "RerankOutcome",
    "Reranker",
    "by_fusion",
    "render_candidates",
]

logger = logging.getLogger(__name__)

BATCH_SIZE = 20
KEEP_SCORE = 2
TOP_N = 8
WEAK_TOP_N = 3
"""How many fused candidates go forward when fewer than two scored well."""
TEXT_WORDS = 220
"""Words of each candidate the reranker reads."""
MIN_DEADLINE_S = 20.0
"""Below this much request budget the stage is skipped: generation needs the time more."""
MAX_WORKERS = 2


@dataclass
class RerankOutcome:
    passages: list[RerankedPassage]
    usage: list[Usage] = field(default_factory=list)
    weak_evidence: bool = False
    """No candidate — or only one — scored :data:`KEEP_SCORE`; the top of the
    fused order was passed on so the generator can still say what is near."""
    warning: str | None = None
    """Set when the fused order was used because the model could not be."""
    skipped: bool = False

    @property
    def scored(self) -> bool:
        return self.warning is None and not self.skipped


class Reranker(Protocol):
    def rerank(
        self,
        question: str,
        candidates: Sequence[Candidate],
        *,
        deadline: llm.Deadline | None = None,
    ) -> RerankOutcome: ...


def by_fusion(candidates: Sequence[Candidate], limit: int = TOP_N) -> list[RerankedPassage]:
    """The fused order itself, unscored."""
    return [
        RerankedPassage(passage_id=candidate.passage_id, score=0, rrf=candidate.rrf)
        for candidate in candidates[:limit]
    ]


def _excerpt(text: str, words: int = TEXT_WORDS) -> str:
    tokens = text.split()
    return " ".join(tokens[:words]) + (" …" if len(tokens) > words else "")


def render_candidates(candidates: Sequence[Candidate]) -> str:
    """``<c id="17">header\\ntext</c>`` blocks, one per candidate."""
    return "\n\n".join(
        f'<c id="{candidate.passage_id}">{candidate.header}\n'
        f"{_excerpt(candidate.text_normalized)}</c>"
        for candidate in candidates
    )


class NoopReranker:
    """The fused order, for tests and for ``--no-llm`` runs."""

    def rerank(
        self,
        question: str,
        candidates: Sequence[Candidate],
        *,
        deadline: llm.Deadline | None = None,
    ) -> RerankOutcome:
        return RerankOutcome(passages=by_fusion(candidates), skipped=True)


class LLMListwiseReranker:
    """Score candidates in parallel batches of :data:`BATCH_SIZE` with the rerank model."""

    def __init__(self, *, batch_size: int = BATCH_SIZE, top_n: int = TOP_N) -> None:
        self.batch_size = max(1, batch_size)
        self.top_n = top_n

    def _score_batch(
        self, question: str, batch: Sequence[Candidate], deadline: llm.Deadline | None
    ) -> tuple[dict[int, int], Usage]:
        result, usage = llm.chat_json(
            role="rerank",
            model=settings.SMART_RERANK_MODEL,
            system=prompts.load("reranker"),
            user=f"Question: {question}\n\nCandidates:\n\n{render_candidates(batch)}",
            schema=RerankResult,
            timeout_s=settings.SMART_STAGE_TIMEOUTS_S["rerank"],
            deadline=deadline,
            reasoning_effort="minimal",
            max_tokens=600,
        )
        wanted = {candidate.passage_id for candidate in batch}
        scores: dict[int, int] = {}
        for item in result.scores:
            if item.id in wanted and item.id not in scores:
                scores[item.id] = min(max(item.score, 0), 3)
        return scores, usage

    def rerank(
        self,
        question: str,
        candidates: Sequence[Candidate],
        *,
        deadline: llm.Deadline | None = None,
    ) -> RerankOutcome:
        if not candidates:
            return RerankOutcome(passages=[])
        if deadline is not None and deadline.remaining() < MIN_DEADLINE_S:
            logger.info("smart.rerank: skipped, %.1fs left", deadline.remaining())
            return RerankOutcome(passages=by_fusion(candidates, self.top_n), skipped=True)

        batches = [
            candidates[start : start + self.batch_size]
            for start in range(0, len(candidates), self.batch_size)
        ]
        scores: dict[int, int] = {}
        usage: list[Usage] = []
        try:
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
                for batch_scores, batch_usage in pool.map(
                    lambda batch: self._score_batch(question, batch, deadline), batches
                ):
                    scores.update(batch_scores)
                    usage.append(batch_usage)
        except llm.LLMError as error:
            logger.warning("smart.rerank: falling back to the fused order: %s", error)
            return RerankOutcome(
                passages=by_fusion(candidates, self.top_n),
                usage=usage,
                warning=f"rerank: {error}",
            )

        well_scored = [
            candidate
            for candidate in candidates
            if scores.get(candidate.passage_id, 0) >= KEEP_SCORE
        ]
        kept = sorted(
            well_scored, key=lambda candidate: (-scores[candidate.passage_id], -candidate.rrf)
        )[: self.top_n]
        weak = len(kept) < 2
        if weak:
            chosen = {candidate.passage_id for candidate in kept}
            for candidate in candidates:
                if len(kept) >= WEAK_TOP_N:
                    break
                if candidate.passage_id not in chosen:
                    kept.append(candidate)
                    chosen.add(candidate.passage_id)
        return RerankOutcome(
            passages=[
                RerankedPassage(
                    passage_id=candidate.passage_id,
                    score=scores.get(candidate.passage_id, 0),
                    rrf=candidate.rrf,
                )
                for candidate in kept
            ],
            usage=usage,
            weak_evidence=weak,
        )
