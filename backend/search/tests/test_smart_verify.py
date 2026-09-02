"""Stage 6: quotes resolved to transcript words, markers, ayah placeholders, status."""

from __future__ import annotations

import pytest

from quran.models import Ayah, Surah
from search.smart import verify
from search.smart.schemas import AyahRef, ContextPassage, DraftCitation, GeneratedAnswer

from .conftest import CHUNK_MS, WORD_MS, CorpusFixture, add_words

pytestmark = pytest.mark.django_db

QUOTE = "الصبر عند الصدمة"  # chunk 1: words at 30 000, 31 000, 32 000 ms


@pytest.fixture
def window(corpus: CorpusFixture) -> ContextPassage:
    """One context passage over the first three khawatir chunks, with words."""
    add_words(corpus.khawatir)
    return ContextPassage(
        id="p1",
        passage_ids=[4242],
        transcript_id=corpus.khawatir.transcript.pk,
        segment_id=corpus.khawatir.pk,
        segment_title=corpus.khawatir.title,
        surah=2,
        ayah_start=1,
        ayah_end=10,
        start_ms=0,
        end_ms=3 * CHUNK_MS,
        chunk_idx_start=0,
        chunk_idx_end=2,
        text=" ".join(chunk.text for chunk in corpus.chunks[:3]),
    )


def _answer(
    answer_md: str,
    citations: list[tuple[str, str]] = ((("p1", QUOTE)),),
    *,
    status: str = "answered",
    ayah_refs: list[tuple[int, int]] = (),
    followups: list[str] = (),
) -> GeneratedAnswer:
    return GeneratedAnswer(
        status=status,  # type: ignore[arg-type]
        answer_md=answer_md,
        citations=[DraftCitation(passage_id=pid, quote=quote) for pid, quote in citations],
        ayah_refs=[AyahRef(surah=s, ayah=a) for s, a in ayah_refs],
        followups=list(followups),
    )


def test_a_verbatim_quote_resolves_to_the_words_it_spans(
    window: ContextPassage, corpus: CorpusFixture
) -> None:
    verified = verify.verify(_answer("قال الشيخ صراحةً إن الصبر عند الصدمة الأولى [p1]."), [window])

    assert verified.status == "answered"
    assert verified.answer_md == "قال الشيخ صراحةً إن الصبر عند الصدمة الأولى [1]."
    (citation,) = verified.citations
    assert citation.n == 1 and citation.passage_id == 4242
    assert citation.start_ms == CHUNK_MS
    assert citation.end_ms == CHUNK_MS + 2 * WORD_MS + WORD_MS - 100
    assert citation.quote_display == "الصَّبْرُ عِنْدَ الصَّدْمَةِ"
    assert citation.chunk_id == corpus.chunks[1].pk
    assert citation.segment_id == corpus.khawatir.pk
    assert citation.listen_url == f"/listen/{corpus.khawatir.pk}?t={CHUNK_MS}"
    assert (citation.surah, citation.ayah_start, citation.ayah_end) == (2, 1, 10)
    assert verified.notes == []


def test_a_quote_with_a_typo_is_still_placed(window: ContextPassage) -> None:
    verified = verify.verify(
        _answer("الصبر أول الأمر [p1].", [("p1", "الصبن عند الصدمه الاولي")]), [window]
    )

    (citation,) = verified.citations
    assert citation.start_ms == CHUNK_MS and citation.quote_display.endswith("الْأُولَى")


@pytest.mark.parametrize(
    ("citation", "note"),
    [
        (("p1", "كلام لا وجود له في المقطع أبدًا"), "not found"),
        (("p1", "الصبر عند"), "2 words"),
        (("p1", " ".join(["كلمة"] * 61)), "61 words"),
        (("p7", QUOTE), "unknown passage"),
    ],
)
def test_bad_citations_are_dropped_and_the_answer_downgraded(
    window: ContextPassage, citation: tuple[str, str], note: str
) -> None:
    verified = verify.verify(_answer("قال الشيخ كذا [p1].", [citation]), [window])

    assert verified.citations == []
    assert verified.status == "not_found"
    assert verified.answer_md == verify.NOT_FOUND_COPY
    assert any(note in item for item in verified.notes)


