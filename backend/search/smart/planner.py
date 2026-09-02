"""Stage 1 — turn the reader's question into a :class:`QueryPlan`.

The planner model rewrites the question in the register of the transcripts
(what the Sheikh would have *said*, not what the reader typed), extracts
keywords and ayah references, and guesses whether the corpus can answer at
all. It is advisory: every failure — provider down, budget spent, deadline
gone, malformed answer — falls back to :func:`naive_plan`, which searches the
question as typed. Retrieval never waits on a plan that is not coming.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings
from django.db.models import Q

from corpus.arabic import normalize_for_index
from quran.models import Ayah

from . import llm, prompts
from .schemas import AyahRef, QueryPlan, Usage

__all__ = ["MAX_KEYWORDS", "MAX_REWRITES", "PlanResult", "naive_plan", "plan", "tidy_plan"]

logger = logging.getLogger(__name__)

MAX_REWRITES = 5
MAX_KEYWORDS = 8
MAX_TOPIC_CHARS = 120
SURAH_COUNT = 114


@dataclass
class PlanResult:
    plan: QueryPlan
    usage: Usage | None = None
    warning: str | None = None
    """Why the plan is the naive one, when it is."""

    @property
    def naive(self) -> bool:
        return self.warning is not None


def naive_plan(question: str) -> QueryPlan:
    """The plan retrieval uses when the planner cannot be asked: the question itself."""
    return QueryPlan(
        intent="opinion",
        language="ar",
        topic_ar=question.strip()[:MAX_TOPIC_CHARS],
        rewrites=[],
        keywords=[],
        ayah_refs=[],
        surah_hint=None,
        answerable_from_corpus="maybe",
    )


def _dedupe(texts: list[str], *, exclude: str = "", limit: int) -> list[str]:
    seen = {normalize_for_index(exclude)} if exclude else set()
    kept: list[str] = []
    for text in texts:
        key = normalize_for_index(text)
        if key and key not in seen:
            seen.add(key)
            kept.append(text.strip())
        if len(kept) >= limit:
            break
    return kept


def _existing_refs(refs: list[AyahRef]) -> list[AyahRef]:
    """``refs`` that name a real ayah (in order, deduplicated); the model's
    numbers are checked against the canonical mushaf, never trusted."""
    wanted = {
        (ref.surah, ref.ayah)
        for ref in refs
        if 1 <= ref.surah <= SURAH_COUNT and ref.ayah >= 1
    }
    if not wanted:
        return []
    condition = Q()
    for surah, ayah in wanted:
        condition |= Q(surah_id=surah, number=ayah)
    existing = set(Ayah.objects.filter(condition).values_list("surah_id", "number"))
    kept: list[AyahRef] = []
    seen: set[tuple[int, int]] = set()
    for ref in refs:
        key = (ref.surah, ref.ayah)
        if key in existing and key not in seen:
            seen.add(key)
            kept.append(ref)
    return kept


def tidy_plan(question: str, raw: QueryPlan) -> QueryPlan:
    """Bound and clean a model-made plan: deduplicated rewrites that are not
    the question again, capped keywords, ayah refs that exist, a sane surah."""
    surah_hint = raw.surah_hint if raw.surah_hint and 1 <= raw.surah_hint <= SURAH_COUNT else None
    return raw.model_copy(
        update={
            "topic_ar": raw.topic_ar.strip()[:MAX_TOPIC_CHARS],
            "rewrites": _dedupe(raw.rewrites, exclude=question, limit=MAX_REWRITES),
            "keywords": _dedupe(raw.keywords, limit=MAX_KEYWORDS),
            "ayah_refs": _existing_refs(raw.ayah_refs),
            "surah_hint": surah_hint,
        }
    )


def plan(question: str, *, deadline: llm.Deadline | None = None) -> PlanResult:
    """Ask the planner model; on any failure return the naive plan with a warning."""
    try:
        raw, usage = llm.chat_json(
            role="planner",
            model=settings.SMART_PLANNER_MODEL,
            system=prompts.load("planner"),
            user=question,
            schema=QueryPlan,
            timeout_s=settings.SMART_STAGE_TIMEOUTS_S["planner"],
            deadline=deadline,
            reasoning_effort="minimal",
            max_tokens=800,
        )
    except llm.LLMError as error:
        logger.warning("smart.plan: falling back to the naive plan: %s", error)
        return PlanResult(plan=naive_plan(question), warning=f"planner: {error}")
    return PlanResult(plan=tidy_plan(question, raw), usage=usage)
