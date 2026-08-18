"""Cluster chunk embeddings into candidate topics (Phase 7).

Nothing here is authoritative. A cluster label is a guess about what a group of
passages has in common, so every :class:`~corpus.models.Topic` this module
creates is ``is_published=False`` and stays invisible to readers until a human
opens the admin and publishes it. That gate is what makes a crude labeller
safe.

Clustering
----------
HDBSCAN when it is installed (it finds its own cluster count and calls the rest
noise), otherwise a deterministic seeded k-means over the L2-normalized
vectors — cosine similarity, which is the metric the embeddings were trained
for. The fallback is not an approximation of HDBSCAN, it is a different and
blunter tool: ``k = max(2, n // 8)``, Lloyd iterations until the assignments
stop moving, and any cluster left with fewer than
:data:`MIN_CLUSTER_MEMBERS` members is dropped rather than published as a
topic. Seeded from :data:`KMEANS_SEED`, so two runs over the same corpus
produce the same topics. No new dependency either way — numpy is already here
for the pipeline.

Labelling
---------
:func:`get_topic_labeler` mirrors :func:`corpus.embeddings.get_embedder`: the
interface is real, the backend is swappable. :class:`StubLabeler` picks the
most frequent informative token among the cluster's most central passages —
good enough to tell a reviewer what they are looking at.
:class:`LLMLabeler` documents the prompt the real thing will send and raises
:class:`NotImplementedError`, because a fabricated Arabic label is worse than
an obviously mechanical one.

Slugs are ASCII (``/api/topics/<slug:slug>/`` is an ASCII route) and namespaced
``auto-``: that prefix is what ``build_topics --rebuild`` deletes, so a
hand-made topic is never swept away by a re-run.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from django.conf import settings
from django.db import transaction
from django.utils.text import slugify

from .arabic import normalize_for_index
from .models import Chunk, ChunkTopic, Topic

__all__ = [
    "AUTO_SLUG_PREFIX",
    "BuildResult",
    "LLMLabeler",
    "NotEnoughChunks",
    "StubLabeler",
    "TopicLabel",
    "TopicLabeler",
    "build_topics",
    "get_topic_labeler",
]

logger = logging.getLogger(__name__)

AUTO_SLUG_PREFIX = "auto-"
"""Namespace for every machine-made topic; ``--rebuild`` deletes exactly these."""

MIN_CHUNKS = 10
"""Fewer embedded chunks than this and clustering is theatre, not analysis."""

MIN_CLUSTER_MEMBERS = 3
"""A "theme" the corpus returns to twice is a coincidence."""

CENTRAL_SAMPLE = 10
"""How many of a cluster's most central passages the labeller reads."""

CHUNKS_PER_CLUSTER = 8
"""k-means only: the divisor behind ``k = max(2, n // 8)``."""

KMEANS_SEED = 0
KMEANS_MAX_ITERATIONS = 50

MIN_TOKEN_CHARS = 3
"""Two-letter Arabic tokens are particles, not themes."""

_STOPWORDS: frozenset[str] = frozenset(
    normalize_for_index(word)
    for word in (
        "من", "في", "على", "عن", "إلى", "مع", "بين", "عند", "بعد", "قبل",
        "أن", "إن", "أنه", "إنه", "ما", "لا", "لم", "لن", "قد", "كل",
        "هذا", "هذه", "ذلك", "تلك", "الذي", "التي", "الذين", "هو", "هي", "هم",
        "كان", "كانت", "يكون", "ثم", "بل", "لكن", "أو", "يا", "كما", "حتى",
        "له", "لها", "به", "بها", "عليه", "عليها", "منه", "منها", "فيه", "فيها",
        "قال", "قلت", "يقول", "نقول", "إذا", "إذ", "لأن", "لكي", "وقد", "وما",
    )
)
"""Arabic function words, normalized. Deliberately small: over-filtering hides
the words that actually distinguish one cluster from another."""

_TRANSLITERATION = {
    "ا": "a", "ب": "b", "ت": "t", "ث": "th", "ج": "j", "ح": "h", "خ": "kh",
    "د": "d", "ذ": "dh", "ر": "r", "ز": "z", "س": "s", "ش": "sh", "ص": "s",
    "ض": "d", "ط": "t", "ظ": "z", "ع": "a", "غ": "gh", "ف": "f", "ق": "q",
    "ك": "k", "ل": "l", "م": "m", "ن": "n", "ه": "h", "و": "w", "ي": "y",
    "ء": "", "ﻻ": "la",
}
"""Arabic → ASCII for slugs only. Not a transliteration scheme anybody should
read: it exists because the topic route is ``<slug:slug>``, which is ASCII."""

FALLBACK_SLUG = "topic"
FALLBACK_NAME = "موضوع بلا تسمية"


class NotEnoughChunks(RuntimeError):
    """The corpus does not hold enough embedded chunks to cluster."""


