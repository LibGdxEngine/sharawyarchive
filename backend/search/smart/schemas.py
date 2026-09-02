"""Typed contracts between the smart-search stages.

Two families live here. The ``Strict*`` models are what the language models
must emit: they are turned into strict JSON schemas (every object closed, every
property required) so that a provider honouring ``response_format`` cannot
return a shape the verifier does not expect. The rest are plain internal
records and the public response shape (API_CONTRACT.md).

All timestamps are integer milliseconds (CLAUDE.md rule 5).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "AyahOut",
    "AyahRef",
    "Candidate",
    "Citation",
    "ContextPassage",
    "DraftCitation",
    "GeneratedAnswer",
    "PassageOut",
    "QueryPlan",
    "RerankResult",
    "RerankScore",
    "RerankedPassage",
    "SmartResponse",
    "StageTiming",
    "Usage",
    "strict_json_schema",
]

Intent = Literal["opinion", "tafseer", "story", "phrase_lookup", "out_of_scope"]
Answerability = Literal["likely", "maybe", "unlikely"]
GeneratedStatus = Literal["answered", "partial", "not_found"]
ResponseStatus = Literal["answered", "partial", "not_found", "degraded"]


class StrictModel(BaseModel):
    """Base for everything a model is asked to emit: no extras, no defaults."""

    model_config = ConfigDict(extra="forbid")


# --- Model outputs ------------------------------------------------------------


class AyahRef(StrictModel):
    surah: int
    ayah: int


class QueryPlan(StrictModel):
    """Stage 1: the question rewritten in the register of the transcripts."""

    intent: Intent
    language: Literal["ar", "en", "other"]
    topic_ar: str
    rewrites: list[str]
    keywords: list[str]
    ayah_refs: list[AyahRef]
    surah_hint: int | None
    answerable_from_corpus: Answerability


class RerankScore(StrictModel):
    id: int
    score: int
    """3 = directly answers, 2 = addresses the topic, 1 = tangential, 0 = unrelated."""


class RerankResult(StrictModel):
    scores: list[RerankScore]


class DraftCitation(StrictModel):
    passage_id: str
    """The ``pN`` id of a rendered passage."""
    quote: str
    """A verbatim span of that passage — the verifier rejects anything else."""


class GeneratedAnswer(StrictModel):
    """Stage 5: the raw generator output, before verification."""

    status: GeneratedStatus
    answer_md: str
    citations: list[DraftCitation]
    ayah_refs: list[AyahRef]
    followups: list[str]


# --- Internal records ---------------------------------------------------------


class Usage(BaseModel):
    """What one provider call cost."""

    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: Decimal | None = None
    latency_ms: int = 0


class StageTiming(BaseModel):
    stage: str
    latency_ms: int
    usage: Usage | None = None
    failed: bool = False
    note: str = ""


class Candidate(BaseModel):
    """One retrieved passage after reciprocal-rank fusion."""

    passage_id: int
    header: str
    text_normalized: str
    rrf: float
    channel_ranks: dict[str, int] = Field(default_factory=dict)


class RerankedPassage(BaseModel):
    passage_id: int
    score: int
    rrf: float


class ContextPassage(BaseModel):
    """A merged window of passages rendered for the generator as ``<passage id="pN">``."""

    id: str
    passage_ids: list[int]
    transcript_id: int
    segment_id: int
    segment_title: str
    surah: int | None
    ayah_start: int | None
    ayah_end: int | None
    start_ms: int
    end_ms: int
    chunk_idx_start: int
    chunk_idx_end: int
    text: str


# --- Public response (API_CONTRACT.md, POST /api/search/smart/) ---------------


class Citation(BaseModel):
    n: int
    passage_id: int
    chunk_id: int | None
    segment_id: int
    segment_title: str
    surah: int | None
    ayah_start: int | None
    ayah_end: int | None
    start_ms: int
    end_ms: int
    quote_display: str
    listen_url: str


class PassageOut(BaseModel):
    passage_id: int
    chunk_id: int | None
    segment_id: int
    segment_title: str
    surah: int | None
    ayah_start: int | None
    ayah_end: int | None
    start_ms: int
    end_ms: int
    excerpt_display: str
    score: float


class AyahOut(BaseModel):
    """A canonical ayah, hydrated from the ``quran`` app — never from a model."""

    surah: int
    ayah: int
    surah_name_ar: str
    text_uthmani: str


class SmartResponse(BaseModel):
    query_id: str
    mode: Literal["smart"] = "smart"
    status: ResponseStatus
    answer_md: str | None
    citations: list[Citation] = Field(default_factory=list)
    passages: list[PassageOut] = Field(default_factory=list)
    ayah_refs: list[AyahOut] = Field(default_factory=list)
    followups: list[str] = Field(default_factory=list)
    cache_hit: bool = False
    debug: dict[str, Any] | None = None


# --- Strict JSON schema -------------------------------------------------------


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The JSON schema of ``model`` in the form strict structured output needs.

    Every object node is closed (``additionalProperties: false``) and lists all
    of its properties as required, recursively through ``$defs``. Pydantic
    already emits that for a ``StrictModel`` without defaults; this makes the
    guarantee explicit and independent of field declarations.
    """
    schema = model.model_json_schema()
    _strictify(schema)
    return schema


def _strictify(node: Any) -> None:
    if isinstance(node, dict):
        if "properties" in node or node.get("type") == "object":
            node["additionalProperties"] = False
            node["required"] = list(node.get("properties", {}).keys())
        for value in node.values():
            _strictify(value)
    elif isinstance(node, list):
        for item in node:
            _strictify(item)
