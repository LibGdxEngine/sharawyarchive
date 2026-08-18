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
    assert set(body) == {"query", "mode", "ayah_matches", "results", "page", "total"}
    assert (body["query"], body["mode"], body["page"]) == ("الصبر عند الصدمة", "hybrid", 1)
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


@pytest.mark.parametrize("mode", ["lexical", "semantic", "hybrid"])
def test_mode_is_echoed_back(api: APIClient, indexed_corpus: CorpusFixture, mode: str) -> None:
    response = api.get(URL, {"q": "الصبر", "mode": mode})
    assert response.status_code == 200
    assert response.json()["mode"] == mode


def test_filters_are_forwarded_to_the_services_layer(
    api: APIClient, indexed_corpus: CorpusFixture
) -> None:
    body = api.get(
        URL, {"q": "ال", "mode": "lexical", "kind": SegmentKind.RECITATION, "surah": 3}
    ).json()
    assert body["results"]
    assert {result["kind"] for result in body["results"]} == {SegmentKind.RECITATION}
    assert {result["surah"] for result in body["results"]} == {3}


def test_page_selects_a_later_slice(api: APIClient, indexed_corpus: CorpusFixture) -> None:
    first = api.get(URL, {"q": "ال", "mode": "lexical"}).json()
    second = api.get(URL, {"q": "ال", "mode": "lexical", "page": 2}).json()
    assert second["page"] == 2
    first_ids = {result["chunk_id"] for result in first["results"]}
    assert first_ids.isdisjoint({result["chunk_id"] for result in second["results"]})


@pytest.mark.parametrize(
    "params",
    [
        {},  # q missing
        {"q": ""},
        {"q": "   "},
        {"q": "الصبر", "mode": "fuzzy"},
        {"q": "الصبر", "kind": "podcast"},
        {"q": "الصبر", "surah": "two"},
        {"q": "الصبر", "page": "0"},
        {"q": "الصبر", "page": "last"},
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
