"""Semantic retrieval over pgvector, hybrid fusion, and the HNSW query plan.

The stub embedder maps normalized text to a deterministic unit vector, so a
query that repeats a chunk's own text embeds to that chunk's exact vector and
lands at cosine distance 0.
"""

from __future__ import annotations

import numpy as np
import pytest
from django.db import connection
from django.db.models import QuerySet
from pgvector.django import CosineDistance

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

INDEXED_CHUNKS = 5_000
"""Rows in the ``indexed_scale_corpus`` fixture.

Below a few thousand rows the chunk table is a handful of heap pages — the
1024-float vectors are TOASTed out of line — and PostgreSQL will (correctly)
read all of it rather than descend an index. Any claim about the HNSW plan
under that size is a claim about a plan production never runs. This is roughly
the smallest corpus where the planner reaches for ``chunk_embedding_hnsw``
without being pushed."""

NEAR_CLUSTER = 4_500
"""Of :data:`INDEXED_CHUNKS`, how many crowd around the query vector. They all
sit in the khawatir segment; the remainder go to the recitation segment,
pointing the opposite way. That separation is the point: it makes the corpus's
nearest neighbours to the query and the *recitation* segment's nearest
neighbours to it two completely different sets of rows."""

SCALE_SEED = 20240611
SCATTER = 0.05
"""How far the cluster members stray from their centre. Small enough that the
whole near cluster beats every far one, big enough that they are 4500 distinct
vectors rather than 4500 copies."""

OFFSET_IDX = 100
"""Clear of the ``corpus`` fixture's own chunk indices — ``(transcript, idx)``
is unique."""


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
        # Deep pagination is a vector-scan amplifier: page N asks the ANN index
        # for N * page_size rows, so an uncapped page turns one anonymous GET
        # into a multi-million-row scan.
        ({"page": services.MAX_PAGE + 1}, f"page must be {services.MAX_PAGE} or less"),
        ({"page": 500_000}, f"page must be {services.MAX_PAGE} or less"),
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


def test_the_last_allowed_page_is_still_served(embedded_corpus: CorpusFixture) -> None:
    """The cap is a boundary, not an off-by-one: page 100 is a real page."""
    response = services.search(SABR, mode="semantic", page=services.MAX_PAGE)

    assert response.page == services.MAX_PAGE
    assert response.results == []  # past the end of a ten-chunk corpus


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


def test_semantic_search_over_the_bulk_corpus_finds_the_exact_text(
    bulk_embedded_chunks: int,
) -> None:
    text = "مقطع رقم 7 من خواطر الشيخ الشعراوي"
    assert services.semantic_search(text, limit=5)[0].text == text


# --- The HNSW index, at a size where the planner actually reaches for it -----


@pytest.fixture
def indexed_scale_corpus(corpus: CorpusFixture) -> int:
    """:data:`INDEXED_CHUNKS` embedded chunks in two well-separated clusters.

    :data:`NEAR_CLUSTER` of them crowd around the vector ``SABR`` embeds to and
    live in the khawatir segment; the rest point the opposite way and live in
    the recitation segment. So the corpus-wide nearest neighbours of a query
    for ``SABR`` are *all* khawatir, and the same query filtered to recitation
    has to look past every one of them. A uniformly random corpus would let a
    filtered query pass by luck.

    The HNSW index is dropped for the load and rebuilt from its own catalogue
    definition afterwards — the same thing a bulk import does, and about three
    times faster than 5000 incremental index inserts, which is what keeps this
    module inside its runtime budget. All of it is inside the test transaction,
    index included, so it rolls back with everything else.
    """
    centre = np.asarray(StubEmbedder().embed_query(SABR), dtype=np.float32)
    rng = np.random.default_rng(SCALE_SEED)
    plans = (
        (corpus.khawatir, centre, NEAR_CLUSTER),
        (corpus.recitation, -centre, INDEXED_CHUNKS - NEAR_CLUSTER),
    )

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT indexdef FROM pg_indexes WHERE indexname = 'chunk_embedding_hnsw'"
        )
        (index_ddl,) = cursor.fetchone()
        cursor.execute("DROP INDEX chunk_embedding_hnsw")

    for segment, direction, count in plans:
        Chunk.objects.bulk_create(
            (
                Chunk(
                    transcript=segment.transcript,
                    idx=OFFSET_IDX + index,
                    text=f"{segment.kind} {index}",
                    text_normalized=f"{segment.kind} {index}",
                    start_ms=index * 1_000,
                    end_ms=(index + 1) * 1_000,
                    embedding=vector,
                )
                for index, vector in enumerate(_around(rng, direction, count))
            ),
            batch_size=1_000,
        )

    with connection.cursor() as cursor:
        # The test transaction defers foreign-key checks, and CREATE INDEX
        # refuses to run with trigger events pending.
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute(index_ddl)
        # The planner needs current statistics to cost the index; a live corpus
        # has them from autovacuum. Unlike `enable_seqscan = off` this does not
        # tell PostgreSQL which plan to pick, only how big the table is.
        cursor.execute("ANALYZE corpus_chunk")
    return INDEXED_CHUNKS


