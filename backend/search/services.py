"""Search ranking for the Sha'rawy Archive: lexical, semantic and hybrid.

All ranking lives here; views stay thin (``SHAARAWY_PROJECT_PLAN.md``, Phase 3).

Three retrieval paths share one response shape:

``lexical``
    Meilisearch over the ``chunks`` index. Only ``text_normalized`` is
    searchable, and the query is passed through
    :func:`corpus.arabic.normalize_for_index` first, so a reader typing full
    diacritics or the "wrong" hamza gets the same hits as the canonical
    spelling (``CLAUDE.md`` rule 2).
``semantic``
    pgvector cosine distance over ``Chunk.embedding``, query embedded by
    :func:`corpus.embeddings.get_embedder` (the e5 ``query: `` prefix lives in
    the embedder, not here).
``hybrid``
    Reciprocal rank fusion (k=60) of the two ranked id lists. Default mode.

Independently of the three paths, a query that looks like an ayah reference
(``2:255``, ``٢:٢٥٥``, ``البقرة 255``, ``آية الكرسي``) resolves to exact Ayah
rows which are surfaced *above* the chunk results in ``ayah_matches``.

Chunk display text always keeps its diacritics; only the index/query form is
normalized.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import meilisearch
from django.conf import settings
from django.db import DatabaseError, connection, transaction
from django.db.models import QuerySet
from meilisearch.errors import MeilisearchApiError
from pgvector.django import CosineDistance

from corpus.arabic import normalize_for_index
from corpus.embeddings import get_embedder
from corpus.models import Chunk, SegmentKind
from quran.models import Ayah, Surah

from .ayah_names import ayah_for_name

__all__ = [
    "AyahMatch",
    "SearchIndexError",
    "SearchParameterError",
    "SearchResponse",
    "SearchResult",
    "chunks_index_name",
    "delete_segment_chunks",
    "ensure_chunks_index",
    "hnsw_scan",
    "index_chunks",
    "lexical_search",
    "nearest_chunks",
    "parse_ayah_reference",
    "rrf_merge",
    "search",
    "semantic_search",
]

logger = logging.getLogger(__name__)

# --- Tunables ----------------------------------------------------------------

CHUNKS_INDEX = "chunks"
"""Index name, before ``settings.MEILI_INDEX_PREFIX`` is applied."""

RRF_K = 60
"""Reciprocal rank fusion constant; 60 is the value from Cormack et al. 2009."""

SEARCH_MODES: tuple[str, ...] = ("lexical", "semantic", "hybrid")
DEFAULT_MODE = "hybrid"

DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 50
MAX_PAGE = 100
"""Deep pagination is a vector-scan amplifier: page N costs a LIMIT of
``N * page_size`` rows through the ANN index, so an unbounded ``page`` turns one
anonymous GET into a multi-million-row scan (API_CONTRACT.md amendment 2).
The cap bounds retrieval depth at ``MAX_PAGE * MAX_PAGE_SIZE``."""

CANDIDATE_POOL = 100
"""How deep each retrieval path goes before fusion and pagination."""

HNSW_MIN_EF_SEARCH = 40
"""pgvector's own default; never search *less* deeply than stock."""

HNSW_MAX_EF_SEARCH = 1000
"""Past this the index scan costs more than the sequential scan it replaces."""

INDEX_BATCH_SIZE = 1000
TASK_TIMEOUT_MS = 30_000

INDEX_SETTINGS: dict[str, Any] = {
    "searchableAttributes": ["text_normalized"],
    "filterableAttributes": ["surah", "kind", "ayah_start", "segment_id"],
    "sortableAttributes": ["surah", "start_ms"],
}


class SearchParameterError(ValueError):
    """A caller-supplied search parameter is invalid (maps to HTTP 400)."""


class SearchIndexError(RuntimeError):
    """A Meilisearch task did not succeed."""


# --- Response shape (API_CONTRACT.md, GET /api/search/) ----------------------


@dataclass(frozen=True)
class AyahMatch:
    """An exact Quran verse resolved from the query itself."""

    surah: int
    number: int
    text_uthmani: str
    surah_name_ar: str


