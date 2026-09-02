"""The strict phrase verifier, in isolation (no database, no Meilisearch)."""

from __future__ import annotations

import pytest

from corpus.arabic import normalize_for_index
from search import matching, services
from search.matching import (
    PhraseMatch,
    edit_distance,
    phrase_match,
    tokenize,
    typo_budget,
    typo_cost,
)

from .conftest import KHAWATIR_TEXTS

SABR = normalize_for_index(KHAWATIR_TEXTS[1])  # الصبر عند الصدمه الاولي
IMAN = normalize_for_index(KHAWATIR_TEXTS[0])  # الايمان بالله وحده لا شريك له


@pytest.mark.parametrize(
    ("word", "budget"),
    [
        ("له", 0),
        ("عند", 0),
        ("255", 0),
        ("الله", 1),
        ("الصبر", 1),
        ("طمانينه", 1),
        ("المومنين", 2),
        ("السماوات", 2),
    ],
)
def test_typo_budget_grows_with_word_length(word: str, budget: int) -> None:
    assert typo_budget(word) == budget


@pytest.mark.parametrize(
    ("a", "b", "distance"),
    [
        ("الصبر", "الصبر", 0),
        ("الصبن", "الصبر", 1),  # substitution
        ("الصدم", "الصدمه", 1),  # deletion
        ("الصبر", "الصبرر", 1),  # insertion
        ("الصرب", "الصبر", 1),  # adjacent transposition is one edit
        ("الظبن", "الصبر", 2),
        ("ابراهيم", "ابرهم", 2),
        ("الموممنون", "المومنين", 2),
        ("الموممنوون", "المومنين", 3),
    ],
)
def test_edit_distance_counts_each_operation_once(a: str, b: str, distance: int) -> None:
    assert edit_distance(a, b, limit=3) == distance


def test_edit_distance_stops_at_the_limit() -> None:
    assert edit_distance("ابراهيم", "ابرهم", limit=1) == 2  # reported as limit + 1
    assert edit_distance("الموممنوون", "المومنين", limit=2) == 3
    assert edit_distance("قصير", "طويل جدا", limit=2) == 3  # length gap alone exceeds it


@pytest.mark.parametrize(
    ("query_word", "doc_word", "cost"),
    [
        ("الصبر", "الصبر", 0),
        ("الصبن", "الصبر", 1),
        ("الصرب", "الصبر", 1),
        ("الصب", "الصبر", 1),  # a prefix one letter short is a deletion within budget
        ("الصدم", "الصدمه", 1),
        ("المومنون", "المومنين", 1),
        ("الموممنون", "المومنين", 2),
        ("السماوات", "السموت", 2),  # imlaei spelling against the Uthmani index form
        ("الصلاه", "الصلوه", 1),
        ("داوود", "داود", 1),
    ],
)
def test_typo_cost_within_budget(query_word: str, doc_word: str, cost: int) -> None:
    assert typo_cost(query_word, doc_word) == cost


@pytest.mark.parametrize(
    ("query_word", "doc_word"),
    [
        ("عنت", "عند"),  # 1-3 letters: exact only
        ("عن", "عند"),
        ("الظبن", "الصبر"),  # two edits on a 5-letter word
        ("بلصبر", "الصبر"),  # the first letter must match
        ("بلمومنين", "المومنين"),  # even with a two-edit budget
        ("لصبر", "الصبر"),  # deleted first letter: first letters differ
        ("ابراهيم", "ابرهم"),  # 7 letters allow one edit, this needs two
        ("الصد", "الصدمه"),  # a prefix two letters short
        ("الموممنوون", "المومنين"),  # three edits on a long word
        ("الله", "بالله"),  # clitic: the extra letter is a first-letter change
    ],
)
def test_typo_cost_rejects_beyond_budget(query_word: str, doc_word: str) -> None:
    assert typo_cost(query_word, doc_word) is None


def test_thresholds_are_the_ones_meilisearch_is_configured_with() -> None:
    assert (matching.ONE_TYPO_MIN_LETTERS, matching.TWO_TYPOS_MIN_LETTERS) == (4, 8)
    assert services.TYPO_TOLERANCE["minWordSizeForTypos"] == {"oneTypo": 4, "twoTypos": 8}


