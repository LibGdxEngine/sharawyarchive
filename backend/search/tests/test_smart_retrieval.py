"""Hybrid retrieval over passages (``search.smart.retrieval``).

Lexical and ayah-anchored channels run against Postgres alone; the semantic
channel gets hand-made unit vectors written straight into the table, so no
provider is involved until :func:`retrieve` itself, whose embedding call is
respx-mocked. Everything asserts on ids and order, never on scores.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import pytest
import respx
from django.db import connection
from pytest_django.fixtures import Settings

from corpus.arabic import normalize_for_index, stem_text
from corpus.models import Segment
from search.models import EMBEDDING_DIMENSIONS, Passage
from search.smart import embedding_model_tag, passages, retrieval
from search.smart.retrieval import Filters, RankedList, rrf_fuse
from search.smart.schemas import AyahRef, QueryPlan

from .conftest import CorpusFixture
from .openrouter_fakes import embedding_response, error_response, request_json, stub_vector

pytestmark = pytest.mark.django_db

DIMS = EMBEDDING_DIMENSIONS


@dataclass(frozen=True)
class PassageCorpus:
    corpus: CorpusFixture
    khawatir: list[Passage]
    recitation: list[Passage]

    @property
    def all(self) -> list[Passage]:
        return self.khawatir + self.recitation

    def holding(self, word: str) -> list[Passage]:
        """Passages whose stemmed text holds the stem of ``word``."""
        stem = stem_text(normalize_for_index(word))
        return [row for row in self.all if stem in stem_text(row.text_normalized).split()]


def make_passage(
    segment: Segment,
    text: str,
    *,
    ordinal: int,
    embed: bool = True,
    model_tag: str | None = None,
) -> Passage:
    """A passage row with the derived columns filled the way the builder does."""
    header = passages.header_for(segment)
    normalized = normalize_for_index(text)
    return Passage.objects.create(
        transcript=segment.transcript,
        segment=segment,
        surah=segment.surah_id,
        ayah_start=segment.ayah_start,
        ayah_end=segment.ayah_end,
        ordinal=ordinal,
        chunk_idx_start=0,
        chunk_idx_end=0,
        start_ms=0,
        end_ms=1000,
        word_count=len(normalized.split()),
        header=header,
        text=text,
        text_normalized=normalized,
        text_stem=stem_text(normalize_for_index(header) + " " + normalized),
        content_hash=passages.content_hash(header, normalized),
        embedding=stub_vector(normalized, DIMS) if embed else None,
        embedding_model=(model_tag or embedding_model_tag()) if embed else "",
        embedded_hash=passages.content_hash(header, normalized) if embed else "",
    )


@pytest.fixture
def passage_corpus(corpus: CorpusFixture, smart_settings: Settings) -> PassageCorpus:
    """Both fixture transcripts cut into passages and embedded with stub vectors."""
    smart_settings.SMART_EMBEDDING_DIMENSIONS = DIMS
    for segment in (corpus.khawatir, corpus.recitation):
        transcript = passages.transcripts_with_chunks().get(pk=segment.transcript.pk)
        passages.build_for_transcript(transcript, min_words=6, max_words=12)
    for row in Passage.objects.all():
        row.embedding = stub_vector(row.text_normalized, DIMS)
        row.embedding_model = embedding_model_tag()
        row.embedded_hash = row.content_hash
        row.save()
    return PassageCorpus(
        corpus=corpus,
        khawatir=list(Passage.objects.filter(segment=corpus.khawatir).order_by("ordinal")),
        recitation=list(Passage.objects.filter(segment=corpus.recitation).order_by("ordinal")),
    )


def _ids(hits: list[tuple[int, float]]) -> list[int]:
    return [pk for pk, _ in hits]


# --- lexical --------------------------------------------------------------------


def test_lexical_finds_the_passages_holding_the_word(passage_corpus: PassageCorpus) -> None:
    hits = retrieval.lexical_candidates("الصبر")

    assert set(_ids(hits)) == {row.pk for row in passage_corpus.holding("الصبر")}
    assert len(hits) >= 2


def test_lexical_recall_survives_clitics(passage_corpus: PassageCorpus) -> None:
    """A passage that only ever says بالصبر is found by الصبر, and vice versa."""
    row = make_passage(passage_corpus.corpus.khawatir, "نتحلى بالصبر عند الشدائد", ordinal=99)

    assert row.pk in _ids(retrieval.lexical_candidates("الصبر"))
    assert row.pk in _ids(retrieval.lexical_candidates("والصبر"))
    assert row.pk in _ids(retrieval.lexical_candidates("صبر"))


def test_lexical_ranks_passages_with_every_term_first(passage_corpus: PassageCorpus) -> None:
    both = make_passage(passage_corpus.corpus.khawatir, "الصبر والشكر جناحا الإيمان", ordinal=98)
    only = make_passage(passage_corpus.corpus.khawatir, "الشكر على النعمة واجب", ordinal=99)

    ids = _ids(retrieval.lexical_candidates("الصبر الشكر"))

    assert ids[0] == both.pk
    assert only.pk in ids


def test_a_query_of_stop_words_alone_finds_nothing(passage_corpus: PassageCorpus) -> None:
    assert retrieval.lexical_candidates("في من على") == []
    assert retrieval.lexical_candidates("") == []


def test_lexical_honours_the_filters(passage_corpus: PassageCorpus) -> None:
    # الْقَلْب appears in khawatir chunks 4, 9, 10 and in a recitation chunk.
    unfiltered = _ids(retrieval.lexical_candidates("القلب"))
    assert {row.segment_id for row in Passage.objects.filter(pk__in=unfiltered)} == {
        passage_corpus.corpus.khawatir.pk,
        passage_corpus.corpus.recitation.pk,
    }

    by_surah = _ids(retrieval.lexical_candidates("القلب", filters=Filters(surah=3)))
    assert by_surah and all(
        row.segment_id == passage_corpus.corpus.recitation.pk
        for row in Passage.objects.filter(pk__in=by_surah)
    )
    assert retrieval.lexical_candidates("القلب", filters=Filters(source_id=10**6)) == []


def test_lexical_respects_the_limit(passage_corpus: PassageCorpus) -> None:
    assert len(retrieval.lexical_candidates("القلب", limit=1)) == 1


# --- semantic -------------------------------------------------------------------


def test_semantic_returns_the_nearest_passage_first(passage_corpus: PassageCorpus) -> None:
    target = passage_corpus.khawatir[3]

    hits = retrieval.semantic_candidates(stub_vector(target.text_normalized, DIMS), limit=5)

    assert _ids(hits)[0] == target.pk
    assert hits[0][1] == pytest.approx(0.0, abs=1e-3)
    assert len(hits) == 5


def test_semantic_ignores_rows_embedded_under_another_model(
    passage_corpus: PassageCorpus,
) -> None:
    stale = make_passage(
        passage_corpus.corpus.khawatir, "مقطع بنموذج قديم", ordinal=99, model_tag="old/model@1024"
    )

    hits = retrieval.semantic_candidates(stub_vector(stale.text_normalized, DIMS))

    assert stale.pk not in _ids(hits)
    assert len(hits) == len(passage_corpus.all)


def test_semantic_honours_the_filters(passage_corpus: PassageCorpus) -> None:
    vector = stub_vector(passage_corpus.khawatir[0].text_normalized, DIMS)

    hits = retrieval.semantic_candidates(vector, filters=Filters(surah=3))

    assert set(_ids(hits)) == {row.pk for row in passage_corpus.recitation}


def _show(name: str) -> str:
    with connection.cursor() as cursor:
        cursor.execute(f"SHOW {name}")
        return str(cursor.fetchone()[0])


def test_hnsw_scan_widens_the_search_and_enables_iterative_scans(
    passage_corpus: PassageCorpus,
) -> None:
    # A vector operation must have loaded the extension before SHOW works.
    retrieval.semantic_candidates(stub_vector("x", DIMS), limit=1)

    with retrieval.hnsw_scan(500):
        assert _show("hnsw.ef_search") == "500"
        assert _show("hnsw.iterative_scan") == "relaxed_order"


@pytest.mark.parametrize(("depth", "expected"), [(5, "40"), (100, "100"), (5000, "1000")])
def test_hnsw_scan_clamps_the_depth(
    passage_corpus: PassageCorpus, depth: int, expected: str
) -> None:
    retrieval.semantic_candidates(stub_vector("x", DIMS), limit=1)

    with retrieval.hnsw_scan(depth):
        assert _show("hnsw.ef_search") == expected


# --- ayah anchored ----------------------------------------------------------------


def test_ayah_anchoring_keeps_the_segments_covering_the_verse(
    passage_corpus: PassageCorpus,
) -> None:
    hits = retrieval.ayah_anchored_candidates([AyahRef(surah=2, ayah=5)], None)

    assert _ids(hits) == [row.pk for row in passage_corpus.khawatir]
    assert retrieval.ayah_anchored_candidates([AyahRef(surah=2, ayah=50)], None) == []
    assert retrieval.ayah_anchored_candidates([], None) == []


def test_ayah_anchoring_orders_by_similarity_when_given_a_vector(
    passage_corpus: PassageCorpus,
) -> None:
    target = passage_corpus.khawatir[-1]

    hits = retrieval.ayah_anchored_candidates(
        [AyahRef(surah=2, ayah=5), AyahRef(surah=3, ayah=7)],
        stub_vector(target.text_normalized, DIMS),
    )

    assert _ids(hits)[0] == target.pk
    assert set(_ids(hits)) == {row.pk for row in passage_corpus.all}


# --- rrf ------------------------------------------------------------------------


def test_rrf_sums_reciprocal_ranks_and_records_where_each_id_ranked() -> None:
    fused = rrf_fuse([RankedList("a", [1, 2]), RankedList("b", [2, 3])], k=60)

    assert [pid for pid, _, _ in fused] == [2, 1, 3]
    assert fused[0][1] == pytest.approx(1 / 61 + 1 / 62)
    assert fused[0][2] == {"a": 2, "b": 1}
    assert fused[1][2] == {"a": 1}


def test_rrf_weights_a_list() -> None:
    fused = rrf_fuse([RankedList("a", [1], 2.0), RankedList("b", [2, 3]), RankedList("c", [2])])

    # 2/61 for id 1 beats 1/61 + 1/61 = 2/61? No — equal; the tie goes to the id seen first.
    assert [pid for pid, _, _ in fused] == [1, 2, 3]
    assert fused[0][1] == pytest.approx(fused[1][1])


def test_rrf_breaks_ties_by_first_appearance_then_id() -> None:
    assert [pid for pid, _, _ in rrf_fuse([RankedList("a", [7]), RankedList("b", [3])])] == [7, 3]
    assert [pid for pid, _, _ in rrf_fuse([RankedList("a", [3]), RankedList("b", [7])])] == [3, 7]
    # Equal scores, both first seen in list "a": the better rank there wins.
    assert [pid for pid, _, _ in rrf_fuse([RankedList("a", [9, 4]), RankedList("b", [4, 9])])] == [
        9,
        4,
    ]


def test_rrf_counts_a_repeated_id_once_and_honours_the_limit() -> None:
    fused = rrf_fuse([RankedList("a", [1, 1, 2, 3])], limit=2)

    assert [pid for pid, _, _ in fused] == [1, 2]
    assert fused[0][1] == pytest.approx(1 / 61)


# --- query_texts ------------------------------------------------------------------


def test_query_texts_puts_the_question_first_and_dedupes_in_index_form() -> None:
    plan = QueryPlan(
        intent="opinion",
        language="ar",
        topic_ar="الصبر",
        rewrites=["الصَّبر", " ", "فضل الصبر", "الصبر"],
        keywords=[],
        ayah_refs=[],
        surah_hint=None,
        answerable_from_corpus="likely",
    )

    assert retrieval.query_texts("الصبر", plan) == ["الصبر", "فضل الصبر"]
    assert retrieval.query_texts("  الصبر ", None) == ["الصبر"]


# --- retrieve -------------------------------------------------------------------


def _embed_stub(request: httpx.Request) -> httpx.Response:
    texts = request_json(request)["input"]
    return embedding_response([stub_vector(text.split("Query: ", 1)[-1], DIMS) for text in texts])


def test_retrieve_without_the_provider_is_lexical_only(passage_corpus: PassageCorpus) -> None:
    result = retrieval.retrieve("الصبر عند الصدمة", use_llm=False)

    assert [lst.name for lst in result.lists] == ["lexical:0"]
    assert result.lists[0].weight == retrieval.ORIGINAL_QUESTION_WEIGHT
    assert result.usage is None and result.warnings == []
    assert result.queries == ["الصبر عند الصدمة"]
    top = result.candidates[0]
    assert top.passage_id in {row.pk for row in passage_corpus.holding("الصبر")}
    assert top.header.startswith("خواطر البقرة")
    assert top.channel_ranks == {"lexical:0": 1}
    assert top.rrf > 0


def test_retrieve_embeds_every_query_once_and_fuses_all_channels(
    passage_corpus: PassageCorpus, openrouter: respx.MockRouter
) -> None:
    route = openrouter.post("/embeddings").mock(side_effect=_embed_stub)
    plan = QueryPlan(
        intent="tafseer",
        language="ar",
        topic_ar="الرحمة",
        rewrites=["الرحمة في قلوب المؤمنين"],
        keywords=["رحمة", "مؤمنين"],
        ayah_refs=[AyahRef(surah=2, ayah=3)],
        surah_hint=2,
        answerable_from_corpus="likely",
    )

    result = retrieval.retrieve("ماذا قال الشيخ عن الرحمة", plan)

    assert route.call_count == 1
    body = request_json(route.calls.last.request)
    assert len(body["input"]) == 2
    assert all(text.startswith("Instruct:") for text in body["input"])
    assert body["input"][0].endswith("ماذا قال الشيخ عن الرحمة")
    names = [lst.name for lst in result.lists]
    assert names == [
        "lexical:0",
        "lexical:1",
        "lexical:keywords",
        "semantic:0",
        "semantic:1",
        "ayah",
    ]
    weights = {lst.name: lst.weight for lst in result.lists}
    assert weights["lexical:0"] == weights["semantic:0"] == retrieval.ORIGINAL_QUESTION_WEIGHT
    assert weights["lexical:1"] == weights["semantic:1"] == weights["ayah"] == 1.0
    assert result.usage is not None and result.warnings == []
    assert result.candidates and len(result.candidates) <= retrieval.FUSED_LIMIT
    assert all(
        "semantic:0" in candidate.channel_ranks or "lexical:0" in candidate.channel_ranks
        or "ayah" in candidate.channel_ranks
        for candidate in result.candidates
    )


def test_retrieve_degrades_to_lexical_when_embedding_fails(
    passage_corpus: PassageCorpus, openrouter: respx.MockRouter
) -> None:
    route = openrouter.post("/embeddings").mock(return_value=error_response(500, "down"))

    result = retrieval.retrieve("الصبر")

    assert route.called
    assert [lst.name for lst in result.lists] == ["lexical:0"]
    assert len(result.warnings) == 1 and result.warnings[0].startswith("embed:")
    assert result.candidates


def test_retrieve_applies_the_filters_to_every_channel(
    passage_corpus: PassageCorpus, openrouter: respx.MockRouter
) -> None:
    openrouter.post("/embeddings").mock(side_effect=_embed_stub)

    result = retrieval.retrieve("القلب", filters=Filters(surah=3))

    recitation = {row.pk for row in passage_corpus.recitation}
    assert result.candidates
    assert {candidate.passage_id for candidate in result.candidates} <= recitation
