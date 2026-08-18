"""Ayah reference parsing: numeric, surah name, and curated famous names."""

from __future__ import annotations

import pytest

from quran.models import Surah
from search.ayah_names import FAMOUS_AYAH_NAMES
from search.services import parse_ayah_reference

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "query",
    [
        "2:255",
        "٢:٢٥٥",  # Arabic-Indic digits
        "2 : 255",
        "  2:255  ",
        "البقرة 255",
        "البقره ٢٥٥",  # ta-marbuta folded, Arabic-Indic digits
        "سورة البقرة آية 255",
        "آية الكرسي",
        "اية الكرسى",  # bare hamza + alef maqsura
    ],
)
def test_parse_ayah_reference_resolves_ayat_al_kursi(
    quran_slice: dict[int, Surah], query: str
) -> None:
    (ayah,) = parse_ayah_reference(query)
    assert (ayah.surah_id, ayah.number) == (2, 255)
    assert ayah.surah.name_ar == "البقرة"


def test_parse_ayah_reference_handles_a_two_word_surah_name(
    quran_slice: dict[int, Surah],
) -> None:
    (ayah,) = parse_ayah_reference("آل عمران 61")
    assert (ayah.surah_id, ayah.number) == (3, 61)


@pytest.mark.parametrize(
    ("name", "reference"),
    [(name, reference) for name, reference in FAMOUS_AYAH_NAMES.items()],
)
def test_curated_names_resolve_when_the_ayah_exists(
    quran_slice: dict[int, Surah], name: str, reference: tuple[int, int]
) -> None:
    matches = parse_ayah_reference(name)
    if reference in {(2, 255), (2, 282), (3, 61), (24, 35)}:
        (ayah,) = matches
        assert (ayah.surah_id, ayah.number) == reference
    else:  # 9:5 — surah at-Tawbah is outside this fixture slice
        assert matches == []


@pytest.mark.parametrize(
    "query",
    [
        "",
        "   ",
        "الرحمة في قلوب المؤمنين",  # ordinary prose
        "255",
        "hello world",
        "2:9999",  # ayah out of range
        "999:1",  # surah out of range
        "سورة الفيل 3",  # surah not in the fixture slice
        "آية الفتح",  # not in the curated table
    ],
)
def test_parse_ayah_reference_returns_nothing_for_non_references(
    quran_slice: dict[int, Surah], query: str
) -> None:
    assert parse_ayah_reference(query) == []
