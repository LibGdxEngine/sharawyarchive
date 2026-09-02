"""GET /api/surahs/, /api/surahs/{n}/ and /api/ayahs/{s}/{a}/ per API_CONTRACT.md."""

from __future__ import annotations

from typing import Any

import pytest
from rest_framework.test import APIClient

from api.cache import IMMUTABLE
from api.tests.factories import (
    Archive,
    clear_quran,
    make_audio_asset,
    make_segment,
    make_surah,
)
from quran.views import MAX_AYAH_SEGMENTS

pytestmark = pytest.mark.django_db

SURAH_KEYS = {
    'number',
    'name_ar',
    'name_ar_plain',
    'name_en',
    'ayah_count',
    'revelation_place',
    'segment_count',
    'juz_start',
    'juz_end',
    'page_start',
    'page_end',
}
LOCATION_KEYS = {'surah', 'number', 'surah_name_ar', 'juz', 'page'}
SURAH_DETAIL_KEYS = {'number', 'name_ar', 'name_en', 'ayah_count', 'revelation_place', 'ayahs'}
PAGE_AYAH_KEYS = {
    'number',
    'text_uthmani',
    'juz',
    'page',
    'sajda',
    'segment_count',
    'segments',
}
PAGE_AYAH_SEGMENT_KEYS = {'id', 'kind', 'title'}
AYAH_KEYS = {'surah', 'number', 'text_uthmani', 'text_imlaei', 'juz', 'page', 'segments'}
SEGMENT_KEYS = {'id', 'kind', 'title', 'ayah_start', 'ayah_end', 'duration_ms'}


# --- GET /api/surahs/ --------------------------------------------------------


def test_surah_list_returns_the_contract_shape(api: APIClient, archive: Archive) -> None:
    response = api.get('/api/surahs/')

    assert response.status_code == 200
    assert response.headers['Cache-Control'] == IMMUTABLE
    (row,) = response.json()
    assert set(row) == SURAH_KEYS
    assert row['number'] == 2
    assert row['name_ar'] == 'البقرة'
    assert row['revelation_place'] == 'madinah'
    assert row['segment_count'] == 2  # both fixture segments hang off this surah


def test_surah_list_counts_segments_per_surah(api: APIClient, archive: Archive) -> None:
    make_surah(number=3, ayah_count=4, name_ar='آل عمران', name_en='Aal-Imran')

    counts = {row['number']: row['segment_count'] for row in api.get('/api/surahs/').json()}

    assert counts == {2: 2, 3: 0}


def test_surah_list_carries_the_juz_and_page_span(api: APIClient, archive: Archive) -> None:
    """The index filters by juz and mushaf page, so each row states its span."""
    (row,) = api.get('/api/surahs/').json()

    ayahs = archive.surah.ayahs.all()
    assert (row['juz_start'], row['juz_end']) == (
        min(ayah.juz for ayah in ayahs),
        max(ayah.juz for ayah in ayahs),
    )
    assert (row['page_start'], row['page_end']) == (
        min(ayah.page for ayah in ayahs),
        max(ayah.page for ayah in ayahs),
    )


def test_surah_list_segment_count_survives_the_ayah_join(
    api: APIClient, archive: Archive
) -> None:
    """Regression: aggregating over ayahs must not multiply the segment count.

    ``Count('segments')`` next to ``Min('ayahs__juz')`` counts one row per
    (segment, ayah) pair, so this surah's 2 segments would report as 2 x 45.
    """
    long_one = make_surah(number=5, ayah_count=45, name_ar='المائدة', name_en='Al-Maidah')[0]
    for ordinal in range(2):
        make_segment(
            archive.source,
            archive.audio,
            surah=long_one,
            ayah_start=1,
            ayah_end=10,
            title=f'المائدة {ordinal}',
            ordinal=ordinal,
        )

    counts = {row['number']: row['segment_count'] for row in api.get('/api/surahs/').json()}

    assert counts == {2: 2, 5: 2}


def test_surah_list_is_one_query(
    api: APIClient, archive: Archive, django_assert_num_queries: Any
) -> None:
    """114 rows with their counts must not cost 114 count queries."""
    make_surah(number=3, ayah_count=4, name_ar='آل عمران', name_en='Aal-Imran')

    with django_assert_num_queries(1):
        api.get('/api/surahs/')


def test_surah_list_is_ordered_by_number(api: APIClient, archive: Archive) -> None:
    make_surah(number=1, ayah_count=7, name_ar='الفاتحة', name_en='Al-Fatihah')

    assert [row['number'] for row in api.get('/api/surahs/').json()] == [1, 2]


