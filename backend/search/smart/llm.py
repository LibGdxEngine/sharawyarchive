"""OpenRouter client for the smart-search stages.

One thin layer over the ``openai`` SDK pointed at OpenRouter's OpenAI-compatible
API. It owns everything the stages must not repeat: strict JSON-schema output,
provider routing that honours the schema, per-call timeouts bounded by the
request's :class:`Deadline`, retries (tenacity, never the SDK's own), usage and
cost accounting, and the daily spend cap. Embeddings get the same treatment,
plus Matryoshka truncation so that query and passage vectors always share one
model tag (:func:`search.smart.embedding_model_tag`).

Nothing here knows about prompts, passages or Django models.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from functools import lru_cache
from typing import Any

import httpx
import numpy as np
import openai
from django.conf import settings
from pydantic import BaseModel, ValidationError
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_random_exponential

from . import budget
from .schemas import Usage, strict_json_schema

__all__ = [
    "ATTEMPTS",
    "BudgetExhausted",
    "Deadline",
    "LLMError",
    "LLMSchemaError",
    "LLMTimeout",
    "chat_json",
    "client",
    "embed",
    "fit_vector",
    "format_query",
]

logger = logging.getLogger(__name__)

APP_TITLE = "Sha'rawy Archive"
CONNECT_TIMEOUT_S = 3.0
MIN_CALL_S = 2.0
"""No call is attempted with less than this much of the request budget left."""
ATTEMPTS = 3
"""One call plus two retries, on 429 / 5xx / connection errors / timeouts only."""
QUERY_INSTRUCTION = (
    "Instruct: Given a question about Sheikh Al-Sha'rawy's Quran commentary, "
    "retrieve transcript passages that answer it\nQuery: "
)
"""Qwen3 embeddings are instruction-aware: queries carry this prefix, passages do not."""

class LLMError(RuntimeError):
    """The provider could not produce a usable answer for this call."""


class LLMTimeout(LLMError):
    """The call, or the request budget it lives in, ran out of time."""


class LLMSchemaError(LLMError):
    """The provider answered, but not in the requested shape."""


class BudgetExhausted(LLMError):
    """Today's spend cap is reached; no call was made."""


@dataclass
class Deadline:
    """The wall-clock budget of one smart-search request (seconds)."""

    budget_s: float
    started: float = field(default_factory=time.monotonic)

    def remaining(self) -> float:
        return max(0.0, self.budget_s - (time.monotonic() - self.started))

    def expired(self) -> bool:
        return self.remaining() <= 0.0


@lru_cache(maxsize=4)
def _client_for(base_url: str, api_key: str, referer: str) -> openai.OpenAI:
    return openai.OpenAI(
        base_url=base_url,
        api_key=api_key or "missing-key",
        max_retries=0,  # tenacity owns retries; the SDK's own would multiply attempts
        default_headers={"HTTP-Referer": referer, "X-Title": APP_TITLE},
    )


def client() -> openai.OpenAI:
    """The shared SDK client for the configured OpenRouter endpoint."""
    return _client_for(
        settings.OPENROUTER_BASE_URL, settings.OPENROUTER_API_KEY, settings.SITE_BASE_URL
    )


def _retryable(error: BaseException) -> bool:
    transient = openai.APITimeoutError | openai.APIConnectionError | openai.RateLimitError
    if isinstance(error, transient):
        return True
    return isinstance(error, openai.APIStatusError) and error.status_code >= 500


def _retrying() -> Retrying:
    return Retrying(
        stop=stop_after_attempt(ATTEMPTS),
        wait=wait_random_exponential(multiplier=0.5, max=4),
        retry=retry_if_exception(_retryable),
        reraise=True,
    )


def _call_timeout(timeout_s: float, deadline: Deadline | None) -> float:
    if deadline is None:
        return timeout_s
    remaining = deadline.remaining()
    if remaining < MIN_CALL_S:
        raise LLMTimeout(f"request budget exhausted ({remaining:.1f}s left)")
    return min(timeout_s, remaining)


def _cost(usage: Any, model: str, prompt_tokens: int, completion_tokens: int) -> Decimal | None:
    """OpenRouter's own ``usage.cost`` when present, else the fallback price table."""
    extra = getattr(usage, "model_extra", None) or {}
    cost = extra.get("cost")
    if cost is not None:
        return Decimal(str(cost))
    prices = settings.SMART_PRICES_USD_PER_MTOKEN.get(model)
    if prices is None:
        return None
    prompt_price, completion_price = prices
    total = Decimal(prompt_tokens) * Decimal(str(prompt_price)) + Decimal(
        completion_tokens
    ) * Decimal(str(completion_price))
    return total / Decimal(1_000_000)


