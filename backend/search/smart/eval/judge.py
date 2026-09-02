"""Offline faithfulness judge: a frontier model reads the question, the
passages and the answer and marks every sentence supported, unsupported or
contradicted. Evaluation only — nothing on the request path imports this.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from django.conf import settings

from search.smart import context, llm, prompts
from search.smart.schemas import ContextPassage, StrictModel, Usage

__all__ = ["JudgeResult", "JudgeSentence", "judge"]

JUDGE_TIMEOUT_S = 60.0


class JudgeSentence(StrictModel):
    text: str
    verdict: Literal["supported", "unsupported", "contradicted"]
    reason: str


class JudgeResult(StrictModel):
    sentences: list[JudgeSentence]

    @property
    def unsupported(self) -> int:
        return sum(1 for item in self.sentences if item.verdict == "unsupported")

    @property
    def contradicted(self) -> int:
        return sum(1 for item in self.sentences if item.verdict == "contradicted")


def judge(
    question: str, passages: Sequence[ContextPassage], answer_md: str
) -> tuple[JudgeResult, Usage]:
    return llm.chat_json(
        role="judge",
        model=settings.SMART_JUDGE_MODEL,
        system=prompts.load("judge"),
        user=(
            f"Question: {question}\n\nPassages:\n\n{context.render(passages)}\n\n"
            f"Answer:\n{answer_md}"
        ),
        schema=JudgeResult,
        timeout_s=JUDGE_TIMEOUT_S,
        reasoning_effort="medium",
        max_tokens=2500,
        check_budget=False,
    )