@pytest.mark.parametrize(
    ("text", "tokens"),
    [
        ("الصبر، عند الصدمه.", ["الصبر", "عند", "الصدمه"]),
        ("«الله» (2:255)", ["الله", "2", "255"]),
        ("قال: يا ايها الذين امنوا؛ اصبروا", ["قال", "يا", "ايها", "الذين", "امنوا", "اصبروا"]),
        ("؟", []),
        ("", []),
    ],
)
def test_tokenize_splits_on_punctuation_like_meilisearch(text: str, tokens: list[str]) -> None:
    assert tokenize(text) == tokens


def test_phrase_match_finds_the_phrase_anywhere() -> None:
    assert phrase_match(["الصبر"], SABR) == PhraseMatch(typos=0, start=0)
    assert phrase_match(["عند", "الصدمه"], SABR) == PhraseMatch(typos=0, start=1)
    assert phrase_match(["الاولي"], SABR) == PhraseMatch(typos=0, start=3)
    assert phrase_match(tokenize(SABR), SABR) == PhraseMatch(typos=0, start=0)


def test_phrase_match_requires_the_same_order() -> None:
    assert phrase_match(["الصدمه", "عند"], SABR) is None
    assert phrase_match(["عند", "الصبر"], SABR) is None


def test_phrase_match_requires_adjacent_words() -> None:
    assert phrase_match(["الصبر", "الصدمه"], SABR) is None
    assert phrase_match(["الصبر", "الاولي"], SABR) is None


def test_phrase_match_spends_typos_per_word() -> None:
    assert phrase_match(["الصبن", "عند"], SABR) == PhraseMatch(typos=1, start=0)
    assert phrase_match(["الصبن", "عند", "الصدم"], SABR) == PhraseMatch(typos=2, start=0)
    assert phrase_match(["الصبر", "عنت", "الصدمه"], SABR) is None  # 3-letter word must be exact


def test_phrase_match_rejects_a_query_longer_than_the_document() -> None:
    assert phrase_match([*tokenize(SABR), "له"], SABR) is None


def test_phrase_match_prefers_the_window_with_the_fewest_typos() -> None:
    doc = "الصبن عند شيء الصبر عند"
    assert phrase_match(["الصبر", "عند"], doc) == PhraseMatch(typos=0, start=3)
    assert phrase_match(["الصبن", "عند"], doc) == PhraseMatch(typos=0, start=0)


def test_phrase_match_keeps_the_earliest_window_on_a_tie() -> None:
    doc = "الصبن عند شيء الصبن عند"
    assert phrase_match(["الصبر", "عند"], doc) == PhraseMatch(typos=1, start=0)


def test_phrase_match_ignores_glued_punctuation() -> None:
    doc = normalize_for_index("الصَّبْرُ الْجَمِيلُ، عِنْدَ الصَّدْمَةِ.")
    assert phrase_match(["الجميل", "عند", "الصدمه"], doc) == PhraseMatch(typos=0, start=1)


def test_phrase_match_with_an_empty_query_is_none() -> None:
    assert phrase_match([], SABR) is None
    assert phrase_match(["الصبر"], "") is None


@pytest.mark.parametrize(
    "query",
    ["الايمان بالله", "الْإِيمَانُ بِٱللَّٰهِ", "الإيمان بالله", "الأيمان باللّه", "الايمـــان بالله"],
)
def test_normalization_variants_cost_no_typos(query: str) -> None:
    """Hamza, diacritics and tatweel are folded before matching (CLAUDE.md rule 2)."""
    assert phrase_match(tokenize(normalize_for_index(query)), IMAN) == PhraseMatch(0, 0)


@pytest.mark.parametrize(
    ("text", "limit", "snippet"),
    [
        ("ab cd ef", 5, "ab cd"),
        ("ab cd ef", 6, "ab cd"),
        ("abcdefgh", 5, "abcde"),
        ("ab cd", 80, "ab cd"),
        ("  ab cd  ", 80, "ab cd"),
        ("ab cd ef", 2, "ab"),
    ],
)
def test_snippet_ends_on_a_word_boundary(text: str, limit: int, snippet: str) -> None:
    assert services._snippet(text, limit) == snippet
