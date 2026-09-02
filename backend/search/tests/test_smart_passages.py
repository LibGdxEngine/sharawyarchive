"""The passage planner and builder (``search.smart.passages``).

The planner is pure and tested like ``pipeline/chunking.py``: hand-made chunk
sequences with known word counts and silence gaps. The builder runs against
the database and must be idempotent by content hash, carry embeddings across a
rebuild when the text did not change, and follow an approved correction.
"""

from __future__ import annotations

import pytest
from pytest_django.fixtures import DjangoCaptureOnCommitCallbacks, Settings

from corpus import corrections
from corpus.arabic import normalize_for_index
from corpus.models import Chunk
from corpus.tests.conftest import build_passages as build_aligned
from corpus.tests.conftest import make_correction
from search.models import EMBEDDING_DIMENSIONS, Passage
from search.smart import embedding_model_tag, passages
from search.smart.passages import ChunkInfo, Window, plan_windows

from .conftest import CorpusFixture
from .openrouter_fakes import stub_vector

pytestmark = pytest.mark.django_db


def _chunks(words: list[int], gaps: list[int] | None = None) -> list[ChunkInfo]:
    """Chunks of ``words`` words, 10 s long, separated by ``gaps`` ms of silence."""
    gaps = gaps or [0] * (len(words) - 1)
    infos: list[ChunkInfo] = []
    start = 0
    for index, count in enumerate(words):
        infos.append(ChunkInfo(idx=index, start_ms=start, end_ms=start + 10_000, words=count))
        start += 10_000 + (gaps[index] if index < len(gaps) else 0)
    return infos


# --- plan_windows -------------------------------------------------------------


def test_no_chunks_means_no_windows() -> None:
    assert plan_windows([]) == []


def test_a_short_transcript_is_one_window() -> None:
    assert plan_windows(_chunks([40, 30, 20])) == [Window(0, 2)]


def test_a_single_oversized_chunk_is_a_window_of_its_own() -> None:
    assert plan_windows(_chunks([500])) == [Window(0, 0)]


def test_windows_close_at_the_widest_gap_and_overlap_by_one_chunk() -> None:
    # 6 × 100 words; the widest gap reachable before 300 words wins each time.
    chunks = _chunks([100] * 6, gaps=[10, 500, 2000, 100, 3000])

    windows = plan_windows(chunks, min_words=150, max_words=300)

    assert windows == [Window(0, 2), Window(2, 4), Window(4, 5)]
    covered = {index for window in windows for index in range(window.first, window.last + 1)}
    assert covered == set(range(6))


def test_at_max_words_with_no_gap_the_earliest_edge_wins() -> None:
    windows = plan_windows(_chunks([100] * 4), min_words=150, max_words=300)

    assert windows[0] == Window(0, 1)


def test_no_overlap_after_a_single_chunk_window() -> None:
    chunks = _chunks([200, 200, 200], gaps=[5000, 5000])

    windows = plan_windows(chunks, min_words=150, max_words=300)

    assert windows == [Window(0, 0), Window(1, 1), Window(2, 2)]


def test_a_tiny_tail_is_folded_into_the_window_before_it() -> None:
    windows = plan_windows(_chunks([200, 300, 20], gaps=[5000, 100]), min_words=150, max_words=300)

    assert windows == [Window(0, 0), Window(1, 2)]


def test_planning_is_deterministic() -> None:
    chunks = _chunks([37, 61, 12, 88, 45, 90, 33, 70], gaps=[100, 900, 50, 1200, 300, 40, 800])

    assert plan_windows(chunks) == plan_windows(chunks)


# --- header_for / content_hash ------------------------------------------------


def test_the_header_names_segment_surah_ayahs_and_source(corpus: CorpusFixture) -> None:
    header = passages.header_for(corpus.khawatir)

    assert header == "خواطر البقرة — سورة البقرة: الآيات 1–10 — التلفزيون المصري"


def test_the_header_copes_with_a_segment_outside_the_mushaf() -> None:
    aligned = build_aligned()

    assert passages.header_for(aligned.segment) == "خواطر مرتبة — التلفزيون المصري"


def test_the_content_hash_covers_header_and_text() -> None:
    assert passages.content_hash("h", "t") != passages.content_hash("h", "t2")
    assert passages.content_hash("h", "t") != passages.content_hash("h2", "t")
    assert passages.content_hash("h", "t") == passages.content_hash("h", "t")


# --- build_for_transcript -----------------------------------------------------


def _build(transcript_pk: int, **kwargs: object) -> passages.BuildStats:
    transcript = passages.transcripts_with_chunks().get(pk=transcript_pk)
    return passages.build_for_transcript(transcript, min_words=6, max_words=12, **kwargs)  # type: ignore[arg-type]


def test_building_writes_passages_over_the_chunks(corpus: CorpusFixture) -> None:
    stats = _build(corpus.khawatir.transcript.pk)

    rows = list(Passage.objects.filter(segment=corpus.khawatir).order_by("ordinal"))
    assert stats.created == len(rows) > 1 and stats.deleted == 0
    assert [row.ordinal for row in rows] == list(range(len(rows)))
    first = rows[0]
    members = Chunk.objects.filter(
        transcript=corpus.khawatir.transcript,
        idx__gte=first.chunk_idx_start,
        idx__lte=first.chunk_idx_end,
    ).order_by("idx")
    assert first.text == " ".join(chunk.text for chunk in members)
    assert first.text_normalized == " ".join(chunk.text_normalized for chunk in members)
    assert first.start_ms == members.first().start_ms
    assert first.end_ms == members.last().end_ms
    assert first.word_count == sum(len(chunk.text_normalized.split()) for chunk in members)
    assert first.surah == 2 and first.ayah_start == 1 and first.ayah_end == 10
    assert first.content_hash == passages.content_hash(first.header, first.text_normalized)
    assert first.text_stem and "الصبر" not in first.text_stem  # stemmed, not raw
    assert not first.is_embedded


