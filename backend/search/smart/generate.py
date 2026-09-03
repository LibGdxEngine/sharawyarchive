"""Stage 5 — write the answer from the context, as strict JSON.

The generator sees only the rendered passages and the question. Its output is
never shown to anyone before :mod:`search.smart.verify` has checked every
quote against the transcript words and every ayah placeholder against the
mushaf. One regeneration is allowed when the first answer breaks the schema
or is not in Arabic; a second failure is the caller's to degrade on.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence

from django.conf import settings

from . import context, llm, prompts
from .schemas import ContextPassage, GeneratedAnswer, QueryPlan, Usage

__all__ = ["MIN_ARABIC_RATIO", "generate", "is_arabic"]

logger = logging.getLogger(__name__)

MIN_ARABIC_RATIO = 0.7
RETRY_TOKEN_FACTOR = 2
"""The retry doubles the completion budget…"""
RETRY_REASONING_EFFORT = "low"
"""…and thinks less, so the extra budget reaches the answer rather than the
scratchpad. The first attempt keeps ``medium`` for quality; the second exists
to produce *something* usable."""
_ARABIC = re.compile(r"[؀-ۿ]")
_LETTER = re.compile(r"[^\W\d_]")
_RETRY_NOTE = (
    "\n\nThe previous answer was rejected. "
    "Answer in Arabic and match the JSON schema exactly."
)
_TRUNCATED_NOTE = (
    "\n\nThe previous answer was cut off before it finished. "
    "Answer again, complete and self-contained, at most 120 words, "
    "with at most three citations."
)


def is_arabic(text: str) -> bool:
    """Whether at least :data:`MIN_ARABIC_RATIO` of the letters are Arabic."""
    letters = _LETTER.findall(text)
    if not letters:
        return False
    return len(_ARABIC.findall(text)) / len(letters) >= MIN_ARABIC_RATIO


def _note(error: llm.LLMError | None) -> str:
    """What to tell the model on the retry, given how the first answer failed."""
    return _TRUNCATED_NOTE if isinstance(error, llm.LLMTruncated) else _RETRY_NOTE


def _user_message(question: str, plan: QueryPlan, passages: Sequence[ContextPassage]) -> str:
    return (
        f"Question: {question}\nTopic: {plan.topic_ar}\n\n"
        f"Passages:\n\n{context.render(passages)}"
    )


def generate(
    question: str,
    passages: Sequence[ContextPassage],
    plan: QueryPlan,
    *,
    deadline: llm.Deadline | None = None,
) -> tuple[GeneratedAnswer, list[Usage]]:
    """The generator's answer and the usage of every call it took (one or two)."""
    system = prompts.load("generator")
    user = _user_message(question, plan, passages)
    usages: list[Usage] = []
    last_error: llm.LLMError | None = None
    base_tokens = settings.SMART_GENERATOR_MAX_TOKENS
    for attempt in range(2):
        retrying = attempt > 0
        try:
            answer, usage = llm.chat_json(
                role="generator",
                model=settings.SMART_GENERATOR_MODEL,
                system=system,
                user=user + _note(last_error) if retrying else user,
                schema=GeneratedAnswer,
                timeout_s=settings.SMART_STAGE_TIMEOUTS_S["generate"],
                deadline=deadline,
                reasoning_effort=RETRY_REASONING_EFFORT if retrying else "medium",
                max_tokens=base_tokens * RETRY_TOKEN_FACTOR if retrying else base_tokens,
                fallback_models=settings.SMART_GENERATOR_FALLBACK_MODELS,
            )
        except llm.LLMSchemaError as error:
            last_error = error
            logger.warning("smart.generate: attempt %d rejected: %s", attempt + 1, error)
            continue
        usages.append(usage)
        if is_arabic(answer.answer_md):
            return answer, usages
        last_error = llm.LLMSchemaError("generator: answer is not in Arabic")
        logger.warning("smart.generate: attempt %d not Arabic", attempt + 1)
    assert last_error is not None
    raise last_error