# --- GET /api/surahs/{n}/ ----------------------------------------------------


def test_surah_detail_returns_the_contract_shape(api: APIClient, archive: Archive) -> None:
    response = api.get('/api/surahs/2/')

    assert response.status_code == 200
    assert response.headers['Cache-Control'] == IMMUTABLE
    body = response.json()
    assert set(body) == SURAH_DETAIL_KEYS
    assert set(body['ayahs']) == {'count', 'page', 'page_size', 'results'}
    assert (body['ayahs']['count'], body['ayahs']['page'], body['ayahs']['page_size']) == (3, 1, 20)
    assert len(body['ayahs']['results']) == 3
    (first, second, third) = body['ayahs']['results']
    assert set(first) == PAGE_AYAH_KEYS
    assert first['number'] == 1
    assert first['sajda'] is False
    # Coverage counts: segment 1-2 and segment 1-1 both cover ayah 1.
    assert [first['segment_count'], second['segment_count'], third['segment_count']] == [2, 1, 0]


def test_surah_detail_inlines_the_segments_covering_each_ayah(
    api: APIClient, archive: Archive
) -> None:
    """The page carries listen targets, so the client never fans out per ayah."""
    results = api.get('/api/surahs/2/').json()['ayahs']['results']

    covering = {row['number']: [segment['id'] for segment in row['segments']] for row in results}
    assert covering == {
        1: [archive.segment.pk, archive.other.pk],
        2: [archive.segment.pk],
        3: [],
    }
    (segment,) = results[1]['segments']
    assert set(segment) == PAGE_AYAH_SEGMENT_KEYS
    assert (segment['kind'], segment['title']) == ('khawatir', archive.segment.title)


def test_surah_detail_caps_inlined_segments_but_not_the_count(
    api: APIClient, archive: Archive
) -> None:
    """A heavily covered ayah truncates its list; ``segment_count`` stays true."""
    extra = MAX_AYAH_SEGMENTS + 1
    for ordinal in range(extra):
        make_segment(
            archive.source,
            make_audio_asset(),
            surah=archive.surah,
            ayah_start=1,
            ayah_end=1,
            title=f'خواطر إضافية {ordinal}',
            ordinal=10 + ordinal,
        )

    (first, *_) = api.get('/api/surahs/2/').json()['ayahs']['results']

    assert first['segment_count'] == 2 + extra
    assert len(first['segments']) == MAX_AYAH_SEGMENTS


def test_surah_detail_is_a_constant_number_of_queries(
    api: APIClient, archive: Archive, django_assert_num_queries: Any
) -> None:
    """Coverage stays one query however many segments hang off the page."""
    for ordinal in range(5):
        make_segment(
            archive.source,
            make_audio_asset(),
            surah=archive.surah,
            ayah_start=1,
            ayah_end=3,
            title=f'خواطر إضافية {ordinal}',
            ordinal=20 + ordinal,
        )

    with django_assert_num_queries(3):  # surah, ayah page, covering segments
        api.get('/api/surahs/2/')


def test_a_segment_without_an_ayah_range_is_not_inlined(
    api: APIClient, archive: Archive
) -> None:
    archive.other.ayah_start = None
    archive.other.ayah_end = None
    archive.other.save(update_fields=['ayah_start', 'ayah_end'])

    (first, *_) = api.get('/api/surahs/2/').json()['ayahs']['results']

    assert [segment['id'] for segment in first['segments']] == [archive.segment.pk]
    assert first['segment_count'] == 1


@pytest.fixture
def long_surah(db: None) -> None:
    clear_quran()
    make_surah(number=4, ayah_count=45, name_ar='النساء', name_en='An-Nisa')


@pytest.mark.parametrize(
    ('page', 'expected_numbers'),
    [
        (None, (1, 20)),
        (1, (1, 20)),
        (2, (21, 40)),
        (3, (41, 45)),
    ],
)
def test_surah_detail_paginates_by_twenty(
    api: APIClient, long_surah: None, page: int | None, expected_numbers: tuple[int, int]
) -> None:
    body = api.get('/api/surahs/4/', {} if page is None else {'page': page}).json()

    results = body['ayahs']['results']
    assert body['ayahs']['count'] == 45
    assert body['ayahs']['page'] == (page or 1)
    assert (results[0]['number'], results[-1]['number']) == expected_numbers


def test_surah_detail_rejects_a_page_past_the_end(api: APIClient, long_surah: None) -> None:
    assert api.get('/api/surahs/4/', {'page': 4}).status_code == 404


