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
}
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
