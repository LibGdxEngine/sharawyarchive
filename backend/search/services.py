"""Search ranking for the Sha'rawy Archive: lexical retrieval over Meilisearch.

All ranking lives here; views stay thin (``SHAARAWY_PROJECT_PLAN.md``, Phase 3).

Retrieval is Meilisearch over two indexes: the ``chunks`` index holds the ASR
machine transcripts of audio segments, and the ``ayahs`` index holds the
canonical mushaf text (``Ayah.text_normalized``). In both indexes only
``text_normalized`` is searchable, and the query is passed through
:func:`corpus.arabic.normalize_for_index` first, so a reader typing full
diacritics or the "wrong" hamza gets the same hits as the canonical spelling
(``CLAUDE.md`` rule 2). Rule 1 is respected structurally: mushaf text is
indexed from ``quran.Ayah`` rows only — ASR output never enters the ``ayahs``
index, and canonical text never enters ``chunks``.

Independently of retrieval, a query that looks like an ayah reference
(``2:255``, ``٢:٢٥٥``, ``البقرة 255``, ``آية الكرسي``) resolves to exact Ayah
rows which are surfaced *above* the chunk results in ``ayah_matches``;
full-text mushaf hits come back separately in ``verse_matches``.

Chunk display text always keeps its diacritics; only the index/query form is
normalized.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import meilisearch
from django.conf import settings
from django.db.models import QuerySet
from meilisearch.errors import MeilisearchApiError

from corpus.arabic import normalize_for_index
from corpus.models import Chunk, SegmentKind
from quran.models import Ayah, Surah

from .ayah_names import ayah_for_name

__all__ = [
    "AyahMatch",
    "SearchIndexError",
    "SearchParameterError",
    "SearchResponse",
    "SearchResult",
    "VerseMatch",
    "ayahs_index_name",
    "chunks_index_name",
    "delete_segment_chunks",
    "ensure_ayahs_index",
    "ensure_chunks_index",
    "index_ayahs",
    "index_chunks",
    "lexical_search",
    "parse_ayah_reference",
    "search",
    "suggest",
    "verse_search",
]

# --- Tunables ----------------------------------------------------------------

CHUNKS_INDEX = "chunks"
"""Chunks index name, before ``settings.MEILI_INDEX_PREFIX`` is applied."""

AYAHS_INDEX = "ayahs"
"""Ayahs index name, before ``settings.MEILI_INDEX_PREFIX`` is applied."""

DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 50
MAX_PAGE = 100
"""An unbounded ``page`` would turn one anonymous GET into an arbitrarily deep
retrieval (API_CONTRACT.md amendment 2). The cap bounds retrieval depth at
``MAX_PAGE * MAX_PAGE_SIZE``."""

CANDIDATE_POOL = 100
"""How deep retrieval goes before pagination."""

INDEX_BATCH_SIZE = 1000
TASK_TIMEOUT_MS = 30_000

INDEX_SETTINGS: dict[str, Any] = {
    "searchableAttributes": ["text_normalized"],
    "filterableAttributes": ["surah", "kind", "ayah_start", "segment_id"],
    "sortableAttributes": ["surah", "start_ms"],
}

AYAH_INDEX_SETTINGS: dict[str, Any] = {
    "searchableAttributes": ["text_normalized"],
    "filterableAttributes": ["surah"],
}

VERSE_MATCH_LIMIT = 8
"""Mushaf full-text matches are a fixed top excerpt, repeated on every page
like ``ayah_matches`` — deep paging happens over the chunk ``results`` only."""


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
class VerseMatch:
    """A mushaf verse whose normalized text matched the query.

    Unlike :class:`AyahMatch` this is full-text search over the canonical
    corpus (``Ayah.text_normalized``), not a reference parsed from the query.
    Display text keeps full Uthmani diacritics.
    """

    surah: int
    number: int
    text_uthmani: str
    surah_name_ar: str
    juz: int
    page: int


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
    """``total`` is Meilisearch's estimate of the matching document count
    over the chunks index; ``verse_matches`` and ``ayah_matches`` are small
    fixed answer blocks that stay identical on every page."""

    query: str
    ayah_matches: list[AyahMatch]
    verse_matches: list[VerseMatch]
    results: list[SearchResult]
    page: int
    total: int


# --- Meilisearch plumbing ----------------------------------------------------


def chunks_index_name() -> str:
    """Prefixed name of the chunks index; the prefix isolates test runs."""
    return f"{settings.MEILI_INDEX_PREFIX}{CHUNKS_INDEX}"


def ayahs_index_name() -> str:
    """Prefixed name of the ayahs (mushaf text) index."""
    return f"{settings.MEILI_INDEX_PREFIX}{AYAHS_INDEX}"


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


# --- Ayahs (mushaf text) index ------------------------------------------------


def ensure_ayahs_index() -> None:
    """Create the ayahs index if absent and (re)apply :data:`AYAH_INDEX_SETTINGS`.

    Synchronous: returns only once Meilisearch has finished the tasks.
    """
    client = meili_client()
    name = ayahs_index_name()
    try:
        client.get_index(name)
    except MeilisearchApiError as error:
        if not _index_missing(error):
            raise
        _wait(client, client.create_index(name, {"primaryKey": "id"}))
    _wait(client, client.index(name).update_settings(dict(AYAH_INDEX_SETTINGS)))


def _ayah_document(ayah: Ayah) -> dict[str, Any]:
    """The leanest possible document: the verse text is only needed at display
    time, and display rows are hydrated from the database, so the index holds
    nothing but the normalized form and its citation."""
    return {
        "id": ayah.pk,
        "surah": ayah.surah_id,
        "number": ayah.number,
        "text_normalized": ayah.text_normalized,
    }


def index_ayahs(ayahs: Iterable[Ayah]) -> int:
    """Upsert ``ayahs`` into the ayahs index and return how many.

    Synchronous, batched, and idempotent — documents are keyed by ayah id, so
    re-running ``manage.py index_quran`` overwrites rather than duplicates.
    """
    documents = [_ayah_document(ayah) for ayah in ayahs]
    if not documents:
        return 0
    client = meili_client()
    index = client.index(ayahs_index_name())
    for task_info in index.add_documents_in_batches(
        documents, batch_size=INDEX_BATCH_SIZE, primary_key="id"
    ):
        _wait(client, task_info)
    return len(documents)


def verse_search(
    query: str,
    *,
    surah: int | None = None,
    limit: int = VERSE_MATCH_LIMIT,
) -> list[int]:
    """Ranked Ayah primary keys whose normalized text matches ``query``.

    The query is normalized here, exactly as the indexed text was. A missing
    index yields an empty result, so search keeps working before
    ``manage.py index_quran`` has ever run.
    """
    options: dict[str, Any] = {
        "limit": limit,
        "attributesToRetrieve": ["id"],
        "matchingStrategy": "all",
    }
    if surah is not None:
        options["filter"] = [f"surah = {int(surah)}"]
    index = meili_client().index(ayahs_index_name())
    try:
        response = index.search(normalize_for_index(query), options)
    except MeilisearchApiError as error:
        if _index_missing(error):
            return []
        raise
    return [int(hit["id"]) for hit in response["hits"]]


def _hydrate_verses(ayah_ids: Sequence[int]) -> list[VerseMatch]:
    """Load ayahs by id and return them in the ranked order they came in."""
    if not ayah_ids:
        return []
    ayahs = {
        ayah.pk: ayah
        for ayah in Ayah.objects.filter(pk__in=ayah_ids).select_related("surah")
    }
    matches = []
    for ayah_id in ayah_ids:
        ayah = ayahs.get(ayah_id)
        if ayah is None:  # indexed but since deleted from the database
            continue
        matches.append(
            VerseMatch(
                surah=ayah.surah_id,
                number=ayah.number,
                text_uthmani=ayah.text_uthmani,
                surah_name_ar=ayah.surah.name_ar,
                juz=ayah.juz,
                page=ayah.page,
            )
        )
    return matches


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
    whole corpus back as prefix matches.
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


SUGGEST_LIMIT = 6
"""How many autocomplete suggestions to return."""

SUGGEST_MIN_CHARS = 2
"""Don't query Meilisearch for single-character input — noise."""


