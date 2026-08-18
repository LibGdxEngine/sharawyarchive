"""Approving and rejecting a correction (``corpus.corrections``).

The fixture is three ten-word chunks over one aligned transcript (see
``conftest.build_passages``), which is the smallest corpus in which "only the
chunks that overlap the edit are rebuilt" means anything.
"""

from __future__ import annotations

import numpy as np
import pytest
from pytest_django.fixtures import DjangoCaptureOnCommitCallbacks

from corpus import corrections
from corpus.arabic import normalize_for_index
from corpus.embeddings import StubEmbedder
from corpus.models import Chunk, CorrectionStatus, TranscriptWord
from search import services

from .conftest import WORD_LENGTH_MS, WORD_STEP_MS, Passages, make_correction

pytestmark = pytest.mark.django_db

MIDDLE = 1
"""The chunk every correction below lands in: words 10-19."""

TARGET = (12, 14)
"""``قلوب المؤمنين نور`` — three words in the middle of the middle chunk."""


def _texts(passages: Passages) -> list[str]:
    return [word.text for word in passages.words()]


def _timings(passages: Passages) -> list[tuple[int, int]]:
    return [(word.start_ms, word.end_ms) for word in passages.words()]


def _snapshot(chunk_id: int) -> tuple[str, str, int, int, list[float]]:
    """Everything about a chunk an approval could plausibly touch."""
    fresh = Chunk.objects.get(pk=chunk_id)
    return (
        fresh.text,
        fresh.text_normalized,
        fresh.start_ms,
        fresh.end_ms,
        list(fresh.embedding),
    )


# --- Word ranges -------------------------------------------------------------


def test_a_chunk_knows_which_words_it_holds(passages: Passages) -> None:
    assert [corrections.chunk_word_range(chunk) for chunk in passages.chunks] == [
        (0, 9),
        (10, 19),
        (20, 29),
    ]


def test_original_text_is_the_words_as_they_stand(passages: Passages) -> None:
    correction = make_correction(passages, *TARGET, "قلوب المسلمين نور")

    assert corrections.original_text_for(correction) == "قلوب المؤمنين نور"


def test_the_play_range_is_the_span_of_the_selected_words(passages: Passages) -> None:
    correction = make_correction(passages, *TARGET, "قلوب المسلمين نور")

    assert corrections.word_span_ms(correction) == (
        12 * WORD_STEP_MS,
        14 * WORD_STEP_MS + WORD_LENGTH_MS,
    )


# --- Replacing the words -----------------------------------------------------


def test_an_equal_count_replacement_keeps_every_timing(passages: Passages) -> None:
    before = _timings(passages)
    correction = make_correction(passages, *TARGET, "قلوب المسلمين ضياء")

    corrections.approve(correction)

    assert _texts(passages)[12:15] == ["قلوب", "المسلمين", "ضياء"]
    assert _timings(passages) == before


def test_a_shorter_replacement_redistributes_and_renumbers(passages: Passages) -> None:
    correction = make_correction(passages, *TARGET, "قلوب مؤمنة")

    corrections.approve(correction)

    words = passages.words()
    assert [word.idx for word in words] == list(range(29))  # 30 - 3 + 2
    assert [word.text for word in words[11:15]] == ["في", "قلوب", "مؤمنة", "يهدي"]
    # The two new words split the 12000-14900 ms the three old ones covered.
    assert [(word.start_ms, word.end_ms) for word in words[12:14]] == [
        (12_000, 13_450),
        (13_450, 14_900),
    ]
    # Everything after the edit keeps its own timing, only its index moves.
    assert (words[14].text, words[14].start_ms) == ("يهدي", 15_000)


def test_a_longer_replacement_redistributes_and_renumbers(passages: Passages) -> None:
    correction = make_correction(passages, *TARGET, "قلوب من آمنوا بربهم نور")

    corrections.approve(correction)

    words = passages.words()
    assert [word.idx for word in words] == list(range(32))  # 30 - 3 + 5
    assert [word.text for word in words[12:17]] == ["قلوب", "من", "آمنوا", "بربهم", "نور"]
    assert [(word.start_ms, word.end_ms) for word in words[12:17]] == [
        (12_000, 12_580),
        (12_580, 13_160),
        (13_160, 13_740),
        (13_740, 14_320),
        (14_320, 14_900),
    ]
    assert (words[17].text, words[17].start_ms) == ("يهدي", 15_000)


def test_a_replacement_word_never_outgrows_the_column(passages: Passages) -> None:
    correction = make_correction(passages, *TARGET, "ا" * 400)

    corrections.approve(correction)

    assert len(passages.words()[12].text) == corrections.MAX_WORD_CHARS


# --- The transcript ----------------------------------------------------------


def test_the_transcript_is_recomputed_and_versioned(passages: Passages) -> None:
    correction = make_correction(passages, *TARGET, "قلوب مؤمنة")

    result = corrections.approve(correction, reviewed_by="reviewer")

    passages.transcript.refresh_from_db()
    expected = " ".join(_texts(passages))
    assert passages.transcript.raw_text == expected
    assert passages.transcript.text_normalized == normalize_for_index(expected)
    assert passages.transcript.word_count == 29
    assert passages.transcript.version == 2
    assert passages.transcript.is_human_reviewed is True
    assert (result.words_replaced, result.words_written, result.version) == (3, 2, 2)
    assert result.reviewed_by == "reviewer"


def test_an_approved_correction_is_closed(passages: Passages) -> None:
    correction = make_correction(passages, *TARGET, "قلوب مؤمنة")

    corrections.approve(correction)

    correction.refresh_from_db()
    assert correction.status == CorrectionStatus.APPROVED


# --- The chunks --------------------------------------------------------------