def _around(rng: np.random.Generator, centre: np.ndarray, count: int) -> np.ndarray:
    """``count`` unit vectors scattered tightly around ``centre``."""
    vectors = centre + rng.standard_normal((count, len(centre))).astype(np.float32) * SCATTER
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def _plan(queryset: QuerySet[Chunk]) -> str:
    """The plan PostgreSQL would choose for ``queryset``, unprompted."""
    sql, params = queryset.query.sql_with_params()
    with connection.cursor() as cursor:
        cursor.execute(f"EXPLAIN {sql}", params)
        return "\n".join(row[0] for row in cursor.fetchall())


def test_semantic_query_plan_uses_the_hnsw_index(indexed_scale_corpus: int) -> None:
    """The ordering path must be the ``chunk_embedding_hnsw`` index, not a sort
    over a sequential scan (SHAARAWY_PROJECT_PLAN.md, Phase 3).

    Nothing is forced here: no ``enable_seqscan = off``, because turning the
    alternative off proves only that the index *can* serve the query. On a
    corpus this size the planner picks it because it is genuinely cheaper,
    which is the claim actually worth making.
    """
    plan = _plan(services.semantic_queryset(SABR, limit=10))

    assert "chunk_embedding_hnsw" in plan, plan
    assert "Seq Scan on corpus_chunk" not in plan, plan


def test_a_filtered_ann_query_still_fills_the_page(
    indexed_scale_corpus: int, corpus: CorpusFixture
) -> None:
    """Regression: this is what :func:`search.services.hnsw_scan` is for.

    The shape is ``/related/``'s: order the whole corpus by distance, then drop
    the segment we started from. Both halves matter. Because the ordering has
    no other predicate on ``corpus_chunk`` the planner really does use the HNSW
    index — and because the exclusion is applied *above* that scan, it throws
    away rows the scan already committed to. Every one of the 40 candidates
    pgvector visits by default lands in the excluded segment here, so before
    the fix this came back empty, with nothing anywhere to say the answer was
    not simply "no neighbours".
    """
    centre = StubEmbedder().embed_query(SABR)
    query = (
        Chunk.objects.filter(embedding__isnull=False)
        .exclude(transcript__segment_id=corpus.khawatir.pk)
        .select_related("transcript__segment")
    )
    ordered = query.annotate(distance=CosineDistance("embedding", centre)).order_by(
        "distance"
    )[:10]
    assert "chunk_embedding_hnsw" in _plan(ordered)  # otherwise this proves nothing

    hits = services.nearest_chunks(query, centre, limit=10)

    assert len(hits) == 10
    assert {hit.transcript.segment.pk for hit in hits} == {corpus.recitation.pk}


def test_a_filtered_semantic_query_is_exact(indexed_scale_corpus: int) -> None:
    """``kind=``/``surah=`` are a different story: the join makes the planner
    reach the chunks through ``transcript_id`` and sort them exactly, so those
    filters were never the ones losing rows. Asserted so that a future index
    that *does* put them on the approximate path is caught here."""
    hits = services.semantic_search(SABR, kind=SegmentKind.RECITATION, limit=10)

    assert len(hits) == 10
    assert {hit.transcript.segment.kind for hit in hits} == {SegmentKind.RECITATION}


# --- The scan settings themselves --------------------------------------------


def _guc(name: str) -> str:
    with connection.cursor() as cursor:
        cursor.execute(f"SHOW {name}")
        return str(cursor.fetchone()[0])


@pytest.fixture
def vector_session(db: None) -> None:
    """pgvector registers its ``hnsw.*`` settings when the extension's library
    is first loaded into the backend, which happens on the first vector
    operation — not at connect. Force one, so ``SHOW hnsw.*`` is answerable
    regardless of what ran on this connection before."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT '[1]'::vector <=> '[1]'::vector")


@pytest.mark.parametrize(
    ("depth", "expected"),
    [
        (500, "500"),
        (1, str(services.HNSW_MIN_EF_SEARCH)),  # never shallower than stock
        (10**6, str(services.HNSW_MAX_EF_SEARCH)),  # nor deeper than useful
    ],
)
def test_the_scan_depth_follows_the_requested_limit(
    vector_session: None, depth: int, expected: str
) -> None:
    """Both settings really are applied, and the depth is clamped to a band.

    (That they are ``SET LOCAL`` and therefore die with the transaction is not
    asserted here: pytest wraps every test in an outer transaction of its own,
    so inside the suite there is no transaction boundary to observe.)
    """
    with services.hnsw_scan(depth):
        assert _guc("hnsw.ef_search") == expected
        assert _guc("hnsw.iterative_scan") == "relaxed_order"
