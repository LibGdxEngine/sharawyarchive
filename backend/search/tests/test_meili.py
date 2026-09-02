"""Lexical search against a live Meilisearch instance.

Every test here owns a private index (see the ``meili_prefix`` fixture) and
deletes it on teardown, so the suite is safe to run against the shared dev
server.
"""

from __future__ import annotations

import pytest

from corpus.models import SegmentKind
from quran.models import Ayah, Surah
from search import services

from .conftest import KHAWATIR_TEXTS, RECITATION_TEXTS, CorpusFixture

pytestmark = pytest.mark.django_db

IMAN = KHAWATIR_TEXTS[0]  # الْإِيمَانُ بِاللَّهِ وَحْدَهُ ...
SABR = KHAWATIR_TEXTS[1]  # الصَّبْرُ عِنْدَ الصَّدْمَةِ الْأُولَى
HAJJ = RECITATION_TEXTS[1]  # الْحَجُّ عَرَفَةُ وَالطَّوَافُ سَبْعًا
RAHMA = KHAWATIR_TEXTS[2]  # الرَّحْمَةُ فِي قُلُوبِ الْمُؤْمِنِينَ
GAPPED = KHAWATIR_TEXTS[6]  # الصَّبْرُ الْجَمِيلُ، عِنْدَ الصَّدْمَةِ.
REVERSED = KHAWATIR_TEXTS[7]  # عِنْدَ الصَّدْمَةِ الصَّبْرُ
MUMINUN = KHAWATIR_TEXTS[8]  # الْمُؤْمِنُونَ إِخْوَةٌ
LONG = KHAWATIR_TEXTS[11]  # longer than a suggestion snippet
CLITIC = KHAWATIR_TEXTS[12]  # تَحَلَّوْا بِالصَّبْرِ ... — الصبر only behind a clitic


def _ids(query: str, **kwargs: object) -> list[int]:
    ids, _ = services.lexical_search(query, **kwargs)  # type: ignore[arg-type]
    return ids


def test_ensure_chunks_index_configures_the_attributes(chunks_index: str) -> None:
    settings = services.meili_client().index(chunks_index).get_settings()
    assert settings["searchableAttributes"] == ["text_normalized", "text_stem"]
    assert sorted(settings["filterableAttributes"]) == [
        "ayah_start",
        "kind",
        "segment_id",
        "surah",
    ]
    assert sorted(settings["sortableAttributes"]) == ["start_ms", "surah"]
    assert settings["typoTolerance"]["minWordSizeForTypos"] == {"oneTypo": 4, "twoTypos": 8}
    assert settings["rankingRules"] == services.RANKING_RULES


def test_ensure_ayahs_index_configures_both_spellings_and_strictness(ayahs_index: str) -> None:
    settings = services.meili_client().index(ayahs_index).get_settings()
    assert settings["searchableAttributes"] == ["text_normalized", "text_imlaei_normalized"]
    assert settings["filterableAttributes"] == ["surah"]
    assert settings["typoTolerance"]["minWordSizeForTypos"] == {"oneTypo": 4, "twoTypos": 8}
    assert settings["rankingRules"] == services.RANKING_RULES


def test_ensure_chunks_index_is_idempotent(chunks_index: str) -> None:
    services.ensure_chunks_index()
    settings = services.meili_client().index(chunks_index).get_settings()
    assert settings["searchableAttributes"] == ["text_normalized", "text_stem"]


def test_index_chunks_stores_the_document_shape(
    chunks_index: str, corpus: CorpusFixture
) -> None:
    assert services.index_chunks(corpus.chunks) == len(corpus.chunks)

    chunk = corpus.chunk_for(IMAN)
    document = services.meili_client().index(chunks_index).get_document(chunk.pk)
    assert document.text == IMAN  # display text keeps its diacritics
    assert document.text_normalized == chunk.text_normalized
    assert document.text_stem == "ايمان الله وحده لا شريك له"
    assert document.segment_id == corpus.khawatir.pk
    assert document.segment_title == "خواطر البقرة"
    assert (document.surah, document.ayah_start, document.ayah_end) == (2, 1, 10)
    assert document.kind == SegmentKind.KHAWATIR
    assert (document.start_ms, document.end_ms) == (chunk.start_ms, chunk.end_ms)


def test_index_chunks_upserts_rather_than_duplicates(
    chunks_index: str, corpus: CorpusFixture
) -> None:
    services.index_chunks(corpus.chunks)
    services.index_chunks(corpus.chunks)
    assert services.meili_client().index(chunks_index).get_stats().number_of_documents == len(
        corpus.chunks
    )


