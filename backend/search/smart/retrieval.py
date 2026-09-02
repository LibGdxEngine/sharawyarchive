"""Hybrid retrieval over :class:`search.models.Passage`.

Three channels, all returning passage ids best-first:

* **lexical** — Postgres full-text search on the light-stemmed ``text_stem``
  column (the ``simple`` config: stemming and stop words are ours, see
  :func:`corpus.arabic.stem_text`), all-terms first, then any-term;
* **semantic** — pgvector cosine distance over the HNSW index, evaluated
  inside :func:`hnsw_scan` so a filtered scan cannot silently underfetch;
* **ayah-anchored** — passages of segments covering the ayahs the planner
  extracted, ordered by similarity to the question.

The lists are fused by reciprocal rank (:func:`rrf_fuse`); the lists derived
from the reader's own words weigh double. Everything is deterministic for a
given database state.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field

from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db import DatabaseError, connection, transaction
from django.db.models import F, Q, QuerySet
from pgvector.django import CosineDistance

from corpus.arabic import normalize_for_index, stem_text
from search.models import Passage

from . import embedding_model_tag, llm
from .schemas import AyahRef, Candidate, QueryPlan, Usage

__all__ = [
    "Filters",
    "RankedList",
    "Retrieval",
    "ayah_anchored_candidates",
    "hnsw_scan",
    "lexical_candidates",
    "query_texts",
    "retrieve",
    "rrf_fuse",
    "semantic_candidates",
]

logger = logging.getLogger(__name__)

LEXICAL_LIMIT = 50
SEMANTIC_LIMIT = 50
AYAH_LIMIT = 30
FUSED_LIMIT = 40
RRF_K = 60
ORIGINAL_QUESTION_WEIGHT = 2.0
HNSW_MIN_EF_SEARCH = 40
HNSW_MAX_EF_SEARCH = 1000


@dataclass(frozen=True)
class Filters:
    """Optional narrowing of every channel."""

    surah: int | None = None
    source_id: int | None = None

    def as_dict(self) -> dict[str, int | None]:
        return {"surah": self.surah, "source_id": self.source_id}


NO_FILTERS = Filters()


@dataclass
class RankedList:
    name: str
    ids: list[int]
    weight: float = 1.0


@dataclass
class Retrieval:
    candidates: list[Candidate]
    lists: list[RankedList] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    usage: Usage | None = None
    warnings: list[str] = field(default_factory=list)


def _filtered(queryset: QuerySet[Passage], filters: Filters) -> QuerySet[Passage]:
    if filters.surah is not None:
        queryset = queryset.filter(surah=filters.surah)
    if filters.source_id is not None:
        queryset = queryset.filter(segment__source_id=filters.source_id)
    return queryset


@contextmanager
def hnsw_scan(depth: int) -> Iterator[None]:
    """Run the enclosed block with an HNSW scan deep enough to fill ``depth``.

    An approximate index scan visits ``hnsw.ef_search`` candidates (40 by
    default) and only then applies the plan's filters, so a filtered query
    can come back short — even empty — with no error. ``ef_search`` is raised
    to ``depth`` (clamped) and ``hnsw.iterative_scan`` set to
    ``relaxed_order`` so pgvector keeps scanning when a filter eats the first
    batch. Both are ``SET LOCAL`` and die with the transaction, which is why
    the queryset must be **evaluated inside** the block. On a pgvector older
    than 0.8 the second SET is rolled back to its savepoint and the block runs
    with the wider ``ef_search`` alone.
    """
    ef_search = min(max(int(depth), HNSW_MIN_EF_SEARCH), HNSW_MAX_EF_SEARCH)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL hnsw.ef_search = %s", [ef_search])
        try:
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute("SET LOCAL hnsw.iterative_scan = 'relaxed_order'")
        except DatabaseError:
            logger.warning(
                "hnsw.iterative_scan unavailable (pgvector < 0.8); filtered scans may underfetch"
            )
        yield


def lexical_candidates(
    text: str, *, filters: Filters = NO_FILTERS, limit: int = LEXICAL_LIMIT
) -> list[tuple[int, float]]:
    """Passages whose stemmed text matches ``text``, best rank first.

    Two rounds over the GIN index: passages holding **every** stem, then, to
    fill up to ``limit``, passages holding **any** stem. Ranking is
    ``ts_rank_cd`` (cover density), which rewards more query terms sitting
    closer together. Stop words vanish on both sides; a query made only of
    them yields nothing.
    """
    stems = stem_text(normalize_for_index(text)).split()
    if not stems:
        return []
    results: list[tuple[int, float]] = []
    seen: set[int] = set()
    joiners = (" & ", " | ") if len(stems) > 1 else (" & ",)
    for joiner in joiners:
        query = SearchQuery(joiner.join(stems), config="simple", search_type="raw")
        rows = (
            _filtered(Passage.objects.all(), filters)
            .filter(tsv=query)
            .annotate(rank=SearchRank(F("tsv"), query, cover_density=True))
            .order_by("-rank", "pk")
            .values_list("pk", "rank")[:limit]
        )
        for pk, rank in rows:
            if pk in seen:
                continue
            seen.add(pk)
            results.append((int(pk), float(rank)))
            if len(results) >= limit:
                return results
    return results


def semantic_candidates(
    vector: Sequence[float],
    *,
    filters: Filters = NO_FILTERS,
    limit: int = SEMANTIC_LIMIT,
    model_tag: str | None = None,
) -> list[tuple[int, float]]:
    """Passages nearest to ``vector`` by cosine distance, nearest first.

    Only rows embedded under the current model tag take part: a vector from
    another model or dimension is not comparable.
    """
    tag = model_tag or embedding_model_tag()
    queryset = (
        _filtered(Passage.objects.filter(embedding__isnull=False, embedding_model=tag), filters)
        .annotate(distance=CosineDistance("embedding", list(vector)))
        .order_by("distance", "pk")
        .values_list("pk", "distance")[:limit]
    )
    with hnsw_scan(max(limit, 100)):
        return [(int(pk), float(distance)) for pk, distance in queryset]


def ayah_anchored_candidates(
    refs: Sequence[AyahRef],
    vector: Sequence[float] | None,
    *,
    filters: Filters = NO_FILTERS,
    limit: int = AYAH_LIMIT,
) -> list[tuple[int, float]]:
    """Passages of segments that cover one of ``refs``.

    Ordered by similarity to ``vector`` when one is given (embedded rows only),
    otherwise by position in the corpus.
    """
    if not refs:
        return []
    covering = Q()
    for ref in refs:
        covering |= Q(surah=ref.surah, ayah_start__lte=ref.ayah, ayah_end__gte=ref.ayah)
    queryset = _filtered(Passage.objects.filter(covering), filters)
    if vector is None:
        rows = queryset.order_by("segment_id", "ordinal").values_list("pk", flat=True)[:limit]
        return [(int(pk), 0.0) for pk in rows]
    ranked = (
        queryset.filter(embedding__isnull=False, embedding_model=embedding_model_tag())
        .annotate(distance=CosineDistance("embedding", list(vector)))
        .order_by("distance", "pk")
        .values_list("pk", "distance")[:limit]
    )
    with hnsw_scan(max(limit, 100)):
        return [(int(pk), float(distance)) for pk, distance in ranked]


def rrf_fuse(
    lists: Sequence[RankedList], *, k: int = RRF_K, limit: int = FUSED_LIMIT
) -> list[tuple[int, float, dict[str, int]]]:
    """Reciprocal-rank fusion of ``lists``: ``score = Σ weight / (k + rank)``.

    Ranks are 1-based. Ties break by where a passage was first seen (earlier
    list, then better rank), then by id, so the output is a total order.
    Returns ``(passage_id, score, {list name: rank})`` best first.
    """
    scores: dict[int, float] = {}
    ranks: dict[int, dict[str, int]] = {}
    first_seen: dict[int, tuple[int, int]] = {}
    for list_index, ranked in enumerate(lists):
        seen: set[int] = set()
        for position, passage_id in enumerate(ranked.ids, start=1):
            if passage_id in seen:
                continue
            seen.add(passage_id)
            scores[passage_id] = scores.get(passage_id, 0.0) + ranked.weight / (k + position)
            ranks.setdefault(passage_id, {})[ranked.name] = position
            first_seen.setdefault(passage_id, (list_index, position))
    ordered = sorted(scores, key=lambda pid: (-scores[pid], first_seen[pid], pid))
    return [(pid, scores[pid], ranks[pid]) for pid in ordered[:limit]]


def query_texts(question: str, plan: QueryPlan | None) -> list[str]:
    """The reader's question followed by the planner's rewrites, deduplicated in index form."""
    texts: list[str] = []
    seen: set[str] = set()
    for candidate in [question, *(plan.rewrites if plan is not None else [])]:
        key = normalize_for_index(candidate)
        if key and key not in seen:
            seen.add(key)
            texts.append(candidate.strip())
    return texts


def retrieve(
    question: str,
    plan: QueryPlan | None = None,
    *,
    filters: Filters = NO_FILTERS,
    deadline: llm.Deadline | None = None,
    use_llm: bool = True,
    limit: int = FUSED_LIMIT,
) -> Retrieval:
    """Run every channel for the question and its rewrites and fuse the results.

    With ``use_llm`` off (or when the embedding call fails) retrieval is
    lexical only and the failure is recorded in ``warnings`` rather than
    raised: the pipeline degrades, it does not stop.
    """
    queries = query_texts(question, plan)
    lists: list[RankedList] = []
    warnings: list[str] = []
    usage: Usage | None = None

    for index, text in enumerate(queries):
        weight = ORIGINAL_QUESTION_WEIGHT if index == 0 else 1.0
        hits = lexical_candidates(text, filters=filters)
        if hits:
            lists.append(RankedList(f"lexical:{index}", [pk for pk, _ in hits], weight))
    if plan is not None and plan.keywords:
        hits = lexical_candidates(" ".join(plan.keywords), filters=filters)
        if hits:
            lists.append(RankedList("lexical:keywords", [pk for pk, _ in hits]))

    vectors: list[list[float]] = []
    if use_llm:
        try:
            vectors, usage = llm.embed(
                [llm.format_query(text) for text in queries], deadline=deadline
            )
        except llm.LLMError as error:
            warnings.append(f"embed: {error}")
            logger.warning("smart.retrieve: embedding failed, lexical only: %s", error)
    for index, vector in enumerate(vectors):
        weight = ORIGINAL_QUESTION_WEIGHT if index == 0 else 1.0
        hits = semantic_candidates(vector, filters=filters)
        if hits:
            lists.append(RankedList(f"semantic:{index}", [pk for pk, _ in hits], weight))

    if plan is not None and plan.ayah_refs:
        hits = ayah_anchored_candidates(
            plan.ayah_refs, vectors[0] if vectors else None, filters=filters
        )
        if hits:
            lists.append(RankedList("ayah", [pk for pk, _ in hits]))

    fused = rrf_fuse(lists, limit=limit)
    rows = {
        row.pk: row
        for row in Passage.objects.filter(pk__in=[pid for pid, _, _ in fused]).only(
            "id", "header", "text_normalized"
        )
    }
    candidates = [
        Candidate(
            passage_id=pid,
            header=rows[pid].header,
            text_normalized=rows[pid].text_normalized,
            rrf=score,
            channel_ranks=channel_ranks,
        )
        for pid, score, channel_ranks in fused
        if pid in rows
    ]
    return Retrieval(
        candidates=candidates, lists=lists, queries=queries, usage=usage, warnings=warnings
    )
