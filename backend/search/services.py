"""Search ranking for the Sha'rawy Archive: strict phrase search over Meilisearch.

All ranking lives here; views stay thin (``SHAARAWY_PROJECT_PLAN.md``, Phase 3).

Search runs in two stages. Meilisearch is the candidate generator: the
``chunks`` index holds the ASR machine transcripts of audio segments and the
``ayahs`` index holds the canonical mushaf text, both searchable on their
``normalize_for_index`` form, and the query goes through
:func:`corpus.arabic.normalize_for_index` first so a reader typing full
diacritics or the "wrong" hamza gets the same hits as the canonical spelling
(``CLAUDE.md`` rule 2). :mod:`search.matching` is then the gate: a candidate
survives only when every query word occurs in its text consecutively and in
order, each within a typo budget set by the word's length (1-3 letters exact,
4-7 letters one edit, 8+ letters two). Survivors are ordered by edits used,
then by Meilisearch's rank. Rule 1 is respected structurally: mushaf text is
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

from corpus.arabic import light_stem, normalize_for_index
from corpus.models import Chunk, SegmentKind
from quran.models import Ayah, Surah

from . import matching
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

VERIFY_POOL = 1000
"""How many Meilisearch candidates the phrase verifier scans per query.

Equal to Meilisearch's default ``pagination.maxTotalHits`` (a larger ``limit``
is silently capped, so raising this means raising that setting too) and to
``MAX_PAGE * DEFAULT_PAGE_SIZE``, so every page the view can ask for is served
from one pool."""

INDEX_BATCH_SIZE = 1000
TASK_TIMEOUT_MS = 30_000

TYPO_TOLERANCE: dict[str, Any] = {
    "enabled": True,
    "minWordSizeForTypos": {
        # The same letter thresholds as search.matching (Meilisearch counts
        # characters, verified live on v1.15), so retrieval never withholds a
        # candidate the verifier would accept.
        "oneTypo": matching.ONE_TYPO_MIN_LETTERS,
        "twoTypos": matching.TWO_TYPOS_MIN_LETTERS,
    },
}

RANKING_RULES = ["words", "proximity", "typo", "attribute", "sort", "exactness"]
"""Meilisearch v1.15 rule names. ``proximity`` is promoted above ``typo`` so
that documents holding the query words adjacent and in order fill the
candidate pool before ones that merely contain them somewhere."""

CHUNK_TEXT_ATTRIBUTES = ["text_normalized"]
"""Chunk attributes the verifier checks."""

CHUNK_SEARCHABLE_ATTRIBUTES = ["text_normalized", "text_stem"]
"""What Meilisearch matches on, in weight order. ``text_stem`` holds the
light stem of every word (``بالصبر`` → ``صبر``) so that a stemmed query can
reach chunks where the word only occurs with a clitic; the verifier then
re-reads them against ``text_normalized`` and ranks such stem matches last."""

AYAH_TEXT_ATTRIBUTES = ["text_normalized", "text_imlaei_normalized"]
"""The mushaf is indexed in both its Uthmani and imlaei spellings: readers type
``السماوات`` and ``ابراهيم``, the Uthmani text says ``السموت`` and ``ابرهم``,
and a strict typo budget cannot bridge the second pair."""

INDEX_SETTINGS: dict[str, Any] = {
    "searchableAttributes": CHUNK_SEARCHABLE_ATTRIBUTES,
    "filterableAttributes": ["surah", "kind", "ayah_start", "segment_id"],
    "sortableAttributes": ["surah", "start_ms"],
    "typoTolerance": TYPO_TOLERANCE,
    "rankingRules": RANKING_RULES,
}

AYAH_INDEX_SETTINGS: dict[str, Any] = {
    "searchableAttributes": AYAH_TEXT_ATTRIBUTES,
    "filterableAttributes": ["surah"],
    "typoTolerance": TYPO_TOLERANCE,
    "rankingRules": RANKING_RULES,
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
    """``total`` is the number of chunks that passed phrase verification —
    exact while fewer than :data:`VERIFY_POOL` candidates came back, a lower
    bound once the pool saturates; ``verse_matches`` and ``ayah_matches`` are
    small fixed answer blocks that stay identical on every page."""

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
        "text_stem": matching.stem_words(chunk.text_normalized),
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
    nothing but the two normalized spellings and the citation."""
    return {
        "id": ayah.pk,
        "surah": ayah.surah_id,
        "number": ayah.number,
        "text_normalized": ayah.text_normalized,
        "text_imlaei_normalized": normalize_for_index(ayah.text_imlaei),
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
    """Ranked Ayah primary keys whose text contains ``query`` as a phrase.

    The same two stages as :func:`lexical_search`, over the ayahs index; the
    phrase may match either the Uthmani or the imlaei spelling. A missing
    index yields an empty result, so search keeps working before
    ``manage.py index_quran`` has ever run.
    """
    words = matching.parse_query(query)
    if not words:
        return []
    filters = [f"surah = {int(surah)}"] if surah is not None else []
    hits = _candidates(
        ayahs_index_name(),
        [word.text for word in words],
        filters=filters,
        attributes=AYAH_TEXT_ATTRIBUTES,
    )
    if hits is None:
        return []
    return _verify(hits, words, attributes=AYAH_TEXT_ATTRIBUTES)[:limit]


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


def _query_tokens(query: str) -> list[str]:
    """The query as index-form words — what both stages match on."""
    return [word.text for word in matching.parse_query(query)]


def _stemmed_tokens(words: Sequence[matching.QueryWord]) -> list[str] | None:
    """The query with every non-strict word light-stemmed, or ``None`` when
    stemming changes nothing (then a second candidate query would only repeat
    the first)."""
    stemmed = [word.text if word.strict else light_stem(word.text) for word in words]
    return stemmed if stemmed != [word.text for word in words] else None


def _candidates(
    index_name: str,
    tokens: Sequence[str],
    *,
    filters: Sequence[str],
    attributes: Sequence[str],
) -> list[dict[str, Any]] | None:
    """Meilisearch's top :data:`VERIFY_POOL` hits for ``tokens``, each carrying
    ``id`` plus the text ``attributes`` the verifier needs; ``None`` when the
    index does not exist yet.

    The words are re-joined with single spaces rather than sent raw, so query
    syntax a reader might type (``"..."`` phrases, ``-word`` negation) is
    inert. ``matchingStrategy`` is ``all`` on purpose: with Meilisearch's
    default the engine drops query words until something matches, and in
    Arabic almost every word starts with the article ``ال``, so a two-word
    query drags the whole corpus back as prefix matches. Meilisearch only looks
    at the first ten words; the verifier checks all of them.
    """
    options: dict[str, Any] = {
        "limit": VERIFY_POOL,
        "attributesToRetrieve": ["id", *attributes],
        "matchingStrategy": "all",
    }
    if filters:
        options["filter"] = list(filters)
    index = meili_client().index(index_name)
    try:
        response = index.search(" ".join(tokens), options)
    except MeilisearchApiError as error:
        if _index_missing(error):
            return None
        raise
    return list(response["hits"])


def _verify(
    hits: Sequence[dict[str, Any]],
    words: Sequence[matching.QueryWord],
    *,
    attributes: Sequence[str],
) -> list[int]:
    """Ids of the ``hits`` that really contain the phrase, best first.

    A hit survives when :func:`search.matching.phrase_match` finds the query
    words consecutively and in order in any of its ``attributes``; survivors
    are ordered by stem matches used, then edits, then Meilisearch's own rank.
    """
    survivors: list[tuple[int, int, int, int]] = []
    for rank, hit in enumerate(hits):
        best: matching.PhraseMatch | None = None
        for attribute in attributes:
            match = matching.phrase_match(words, hit.get(attribute) or "")
            if match is not None and (best is None or match.cost < best.cost):
                best = match
        if best is not None:
            survivors.append((best.stems, best.typos, rank, int(hit["id"])))
    survivors.sort()
    return [document_id for _, _, _, document_id in survivors]


def lexical_search(
    query: str,
    *,
    kind: str | None = None,
    surah: int | None = None,
) -> tuple[list[int], int]:
    """Chunk ids whose transcript contains ``query`` as a phrase, best first,
    with the count of such chunks.

    Stage one asks Meilisearch for up to :data:`VERIFY_POOL` candidates that
    hold every query word, and — when light-stemming changes any unquoted word —
    up to :data:`VERIFY_POOL` more for the stemmed query, which reaches the
    ``text_stem`` attribute (``الصبر`` → ``صبر`` matches a chunk that only says
    ``بالصبر``). Stage two keeps only those where the words are consecutive, in
    order, and within their per-word typo budget or stem-equal; stem matches
    rank last. The count is exact while the pools did not fill and a lower
    bound when they did. A missing index yields an empty result rather than an
    error, so search keeps working before the first pipeline run.
    """
    words = matching.parse_query(query)
    if not words:
        return [], 0
    filters = _meili_filters(kind, surah)
    hits = _candidates(
        chunks_index_name(),
        [word.text for word in words],
        filters=filters,
        attributes=CHUNK_TEXT_ATTRIBUTES,
    )
    if hits is None:
        return [], 0
    stemmed = _stemmed_tokens(words)
    if stemmed is not None:
        seen = {hit["id"] for hit in hits}
        more = _candidates(
            chunks_index_name(), stemmed, filters=filters, attributes=CHUNK_TEXT_ATTRIBUTES
        )
        hits.extend(hit for hit in more or [] if hit["id"] not in seen)
    ids = _verify(hits, words, attributes=CHUNK_TEXT_ATTRIBUTES)
    return ids, len(ids)


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

SUGGEST_SNIPPET_CHARS = 80
"""Longest suggestion shown, cut back to a word boundary."""


def _snippet(text: str, limit: int = SUGGEST_SNIPPET_CHARS) -> str:
    """The first ``limit`` characters of ``text``, ending on a whole word.

    A suggestion becomes the next query verbatim, and strict search would
    reject a snippet whose last word was cut in half.
    """
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text.rfind(" ", 0, limit + 1)
    return (text[:cut] if cut > 0 else text[:limit]).strip()


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

    Meilisearch always matches the final word — the one still being typed —
    as a prefix, so suggestions need no verification. ``matchingStrategy`` is
    ``all`` here too: with ``last`` a rare word that matches one chunk is
    dropped from the query and every chunk comes back as a suggestion.
    Returns display text (with diacritics) from matching chunks, deduplicated,
    optionally filtered by ``kind``.
    """
    normalized = normalize_for_index(query)
    if len(normalized) < SUGGEST_MIN_CHARS:
        return []
    options: dict[str, Any] = {
        "limit": limit * 3,
        "attributesToRetrieve": ["text"],
        "matchingStrategy": "all",
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
        short = _snippet(text)
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
    index stores only the normalized forms.
    """
    normalized = normalize_for_index(query)
    if len(normalized) < SUGGEST_MIN_CHARS:
        return []
    options: dict[str, Any] = {
        "limit": limit * 3,
        "attributesToRetrieve": ["id"],
        "matchingStrategy": "all",
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
        short = _snippet(match.text_uthmani)
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
    Canonical text and ASR output are never mixed under one ``kind``. Both
    corpora are searched as a strict phrase (see :func:`lexical_search`).

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
    if not _query_tokens(query):
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

    # Every page is a slice of one verified pool of VERIFY_POOL candidates
    # (API_CONTRACT.md amendments 2 and 10).
    ranked, total = lexical_search(query, kind=kind, surah=surah)

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