@dataclass(frozen=True)
class TopicLabel:
    """What a labeller decides a cluster is about. ``slug`` is bare ASCII;
    :func:`build_topics` adds the ``auto-`` namespace and resolves collisions."""

    slug: str
    name_ar: str
    description_ar: str


@dataclass(frozen=True)
class BuildResult:
    """One ``build_topics`` run, for the command's summary."""

    algorithm: str
    labeler: str
    topics: list[Topic]
    chunks_clustered: int
    chunks_considered: int
    topics_deleted: int


# --- Labelling ---------------------------------------------------------------


class TopicLabeler(Protocol):
    def label(self, texts: Sequence[str]) -> TopicLabel: ...


def ascii_slug(token: str) -> str:
    """A routable ASCII slug for an Arabic token, or ``''`` if nothing survives."""
    latin = "".join(_TRANSLITERATION.get(char, char) for char in token)
    return slugify(latin)


class StubLabeler:
    """Name a cluster after the most frequent informative word in it.

    Frequency over the central passages only, counted on the normalized form
    (rule 2) so spelling variants collapse, while the display name keeps the
    surface form with its diacritics. Ties go to the token seen first, which
    makes the label deterministic for a deterministic cluster.
    """

    def label(self, texts: Sequence[str]) -> TopicLabel:
        counts: Counter[str] = Counter()
        surface: dict[str, str] = {}
        for text in texts:
            for raw in text.split():
                token = normalize_for_index(raw)
                if len(token) < MIN_TOKEN_CHARS or token in _STOPWORDS:
                    continue
                counts[token] += 1
                surface.setdefault(token, raw)
        if not counts:
            return TopicLabel(
                slug=FALLBACK_SLUG,
                name_ar=FALLBACK_NAME,
                description_ar=_description(FALLBACK_NAME),
            )
        token, _ = counts.most_common(1)[0]
        name_ar = surface[token]
        return TopicLabel(
            slug=ascii_slug(token) or FALLBACK_SLUG,
            name_ar=name_ar,
            description_ar=_description(name_ar),
        )


def _description(name_ar: str) -> str:
    return f"مقاطع متقاربة دلاليًا حول: {name_ar}. تسمية آلية بانتظار المراجعة."


class LLMLabeler:
    """The intended labeller: an LLM reads the central passages and names them.

    Unimplemented on purpose. The interface is settled and
    :func:`get_topic_labeler` will hand it out as soon as a backend exists, but
    until then there is nothing to call — and inventing an Arabic label for a
    religious corpus without a model behind it would be exactly the failure the
    ``is_published`` gate is there to prevent.
    """

    PROMPT = (
        "أنت مفهرس لأرشيف خواطر الشيخ محمد متولي الشعراوي.\n"
        "فيما يلي مقاطع نصية متقاربة دلاليًا من الأرشيف (نص آلي من تفريغ صوتي، "
        "وليس نص قرآن).\n"
        "اقترح عنوانًا عربيًا قصيرًا (كلمتان أو ثلاث) للموضوع الجامع بينها، "
        "ووصفًا من جملة واحدة، ومعرّفًا لاتينيًا بالحروف الصغيرة.\n"
        "إن لم تجمعها فكرة واحدة فاكتب العنوان: غير واضح.\n"
        'أجب بصيغة JSON: {"slug": ..., "name_ar": ..., "description_ar": ...}\n\n'
        "المقاطع:"
    )
    """Documented, not sent: the central passages are appended one per line and
    the JSON reply is parsed into a :class:`TopicLabel`."""

    def label(self, texts: Sequence[str]) -> TopicLabel:
        raise NotImplementedError(
            "no LLM backend is wired up yet; run with the default stub labeler "
            "and review the labels in the admin before publishing"
        )


def get_topic_labeler() -> TopicLabeler:
    """The configured labeller (``settings.TOPIC_LABELER``, default ``stub``)."""
    backend = getattr(settings, "TOPIC_LABELER", "stub")
    if backend == "stub":
        return StubLabeler()
    if backend == "llm":
        return LLMLabeler()
    raise ValueError(f"Unknown TOPIC_LABELER: {backend!r}")


# --- Clustering --------------------------------------------------------------


def _unit(vectors: np.ndarray) -> np.ndarray:
    """L2-normalize the rows, so a dot product *is* the cosine similarity."""
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


