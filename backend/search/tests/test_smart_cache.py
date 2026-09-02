"""Cache keys, client-address hashing, the daily spend cap and the in-flight cap."""

from __future__ import annotations

import time
from datetime import date
from decimal import Decimal

import pytest
from pytest_django.fixtures import Settings

from search.smart import budget, cache
from search.smart.prompts import PROMPT_VERSION

QUESTION = "ما رأي الشيخ في الصبر"


def test_question_hash_ignores_diacritics_and_whitespace() -> None:
    assert cache.question_hash(QUESTION) == cache.question_hash("  ما  رأى الشيخ في الصَّبر ")
    assert cache.question_hash(QUESTION) != cache.question_hash("ما رأي الشيخ في الشكر")


def test_question_hash_includes_only_real_filters() -> None:
    plain = cache.question_hash(QUESTION)

    assert cache.question_hash(QUESTION, {"surah": None}) == plain
    assert cache.question_hash(QUESTION, {"surah": 2}) != plain
    assert cache.question_hash(QUESTION, {"surah": 2}) == cache.question_hash(
        QUESTION, {"surah": 2, "source_id": None}
    )


def test_response_key_carries_prompt_version_and_embedding_tag(smart_settings: Settings) -> None:
    assert cache.response_key("abc") == f"smart:{PROMPT_VERSION}:test/embed@8:abc"


def test_response_round_trip(smart_settings: Settings) -> None:
    assert cache.get_response("missing") is None

    cache.set_response("abc", {"status": "answered", "answer_md": "…"})

    assert cache.get_response("abc") == {"status": "answered", "answer_md": "…"}


def test_ip_hash_is_salted_per_day_and_never_contains_the_address() -> None:
    today = cache.ip_hash("10.0.0.1", day=date(2026, 9, 2))
    tomorrow = cache.ip_hash("10.0.0.1", day=date(2026, 9, 3))

    assert len(today) == 32 and int(today, 16) >= 0
    assert today != tomorrow
    assert today != cache.ip_hash("10.0.0.2", day=date(2026, 9, 2))
    assert "10.0.0.1" not in today
    assert cache.ip_hash(None) == ""
    assert cache.ip_hash("") == ""


# --- budget -------------------------------------------------------------------


def test_spend_accumulates_and_ignores_nothing_burgers(smart_settings: Settings) -> None:
    assert budget.spend_today() == Decimal("0")

    budget.add_spend(Decimal("0.001"))
    budget.add_spend(Decimal("0.0025"))
    budget.add_spend(None)
    budget.add_spend(Decimal("0"))

    assert budget.spend_today() == Decimal("0.0035")
    assert not budget.over_budget()


def test_over_budget_trips_at_the_daily_cap(smart_settings: Settings) -> None:
    budget.add_spend(Decimal("4.999"))
    assert not budget.over_budget()

    budget.add_spend(Decimal("0.001"))

    assert budget.over_budget()


def test_spend_key_is_per_utc_day() -> None:
    assert budget.spend_key(date(2026, 9, 2)) == "smart:spend:2026-09-02"


# --- in-flight cap --------------------------------------------------------------


def test_inflight_slots_are_limited_and_released(smart_settings: Settings) -> None:
    with budget.inflight_slot(limit=2) as first:
        assert first
        with budget.inflight_slot(limit=2) as second:
            assert second
            assert budget.inflight_count() == 2
            with budget.inflight_slot(limit=2) as third:
                assert not third
        assert budget.inflight_count() == 1
    assert budget.inflight_count() == 0

    with budget.inflight_slot(limit=1) as again:
        assert again


def test_inflight_slot_is_released_when_the_block_raises(smart_settings: Settings) -> None:
    with pytest.raises(RuntimeError):
        with budget.inflight_slot(limit=1) as acquired:
            assert acquired
            raise RuntimeError("boom")

    assert budget.inflight_count() == 0


def test_stale_leases_do_not_block_new_requests(smart_settings: Settings) -> None:
    budget.redis_client().zadd(
        budget.INFLIGHT_KEY, {"dead-worker": time.time() - budget.INFLIGHT_LEASE_S - 5}
    )

    assert budget.inflight_count() == 0
    with budget.inflight_slot(limit=1) as acquired:
        assert acquired


def test_inflight_default_limit_comes_from_settings(smart_settings: Settings) -> None:
    smart_settings.SMART_MAX_INFLIGHT = 1

    with budget.inflight_slot() as first, budget.inflight_slot() as second:
        assert first and not second