@dataclass(frozen=True)
class SearchResult:
    """One retrieved chunk, with the display text (diacritics intact)."""

    chunk_id: int
    segment_id: int
    segment_title: str
    surah: int | None
    ayah_start: int | None
    ayah_end: int | None
    kind: str
    text: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class SearchResponse:
    """``total`` is the size of the ranked candidate set: Meilisearch's estimate
    in ``lexical`` mode, otherwise the number of candidates retrieved, which is
    capped by :data:`CANDIDATE_POOL`."""

    query: str
    mode: str
    ayah_matches: list[AyahMatch]
    results: list[SearchResult]
    page: int
    total: int


# --- Meilisearch plumbing ----------------------------------------------------


def chunks_index_name() -> str:
    """Prefixed name of the chunks index; the prefix isolates test runs."""
    return f"{settings.MEILI_INDEX_PREFIX}{CHUNKS_INDEX}"


@lru_cache(maxsize=4)
def _client_for(url: str, api_key: str) -> meilisearch.Client:
    return meilisearch.Client(url, api_key)


def meili_client() -> meilisearch.Client:
    """Client for the configured instance, cached per (url, key) pair so that
    overriding the settings in tests hands back a different client."""
    return _client_for(settings.MEILI_URL, settings.MEILI_MASTER_KEY)


def _wait(client: meilisearch.Client, task_info: Any) -> None:
    """Block until a Meilisearch task finishes; raise if it failed."""
    task = client.wait_for_task(task_info.task_uid, timeout_in_ms=TASK_TIMEOUT_MS)
    if task.status != "succeeded":
        raise SearchIndexError(f"Meilisearch task {task.uid} {task.status}: {task.error}")


def _index_missing(error: MeilisearchApiError) -> bool:
    return error.code == "index_not_found"


def ensure_chunks_index() -> None:
    """Create the chunks index if absent and (re)apply :data:`INDEX_SETTINGS`.

    Synchronous: returns only once Meilisearch has finished the tasks.
    """
    client = meili_client()
    name = chunks_index_name()
    try:
        client.get_index(name)
    except MeilisearchApiError as error:
        if not _index_missing(error):
            raise
        _wait(client, client.create_index(name, {"primaryKey": "id"}))
    _wait(client, client.index(name).update_settings(dict(INDEX_SETTINGS)))


def _document(chunk: Chunk) -> dict[str, Any]:
    segment = chunk.transcript.segment
    return {
        "id": chunk.pk,
        "segment_id": segment.pk,
        "segment_title": segment.title,
        "surah": segment.surah_id,
        "ayah_start": segment.ayah_start,
        "ayah_end": segment.ayah_end,
        "kind": segment.kind,
        "text": chunk.text,
        "text_normalized": chunk.text_normalized,
        "start_ms": chunk.start_ms,
        "end_ms": chunk.end_ms,
    }


def index_chunks(chunks: Iterable[Chunk]) -> int:
    """Upsert ``chunks`` into the Meilisearch index and return how many.

    Synchronous, batched, and idempotent — documents are keyed by chunk id, so
    re-indexing a segment overwrites rather than duplicates. Callers passing a
    plain iterable should have selected ``transcript__segment`` already; a
    queryset gets that for free here.
    """
    if isinstance(chunks, QuerySet):
        chunks = chunks.select_related("transcript__segment")
    documents = [_document(chunk) for chunk in chunks]
    if not documents:
        return 0
    client = meili_client()
    index = client.index(chunks_index_name())
    for task_info in index.add_documents_in_batches(
        documents, batch_size=INDEX_BATCH_SIZE, primary_key="id"
    ):
        _wait(client, task_info)
    return len(documents)


def delete_segment_chunks(segment_id: int) -> None:
    """Remove every indexed chunk of one segment. A missing index is a no-op."""
    client = meili_client()
    name = chunks_index_name()
    try:
        client.get_index(name)
    except MeilisearchApiError as error:
        if _index_missing(error):
            return
        raise
    _wait(client, client.index(name).delete_documents(filter=f"segment_id = {int(segment_id)}"))


# --- Retrieval ---------------------------------------------------------------


