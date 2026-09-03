"""The smart-search request, end to end.

plan → retrieve → rerank → context → generate → verify → respond, under one
:class:`Deadline`. Every request writes one :class:`SmartQuery` row (cache
hits included); only answers that were actually verified are cached. A stage
that fails leaves a warning behind and the request goes on; only when no
verified answer could be produced is the response ``degraded`` — and even then
it carries the passages, so the reader has something to listen to.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from django.conf import settings

from corpus.arabic import normalize_for_index, normalize_light
from search.models import SmartQuery

from . import PROMPT_VERSION, cache, context, generate, llm, planner, rerank, retrieval, verify
from .schemas import (
    ContextPassage,
    PassageOut,
    RerankedPassage,
    SmartResponse,
    StageTiming,
    Usage,
)

__all__ = [
    "BUDGET_COPY",
    "EXCERPT_WORDS",
    "MIN_GENERATE_S",
    "RunContext",
    "run_smart_search",
]

logger = logging.getLogger(__name__)

MIN_GENERATE_S = 8.0
"""Generation is not attempted with less request budget than this."""
EXCERPT_WORDS = 60
BUDGET_COPY = "تجاوزنا الحد اليومي للبحث الذكي؛ هذه أقرب المقاطع لسؤالك، ويمكنك الاستماع إليها."
CACHEABLE = frozenset({"answered", "partial", "not_found"})


@dataclass
class RunContext:
    """Who asked, and what to record about it."""

    session_key: str = ""
    ip_hash: str = ""
    user: Any = None
    debug: bool = False
    reranker: rerank.Reranker | None = None
    use_llm: bool = True
    """``False`` = no provider at all: naive plan, lexical retrieval, fused order, no answer."""
    on_event: Callable[[str, dict[str, Any]], None] | None = None
    """Progress sink for a streaming response: ``("stage", {"stage": …})`` as each
    stage begins and ``("passages", {"passages": […]})`` as soon as the
    reranked passages are known. Never called for a cache hit."""

    def emit(self, name: str, data: dict[str, Any]) -> None:
        if self.on_event is not None:
            self.on_event(name, data)


@dataclass
class _Trace:
    timings: list[StageTiming] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    usages: list[Usage] = field(default_factory=list)
    models: dict[str, str] = field(default_factory=dict)

    def stage(self, name: str, started: float, usage: Sequence[Usage] = (), note: str = "") -> None:
        latency = int((time.monotonic() - started) * 1000)
        self.timings.append(
            StageTiming(
                stage=name, latency_ms=latency, usage=usage[0] if usage else None, note=note
            )
        )
        self.usages.extend(usage)

    @property
    def cost(self) -> Decimal:
        return sum((u.cost_usd or Decimal("0") for u in self.usages), Decimal("0"))

    def latency(self) -> dict[str, int]:
        return {timing.stage: timing.latency_ms for timing in self.timings}


def _excerpt(text: str) -> str:
    words = text.split()
    return " ".join(words[:EXCERPT_WORDS]) + (" …" if len(words) > EXCERPT_WORDS else "")


def _passages_out(reranked: Sequence[RerankedPassage]) -> list[PassageOut]:
    from .passages import hydrate

    rows = {row.pk: row for row in hydrate([item.passage_id for item in reranked])}
    out: list[PassageOut] = []
    for item in reranked:
        row = rows.get(item.passage_id)
        if row is None:
            continue
        out.append(
            PassageOut(
                passage_id=row.pk,
                chunk_id=None,
                segment_id=row.segment_id,
                segment_title=row.segment.title,
                surah=row.surah,
                ayah_start=row.ayah_start,
                ayah_end=row.ayah_end,
                start_ms=int(row.start_ms),
                end_ms=int(row.end_ms),
                excerpt_display=_excerpt(row.text),
                score=float(item.score) if item.score else round(item.rrf, 6),
            )
        )
    return out


def _debug_payload(
    trace: _Trace, plan: Any, found: retrieval.Retrieval | None, verified_notes: list[str]
) -> dict[str, Any]:
    return {
        "prompt_version": PROMPT_VERSION,
        "plan": plan.model_dump() if plan is not None else None,
        "queries": found.queries if found else [],
        "lists": [
            {"name": lst.name, "weight": lst.weight, "ids": lst.ids[:10]} for lst in found.lists
        ]
        if found
        else [],
        "warnings": trace.warnings,
        "verify": verified_notes,
        "timings": [timing.model_dump(mode="json") for timing in trace.timings],
        "models": trace.models,
        "cost_usd": str(trace.cost),
    }


def _record(
    *,
    question: str,
    filters: retrieval.Filters,
    run: RunContext,
    response: SmartResponse,
    trace: _Trace,
    plan: Any,
    found: retrieval.Retrieval | None,
    reranked: Sequence[RerankedPassage],
    error: str = "",
    cache_hit: bool = False,
) -> None:
    def write() -> None:
        SmartQuery.objects.create(
            id=uuid.UUID(response.query_id),
            user=run.user if getattr(run.user, "pk", None) else None,
            session_key=run.session_key[:64],
            ip_hash=run.ip_hash[:64],
            question=question[:2000],
            question_normalized=normalize_for_index(question)[:2000],
            question_hash=cache.question_hash(question, filters.as_dict()),
            lang=plan.language if plan is not None else "",
            filters={k: v for k, v in filters.as_dict().items() if v is not None},
            plan=plan.model_dump() if plan is not None else None,
            candidate_ids=[c.passage_id for c in found.candidates] if found else [],
            reranked=[item.model_dump() for item in reranked] or None,
            answer=response.model_dump(exclude={"debug"}),
            status=response.status if not error else "error",
            models_used=trace.models,
            prompt_version=PROMPT_VERSION,
            usage={
                "prompt_tokens": sum(u.prompt_tokens for u in trace.usages),
                "completion_tokens": sum(u.completion_tokens for u in trace.usages),
                "calls": len(trace.usages),
            },
            cost_usd=trace.cost,
            latency_ms=trace.latency(),
            cache_hit=cache_hit,
            error=error[:2000],
        )

    try:
        write()
    except Exception:  # noqa: BLE001 — bookkeeping must never fail the answer
        logger.exception("smart: could not record the query")


def run_smart_search(
    question: str,
    *,
    filters: retrieval.Filters | None = None,
    run: RunContext | None = None,
) -> SmartResponse:
    filters = filters or retrieval.NO_FILTERS
    run = run or RunContext()
    question = question.strip()
    deadline = llm.Deadline(budget_s=settings.SMART_REQUEST_BUDGET_S)
    started_all = time.monotonic()
    trace = _Trace()
    query_id = str(uuid.uuid4())
    qhash = cache.question_hash(question, filters.as_dict())

    cached = cache.get_response(qhash)
    if cached is not None:
        response = SmartResponse.model_validate(
            {**cached, "query_id": query_id, "cache_hit": True}
        )
        response.debug = {"cache": "hit"} if run.debug else None
        trace.stage("total", started_all)
        _record(
            question=question, filters=filters, run=run, response=response, trace=trace,
            plan=None, found=None, reranked=[], cache_hit=True,
        )
        return response

    # 1. plan
    started = time.monotonic()
    if run.use_llm:
        planned = planner.plan(question, deadline=deadline)
        plan = planned.plan
        if planned.warning:
            trace.warnings.append(planned.warning)
        trace.stage(
            "plan", started, [planned.usage] if planned.usage else (), planned.warning or ""
        )
        trace.models["planner"] = settings.SMART_PLANNER_MODEL
    else:
        plan = planner.naive_plan(question)
        trace.stage("plan", started, note="naive")

    # 2. retrieve
    run.emit("stage", {"stage": "retrieve"})
    started = time.monotonic()
    found = retrieval.retrieve(
        question, plan, filters=filters, deadline=deadline, use_llm=run.use_llm
    )
    trace.warnings.extend(found.warnings)
    trace.stage("retrieve", started, [found.usage] if found.usage else ())
    if run.use_llm:
        trace.models["embedding"] = settings.SMART_EMBEDDING_MODEL

    if not found.candidates:
        response = SmartResponse(
            query_id=query_id, status="not_found", answer_md=verify.NOT_FOUND_COPY
        )
        trace.stage("total", started_all)
        response.debug = _debug_payload(trace, plan, found, []) if run.debug else None
        cache.set_response(qhash, response.model_dump(exclude={"debug", "query_id", "cache_hit"}))
        _record(
            question=question, filters=filters, run=run, response=response, trace=trace,
            plan=plan, found=found, reranked=[],
        )
        return response

    # 3. rerank
    run.emit("stage", {"stage": "rerank"})
    started = time.monotonic()
    reranker = run.reranker or (
        rerank.LLMListwiseReranker() if run.use_llm else rerank.NoopReranker()
    )
    outcome = reranker.rerank(question, found.candidates, deadline=deadline)
    if outcome.warning:
        trace.warnings.append(outcome.warning)
    trace.stage(
        "rerank", started, outcome.usage,
        "skipped" if outcome.skipped else ("weak_evidence" if outcome.weak_evidence else ""),
    )
    if outcome.scored:
        trace.models["rerank"] = settings.SMART_RERANK_MODEL
    passages_out = _passages_out(outcome.passages)
    run.emit("passages", {"passages": [row.model_dump() for row in passages_out]})

    # 4. context
    started = time.monotonic()
    windows: list[ContextPassage] = context.assemble(outcome.passages)
    trace.stage("context", started)

    # 5 + 6. generate and verify
    run.emit("stage", {"stage": "generate"})
    status: str = "degraded"
    answer_md: str | None = None
    citations: list[Any] = []
    ayah_refs: list[Any] = []
    followups: list[str] = []
    verify_notes: list[str] = []
    started = time.monotonic()
    if not run.use_llm:
        trace.stage("generate", started, note="skipped: no llm")
    elif not windows:
        status, answer_md = "not_found", verify.NOT_FOUND_COPY
        trace.stage("generate", started, note="skipped: no context")
    elif deadline.remaining() < MIN_GENERATE_S:
        trace.warnings.append("generate: request budget exhausted")
        trace.stage("generate", started, note="skipped: deadline")
    else:
        try:
            answer, usages = generate.generate(question, windows, plan, deadline=deadline)
            trace.models["generator"] = settings.SMART_GENERATOR_MODEL
            trace.stage("generate", started, usages)
            started = time.monotonic()
            verified = verify.verify(answer, windows)
            trace.stage("verify", started, note=f"{len(verified.notes)} notes")
            status = verified.status
            answer_md = verified.answer_md
            citations = verified.citations
            ayah_refs = verified.ayah_refs
            followups = verified.followups
            verify_notes = verified.notes
        except llm.BudgetExhausted as error:
            trace.warnings.append(f"generate: {error}")
            trace.stage("generate", started, note="budget")
            answer_md = BUDGET_COPY
        except (llm.LLMError, verify.VerifyError) as error:
            trace.warnings.append(f"generate: {error}")
            trace.stage("generate", started, note="failed")
            logger.warning("smart: degraded: %s", error)

    response = SmartResponse(
        query_id=query_id,
        status=status,  # type: ignore[arg-type]
        answer_md=answer_md,
        citations=citations,
        passages=passages_out,
        ayah_refs=ayah_refs,
        followups=followups,
    )
    trace.stage("total", started_all)
    if run.debug:
        response.debug = _debug_payload(trace, plan, found, verify_notes)
    if status in CACHEABLE:
        cache.set_response(qhash, response.model_dump(exclude={"debug", "query_id", "cache_hit"}))
    _record(
        question=question, filters=filters, run=run, response=response, trace=trace,
        plan=plan, found=found, reranked=outcome.passages,
    )
    return response


def excerpt_display(text: str) -> str:
    """Display form of a passage excerpt for callers outside the pipeline."""
    return _excerpt(normalize_light(text))
