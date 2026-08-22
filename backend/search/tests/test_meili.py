"""Lexical search against a live Meilisearch instance.

Every test here owns a private index (see the ``meili_prefix`` fixture) and
deletes it on teardown, so the suite is safe to run against the shared dev
server.
"""

from __future__ import annotations

import pytest

from corpus.models import SegmentKind
from quran.models import Ayah, Surah
from search import services

from .conftest import KHAWATIR_TEXTS, RECITATION_TEXTS, CorpusFixture

pytestmark = pytest.mark.django_db

IMAN = KHAWATIR_TEXTS[0]  # الْإِيمَانُ بِاللَّهِ وَحْدَهُ ...
SABR = KHAWATIR_TEXTS[1]  # الصَّبْرُ عِنْدَ الصَّدْمَةِ الْأُولَى
HAJJ = RECITATION_TEXTS[1]  # الْحَجُّ عَرَفَةُ وَالطَّوَافُ سَبْعًا


def _ids(query: str, **kwargs: object) -> list[int]:
    ids, _ = services.lexical_search(query, **kwargs)  # type: ignore[arg-type]
    return ids


def test_ensure_chunks_index_configures_the_attributes(chunks_index: str) -> None:
    settings = services.meili_client().index(chunks_index).get_settings()
    assert settings["searchableAttributes"] == ["text_normalized"]
    assert sorted(settings["filterableAttributes"]) == [
        "ayah_start",
        "kind",
        "segment_id",
        "surah",
    ]
    assert sorted(settings["sortableAttributes"]) == ["start_ms", "surah"]


def test_ensure_chunks_index_is_idempotent(chunks_index: str) -> None:
    services.ensure_chunks_index()
    settings = services.meili_client().index(chunks_index).get_settings()
    assert settings["searchableAttributes"] == ["text_normalized"]


def test_index_chunks_stores_the_document_shape(
    chunks_index: str, corpus: CorpusFixture
) -> None:
    assert services.index_chunks(corpus.chunks) == len(corpus.chunks)

    chunk = corpus.chunk_for(IMAN)
    document = services.meili_client().index(chunks_index).get_document(chunk.pk)
    assert document.text == IMAN  # display text keeps its diacritics
    assert document.text_normalized == chunk.text_normalized
    assert document.segment_id == corpus.khawatir.pk
    assert document.segment_title == "خواطر البقرة"
    assert (document.surah, document.ayah_start, document.ayah_end) == (2, 1, 10)
    assert document.kind == SegmentKind.KHAWATIR
    assert (document.start_ms, document.end_ms) == (chunk.start_ms, chunk.end_ms)


def test_index_chunks_upserts_rather_than_duplicates(
    chunks_index: str, corpus: CorpusFixture
) -> None:
    services.index_chunks(corpus.chunks)
    services.index_chunks(corpus.chunks)
    assert services.meili_client().index(chunks_index).get_stats().number_of_documents == len(
        corpus.chunks
    )


def test_index_chunks_ignores_an_empty_batch(chunks_index: str) -> None:
    assert services.index_chunks([]) == 0


def test_exact_phrase_ranks_its_own_chunk_first(indexed_corpus: CorpusFixture) -> None:
    response = services.search("الصبر عند الصدمة")
    assert response.results[0].chunk_id == indexed_corpus.chunk_for(SABR).pk
    assert response.results[0].text == SABR
    assert response.total >= 1


@pytest.mark.parametrize(
    "query",
    [
        "الايمان بالله",  # canonical index spelling
        "الْإِيمَانُ بِٱللَّٰهِ",  # full diacritics, alef wasla, dagger alif
        "الإيمان بالله",  # hamza below
        "الأيمان باللّه",  # wrong hamza (above) + shadda
        "الايمـــان بالله",  # tatweel padding
    ],
)
def test_hamza_and_diacritic_variants_return_the_canonical_result(
    indexed_corpus: CorpusFixture, query: str
) -> None:
    """The key normalization guarantee: however the reader spells it, the query
    is folded to the same form the index holds (CLAUDE.md rule 2)."""
    canonical = _ids("الايمان بالله")
    assert canonical[0] == indexed_corpus.chunk_for(IMAN).pk
    assert _ids(query) == canonical