def test_rebuilding_unchanged_text_writes_nothing(corpus: CorpusFixture) -> None:
    _build(corpus.khawatir.transcript.pk)
    before = list(Passage.objects.order_by("pk").values_list("pk", "content_hash"))

    stats = _build(corpus.khawatir.transcript.pk)

    assert stats.created == stats.deleted == 0
    assert stats.unchanged == len(before)
    assert list(Passage.objects.order_by("pk").values_list("pk", "content_hash")) == before


def test_force_rewrites_even_unchanged_text(corpus: CorpusFixture) -> None:
    _build(corpus.khawatir.transcript.pk)
    before = set(Passage.objects.values_list("pk", flat=True))

    stats = _build(corpus.khawatir.transcript.pk, force=True)

    assert stats.deleted == len(before) and stats.created == len(before)
    assert set(Passage.objects.values_list("pk", flat=True)).isdisjoint(before)


def test_a_dry_run_plans_but_writes_nothing(corpus: CorpusFixture) -> None:
    stats = _build(corpus.khawatir.transcript.pk, dry_run=True)

    assert stats.created > 0
    assert not Passage.objects.exists()


def _embed_all(settings: Settings) -> None:
    settings.SMART_EMBEDDING_DIMENSIONS = EMBEDDING_DIMENSIONS
    for row in Passage.objects.all():
        row.embedding = stub_vector(row.text_normalized, EMBEDDING_DIMENSIONS)
        row.embedding_model = embedding_model_tag()
        row.embedded_hash = row.content_hash
        row.save()


def test_a_changed_chunk_rebuilds_and_carries_the_untouched_embeddings(
    corpus: CorpusFixture, smart_settings: Settings
) -> None:
    transcript = corpus.khawatir.transcript
    _build(transcript.pk)
    _embed_all(smart_settings)
    last = transcript.chunks.order_by("-idx").first()
    assert last is not None
    last.text = "كلام جديد تمامًا في هذا المقطع"
    last.text_normalized = normalize_for_index(last.text)
    last.save()
    hashes_before = {row.content_hash for row in Passage.objects.all()}

    stats = _build(transcript.pk)

    rows = list(Passage.objects.order_by("ordinal"))
    touched = [row for row in rows if row.chunk_idx_end >= last.idx]
    untouched = [row for row in rows if row.chunk_idx_end < last.idx]
    assert touched and untouched
    assert stats.created == len(rows) and stats.carried == len(untouched)
    assert all(row.is_embedded and row.embedded_hash == row.content_hash for row in untouched)
    assert all(not row.is_embedded for row in touched)
    assert all(row.content_hash not in hashes_before for row in touched)
    assert all(row.content_hash in hashes_before for row in untouched)


def test_refresh_for_chunks_touches_only_the_owning_transcript(corpus: CorpusFixture) -> None:
    _build(corpus.khawatir.transcript.pk)
    _build(corpus.recitation.transcript.pk)
    recitation = Passage.objects.filter(segment=corpus.recitation)
    recitation_pks = set(recitation.values_list("pk", flat=True))
    chunk = corpus.chunks[0]
    chunk.text_normalized = normalize_for_index("نص مختلف")
    chunk.save()

    stats = passages.refresh_for_chunks([chunk.pk])

    assert stats.transcripts == 1 and stats.created > 0
    assert set(recitation.values_list("pk", flat=True)) == recitation_pks


def test_hydrate_keeps_order_and_drops_unknown_ids(corpus: CorpusFixture) -> None:
    _build(corpus.khawatir.transcript.pk)
    pks = list(Passage.objects.order_by("pk").values_list("pk", flat=True))

    rows = passages.hydrate([pks[-1], 10**9, pks[0]])

    assert [row.pk for row in rows] == [pks[-1], pks[0]]
    assert rows[0].segment.surah.name_ar == "البقرة"  # preloaded, no extra query needed


def test_transcripts_with_chunks_skips_empty_transcripts(corpus: CorpusFixture) -> None:
    Chunk.objects.filter(transcript=corpus.recitation.transcript).delete()

    assert list(passages.transcripts_with_chunks()) == [corpus.khawatir.transcript]


# --- corrections ----------------------------------------------------------------


def test_an_approved_correction_rewrites_the_covering_passage(
    meili_prefix: str,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    aligned = build_aligned()
    transcript = passages.transcripts_with_chunks().get(pk=aligned.transcript.pk)
    passages.build_for_transcript(transcript)
    before = Passage.objects.get()
    assert "مؤمنة" not in before.text
    correction = make_correction(aligned, 12, 13, "قلوب مؤمنة")

    with django_capture_on_commit_callbacks(execute=True):
        corrections.approve(correction)

    after = Passage.objects.get()
    assert after.ordinal == before.ordinal == 0
    assert after.content_hash != before.content_hash
    assert "مؤمنة" in after.text
    assert normalize_for_index("مؤمنة") in after.text_normalized
    assert after.text == " ".join(chunk.text for chunk in transcript.chunks.order_by("idx"))