def _kmeans(unit: np.ndarray) -> list[list[int]]:
    """Seeded spherical k-means. Returns the member row indices per cluster."""
    count = len(unit)
    k = min(max(2, count // CHUNKS_PER_CLUSTER), count)
    rng = np.random.RandomState(KMEANS_SEED)
    centroids = unit[rng.choice(count, size=k, replace=False)].copy()
    assignments = np.full(count, -1)
    for _ in range(KMEANS_MAX_ITERATIONS):
        nearest = np.argmax(unit @ centroids.T, axis=1)
        if np.array_equal(nearest, assignments):
            break
        assignments = nearest
        for cluster in range(k):
            members = unit[assignments == cluster]
            if len(members):  # an emptied centroid keeps its place
                centroids[cluster] = _unit(members.mean(axis=0, keepdims=True))[0]
    return [np.flatnonzero(assignments == cluster).tolist() for cluster in range(k)]


def _hdbscan(unit: np.ndarray, module: object) -> list[list[int]]:
    labels = module.HDBSCAN(  # type: ignore[attr-defined]
        min_cluster_size=MIN_CLUSTER_MEMBERS, metric="euclidean"
    ).fit_predict(unit)
    return [
        np.flatnonzero(labels == label).tolist()
        for label in sorted(set(int(value) for value in labels) - {-1})
    ]


def cluster_vectors(vectors: np.ndarray) -> tuple[str, list[list[int]]]:
    """Group row indices of ``vectors``; returns ``(algorithm, clusters)``.

    Clusters below :data:`MIN_CLUSTER_MEMBERS` are dropped, and the rest come
    back largest first (ties by first member) so the output order does not
    depend on the clustering library's internals.
    """
    unit = _unit(vectors)
    try:
        import hdbscan
    except ImportError:
        algorithm, clusters = "kmeans", _kmeans(unit)
    else:
        algorithm, clusters = "hdbscan", _hdbscan(unit, hdbscan)
    kept = [members for members in clusters if len(members) >= MIN_CLUSTER_MEMBERS]
    kept.sort(key=lambda members: (-len(members), members[0]))
    return algorithm, kept


def _centrality(unit: np.ndarray, members: Sequence[int]) -> list[float]:
    """Cosine similarity of each member to its cluster's centroid."""
    centroid = _unit(unit[list(members)].mean(axis=0, keepdims=True))[0]
    return (unit[list(members)] @ centroid).tolist()


# --- Building ----------------------------------------------------------------


def _load_vectors() -> tuple[list[int], np.ndarray]:
    rows = list(
        Chunk.objects.filter(embedding__isnull=False)
        .order_by("pk")
        .values_list("pk", "embedding")
    )
    ids = [int(pk) for pk, _ in rows]
    vectors = np.asarray([vector for _, vector in rows], dtype=float)
    return ids, vectors


def _unique_slug(base: str, taken: set[str]) -> str:
    slug = f"{AUTO_SLUG_PREFIX}{base}"
    candidate, suffix = slug, 1
    while candidate in taken:
        suffix += 1
        candidate = f"{slug}-{suffix}"
    taken.add(candidate)
    return candidate


@transaction.atomic
def build_topics(*, min_chunks: int = MIN_CHUNKS, rebuild: bool = False) -> BuildResult:
    """Cluster every embedded chunk and create one unpublished topic per cluster.

    ``rebuild`` drops the existing ``auto-`` topics first, which is the only
    idempotent way to run this: without it a second run adds a second set of
    topics (with ``-2`` suffixed slugs) rather than updating the first.

    Raises :class:`NotEnoughChunks` when the corpus holds fewer than
    ``min_chunks`` embedded chunks.
    """
    auto = Topic.objects.filter(slug__startswith=AUTO_SLUG_PREFIX)
    deleted = 0
    if rebuild:
        deleted = auto.count()
        auto.delete()

    ids, vectors = _load_vectors()
    if len(ids) < min_chunks:
        raise NotEnoughChunks(
            f"only {len(ids)} embedded chunk(s); {min_chunks} are needed to cluster. "
            "Run the pipeline's embed stage first, or lower --min-chunks."
        )

    algorithm, clusters = cluster_vectors(vectors)
    unit = _unit(vectors)
    labeler = get_topic_labeler()
    taken = set(Topic.objects.values_list("slug", flat=True))

    created: list[Topic] = []
    clustered = 0
    for members in clusters:
        ranked = sorted(
            zip(members, _centrality(unit, members), strict=True),
            key=lambda pair: (-pair[1], pair[0]),
        )
        central_ids = [ids[row] for row, _ in ranked[:CENTRAL_SAMPLE]]
        texts = _texts_for(central_ids)
        label = labeler.label(texts)
        topic = Topic.objects.create(
            slug=_unique_slug(label.slug, taken),
            name_ar=label.name_ar,
            description_ar=label.description_ar,
            is_published=False,
        )
        ChunkTopic.objects.bulk_create(
            ChunkTopic(chunk_id=ids[row], topic=topic, score=float(score))
            for row, score in ranked
        )
        created.append(topic)
        clustered += len(ranked)

    logger.info(
        "build_topics: %s clusters from %s chunks via %s", len(created), len(ids), algorithm
    )
    return BuildResult(
        algorithm=algorithm,
        labeler=type(labeler).__name__,
        topics=created,
        chunks_clustered=clustered,
        chunks_considered=len(ids),
        topics_deleted=deleted,
    )


def _texts_for(chunk_ids: Sequence[int]) -> list[str]:
    """Display texts of ``chunk_ids``, in the order given (most central first)."""
    by_id = dict(Chunk.objects.filter(pk__in=chunk_ids).values_list("pk", "text"))
    return [by_id[chunk_id] for chunk_id in chunk_ids if chunk_id in by_id]