def _meili_filters(kind: str | None, surah: int | None) -> list[str]:
    filters: list[str] = []
    if kind:
        filters.append(f'kind = "{kind}"')
    if surah is not None:
        filters.append(f"surah = {int(surah)}")
    return filters


def lexical_search(
    query: str,
    *,
    kind: str | None = None,
    surah: int | None = None,
    limit: int = CANDIDATE_POOL,
) -> tuple[list[int], int]:
    """Meilisearch hits for ``query`` as ``(chunk ids in rank order, total)``.

    The query is normalized here, exactly as the indexed ``text_normalized``
    was. A missing index yields an empty result rather than an error, so search
    keeps working before the first pipeline run.

    ``matchingStrategy`` is ``all`` on purpose: with Meilisearch's default the
    engine drops query words until something matches, and in Arabic almost
    every word starts with the article ``ال``, so a two-word query drags the
    whole corpus back as prefix matches. Lexical stays precise; recall for
    loosely worded queries is the semantic path's job.
    """
    options: dict[str, Any] = {
        "limit": limit,
        "attributesToRetrieve": ["id"],
        "matchingStrategy": "all",
    }
    filters = _meili_filters(kind, surah)
    if filters:
        options["filter"] = filters
    index = meili_client().index(chunks_index_name())
    try:
        response = index.search(normalize_for_index(query), options)
    except MeilisearchApiError as error:
        if _index_missing(error):
            return [], 0
        raise
    hits = [int(hit["id"]) for hit in response["hits"]]
    return hits, int(response.get("estimatedTotalHits", len(hits)))


@contextmanager
def hnsw_scan(depth: int) -> Iterator[None]:
    """Run the enclosed block with an HNSW scan deep enough to fill ``depth``.

    An approximate index scan visits a fixed number of candidates
    (``hnsw.ef_search``, 40 by default) and *then* the rest of the plan applies
    whatever predicate sits above it. Anything filtered up there — most
    sharply ``/related/``'s "every segment but this one" — has its rows thrown
    away after the scan already committed to them, and comes back with fewer
    than ``LIMIT``, sometimes zero, with no error anywhere to say so. Two
    settings fix that:

    ``hnsw.ef_search``
        raised to ``depth``, so the scan starts out wide enough for the page
        being asked for, clamped to :data:`HNSW_MIN_EF_SEARCH` ..
        :data:`HNSW_MAX_EF_SEARCH`.
    ``hnsw.iterative_scan``
        ``relaxed_order``, which lets pgvector *keep going* when the filter
        eats the first batch instead of stopping at ``ef_search`` candidates.
        This is the setting that makes a selective filter correct rather than
        merely luckier.

    Both are ``SET LOCAL``, so they die with the transaction and never leak
    onto the next request sharing the connection — which is also why the
    queryset has to be **evaluated inside the block** (``list(...)``, not a
    lazy queryset returned out of it).

    ``iterative_scan`` arrived in pgvector 0.8; on an older server the SET is
    rolled back to the savepoint and the block runs with the wider
    ``ef_search`` alone, which is a smaller improvement rather than a failure.
    """
    ef_search = min(max(int(depth), HNSW_MIN_EF_SEARCH), HNSW_MAX_EF_SEARCH)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL hnsw.ef_search = %s", [ef_search])
        try:
            # Savepointed: a rejected SET would otherwise poison the whole
            # transaction, taking the query with it.
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute("SET LOCAL hnsw.iterative_scan = 'relaxed_order'")
        except DatabaseError:
            logger.warning(
                "hnsw.iterative_scan is unavailable (pgvector < 0.8); filtered "
                "semantic queries may return fewer rows than requested"
            )
        yield


def semantic_queryset(
    query: str,
    *,
    kind: str | None = None,
    surah: int | None = None,
    limit: int = CANDIDATE_POOL,
) -> QuerySet[Chunk]:
    """Chunks ordered by cosine distance to the embedded ``query``.

    Lazy on purpose — :func:`semantic_search` is what callers want. This one
    exists so a test can read the query plan without running it; evaluating it
    outside :func:`hnsw_scan` is the underfetch bug described there.
    """
    vector = get_embedder().embed_query(normalize_for_index(query))
    queryset = Chunk.objects.filter(embedding__isnull=False)
    if kind:
        queryset = queryset.filter(transcript__segment__kind=kind)
    if surah is not None:
        queryset = queryset.filter(transcript__segment__surah_id=surah)
    return _by_distance(queryset, vector, limit=limit)


