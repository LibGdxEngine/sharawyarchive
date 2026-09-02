"""The offline judge and the report's ship gates."""

from __future__ import annotations

import pytest
import respx

from search.smart.eval import FullResult
from search.smart.eval import report as rep
from search.smart.eval.judge import JudgeResult, judge
from search.smart.schemas import ContextPassage

from .openrouter_fakes import chat_completion, request_json

PASSAGE = ContextPassage(
    id="p1",
    passage_ids=[1],
    transcript_id=1,
    segment_id=1,
    segment_title="خواطر",
    surah=2,
    ayah_start=1,
    ayah_end=10,
    start_ms=0,
    end_ms=1000,
    chunk_idx_start=0,
    chunk_idx_end=0,
    text="الصبر عند الصدمة الأولى",
)


def test_judge_reads_question_passages_and_answer(
    openrouter: respx.MockRouter, smart_settings: object
) -> None:
    verdict_payload = {
        "sentences": [
            {"text": "قال الشيخ كذا", "verdict": "supported", "reason": "في المقطع"},
            {"text": "وقال كذا آخر", "verdict": "unsupported", "reason": "لا أثر"},
            {"text": "ونفى ذلك", "verdict": "contradicted", "reason": "العكس"},
        ]
    }
    route = openrouter.post("/chat/completions").mock(
        return_value=chat_completion(verdict_payload, model="test/judge")
    )

    result, usage = judge("سؤال", [PASSAGE], "قال الشيخ كذا [1].")

    assert isinstance(result, JudgeResult)
    assert (result.unsupported, result.contradicted) == (1, 1)
    body = request_json(route.calls.last.request)
    user = body["messages"][1]["content"]
    assert user.startswith("Question: سؤال") and "<passage id=\"p1\"" in user
    assert user.endswith("Answer:\nقال الشيخ كذا [1].")
    assert usage.model == body["model"]


def _result(**overrides: object) -> FullResult:
    base = FullResult(id="x", expected_status="answered", status="answered", latency_ms=1000)
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def test_summary_and_gates_over_a_small_run() -> None:
    results = [
        _result(id="a", hit_rank=1, citations=3, citations_dropped=0, judged=True, sentences=4),
        _result(id="b", hit_rank=9, citations=1, citations_dropped=1, judged=True, sentences=2,
                unsupported=1),
        _result(id="c", expected_status="not_found", status="not_found"),
        _result(id="d", expected_status="not_found", status="answered", latency_ms=20_000),
        _result(id="e", error="boom"),
    ]

    summary = rep.summarize(results, k=8)

    assert summary["n"] == 5 and summary["errors"] == 1 and summary["labelled"] == 2
    assert summary["recall_at_8"] == 0.5 and summary["mrr"] == pytest.approx(0.5556, abs=1e-4)
    assert summary["abstention_accuracy"] == 0.75
    assert summary["confusion"] == {
        "answered": {"answered": 2},
        "not_found": {"not_found": 1, "answered": 1},
    }
    assert summary["citation_validity"] == 0.8
    assert summary["unsupported_ratio"] == pytest.approx(1 / 6, abs=1e-4)
    assert summary["latency_ms"]["p95"] == 20_000.0

    verdicts = rep.gates(summary)
    assert verdicts == {
        "recall_at_8": False,
        "abstention_accuracy": False,
        "citation_validity": False,
        "unsupported_ratio": False,
        "latency_p95_ms": False,
    }


def test_gates_are_unknown_without_data() -> None:
    summary = rep.summarize([], k=8)

    assert summary["recall_at_8"] is None and summary["abstention_accuracy"] is None
    verdicts = rep.gates(summary)
    assert all(value is None for name, value in verdicts.items() if name != "latency_p95_ms")
    assert rep.gates(summary)["latency_p95_ms"] is True  # p95 of nothing is 0 ms