def test_kind_filter_restricts_results_to_one_segment_kind(
    indexed_corpus: CorpusFixture,
) -> None:
    khawatir_ids = {
        chunk.pk
        for chunk in indexed_corpus.chunks
        if chunk.transcript_id == indexed_corpus.khawatir.transcript.pk
    }
    response = services.search("ال", kind=SegmentKind.KHAWATIR)
    assert response.results
    assert {result.chunk_id for result in response.results} <= khawatir_ids
    assert {result.kind for result in response.results} == {SegmentKind.KHAWATIR}


def test_recitation_kind_searches_mushaf_only(indexed_corpus: CorpusFixture) -> None:
    """تلاوة: canonical text only — recitation ASR chunks must not leak in."""
    response = services.search("الحج عرفة", kind=SegmentKind.RECITATION)
    assert response.results == []
    assert response.total == 0


def test_recitation_kind_returns_mushaf_matches(
    indexed_corpus: CorpusFixture, indexed_quran: None, quran_slice: dict[int, Surah]
) -> None:
    """A mushaf query under تلاوة returns canonical verse matches, no chunks."""
    ayah = Ayah.objects.get(surah_id=24, number=35)
    response = services.search(ayah.text_uthmani, kind=SegmentKind.RECITATION)
    assert [match.number for match in response.verse_matches] == [35]
    assert response.results == []


def test_khawatir_kind_never_returns_mushaf_text(
    indexed_corpus: CorpusFixture, indexed_quran: None
) -> None:
    """خواطر: transcripts only — no verse/reference blocks even when they match."""
    response = services.search(SABR, kind=SegmentKind.KHAWATIR)
    assert response.ayah_matches == []
    assert response.verse_matches == []
    assert response.results
    assert {result.kind for result in response.results} == {SegmentKind.KHAWATIR}


def test_surah_filter_restricts_results_to_one_surah(indexed_corpus: CorpusFixture) -> None:
    response = services.search("ال", surah=3)
    assert response.results
    assert {result.surah for result in response.results} == {3}


def test_filters_can_exclude_every_hit(indexed_corpus: CorpusFixture) -> None:
    assert _ids("الحج عرفة", kind=SegmentKind.KHAWATIR) == []
    assert _ids("الحج عرفة", surah=2) == []
    assert _ids("الحج عرفة", surah=3)


def test_delete_segment_chunks_removes_only_that_segment(
    indexed_corpus: CorpusFixture,
) -> None:
    assert _ids("الحج عرفة")

    services.delete_segment_chunks(indexed_corpus.recitation.pk)

    assert _ids("الحج عرفة") == []
    assert _ids("الصبر عند الصدمة")[0] == indexed_corpus.chunk_for(SABR).pk
    remaining = services.meili_client().index(services.chunks_index_name()).get_stats()
    assert remaining.number_of_documents == len(KHAWATIR_TEXTS)


def test_delete_segment_chunks_tolerates_a_missing_index(meili_prefix: str) -> None:
    services.delete_segment_chunks(1)


def test_lexical_search_is_empty_before_the_index_exists(meili_prefix: str) -> None:
    assert services.lexical_search("الايمان بالله") == ([], 0)


def test_verse_search_returns_canonical_mushaf_hits(
    ayahs_index: str, indexed_quran: None, quran_slice: dict[int, Surah]
) -> None:
    """A reader pasting a full ayah (diacritics and all) gets that ayah back —
    the mushaf text is indexed, and the query is normalized the same way."""
    ayah = Ayah.objects.get(surah_id=24, number=35)
    assert services.verse_search(ayah.text_uthmani)[0] == ayah.pk


def test_pagination_walks_the_ranked_list(indexed_corpus: CorpusFixture) -> None:
    ranked = _ids("ال")
    assert len(ranked) > 2

    first = services.search("ال", page=1, page_size=2)
    second = services.search("ال", page=2, page_size=2)

    assert [result.chunk_id for result in first.results] == ranked[:2]
    assert [result.chunk_id for result in second.results] == ranked[2:4]
    assert (first.page, second.page) == (1, 2)
    assert first.total == second.total


def test_hits_deleted_from_the_database_are_dropped_from_the_page(
    indexed_corpus: CorpusFixture,
) -> None:
    """Meilisearch can be ahead of the database between pipeline runs."""
    stale = indexed_corpus.chunk_for(HAJJ)
    stale_id = stale.pk
    stale.delete()

    response = services.search("الحج عرفة")

    assert stale_id in _ids("الحج عرفة")
    assert [result.chunk_id for result in response.results] == []