def _by_distance(
    queryset: QuerySet[Chunk], vector: Sequence[float], *, limit: int
) -> QuerySet[Chunk]:
    """Order by the distance expression alone, so PostgreSQL can answer from
    the ``chunk_embedding_hnsw`` index instead of sorting the table."""
    return queryset.annotate(distance=CosineDistance("embedding", vector)).order_by("distance")[
        :limit
    ]


def nearest_chunks(
    queryset: QuerySet[Chunk], vector: Sequence[float], *, limit: int = CANDIDATE_POOL
) -> list[Chunk]:
    """``limit`` chunks of ``queryset`` nearest to ``vector``, closest first.

    ``queryset`` carries the filters; this adds the ordering and evaluates it
    inside :func:`hnsw_scan`. Callers that already have a vector rather than a
    query string — ``/related/``, which searches by a segment's centroid — come
    through here instead of assembling their own ANN queryset, which is what
    keeps the scan-depth fix in one place.
    """
    ordered = _by_distance(queryset, vector, limit=limit)
    with hnsw_scan(limit):
        return list(ordered)


def semantic_search(
    query: str,
    *,
    kind: str | None = None,
    surah: int | None = None,
    limit: int = CANDIDATE_POOL,
) -> list[Chunk]:
    """Nearest chunks to ``query`` by embedding, closest first."""
    ordered = semantic_queryset(query, kind=kind, surah=surah, limit=limit)
    with hnsw_scan(limit):
        return list(ordered)


def rrf_merge(ranked_lists: list[list[int]], k: int = RRF_K) -> list[int]:
    """Fuse ranked id lists by reciprocal rank fusion.

    ``score(d) = Σ 1 / (k + rank_i(d) + 1)`` over the lists that contain ``d``,
    with ``rank_i`` zero-based. Ties are broken by where the document was first
    seen (earlier list wins, then better rank), which is a total order because
    no two documents share a position — so the output is fully deterministic.
    Repeats within one list count once, at their first position.
    """
    scores: dict[int, float] = {}
    first_seen: dict[int, tuple[int, int]] = {}
    for list_index, ranked in enumerate(ranked_lists):
        for rank, document in enumerate(ranked):
            if document in first_seen and first_seen[document][0] == list_index:
                continue
            scores[document] = scores.get(document, 0.0) + 1.0 / (k + rank + 1)
            first_seen.setdefault(document, (list_index, rank))
    return sorted(scores, key=lambda document: (-scores[document], first_seen[document]))


# --- Ayah references ---------------------------------------------------------

_NUMERIC_REFERENCE_RE = re.compile(r"^(\d{1,3})\s*:\s*(\d{1,3})$")

# Words a reader wraps around a reference: "سورة البقرة آية 255" is the same
# request as "البقرة 255".
_REFERENCE_FILLERS = frozenset(
    normalize_for_index(word) for word in ("سورة", "آية", "الآية", "رقم", "من")
)


def _numeric_reference(normalized: str) -> tuple[int, int] | None:
    match = _NUMERIC_REFERENCE_RE.match(normalized)
    if match is None:
        return None
    return int(match[1]), int(match[2])


def _named_reference(normalized: str) -> tuple[int, int] | None:
    """Resolve ``<surah name> <ayah number>`` against ``Surah.name_ar_plain``,
    which the importer stores as ``normalize_for_index(name_ar)``."""
    tokens = [token for token in normalized.split() if token not in _REFERENCE_FILLERS]
    if len(tokens) < 2 or not tokens[-1].isdigit():
        return None
    name = " ".join(tokens[:-1])
    surah = Surah.objects.filter(name_ar_plain=name).values_list("number", flat=True).first()
    if surah is None:
        return None
    return surah, int(tokens[-1])


