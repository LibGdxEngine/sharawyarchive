"""Stage contracts and the strict JSON schema the models are asked to fill."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from search.smart.schemas import (
    GeneratedAnswer,
    QueryPlan,
    RerankResult,
    SmartResponse,
    strict_json_schema,
)


def _objects(node: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if "properties" in node or node.get("type") == "object":
            found.append(node)
        for value in node.values():
            found.extend(_objects(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_objects(item))
    return found


@pytest.mark.parametrize("model", [QueryPlan, RerankResult, GeneratedAnswer])
def test_every_object_in_the_strict_schema_is_closed_and_fully_required(model: type) -> None:
    schema = strict_json_schema(model)

    objects = _objects(schema)
    assert objects, "no object nodes found"
    for node in objects:
        assert node["additionalProperties"] is False
        assert node["required"] == list(node.get("properties", {}).keys())


def test_query_plan_accepts_the_worked_example_and_rejects_extras() -> None:
    plan = QueryPlan.model_validate(
        {
            "intent": "opinion",
            "language": "ar",
            "topic_ar": "مصير والدي النبي",
            "rewrites": ["والدا النبي من أهل الفترة"],
            "keywords": ["أهل الفترة"],
            "ayah_refs": [{"surah": 17, "ayah": 15}],
            "surah_hint": None,
            "answerable_from_corpus": "maybe",
        }
    )
    assert plan.rewrites == ["والدا النبي من أهل الفترة"]

    with pytest.raises(ValidationError):
        QueryPlan.model_validate({**plan.model_dump(), "extra": "no"})
    with pytest.raises(ValidationError):
        QueryPlan.model_validate({**plan.model_dump(), "intent": "rant"})


def test_generated_answer_requires_every_field() -> None:
    answer = GeneratedAnswer.model_validate(
        {
            "status": "answered",
            "answer_md": "قال الشيخ صراحةً … [p1] [[ayah:17:15]]",
            "citations": [{"passage_id": "p1", "quote": "كلام الشيخ كما هو"}],
            "ayah_refs": [{"surah": 17, "ayah": 15}],
            "followups": [],
        }
    )
    assert answer.citations[0].passage_id == "p1"

    with pytest.raises(ValidationError):
        GeneratedAnswer.model_validate({"status": "answered", "answer_md": "…"})


def test_smart_response_defaults() -> None:
    response = SmartResponse(query_id="x", status="degraded", answer_md=None)

    assert response.mode == "smart"
    assert response.citations == [] and response.passages == []
    assert response.cache_hit is False and response.debug is None