def suggest(query: str, kind: str | None = None, limit: int = SUGGEST_LIMIT) -> list[str]:
    """Autocomplete suggestions, scoped by the selected ``kind``.

    ``recitation`` suggests canonical mushaf text; ``khawatir`` suggests
    machine-transcript snippets from khawatir chunks only; ``None`` suggests
    from all chunks (the historical behaviour). The mushaf and ASR sources are
    never mixed when a ``kind`` is chosen.
    """
    if kind == SegmentKind.RECITATION:
        return _mushaf_suggest(query, limit)
    return _chunk_suggest(query, kind=kind, limit=limit)


def _chunk_suggest(query: str, *, kind: str | None, limit: int) -> list[str]:
    """Chunk-snippet suggestions from Meilisearch prefix matching.

    Uses ``matchingStrategy: "last"`` so the final word the user is still
    typing is matched as a prefix. Returns display text (with diacritics)
    from matching chunks, deduplicated, optionally filtered by ``kind``.
    """
    normalized = normalize_for_index(query)
    if len(normalized) < SUGGEST_MIN_CHARS:
        return []
    options: dict[str, Any] = {
        "limit": limit * 3,
        "attributesToRetrieve": ["text"],
        "matchingStrategy": "last",
    }
    if kind:
        options["filter"] = [f'kind = "{kind}"']
    index = meili_client().index(chunks_index_name())
    try:
        response = index.search(normalized, options)
    except MeilisearchApiError as error:
        if _index_missing(error):
            return []
        raise
    seen: set[str] = set()
    results: list[str] = []
    for hit in response["hits"]:
        text: str = hit.get("text", "")
        short = text[:80].strip()
        if short and short not in seen:
            seen.add(short)
            results.append(short)
        if len(results) >= limit:
            break
    return results


