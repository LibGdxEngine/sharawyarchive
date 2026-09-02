"""Smart search («بحث ذكي»): cited, grounded answers over the machine transcripts.

The pipeline is a chain of small, typed stages (docs/smart-search/):
plan → retrieve → rerank → assemble context → generate → verify → respond.
Every provider call goes through :mod:`search.smart.llm`; every stage speaks
the pydantic contracts in :mod:`search.smart.schemas`. Nothing here is imported
by the exact-search code path, and nothing imports ``pipeline/``.
"""

from __future__ import annotations

from django.conf import settings

from .prompts import PROMPT_VERSION

__all__ = ["PROMPT_VERSION", "embedding_model_tag"]


def embedding_model_tag(model: str | None = None, dimensions: int | None = None) -> str:
    """``"<model>@<dims>"`` — the identity a vector was produced under.

    Stored on every embedded row and baked into every cache key, because a
    query vector is only comparable with passage vectors from the very same
    model at the very same dimension.
    """
    model = model or settings.SMART_EMBEDDING_MODEL
    dimensions = dimensions or settings.SMART_EMBEDDING_DIMENSIONS
    return f"{model}@{dimensions}"