def test_orphan_markers_and_unmarked_sentences_go(window: ContextPassage) -> None:
    verified = verify.verify(
        _answer(
            "الجملة الأولى مدعومة [p1]. جملة بلا مرجع. جملة تشير إلى مقطع مفقود [p9].\n"
            "سطر ثانٍ مدعوم أيضًا [p1][p1]."
        ),
        [window],
    )

    assert verified.answer_md == "الجملة الأولى مدعومة [1].\nسطر ثانٍ مدعوم أيضًا [1]."
    assert sum("orphan" in note for note in verified.notes) == 1
    assert sum("unmarked" in note for note in verified.notes) == 2


def test_two_quotes_of_one_passage_expand_its_marker(window: ContextPassage) -> None:
    verified = verify.verify(
        _answer("قال كذا [p1].", [("p1", QUOTE), ("p1", "الرحمة في قلوب المؤمنين")]), [window]
    )

    assert verified.answer_md == "قال كذا [1][2]."
    assert [c.n for c in verified.citations] == [1, 2]
    assert verified.citations[1].start_ms == 2 * CHUNK_MS


def test_ayah_placeholders_are_checked_against_the_mushaf(
    window: ContextPassage, quran_slice: dict[int, Surah]
) -> None:
    verified = verify.verify(
        _answer(
            "استشهد الشيخ بقوله تعالى [[ayah:2:255]] ثم [[ayah:2:9999]] [p1].",
            ayah_refs=[(24, 35), (2, 255), (99, 1)],
        ),
        [window],
    )

    assert verified.answer_md == "استشهد الشيخ بقوله تعالى [[ayah:2:255]] ثم [1]."
    assert [(a.surah, a.ayah) for a in verified.ayah_refs] == [(2, 255), (24, 35)]
    kursi = Ayah.objects.get(surah_id=2, number=255)
    assert verified.ayah_refs[0].text_uthmani == kursi.text_uthmani
    assert verified.ayah_refs[0].surah_name_ar == "البقرة"
    assert any("no such ayah 2:9999" in note for note in verified.notes)


def test_a_not_found_answer_keeps_its_one_sentence(window: ContextPassage) -> None:
    verified = verify.verify(
        _answer("لم أجد في الأرشيف حديثًا صريحًا عن هذا. وهذه جملة ثانية.", [], status="not_found"),
        [window],
    )

    assert verified.status == "not_found"
    assert verified.answer_md == "لم أجد في الأرشيف حديثًا صريحًا عن هذا."


def test_losing_most_citations_makes_an_answer_partial(window: ContextPassage) -> None:
    verified = verify.verify(
        _answer(
            "قال كذا [p1].",
            [("p1", QUOTE), ("p1", "لا وجود لهذا الكلام هنا"), ("p1", "ولا لهذا الكلام أيضًا")],
        ),
        [window],
    )

    assert verified.status == "partial" and len(verified.citations) == 1


def test_a_non_arabic_answer_is_refused(window: ContextPassage) -> None:
    with pytest.raises(verify.VerifyError):
        verify.verify(_answer("The Sheikh said patience comes first [p1]."), [window])


def test_followups_are_arabic_and_at_most_three(window: ContextPassage) -> None:
    verified = verify.verify(
        _answer("قال كذا [p1].", followups=["س1؟", "Question?", " ", "س2؟", "س3؟", "س4؟"]),
        [window],
    )

    assert verified.followups == ["س1؟", "س2؟", "س3؟"]


def test_find_span_handles_an_empty_passage(window: ContextPassage) -> None:
    empty = window.model_copy(update={"start_ms": 10**9, "end_ms": 10**9 + 1})
    offsets = verify.offset_map(empty)

    assert offsets.words == [] and verify.find_span(QUOTE, offsets) is None
    assert verify.find_span("   ", verify.offset_map(window)) is None
