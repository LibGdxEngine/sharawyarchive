"""Stage 4: widening, merging, capping and rendering the generator's context."""

from __future__ import annotations

import pytest

from corpus.arabic import normalize_light
from corpus.models import Chunk
from search.models import Passage
from search.smart import context, passages
from search.smart.schemas import RerankedPassage

from .conftest import CorpusFixture

pytestmark = pytest.mark.django_db


@pytest.fixture
def built(corpus: CorpusFixture) -> CorpusFixture:
    for segment in (corpus.khawatir, corpus.recitation):
        transcript = passages.transcripts_with_chunks().get(pk=segment.transcript.pk)
        passages.build_for_transcript(transcript, min_words=6, max_words=12)
    return corpus


def _seed(passage: Passage, score: int = 3) -> RerankedPassage:
    return RerankedPassage(passage_id=passage.pk, score=score, rrf=0.1)


def _chunk_text(transcript_id: int, start: int, end: int) -> str:
    rows = Chunk.objects.filter(transcript_id=transcript_id, idx__gte=start, idx__lte=end)
    return " ".join(chunk.text for chunk in rows.order_by("idx"))


def test_a_seed_is_widened_by_its_neighbours_and_rebuilt_from_chunks(
    built: CorpusFixture,
) -> None:
    rows = list(Passage.objects.filter(segment=built.khawatir).order_by("ordinal"))
    assert len(rows) >= 4
    seed = rows[2]
    before, after = rows[1], rows[3]

    (window,) = context.assemble([_seed(seed)])

    assert window.id == "p1" and window.passage_ids == [seed.pk]
    assert (window.chunk_idx_start, window.chunk_idx_end) == (
        before.chunk_idx_start,
        after.chunk_idx_end,
    )
    assert window.text == _chunk_text(
        seed.transcript_id, before.chunk_idx_start, after.chunk_idx_end
    )
    assert window.start_ms == before.start_ms and window.end_ms == after.end_ms
    assert (window.segment_id, window.surah, window.ayah_start, window.ayah_end) == (
        built.khawatir.pk,
        2,
        1,
        10,
    )
    assert window.segment_title == "خواطر البقرة"


def test_overlapping_windows_of_one_transcript_merge(built: CorpusFixture) -> None:
    rows = list(Passage.objects.filter(segment=built.khawatir).order_by("ordinal"))

    windows = context.assemble([_seed(rows[1]), _seed(rows[2], score=2)])

    assert len(windows) == 1
    assert windows[0].chunk_idx_start == rows[0].chunk_idx_start
    assert windows[0].chunk_idx_end == rows[3].chunk_idx_end


def test_windows_come_back_in_corpus_order_with_fresh_ids(built: CorpusFixture) -> None:
    khawatir = list(Passage.objects.filter(segment=built.khawatir).order_by("ordinal"))
    recitation = list(Passage.objects.filter(segment=built.recitation).order_by("ordinal"))
    late, early = khawatir[-1], khawatir[0]

    windows = context.assemble([_seed(recitation[0]), _seed(late), _seed(early)])

    assert [w.id for w in windows] == ["p1", "p2", "p3"]
    assert [w.segment_id for w in windows] == [
        built.khawatir.pk,
        built.khawatir.pk,
        built.recitation.pk,
    ]
    assert windows[0].start_ms < windows[1].start_ms
    assert windows[0].passage_ids == [early.pk] and windows[1].passage_ids == [late.pk]


def test_unknown_passages_are_skipped(built: CorpusFixture) -> None:
    assert context.assemble([RerankedPassage(passage_id=10**9, score=3, rrf=0.1)]) == []


def test_a_window_is_trimmed_around_its_seed(
    built: CorpusFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = list(Passage.objects.filter(segment=built.khawatir).order_by("ordinal"))
    seed = rows[2]
    monkeypatch.setattr(context, "MAX_PASSAGE_WORDS", seed.word_count)

    (window,) = context.assemble([_seed(seed)])

    assert (window.chunk_idx_start, window.chunk_idx_end) == (
        seed.chunk_idx_start,
        seed.chunk_idx_end,
    )
    assert len(window.text.split()) == seed.word_count


def test_the_context_budget_drops_the_weakest_windows(
    built: CorpusFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    khawatir = list(Passage.objects.filter(segment=built.khawatir).order_by("ordinal"))
    recitation = list(Passage.objects.filter(segment=built.recitation).order_by("ordinal"))
    (first,) = context.assemble([_seed(recitation[0])])
    monkeypatch.setattr(context, "MAX_CONTEXT_WORDS", 1)

    assert context.assemble([_seed(khawatir[0]), _seed(recitation[0])]) == []

    # Exactly the best window's words: the second, weaker one no longer fits.
    monkeypatch.setattr(context, "MAX_CONTEXT_WORDS", len(first.text.split()))
    windows = context.assemble([_seed(recitation[0]), _seed(khawatir[0])])
    assert [w.passage_ids for w in windows] == [[recitation[0].pk]]


def test_render_emits_passage_blocks_with_letters_only_text(built: CorpusFixture) -> None:
    rows = list(Passage.objects.filter(segment=built.khawatir).order_by("ordinal"))
    seed = rows[0]
    seed.segment.title = 'خواطر "البقرة"'
    seed.segment.save()

    (window,) = context.assemble([_seed(seed)])
    rendered = context.render([window])

    assert rendered.startswith(
        f'<passage id="p1" segment_id="{built.khawatir.pk}" title="خواطر ”البقرة”" '
        f'surah="2" ayahs="1-10" start_ms="{window.start_ms}" end_ms="{window.end_ms}">\n'
    )
    assert rendered.endswith("\n</passage>")
    assert normalize_light(window.text) in rendered
    assert "َ" not in rendered  # no fatha: harakat are stripped
    assert context.render([]) == ""
