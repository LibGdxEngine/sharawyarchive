"""Semantic retrieval over pgvector, hybrid fusion, and the HNSW query plan.

The stub embedder maps normalized text to a deterministic unit vector, so a
query that repeats a chunk's own text embeds to that chunk's exact vector and
lands at cosine distance 0.
"""

from __future__ import annotations

import pytest
from django.db import connection

from corpus.arabic import normalize_for_index
from corpus.embeddings import StubEmbedder
from corpus.models import Chunk, SegmentKind
from search import services

from .conftest import KHAWATIR_TEXTS, RECITATION_TEXTS, CorpusFixture

pytestmark = pytest.mark.django_db

IMAN = KHAWATIR_TEXTS[0]
SABR = KHAWATIR_TEXTS[1]
HAJJ = RECITATION_TEXTS[1]

BULK_CHUNKS = 200


def test_semantic_search_puts_the_exact_text_first(embedded_corpus: CorpusFixture) -> None:
    hits = services.semantic_search(SABR)
    assert hits[0].pk == embedded_corpus.chunk_for(SABR).pk
    assert hits[0].distance == pytest.approx(0.0, abs=1e-6)
    assert len(hits) == len(embedded_corpus.chunks)


def test_semantic_search_normalizes_the_query_before_embedding(
    embedded_corpus: CorpusFixture,
) -> None:
    """A differently spelled query embeds to the same vector as the canonical
    one, because the query goes through normalize_for_index first."""
    plain = services.semantic_search(normalize_for_index(SABR))
    assert [chunk.pk for chunk in plain] == [
        chunk.pk for chunk in services.semantic_search(SABR)
    ]


def test_semantic_search_skips_chunks_without_an_embedding(
    embedded_corpus: CorpusFixture,
) -> None:
    orphan = embedded_corpus.chunk_for(HAJJ)
    Chunk.objects.filter(pk=orphan.pk).update(embedding=None)
    assert orphan.pk not in {chunk.pk for chunk in services.semantic_search(HAJJ)}


def test_semantic_search_applies_the_kind_and_surah_filters(
    embedded_corpus: CorpusFixture,
) -> None:
    recitation = {
        chunk.pk
        for chunk in embedded_corpus.chunks
        if chunk.transcript_id == embedded_corpus.recitation.transcript.pk
    }
    by_kind = services.semantic_search(SABR, kind=SegmentKind.RECITATION)
    by_surah = services.semantic_search(SABR, surah=3)
    assert {chunk.pk for chunk in by_kind} == recitation
    assert {chunk.pk for chunk in by_surah} == recitation


def test_semantic_search_honours_the_limit(embedded_corpus: CorpusFixture) -> None:
    assert len(services.semantic_search(SABR, limit=3)) == 3


def test_semantic_mode_returns_the_chunk_as_a_result(embedded_corpus: CorpusFixture) -> None:
    response = services.search(SABR, mode="semantic")
    assert response.mode == "semantic"
    assert response.results[0].chunk_id == embedded_corpus.chunk_for(SABR).pk
    assert response.results[0].text == SABR
    assert response.total == len(embedded_corpus.chunks)


def test_hybrid_keeps_a_document_that_tops_both_lists_at_the_top(
    chunks_index: str, embedded_corpus: CorpusFixture
) -> None:
    services.index_chunks(embedded_corpus.chunks)
    expected = embedded_corpus.chunk_for(SABR).pk

    lexical_ids, _ = services.lexical_search(SABR)
    semantic_ids = [chunk.pk for chunk in services.semantic_search(SABR)]
    assert lexical_ids[0] == semantic_ids[0] == expected

    response = services.search(SABR, mode="hybrid")
    assert response.mode == "hybrid"
    assert response.results[0].chunk_id == expected
    assert [result.chunk_id for result in response.results] == services.rrf_merge(
        [lexical_ids, semantic_ids]
    )[: len(response.results)]


def test_hybrid_falls_back_to_the_lexical_order_before_anything_is_embedded(
    indexed_corpus: CorpusFixture,
) -> None:
    """Nothing carries an embedding yet, so fusion has a single list to fuse."""
    lexical_ids, _ = services.lexical_search("الايمان بالله")
    assert lexical_ids[0] == indexed_corpus.chunk_for(IMAN).pk

    fused = [result.chunk_id for result in services.search("الايمان بالله").results]
    assert fused == lexical_ids[: len(fused)]


def test_hybrid_is_the_default_mode(chunks_index: str, embedded_corpus: CorpusFixture) -> None:
    services.index_chunks(embedded_corpus.chunks)
    assert services.search(SABR).mode == "hybrid"


@pytest.mark.parametrize("mode", ["lexical", "semantic", "hybrid"])
def test_every_documented_mode_is_accepted(
    chunks_index: str, embedded_corpus: CorpusFixture, mode: str
) -> None:
    assert services.search(SABR, mode=mode).mode == mode


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"mode": "fuzzy"}, "mode must be one of"),
        ({"kind": "podcast"}, "kind must be one of"),
        ({"page": 0}, "page must be 1 or greater"),
        ({"page_size": 0}, "page_size must be between"),
        ({"page_size": 500}, "page_size must be between"),
    ],
)
def test_invalid_parameters_are_rejected(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(services.SearchParameterError, match=message):
        services.search("الصبر", **kwargs)  # type: ignore[arg-type]


def test_a_query_with_no_searchable_text_is_rejected() -> None:
    with pytest.raises(services.SearchParameterError):
        services.search("ـــ")  # tatweel only


@pytest.fixture
def bulk_embedded_chunks(corpus: CorpusFixture) -> int:
    """Enough embedded rows for the planner to prefer an index scan."""
    embedder = StubEmbedder()
    transcript = corpus.khawatir.transcript
    texts = [f"مقطع رقم {index} من خواطر الشيخ الشعراوي" for index in range(BULK_CHUNKS)]
    vectors = embedder.embed_passages(texts)
    Chunk.objects.bulk_create(
        Chunk(
            transcript=transcript,
            idx=len(KHAWATIR_TEXTS) + index,
            text=text,
            text_normalized=normalize_for_index(text),
            start_ms=index * 30_000,
            end_ms=(index + 1) * 30_000,
            embedding=vector,
        )
        for index, (text, vector) in enumerate(zip(texts, vectors, strict=True))
    )
    return BULK_CHUNKS


def test_semantic_query_plan_uses_the_hnsw_index(bulk_embedded_chunks: int) -> None:
    """The ordering path must be the ``chunk_embedding_hnsw`` index, not a sort
    over a sequential scan (SHAARAWY_PROJECT_PLAN.md, Phase 3)."""
    queryset = services.semantic_queryset("مقطع رقم 7 من خواطر الشيخ الشعراوي", limit=10)
    sql, params = queryset.query.sql_with_params()

    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL enable_seqscan = off")
        cursor.execute(f"EXPLAIN {sql}", params)
        plan = "\n".join(row[0] for row in cursor.fetchall())

    assert "chunk_embedding_hnsw" in plan, plan
    assert "hnsw" in plan.lower()


def test_semantic_search_over_the_bulk_corpus_finds_the_exact_text(
    bulk_embedded_chunks: int,
) -> None:
    text = "مقطع رقم 7 من خواطر الشيخ الشعراوي"
    assert services.semantic_search(text, limit=5)[0].text == text
