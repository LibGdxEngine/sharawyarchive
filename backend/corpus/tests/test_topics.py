"""Clustering chunk embeddings into candidate topics (``corpus.topics``).

The fixture is 40 chunks in three groups of identical text. Identical text
means an identical stub embedding (see :class:`corpus.embeddings.StubEmbedder`),
so the groups are exactly separable and any clustering worth shipping has to
find them — which is the point: this suite tests the plumbing around the
algorithm, not the algorithm.
"""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from pytest_django.fixtures import Settings

from api.tests.factories import make_audio_asset
from corpus import topics
from corpus.arabic import normalize_for_index
from corpus.embeddings import StubEmbedder
from corpus.models import (
    Chunk,
    ChunkTopic,
    Segment,
    SegmentKind,
    Source,
    Topic,
    Transcript,
)

pytestmark = pytest.mark.django_db

GROUP_TEXTS = [
    "الصَّبْرُ عِنْدَ الصَّدْمَةِ الْأُولَى وَالصَّبْرُ مِفْتَاحُ الْفَرَجِ",
    "الرَّحْمَةُ فِي قُلُوبِ الْمُؤْمِنِينَ رَحْمَةٌ لَا تَنْقَطِعُ",
    "الْعِلْمُ نُورٌ يَهْدِي الْقَلْبَ وَالْعِلْمُ مِيرَاثُ الْأَنْبِيَاءِ",
]
GROUP_SIZE = 13
CHUNK_MS = 30_000


def build_clusters(size: int = GROUP_SIZE) -> list[Chunk]:
    """``size`` copies of each group text, embedded. 39 chunks by default."""
    source = Source.objects.create(title="التلفزيون المصري", kind="tv")
    segment = Segment.objects.create(
        source=source,
        kind=SegmentKind.KHAWATIR,
        audio=make_audio_asset(),
        duration_ms=CHUNK_MS * size * len(GROUP_TEXTS),
        title="خواطر",
    )
    transcript = Transcript.objects.create(
        segment=segment, engine="stub", raw_text="", text_normalized=""
    )
    texts = [text for text in GROUP_TEXTS for _ in range(size)]
    chunks = Chunk.objects.bulk_create(
        Chunk(
            transcript=transcript,
            idx=index,
            text=text,
            text_normalized=normalize_for_index(text),
            start_ms=index * CHUNK_MS,
            end_ms=(index + 1) * CHUNK_MS,
        )
        for index, text in enumerate(texts)
    )
    vectors = StubEmbedder().embed_passages([chunk.text_normalized for chunk in chunks])
    for chunk, vector in zip(chunks, vectors, strict=True):
        chunk.embedding = vector
    Chunk.objects.bulk_update(chunks, ["embedding"])
    return chunks


@pytest.fixture
def clusters(db: None) -> list[Chunk]:
    return build_clusters()


# --- Labelling ---------------------------------------------------------------


def test_the_stub_labeler_picks_the_repeated_word() -> None:
    label = topics.StubLabeler().label(GROUP_TEXTS[:1] * 3)

    assert normalize_for_index(label.name_ar) == "الصبر"
    assert label.slug == "alsbr"  # ASCII: the topic route is <slug:slug>
    assert "الصبر" in normalize_for_index(label.description_ar)


def test_the_stub_labeler_skips_function_words() -> None:
    label = topics.StubLabeler().label(["في في في على على الصدق"] * 2)

    assert normalize_for_index(label.name_ar) == "الصدق"


def test_the_stub_labeler_falls_back_when_nothing_is_informative() -> None:
    label = topics.StubLabeler().label(["في على من"])

    assert (label.slug, label.name_ar) == (topics.FALLBACK_SLUG, topics.FALLBACK_NAME)


def test_the_llm_labeler_is_an_interface_not_an_implementation() -> None:
    with pytest.raises(NotImplementedError):
        topics.LLMLabeler().label(GROUP_TEXTS)
    assert "JSON" in topics.LLMLabeler.PROMPT


def test_the_default_labeler_is_the_stub() -> None:
    assert isinstance(topics.get_topic_labeler(), topics.StubLabeler)


def test_an_unknown_labeler_backend_is_an_error(settings: Settings) -> None:
    settings.TOPIC_LABELER = "oracle"

    with pytest.raises(ValueError, match="TOPIC_LABELER"):
        topics.get_topic_labeler()


# --- Building ----------------------------------------------------------------