def _strip_fences(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def chat_json[T: BaseModel](
    *,
    role: str,
    model: str,
    system: str,
    user: str,
    schema: type[T],
    timeout_s: float,
    deadline: Deadline | None = None,
    reasoning_effort: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 1200,
    check_budget: bool = True,
) -> tuple[T, Usage]:
    """One chat completion that must come back as a ``schema`` instance.

    ``role`` only labels errors and logs (``planner``, ``reranker``, …).
    Raises :class:`BudgetExhausted` before calling when today's cap is
    reached (unless ``check_budget`` is off — offline evaluation spends from
    its own pocket), :class:`LLMTimeout` when the call or the deadline runs
    out, :class:`LLMSchemaError` when the answer does not validate, and
    :class:`LLMError` for anything else the provider does.
    """
    if check_budget and budget.over_budget():
        raise BudgetExhausted(f"{role}: daily smart-search budget reached")
    timeout = _call_timeout(timeout_s, deadline)
    extra_body: dict[str, Any] = {
        "provider": {"require_parameters": True},
        "usage": {"include": True},
    }
    if reasoning_effort:
        extra_body["reasoning"] = {"effort": reasoning_effort}
    request: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": schema.__name__,
                "strict": True,
                "schema": strict_json_schema(schema),
            },
        },
        "temperature": temperature,
        "max_tokens": max_tokens,
        "extra_body": extra_body,
    }
    started = time.monotonic()
    completion: Any = None
    try:
        for attempt in _retrying():
            with attempt:
                if deadline is not None and deadline.remaining() < MIN_CALL_S:
                    raise LLMTimeout(f"{role}: request budget exhausted before retry")
                completion = (
                    client()
                    .with_options(timeout=httpx.Timeout(timeout, connect=CONNECT_TIMEOUT_S))
                    .chat.completions.create(**request)
                )
    except openai.APITimeoutError as error:
        raise LLMTimeout(f"{role}: {model} timed out after {timeout:.0f}s") from error
    except openai.APIError as error:
        raise LLMError(f"{role}: {model}: {error}") from error
    latency_ms = int((time.monotonic() - started) * 1000)

    content = completion.choices[0].message.content if completion.choices else None
    if not content:
        raise LLMSchemaError(f"{role}: {model} returned no content")
    try:
        parsed = schema.model_validate_json(_strip_fences(content))
    except ValidationError as error:
        raise LLMSchemaError(
            f"{role}: {model} answer does not match {schema.__name__}: {error}"
        ) from error

    usage_obj = completion.usage
    prompt_tokens = int(getattr(usage_obj, "prompt_tokens", 0) or 0)
    completion_tokens = int(getattr(usage_obj, "completion_tokens", 0) or 0)
    usage = Usage(
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=_cost(usage_obj, model, prompt_tokens, completion_tokens),
        latency_ms=latency_ms,
    )
    budget.add_spend(usage.cost_usd)
    logger.info(
        "smart.%s model=%s tokens=%d/%d cost=%s latency_ms=%d",
        role, model, prompt_tokens, completion_tokens, usage.cost_usd, latency_ms,
    )
    return parsed, usage


def format_query(text: str) -> str:
    """A search query in the form the embedding model expects for queries."""
    return QUERY_INSTRUCTION + text


def fit_vector(values: Sequence[float], dimensions: int) -> list[float]:
    """The first ``dimensions`` components of ``values``, L2-normalised.

    Matryoshka-trained models (Qwen3 embeddings) are built so that a prefix of
    the full vector is itself a valid embedding once renormalised; this is what
    the provider's ``dimensions`` parameter does server-side, done here so the
    result does not depend on whether the route forwards that parameter.
    """
    vector = np.asarray(values, dtype=np.float32)
    if vector.ndim != 1 or vector.shape[0] < dimensions:
        got = vector.shape[0] if vector.ndim == 1 else "?"
        raise LLMSchemaError(f"embedding has {got} dimensions, need at least {dimensions}")
    vector = vector[:dimensions]
    norm = float(np.linalg.norm(vector))
    if norm > 0.0:
        vector = vector / norm
    return [float(component) for component in vector]


def _embed_call(request: dict[str, Any], timeout: float) -> Any:
    response: Any = None
    for attempt in _retrying():
        with attempt:
            response = (
                client()
                .with_options(timeout=httpx.Timeout(timeout, connect=CONNECT_TIMEOUT_S))
                .embeddings.create(**request)
            )
    return response


def embed(
    texts: Sequence[str],
    *,
    model: str | None = None,
    dimensions: int | None = None,
    timeout_s: float | None = None,
    deadline: Deadline | None = None,
    check_budget: bool = True,
) -> tuple[list[list[float]], Usage]:
    """Embed ``texts`` (in order) with the configured model at ``dimensions``.

    Asks the provider for ``dimensions`` directly; if the route rejects the
    parameter, takes the full vectors and truncates them with
    :func:`fit_vector`. Either way every returned vector has exactly
    ``dimensions`` components and unit length.
    """
    model = model or settings.SMART_EMBEDDING_MODEL
    dimensions = dimensions or settings.SMART_EMBEDDING_DIMENSIONS
    if not texts:
        return [], Usage(model=model)
    if check_budget and budget.over_budget():
        raise BudgetExhausted("embed: daily smart-search budget reached")
    timeout = _call_timeout(timeout_s or settings.SMART_STAGE_TIMEOUTS_S["embed"], deadline)
    request: dict[str, Any] = {
        "model": model,
        "input": list(texts),
        "encoding_format": "float",
        "extra_body": {"usage": {"include": True}},
    }
    started = time.monotonic()
    try:
        try:
            response = _embed_call({**request, "dimensions": dimensions}, timeout)
        except openai.BadRequestError:
            logger.info(
                "embed: %s rejected dimensions=%d; truncating client-side", model, dimensions
            )
            response = _embed_call(request, timeout)
    except openai.APITimeoutError as error:
        raise LLMTimeout(f"embed: {model} timed out after {timeout:.0f}s") from error
    except openai.APIError as error:
        raise LLMError(f"embed: {model}: {error}") from error
    latency_ms = int((time.monotonic() - started) * 1000)

    items = sorted(response.data, key=lambda item: item.index)
    if len(items) != len(texts):
        raise LLMSchemaError(f"embed: {model} returned {len(items)} vectors for {len(texts)} texts")
    vectors = [fit_vector(item.embedding, dimensions) for item in items]

    usage_obj = response.usage
    prompt_tokens = int(getattr(usage_obj, "prompt_tokens", 0) or 0)
    usage = Usage(
        model=model,
        prompt_tokens=prompt_tokens,
        cost_usd=_cost(usage_obj, model, prompt_tokens, 0),
        latency_ms=latency_ms,
    )
    budget.add_spend(usage.cost_usd)
    return vectors, usage