def test_index_chunks_ignores_an_empty_batch(chunks_index: str) -> None:
    assert services.index_chunks([]) == 0


def test_exact_phrase_returns_only_its_own_chunk(indexed_corpus: CorpusFixture) -> None:
    """Meilisearch alone would also return the gapped and reversed chunks."""
    response = services.search("الصبر عند الصدمة")
    assert [result.chunk_id for result in response.results] == [
        indexed_corpus.chunk_for(SABR).pk
    ]
    assert response.results[0].text == SABR
    assert response.total == 1


@pytest.mark.parametrize(
    "query",
    [
        "الايمان بالله",  # canonical index spelling
        "الْإِيمَانُ بِٱللَّٰهِ",  # full diacritics, alef wasla, dagger alif
        "الإيمان بالله",  # hamza below
        "الأيمان باللّه",  # wrong hamza (above) + shadda
        "الايمـــان بالله",  # tatweel padding
    ],
)
def test_hamza_and_diacritic_variants_return_the_canonical_result(
    indexed_corpus: CorpusFixture, query: str
) -> None:
    """The key normalization guarantee: however the reader spells it, the query
    is folded to the same form the index holds (CLAUDE.md rule 2)."""
    canonical = _ids("الايمان بالله")
    assert canonical[0] == indexed_corpus.chunk_for(IMAN).pk
    assert _ids(query) == canonical


def test_kind_filter_restricts_results_to_one_segment_kind(
    indexed_corpus: CorpusFixture,
) -> None:
    khawatir_ids = {
        chunk.pk
        for chunk in indexed_corpus.chunks
        if chunk.transcript_id == indexed_corpus.khawatir.transcript.pk
    }
    response = services.search("القلب", kind=SegmentKind.KHAWATIR)
    assert len(response.results) == 3
    assert {result.chunk_id for result in response.results} <= khawatir_ids
    assert {result.kind for result in response.results} == {SegmentKind.KHAWATIR}


def test_recitation_kind_searches_mushaf_only(indexed_corpus: CorpusFixture) -> None:
    """تلاوة: canonical text only — recitation ASR chunks must not leak in."""
    response = services.search("الحج عرفة", kind=SegmentKind.RECITATION)
    assert response.results == []
    assert response.total == 0


def test_recitation_kind_returns_mushaf_matches(
    indexed_corpus: CorpusFixture, indexed_quran: None, quran_slice: dict[int, Surah]
) -> None:
    """A mushaf query under تلاوة returns canonical verse matches, no chunks."""
    ayah = Ayah.objects.get(surah_id=24, number=35)
    response = services.search(ayah.text_uthmani, kind=SegmentKind.RECITATION)
    assert [match.number for match in response.verse_matches] == [35]
    assert response.results == []


def test_khawatir_kind_never_returns_mushaf_text(
    indexed_corpus: CorpusFixture, indexed_quran: None
) -> None:
    """خواطر: transcripts only — no verse/reference blocks even when they match."""
    response = services.search(SABR, kind=SegmentKind.KHAWATIR)
    assert response.ayah_matches == []
    assert response.verse_matches == []
    assert response.results
    assert {result.kind for result in response.results} == {SegmentKind.KHAWATIR}


def test_surah_filter_restricts_results_to_one_surah(indexed_corpus: CorpusFixture) -> None:
    response = services.search("القلب", surah=3)
    assert len(response.results) == 1
    assert {result.surah for result in response.results} == {3}


def test_filters_can_exclude_every_hit(indexed_corpus: CorpusFixture) -> None:
    assert _ids("الحج عرفة", kind=SegmentKind.KHAWATIR) == []
    assert _ids("الحج عرفة", surah=2) == []
    assert _ids("الحج عرفة", surah=3)


def test_delete_segment_chunks_removes_only_that_segment(
    indexed_corpus: CorpusFixture,
) -> None:
    assert _ids("الحج عرفة")

    services.delete_segment_chunks(indexed_corpus.recitation.pk)

    assert _ids("الحج عرفة") == []
    assert _ids("الصبر عند الصدمة")[0] == indexed_corpus.chunk_for(SABR).pk
    remaining = services.meili_client().index(services.chunks_index_name()).get_stats()
    assert remaining.number_of_documents == len(KHAWATIR_TEXTS)


def test_delete_segment_chunks_tolerates_a_missing_index(meili_prefix: str) -> None:
    services.delete_segment_chunks(1)