def _mushaf_suggest(query: str, limit: int) -> list[str]:
    """Autocomplete suggestions over the canonical mushaf text.

    Prefix-matches the last typed word like :func:`_chunk_suggest`, then
    hydrates the ranked ayah ids to their Uthmani display text — the ayahs
    index stores only the normalized form.
    """
    normalized = normalize_for_index(query)
    if len(normalized) < SUGGEST_MIN_CHARS:
        return []
    options: dict[str, Any] = {
        "limit": limit * 3,
        "attributesToRetrieve": ["id"],
        "matchingStrategy": "last",
    }
    index = meili_client().index(ayahs_index_name())
    try:
        response = index.search(normalized, options)
    except MeilisearchApiError as error:
        if _index_missing(error):
            return []
        raise
    ids = [int(hit["id"]) for hit in response["hits"]]
    seen: set[str] = set()
    results: list[str] = []
    for match in _hydrate_verses(ids):
        short = match.text_uthmani[:80].strip()
        if short and short not in seen:
            seen.add(short)
            results.append(short)
        if len(results) >= limit:
            break
    return results


def _mushaf_answer_blocks(
    query: str, *, surah: int | None
) -> tuple[list[AyahMatch], list[VerseMatch]]:
    """The two canonical-text answer blocks for a search.

    ``ayah_matches`` are exact references parsed from the query itself;
    ``verse_matches`` are full-text hits over the canonical mushaf text. The
    same verse is never returned in both.
    """
    ayah_matches = [_ayah_match(ayah) for ayah in parse_ayah_reference(query)]
    referenced = {(match.surah, match.number) for match in ayah_matches}
    verse_matches = [
        match
        for match in _hydrate_verses(
            verse_search(query, surah=surah, limit=VERSE_MATCH_LIMIT + len(referenced))
        )
        if (match.surah, match.number) not in referenced  # never show a verse twice
    ][:VERSE_MATCH_LIMIT]
    return ayah_matches, verse_matches


def search(
    query: str,
    *,
    kind: str | None = None,
    surah: int | None = None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> SearchResponse:
    """Run a search scoped by ``kind`` (``SegmentKind`` value or ``None``).

    ``kind`` now names the *content* to search, not just a chunk filter:
    ``recitation`` searches the canonical mushaf text only (``ayah_matches`` +
    ``verse_matches``, no ASR chunks); ``khawatir`` searches the machine
    transcripts only (``results``, no mushaf text); ``None`` returns both.
    Canonical text and ASR output are never mixed under one ``kind``.

    Raises :class:`SearchParameterError` for an unusable query, an unknown
    ``kind``, or out-of-range pagination.
    """
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

    if kind == SegmentKind.RECITATION:
        ayah_matches, verse_matches = _mushaf_answer_blocks(query, surah=surah)
        return SearchResponse(
            query=query,
            ayah_matches=ayah_matches,
            verse_matches=verse_matches,
            results=[],
            page=page,
            total=0,
        )

    # Bounded by MAX_PAGE * MAX_PAGE_SIZE (API_CONTRACT.md amendment 2).
    depth = max(CANDIDATE_POOL, page * page_size)
    ranked, total = lexical_search(query, kind=kind, surah=surah, limit=depth)

    if kind == SegmentKind.KHAWATIR:
        return SearchResponse(
            query=query,
            ayah_matches=[],
            verse_matches=[],
            results=_hydrate(ranked[(page - 1) * page_size : page * page_size]),
            page=page,
            total=total,
        )

    ayah_matches, verse_matches = _mushaf_answer_blocks(query, surah=surah)
    return SearchResponse(
        query=query,
        ayah_matches=ayah_matches,
        verse_matches=verse_matches,
        results=_hydrate(ranked[(page - 1) * page_size : page * page_size]),
        page=page,
        total=total,
    )