def test_only_the_overlapping_chunk_is_rebuilt(passages: Passages) -> None:
    untouched = {
        chunk.pk: _snapshot(chunk.pk) for chunk in passages.chunks if chunk.idx != MIDDLE
    }
    correction = make_correction(passages, *TARGET, "قلوب مؤمنة")

    result = corrections.approve(correction)

    assert result.chunk_ids == (passages.chunks[MIDDLE].pk,)
    assert {pk: _snapshot(pk) for pk in untouched} == untouched


def test_the_rebuilt_chunk_carries_the_new_text_and_embedding(passages: Passages) -> None:
    before = _snapshot(passages.chunks[MIDDLE].pk)
    correction = make_correction(passages, *TARGET, "قلوب مؤمنة")

    corrections.approve(correction)

    chunk = passages.reload(passages.chunks[MIDDLE])
    assert chunk.text == "والرحمة في قلوب مؤمنة يهدي إلى طريق الحق دائما"
    assert chunk.text_normalized == normalize_for_index(chunk.text)
    assert (chunk.start_ms, chunk.end_ms) == (before[2], before[3])  # spans hold
    expected = StubEmbedder().embed_passages([chunk.text_normalized])[0]
    assert np.allclose(np.asarray(chunk.embedding), np.asarray(expected), atol=1e-6)
    assert not np.allclose(np.asarray(chunk.embedding), np.asarray(before[4]), atol=1e-6)


def test_correcting_the_last_word_of_a_chunk_stays_in_that_chunk(
    passages: Passages,
) -> None:
    """A range is bounded by its own chunk, so the edited span is too and the
    neighbour is never dragged into the rebuild."""
    neighbour = _snapshot(passages.chunks[MIDDLE + 1].pk)
    correction = make_correction(passages, 19, 19, "دوما")

    result = corrections.approve(correction)

    assert result.chunk_ids == (passages.chunks[MIDDLE].pk,)
    assert passages.reload(passages.chunks[MIDDLE]).text.endswith("دوما")
    assert _snapshot(passages.chunks[MIDDLE + 1].pk) == neighbour


# --- Search index ------------------------------------------------------------


def test_the_search_index_gets_the_rebuilt_chunk(
    indexed_passages: Passages,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    chunk = indexed_passages.chunks[MIDDLE]
    correction = make_correction(indexed_passages, *TARGET, "قلوب مؤمنة")

    with django_capture_on_commit_callbacks(execute=True):
        corrections.approve(correction)

    document = services.meili_client().index(services.chunks_index_name()).get_document(chunk.pk)
    fresh = indexed_passages.reload(chunk)
    assert document.text == fresh.text
    assert document.text_normalized == fresh.text_normalized


def test_the_index_is_untouched_before_the_transaction_commits(
    indexed_passages: Passages,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """Reindexing a row a rollback would revert is worse than a lagging index."""
    chunk = indexed_passages.chunks[MIDDLE]
    correction = make_correction(indexed_passages, *TARGET, "قلوب مؤمنة")

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        corrections.approve(correction)
        index = services.meili_client().index(services.chunks_index_name())
        assert index.get_document(chunk.pk).text == chunk.text

    assert len(callbacks) == 1


# --- Rejection and refusals --------------------------------------------------


def test_rejecting_changes_nothing_but_the_status(passages: Passages) -> None:
    texts, timings = _texts(passages), _timings(passages)
    chunks = {chunk.pk: _snapshot(chunk.pk) for chunk in passages.chunks}
    correction = make_correction(passages, *TARGET, "قلوب مؤمنة")

    corrections.reject(correction)

    correction.refresh_from_db()
    passages.transcript.refresh_from_db()
    assert correction.status == CorrectionStatus.REJECTED
    assert (_texts(passages), _timings(passages)) == (texts, timings)
    assert {pk: _snapshot(pk) for pk in chunks} == chunks
    assert (passages.transcript.version, passages.transcript.is_human_reviewed) == (1, False)


@pytest.mark.parametrize(
    ("word_start", "word_end"),
    [
        (9, 12),  # starts in the previous chunk
        (18, 21),  # runs into the next one
        (100, 101),  # nowhere near the transcript
    ],
)
def test_a_range_outside_its_chunk_is_refused(
    passages: Passages, word_start: int, word_end: int
) -> None:
    correction = make_correction(
        passages, word_start, word_end, "نص", chunk=passages.chunks[MIDDLE]
    )

    with pytest.raises(corrections.CorrectionError, match="outside"):
        corrections.approve(correction)

    assert TranscriptWord.objects.filter(transcript=passages.transcript).count() == 30
    correction.refresh_from_db()
    assert correction.status == CorrectionStatus.PENDING


def test_an_empty_suggestion_is_refused(passages: Passages) -> None:
    correction = make_correction(passages, *TARGET, "   ")

    with pytest.raises(corrections.CorrectionError, match="no words"):
        corrections.approve(correction)


def test_a_reversed_range_is_refused(passages: Passages) -> None:
    correction = make_correction(passages, 14, 12, "نص")

    with pytest.raises(corrections.CorrectionError):
        corrections.approve(correction)


@pytest.mark.parametrize("status", [CorrectionStatus.APPROVED, CorrectionStatus.REJECTED])
def test_a_reviewed_correction_is_not_reviewed_twice(
    passages: Passages, status: str
) -> None:
    correction = make_correction(passages, *TARGET, "قلوب مؤمنة")
    correction.status = status
    correction.save(update_fields=["status"])

    with pytest.raises(corrections.CorrectionError, match="already"):
        corrections.approve(correction)
    with pytest.raises(corrections.CorrectionError, match="already"):
        corrections.reject(correction)