def test_lexical_search_is_empty_before_the_index_exists(meili_prefix: str) -> None:
    assert services.lexical_search("الايمان بالله") == ([], 0)


def test_verse_search_returns_canonical_mushaf_hits(
    ayahs_index: str, indexed_quran: None, quran_slice: dict[int, Surah]
) -> None:
    """A reader pasting a full ayah (diacritics and all) gets that ayah back —
    the mushaf text is indexed, and the query is normalized the same way."""
    ayah = Ayah.objects.get(surah_id=24, number=35)
    assert services.verse_search(ayah.text_uthmani)[0] == ayah.pk


def test_pagination_walks_the_ranked_list(indexed_corpus: CorpusFixture) -> None:
    ranked = _ids("القلب")
    assert len(ranked) == 4

    first = services.search("القلب", page=1, page_size=2)
    second = services.search("القلب", page=2, page_size=2)

    assert [result.chunk_id for result in first.results] == ranked[:2]
    assert [result.chunk_id for result in second.results] == ranked[2:4]
    assert (first.page, second.page) == (1, 2)
    assert first.total == second.total == 4


def test_hits_deleted_from_the_database_are_dropped_from_the_page(
    indexed_corpus: CorpusFixture,
) -> None:
    """Meilisearch can be ahead of the database between pipeline runs."""
    stale = indexed_corpus.chunk_for(HAJJ)
    stale_id = stale.pk
    stale.delete()

    response = services.search("الحج عرفة")

    assert stale_id in _ids("الحج عرفة")
    assert [result.chunk_id for result in response.results] == []


# --- Strict phrase semantics --------------------------------------------------


def test_words_out_of_order_are_rejected(indexed_corpus: CorpusFixture) -> None:
    assert _ids("عند الصبر") == []
    assert _ids("الصدمة الصبر") == [indexed_corpus.chunk_for(REVERSED).pk]


def test_gapped_words_are_rejected(indexed_corpus: CorpusFixture) -> None:
    """Meilisearch's ``all`` strategy accepts the gapped chunk; the verifier does not."""
    assert _ids("الصبر عند الصدمة") == [indexed_corpus.chunk_for(SABR).pk]
    assert _ids("الجميل عند الصدمة") == [indexed_corpus.chunk_for(GAPPED).pk]


def test_glued_punctuation_does_not_break_adjacency(indexed_corpus: CorpusFixture) -> None:
    assert _ids("الصبر الجميل عند") == [indexed_corpus.chunk_for(GAPPED).pk]
    assert set(_ids("عند الصدمة")) == {
        indexed_corpus.chunk_for(text).pk for text in (SABR, GAPPED, REVERSED)
    }


def test_one_typo_on_a_five_letter_word_is_accepted(indexed_corpus: CorpusFixture) -> None:
    assert _ids("الصبن عند الصدمة") == [indexed_corpus.chunk_for(SABR).pk]


def test_transposition_is_one_edit(indexed_corpus: CorpusFixture) -> None:
    """Pins Meilisearch's transposition-costs-one retrieval as much as ours."""
    assert _ids("الصرب عند الصدمة") == [indexed_corpus.chunk_for(SABR).pk]


def test_one_typo_on_a_three_letter_word_is_rejected(indexed_corpus: CorpusFixture) -> None:
    assert _ids("الصبر عنت الصدمة") == []


def test_two_typos_on_a_five_letter_word_are_rejected(indexed_corpus: CorpusFixture) -> None:
    assert _ids("الظبن عند الصدمة") == []


def test_two_typos_on_an_eight_letter_word_are_accepted(
    indexed_corpus: CorpusFixture,
) -> None:
    assert _ids("قلوب الموممنون") == [indexed_corpus.chunk_for(RAHMA).pk]
    assert _ids("قلوب الموممنوون") == []  # three edits


def test_the_first_letter_must_match(indexed_corpus: CorpusFixture) -> None:
    assert _ids("بلصبر عند الصدمة") == []
    assert _ids("قلوب بلمومنين") == []  # even with a two-edit budget
    assert _ids("قلوب المومنينن") == [indexed_corpus.chunk_for(RAHMA).pk]  # same edit, elsewhere


def test_prefix_of_the_last_word_beyond_budget_is_rejected(
    indexed_corpus: CorpusFixture,
) -> None:
    """Meilisearch prefix-matches the last word; the verifier only allows what
    the typo budget allows (one missing letter on a 4+ letter word)."""
    assert _ids("الصبر عند الصد") == []
    assert _ids("الصبر عند الصدم") == [indexed_corpus.chunk_for(SABR).pk]
    assert _ids("الص") == []