def test_build_topics_finds_the_groups(clusters: list[Chunk]) -> None:
    result = topics.build_topics()

    assert len(result.topics) >= 2
    assert result.chunks_considered == len(clusters)
    for topic in result.topics:
        assert topic.chunk_links.count() >= topics.MIN_CLUSTER_MEMBERS
    assert result.chunks_clustered == sum(
        topic.chunk_links.count() for topic in result.topics
    )


def test_every_topic_lands_unpublished(clusters: list[Chunk]) -> None:
    """The human gate: a cluster label is a guess until someone says otherwise."""
    topics.build_topics()

    assert Topic.objects.exists()
    assert not Topic.objects.filter(is_published=True).exists()


def test_topics_are_namespaced_and_labelled(clusters: list[Chunk]) -> None:
    result = topics.build_topics()

    slugs = [topic.slug for topic in result.topics]
    assert all(slug.startswith(topics.AUTO_SLUG_PREFIX) for slug in slugs)
    assert len(set(slugs)) == len(slugs)
    assert {normalize_for_index(topic.name_ar) for topic in result.topics} <= {
        "الصبر",
        "الرحمه",
        "العلم",
    }


def test_a_score_ranks_the_members(clusters: list[Chunk]) -> None:
    (topic, *_) = topics.build_topics().topics

    scores = list(topic.chunk_links.order_by("-score").values_list("score", flat=True))
    assert scores == sorted(scores, reverse=True)
    assert all(-1.0 <= score <= 1.0 for score in scores)


def test_a_small_corpus_is_refused_politely(db: None) -> None:
    build_clusters(size=1)

    with pytest.raises(topics.NotEnoughChunks, match="embedded chunk"):
        topics.build_topics()

    assert not Topic.objects.exists()


def test_the_threshold_is_configurable(db: None) -> None:
    build_clusters(size=2)

    assert topics.build_topics(min_chunks=6).topics


def test_unembedded_chunks_are_ignored(clusters: list[Chunk]) -> None:
    Chunk.objects.filter(pk=clusters[0].pk).update(embedding=None)

    assert topics.build_topics().chunks_considered == len(clusters) - 1


# --- The command -------------------------------------------------------------


def test_the_command_builds_and_reports(
    clusters: list[Chunk], capsys: pytest.CaptureFixture[str]
) -> None:
    call_command("build_topics")

    output = capsys.readouterr().out
    assert topics.AUTO_SLUG_PREFIX in output
    assert "unpublished" in output
    assert Topic.objects.count() == Topic.objects.filter(is_published=False).count()


def test_rebuild_is_idempotent(clusters: list[Chunk]) -> None:
    call_command("build_topics")
    first = sorted(Topic.objects.values_list("slug", "name_ar"))
    links = ChunkTopic.objects.count()

    call_command("build_topics", "--rebuild")

    assert sorted(Topic.objects.values_list("slug", "name_ar")) == first
    assert ChunkTopic.objects.count() == links


def test_rebuild_leaves_hand_made_topics_alone(clusters: list[Chunk]) -> None:
    keeper = Topic.objects.create(slug="sabr", name_ar="الصبر", is_published=True)

    call_command("build_topics", "--rebuild")

    assert Topic.objects.filter(pk=keeper.pk).exists()


def test_rebuild_keeps_an_auto_topic_a_human_has_published(clusters: list[Chunk]) -> None:
    """Publishing is the one human decision in this module: somebody read the
    passages and said the label holds. A nightly ``--rebuild`` that deleted the
    row would silently undo that review and un-publish the topic."""
    call_command("build_topics")
    reviewed = Topic.objects.first()
    assert reviewed is not None
    reviewed.is_published = True
    reviewed.save(update_fields=["is_published"])

    call_command("build_topics", "--rebuild")

    reviewed.refresh_from_db()
    assert reviewed.is_published is True
    # It keeps its slug, so the URL a reader was given still resolves.
    assert Topic.objects.filter(pk=reviewed.pk, slug=reviewed.slug).exists()
    assert not Topic.objects.filter(
        slug__startswith=topics.AUTO_SLUG_PREFIX, is_published=False
    ).filter(slug=reviewed.slug).exists()


def test_a_rerun_without_rebuild_does_not_collide(clusters: list[Chunk]) -> None:
    call_command("build_topics")
    before = Topic.objects.count()

    call_command("build_topics")

    assert Topic.objects.count() == before * 2
    assert Topic.objects.values("slug").distinct().count() == before * 2


def test_the_command_refuses_a_small_corpus(db: None) -> None:
    build_clusters(size=1)

    with pytest.raises(CommandError, match="embedded chunk"):
        call_command("build_topics")