def parse_ayah_reference(q: str) -> list[Ayah]:
    """Resolve an ayah reference in ``q`` to the Ayah rows it names.

    Understands ``2:255`` (and its Arabic-Indic form ``٢:٢٥٥``), the curated
    famous names of :mod:`search.ayah_names` (``آية الكرسي``), and
    ``<surah name> <number>`` in either bare (``البقرة 255``) or spelled-out
    (``سورة البقرة آية 255``) form. Returns ``[]`` when nothing matches or when
    the reference points outside the corpus.
    """
    normalized = normalize_for_index(q)
    if not normalized:
        return []
    reference = (
        _numeric_reference(normalized)
        or ayah_for_name(normalized)
        or _named_reference(normalized)
    )
    if reference is None:
        return []
    surah, number = reference
    return list(Ayah.objects.select_related("surah").filter(surah_id=surah, number=number))


def _ayah_match(ayah: Ayah) -> AyahMatch:
    return AyahMatch(
        surah=ayah.surah_id,
        number=ayah.number,
        text_uthmani=ayah.text_uthmani,
        surah_name_ar=ayah.surah.name_ar,
    )


# --- The public entry point --------------------------------------------------


def _hydrate(chunk_ids: Sequence[int]) -> list[SearchResult]:
    """Load chunks by id and return them in the ranked order they came in."""
    if not chunk_ids:
        return []
    chunks = {
        chunk.pk: chunk
        for chunk in Chunk.objects.filter(pk__in=chunk_ids).select_related(
            "transcript__segment"
        )
    }
    results = []
    for chunk_id in chunk_ids:
        chunk = chunks.get(chunk_id)
        if chunk is None:  # indexed but since deleted from the database
            continue
        segment = chunk.transcript.segment
        results.append(
            SearchResult(
                chunk_id=chunk.pk,
                segment_id=segment.pk,
                segment_title=segment.title,
                surah=segment.surah_id,
                ayah_start=segment.ayah_start,
                ayah_end=segment.ayah_end,
                kind=segment.kind,
                text=chunk.text,
                start_ms=chunk.start_ms,
                end_ms=chunk.end_ms,
            )
        )
    return results


def search(
    query: str,
    *,
    mode: str = DEFAULT_MODE,
    kind: str | None = None,
    surah: int | None = None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> SearchResponse:
    """Run a search and return one page of results plus any ayah matches.

    Raises :class:`SearchParameterError` for an unusable query, an unknown
    ``mode``/``kind``, or out-of-range pagination.
    """
    if mode not in SEARCH_MODES:
        raise SearchParameterError(f"mode must be one of {', '.join(SEARCH_MODES)}")
    if kind and kind not in SegmentKind.values:
        raise SearchParameterError(f"kind must be one of {', '.join(SegmentKind.values)}")
    if page < 1:
        raise SearchParameterError("page must be 1 or greater")
    if page > MAX_PAGE:
        raise SearchParameterError(f"page must be {MAX_PAGE} or less")
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        raise SearchParameterError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")
    if not normalize_for_index(query):
        raise SearchParameterError("query must contain searchable text")

    ayah_matches = [_ayah_match(ayah) for ayah in parse_ayah_reference(query)]
    # Bounded by MAX_PAGE * MAX_PAGE_SIZE, which is what keeps one request from
    # asking the vector index for millions of rows.
    depth = max(CANDIDATE_POOL, page * page_size)

    if mode == "lexical":
        ranked, total = lexical_search(query, kind=kind, surah=surah, limit=depth)
    elif mode == "semantic":
        ranked = [chunk.pk for chunk in semantic_search(query, kind=kind, surah=surah, limit=depth)]
        total = len(ranked)
    else:
        lexical_ids, _ = lexical_search(query, kind=kind, surah=surah, limit=depth)
        semantic_ids = [
            chunk.pk for chunk in semantic_search(query, kind=kind, surah=surah, limit=depth)
        ]
        ranked = rrf_merge([lexical_ids, semantic_ids])
        total = len(ranked)

    start = (page - 1) * page_size
    return SearchResponse(
        query=query,
        mode=mode,
        ayah_matches=ayah_matches,
        results=_hydrate(ranked[start : start + page_size]),
        page=page,
        total=total,
    )