def test_clitic_prefixes_match_through_the_stem_tier(indexed_corpus: CorpusFixture) -> None:
    """``الله`` reaches ``بالله`` (same light stem) even though the typo tier
    would call the extra letter a first-letter change; the reverse holds too."""
    iman = indexed_corpus.chunk_for(IMAN).pk
    assert _ids("الله") == [iman]
    assert _ids("بالله") == [iman]
    assert _ids("الايمان الله") == [iman]


def test_a_stemmed_query_reaches_a_chunk_meilisearch_would_not_return(
    indexed_corpus: CorpusFixture,
) -> None:
    """``بالصبر`` is one word to Meilisearch, so ``الصبر`` alone never retrieved
    it; the stemmed second query matches ``text_stem`` and the verifier
    accepts the stem match — after every exact hit."""
    sabr, gapped, reversed_, clitic = (
        indexed_corpus.chunk_for(text).pk for text in (SABR, GAPPED, REVERSED, CLITIC)
    )
    ids = _ids("الصبر")
    assert ids[-1] == clitic
    assert set(ids[:-1]) == {sabr, gapped, reversed_}
    assert _ids("صبر")[-1] == clitic and len(_ids("صبر")) == 4
    assert _ids("تحلوا الصبر") == [clitic]


def test_quoted_words_are_exact(indexed_corpus: CorpusFixture) -> None:
    assert _ids('"الله"') == []  # no stem tier
    assert _ids('"بالله"') == [indexed_corpus.chunk_for(IMAN).pk]
    assert _ids('"الصبن" عند الصدمة') == []  # no typos inside the quotes
    assert _ids('الصبن "عند الصدمة"') == [indexed_corpus.chunk_for(SABR).pk]
    assert _ids('«الصبر عند الصدمة»') == [indexed_corpus.chunk_for(SABR).pk]


def test_exact_matches_rank_above_typo_matches(indexed_corpus: CorpusFixture) -> None:
    rahma, muminun = (indexed_corpus.chunk_for(text).pk for text in (RAHMA, MUMINUN))
    assert _ids("المؤمنين") == [rahma, muminun]
    assert _ids("المؤمنون") == [muminun, rahma]


def test_typo_matches_rank_above_stem_matches(indexed_corpus: CorpusFixture) -> None:
    """``مؤمن`` is a typo-free stem of both chunks' word and a one-edit typo of
    neither, so both come through the stem tier; ``المؤمنين`` is exact in one
    and a typo in the other, so the stem tier is never needed."""
    rahma, muminun = (indexed_corpus.chunk_for(text).pk for text in (RAHMA, MUMINUN))
    assert set(_ids("قلوب مؤمن")) == {rahma}
    assert set(_ids("مؤمن")) == {rahma, muminun}
    assert _ids("المؤمنين") == [rahma, muminun]


def test_verse_search_is_strict_and_accepts_imlaei_spelling(
    ayahs_index: str, indexed_quran: None, quran_slice: dict[int, Surah]
) -> None:
    """Holds against the fixture's four ayahs and against the full Quran the
    quran suite's session fixture may have left in the database: ``نور السموت``
    occurs only in 24:35, the gapped ``نور والارض`` and reversed ``السموت نور``
    nowhere (``الله السموت``, say, is a real phrase in 29:44)."""
    ayah = Ayah.objects.get(surah_id=24, number=35)  # ٱللَّهُ نُورُ ٱلسَّمَـٰوَٰتِ وَٱلْأَرْضِ
    assert services.verse_search("نور السموت") == [ayah.pk]  # Uthmani spelling
    assert services.verse_search("نور السماوات") == [ayah.pk]  # imlaei spelling
    assert services.verse_search("نور والارض") == []  # gap
    assert services.verse_search("السموت نور") == []  # order


def test_suggestion_snippet_round_trips_under_strict_search(
    indexed_corpus: CorpusFixture,
) -> None:
    """A clicked suggestion is searched verbatim, so it must be whole words."""
    assert len(LONG) > services.SUGGEST_SNIPPET_CHARS
    assert LONG[services.SUGGEST_SNIPPET_CHARS] != " "  # the cut would split a word
    (snippet,) = services.suggest("الرزق")
    assert len(snippet) <= services.SUGGEST_SNIPPET_CHARS
    assert LONG.startswith(snippet) and LONG[len(snippet)] == " "
    assert [result.chunk_id for result in services.search(snippet).results] == [
        indexed_corpus.chunk_for(LONG).pk
    ]
