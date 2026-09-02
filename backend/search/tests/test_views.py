"""GET /api/search/ — response shape and headers per API_CONTRACT.md."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from corpus.models import SegmentKind

from .conftest import KHAWATIR_TEXTS, CorpusFixture

pytestmark = pytest.mark.django_db

URL = "/api/search/"
SABR = KHAWATIR_TEXTS[1]

RESULT_KEYS = {
    "chunk_id",
    "segment_id",
    "segment_title",
    "surah",
    "ayah_start",
    "ayah_end",
    "kind",
    "text",
    "start_ms",
    "end_ms",
}


@pytest.fixture
def api() -> APIClient:
    return APIClient()


def test_search_returns_the_contract_shape(api: APIClient, indexed_corpus: CorpusFixture) -> None:
    response = api.get(URL, {"q": "الصبر عند الصدمة"})

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    body = response.json()
    assert set(body) == {"query", "ayah_matches", "verse_matches", "results", "page", "total"}
    assert (body["query"], body["page"]) == ("الصبر عند الصدمة", 1)
    assert isinstance(body["total"], int)

    (first, *_) = body["results"]
    assert set(first) == RESULT_KEYS
    assert first["chunk_id"] == indexed_corpus.chunk_for(SABR).pk
    assert first["text"] == SABR  # display text, diacritics intact
    assert first["segment_id"] == indexed_corpus.khawatir.pk
    assert first["segment_title"] == "خواطر البقرة"
    assert (first["surah"], first["ayah_start"], first["ayah_end"]) == (2, 1, 10)
    assert first["kind"] == SegmentKind.KHAWATIR
    assert isinstance(first["start_ms"], int)


def test_ayah_reference_query_populates_ayah_matches(
    api: APIClient, indexed_corpus: CorpusFixture
) -> None:
    body = api.get(URL, {"q": "2:255"}).json()

    assert body["ayah_matches"] == [
        {
            "surah": 2,
            "number": 255,
            "text_uthmani": "ٱللَّهُ لَآ إِلَـٰهَ إِلَّا هُوَ ٱلْحَىُّ ٱلْقَيُّومُ",
            "surah_name_ar": "البقرة",
        }
    ]


def test_a_prose_query_has_no_ayah_matches(api: APIClient, indexed_corpus: CorpusFixture) -> None:
    assert api.get(URL, {"q": "الصبر عند الصدمة"}).json()["ayah_matches"] == []


def test_full_ayah_query_populates_verse_matches(
    api: APIClient, indexed_quran: None
) -> None:
    """Pasting a whole ayah (diacritics included) surfaces it as a mushaf
    full-text match even when no ASR chunk mentions it."""
    from quran.models import Ayah

    ayah = Ayah.objects.get(surah_id=24, number=35)
    body = api.get(URL, {"q": ayah.text_uthmani}).json()

    assert body["ayah_matches"] == []
    assert body["verse_matches"][0]["surah"] == 24
    assert body["verse_matches"][0]["number"] == 35
    assert body["verse_matches"][0]["text_uthmani"] == ayah.text_uthmani


def test_an_unknown_query_param_is_ignored(
    api: APIClient, indexed_corpus: CorpusFixture
) -> None:
    """Old shared URLs carrying the removed ``mode=`` param keep working."""
    response = api.get(URL, {"q": "الصبر", "mode": "hybrid"})
    assert response.status_code == 200
    assert "mode" not in response.json()


def test_filters_are_forwarded_to_the_services_layer(
    api: APIClient, indexed_corpus: CorpusFixture
) -> None:
    body = api.get(URL, {"q": "القلب", "kind": SegmentKind.KHAWATIR, "surah": 2}).json()
    assert body["results"]
    assert {result["kind"] for result in body["results"]} == {SegmentKind.KHAWATIR}
    assert {result["surah"] for result in body["results"]} == {2}


def test_kind_recitation_returns_mushaf_only(
    api: APIClient, indexed_corpus: CorpusFixture
) -> None:
    body = api.get(URL, {"q": "الحج عرفة", "kind": SegmentKind.RECITATION}).json()
    assert body["results"] == []
    assert body["total"] == 0


def test_kind_khawatir_returns_transcripts_only(
    api: APIClient, indexed_corpus: CorpusFixture, indexed_quran: None
) -> None:
    body = api.get(URL, {"q": SABR, "kind": SegmentKind.KHAWATIR}).json()
    assert body["ayah_matches"] == []
    assert body["verse_matches"] == []
    assert body["results"]
    assert {result["kind"] for result in body["results"]} == {SegmentKind.KHAWATIR}


def test_page_beyond_the_results_is_empty_but_keeps_total(
    api: APIClient, indexed_corpus: CorpusFixture
) -> None:
    first = api.get(URL, {"q": "القلب"}).json()
    second = api.get(URL, {"q": "القلب", "page": 2}).json()
    assert len(first["results"]) == 4
    assert (second["page"], second["results"]) == (2, [])
    assert first["total"] == second["total"] == 4


@pytest.mark.parametrize(
    "params",
    [
        {},  # q missing
        {"q": ""},
        {"q": "   "},
        {"q": "الصبر", "kind": "podcast"},
        {"q": "الصبر", "surah": "two"},
        {"q": "الصبر", "page": "0"},
        {"q": "الصبر", "page": "last"},
        {"q": "الصبر", "page": "500000"},  # deep pagination stays capped
    ],
)
def test_bad_requests_are_rejected(
    api: APIClient, indexed_corpus: CorpusFixture, params: dict[str, str]
) -> None:
    response = api.get(URL, params)
    assert response.status_code == 400
    assert response.headers["Cache-Control"] == "no-store"
    assert "detail" in response.json()


def test_search_survives_an_empty_corpus(api: APIClient, chunks_index: str) -> None:
    body = api.get(URL, {"q": "الصبر"}).json()
    assert body["results"] == []
    assert body["total"] == 0


def test_url_is_wired_next_to_the_existing_api_routes(api: APIClient, db: None) -> None:
    """Every ``api/`` include must keep resolving."""
    assert api.get("/api/surahs/").status_code == 200
    assert api.get(URL).status_code == 400


SUGGEST_URL = "/api/search/suggest/"


def test_suggest_returns_matching_snippets(
    api: APIClient, indexed_corpus: CorpusFixture
) -> None:
    response = api.get(SUGGEST_URL, {"q": "الصبر"})
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    suggestions = response.json()
    assert suggestions  # the sabr chunk matches
    assert all(isinstance(text, str) for text in suggestions)
    assert any(SABR.startswith(text) for text in suggestions)


def test_suggest_short_or_empty_query_yields_nothing(
    api: APIClient, indexed_corpus: CorpusFixture
) -> None:
    assert api.get(SUGGEST_URL, {"q": ""}).json() == []
    assert api.get(SUGGEST_URL, {"q": "ا"}).json() == []


def test_suggest_kind_recitation_suggests_mushaf_text(
    api: APIClient, indexed_corpus: CorpusFixture, indexed_quran: None
) -> None:
    from quran.models import Ayah

    ayah = Ayah.objects.get(surah_id=24, number=35)
    suggestions = api.get(SUGGEST_URL, {"q": "الله نور", "kind": "recitation"}).json()

    assert suggestions
    assert ayah.text_uthmani in suggestions


def test_suggest_kind_khawatir_excludes_recitation_chunks(
    api: APIClient, indexed_corpus: CorpusFixture
) -> None:
    # الحج عرفة lives only on a recitation chunk: it appears in the default
    # suggestions but never when the khawatir kind filters the source.
    all_suggestions = api.get(SUGGEST_URL, {"q": "الحج عرفة"}).json()
    khawatir_only = api.get(SUGGEST_URL, {"q": "الحج عرفة", "kind": "khawatir"}).json()
    assert any("الْحَجُّ عَرَفَةُ" in s for s in all_suggestions)
    assert not any("الْحَجُّ عَرَفَةُ" in s for s in khawatir_only)