@pytest.mark.parametrize('page', ['0', '-1', 'last'])
def test_surah_detail_rejects_an_unusable_page(
    api: APIClient, long_surah: None, page: str
) -> None:
    response = api.get('/api/surahs/4/', {'page': page})
    assert response.status_code == 400
    assert 'page' in response.json()


def test_unknown_surah_is_404(api: APIClient, archive: Archive) -> None:
    response = api.get('/api/surahs/114/')
    assert response.status_code == 404
    assert response.headers.get('Cache-Control') != IMMUTABLE  # errors are never cached


# --- GET /api/ayahs/{surah}/{ayah}/ ------------------------------------------


def test_ayah_detail_returns_the_contract_shape(api: APIClient, archive: Archive) -> None:
    response = api.get('/api/ayahs/2/1/')

    assert response.status_code == 200
    assert response.headers['Cache-Control'] == IMMUTABLE
    body = response.json()
    assert set(body) == AYAH_KEYS
    assert (body['surah'], body['number']) == (2, 1)
    assert body['text_uthmani'] and body['text_imlaei']
    assert len(body['segments']) == 2
    (segment, _) = body['segments']
    assert set(segment) == SEGMENT_KEYS
    assert segment['duration_ms'] == 600_000
    assert isinstance(segment['duration_ms'], int)


def test_ayah_detail_lists_only_segments_that_cover_it(
    api: APIClient, archive: Archive
) -> None:
    covering = {
        number: {
            segment['id'] for segment in api.get(f'/api/ayahs/2/{number}/').json()['segments']
        }
        for number in (1, 2, 3)
    }

    assert covering == {
        1: {archive.segment.pk, archive.other.pk},
        2: {archive.segment.pk},
        3: set(),
    }


def test_a_segment_without_an_ayah_range_covers_nothing(
    api: APIClient, archive: Archive
) -> None:
    archive.other.ayah_start = None
    archive.other.ayah_end = None
    archive.other.save(update_fields=['ayah_start', 'ayah_end'])

    body = api.get('/api/ayahs/2/1/').json()

    assert [segment['id'] for segment in body['segments']] == [archive.segment.pk]


@pytest.mark.parametrize('path', ['/api/ayahs/2/99/', '/api/ayahs/9/1/'])
def test_unknown_ayah_is_404(api: APIClient, archive: Archive, path: str) -> None:
    assert api.get(path).status_code == 404


# --- GET /api/quran/locate/ --------------------------------------------------


def test_locate_resolves_a_mushaf_page_to_its_first_ayah(
    api: APIClient, long_surah: None
) -> None:
    response = api.get('/api/quran/locate/', {'page': 3})

    assert response.status_code == 200
    assert response.headers['Cache-Control'] == IMMUTABLE
    body = response.json()
    assert set(body) == LOCATION_KEYS
    # make_surah puts ten ayahs on a page, so page 3 opens on ayah 21.
    assert (body['surah'], body['number'], body['page']) == (4, 21, 3)
    assert body['surah_name_ar'] == 'النساء'


def test_locate_resolves_a_juz_to_its_first_ayah(api: APIClient, long_surah: None) -> None:
    body = api.get('/api/quran/locate/', {'juz': 1}).json()

    assert (body['surah'], body['number'], body['juz']) == (4, 1, 1)


def test_locate_takes_the_first_ayah_in_mushaf_order(api: APIClient, archive: Archive) -> None:
    """Two surahs sharing a page resolve to the earlier one, not either one."""
    make_surah(number=3, ayah_count=4, name_ar='آل عمران', name_en='Aal-Imran')

    body = api.get('/api/quran/locate/', {'page': 1}).json()

    assert (body['surah'], body['number']) == (2, 1)


@pytest.mark.parametrize('query', [{'page': 6}, {'juz': 2}])
def test_locate_past_the_end_is_404(
    api: APIClient, long_surah: None, query: dict[str, int]
) -> None:
    response = api.get('/api/quran/locate/', query)

    assert response.status_code == 404
    assert response.headers.get('Cache-Control') != IMMUTABLE  # errors are never cached


@pytest.mark.parametrize(
    'query',
    [
        {'page': '0'},
        {'juz': '-1'},
        {'page': 'last'},
        {'page': 1, 'juz': 1},  # ambiguous: which one wins?
        {},  # nothing to resolve
    ],
)
def test_locate_rejects_an_unusable_query(
    api: APIClient, long_surah: None, query: dict[str, Any]
) -> None:
    assert api.get('/api/quran/locate/', query).status_code == 400
