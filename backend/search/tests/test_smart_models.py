"""SmartQuery rows, the admin registration and the versioned prompt files."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.contrib import admin

from search.models import SmartQuery, SmartStatus
from search.smart import embedding_model_tag
from search.smart.prompts import PROMPT_VERSION, load


@pytest.mark.django_db
def test_smart_query_round_trips_its_json_and_decimal_fields() -> None:
    row = SmartQuery.objects.create(
        question="ما رأي الشيخ في الصبر؟",
        question_normalized="ما راي الشيخ في الصبر؟",
        question_hash="a" * 64,
        status=SmartStatus.ANSWERED,
        plan={"rewrites": ["الصبر عند الصدمة"]},
        candidate_ids=[1, 2, 3],
        answer={"status": "answered", "answer_md": "…"},
        models_used={"planner": "test/planner"},
        prompt_version=PROMPT_VERSION,
        usage={"planner": {"prompt_tokens": 100}},
        cost_usd=Decimal("0.012345"),
        latency_ms={"planner": 800, "total": 1234},
        ip_hash="f" * 32,
    )

    saved = SmartQuery.objects.get(pk=row.pk)

    assert saved.plan == {"rewrites": ["الصبر عند الصدمة"]}
    assert saved.candidate_ids == [1, 2, 3]
    assert saved.cost_usd == Decimal("0.012345")
    assert saved.total_latency_ms == 1234
    assert saved.cache_hit is False and saved.feedback == "" and saved.user is None
    assert str(saved) == f"smart query {saved.pk} [answered]"


@pytest.mark.django_db
def test_total_latency_is_none_until_recorded() -> None:
    row = SmartQuery.objects.create(
        question="س", question_normalized="س", question_hash="b" * 64, status=SmartStatus.ERROR
    )

    assert row.total_latency_ms is None


def test_smart_query_is_registered_read_only_in_the_admin() -> None:
    model_admin = admin.site._registry[SmartQuery]

    assert model_admin.has_add_permission(None) is False  # type: ignore[arg-type]
    assert model_admin.has_change_permission(None) is False  # type: ignore[arg-type]
    assert "question" in model_admin.readonly_fields


def test_prompts_load_and_carry_the_grounding_markers() -> None:
    assert PROMPT_VERSION == "v1"
    assert "rewrites" in load("planner")
    assert "3 " in load("reranker") and "0 " in load("reranker")
    generator = load("generator")
    assert "[[ayah:S:A]]" in generator and "[p1]" in generator
    assert "رحمه الله" in generator
    assert "supported" in load("judge")
    with pytest.raises(FileNotFoundError):
        load("nope")


def test_embedding_model_tag_reads_settings(smart_settings: object) -> None:
    assert embedding_model_tag() == "test/embed@8"
    assert embedding_model_tag("m", 3) == "m@3"
