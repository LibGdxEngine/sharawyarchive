"""Per-IP throttles (API_CONTRACT.md, "Throttles").

The tests run at a deliberately tiny rate so they finish in milliseconds; the
production rates are asserted separately against the settings themselves. The
``reset_throttles`` fixture wipes the throttle history, which otherwise lives in
the process cache and leaks between tests.
"""

from __future__ import annotations

import pytest
from pytest_django.fixtures import Settings
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle

from api.tests.factories import Archive
from clips.models import Clip
from corpus.models import Correction

CONTRACT_RATES = {'search': '30/min', 'corrections': '10/hour', 'clips': '5/hour'}
TEST_LIMIT = 3


@pytest.fixture
def tight_rates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shrink every scope to :data:`TEST_LIMIT` requests.

    ``SimpleRateThrottle.THROTTLE_RATES`` is bound to the settings dict at
    import time, so overriding ``REST_FRAMEWORK`` at runtime would not reach
    it; the class attribute is the thing to patch.
    """
    monkeypatch.setattr(
        SimpleRateThrottle,
        'THROTTLE_RATES',
        dict.fromkeys(CONTRACT_RATES, f'{TEST_LIMIT}/min'),
    )


def test_configured_rates_match_the_contract(settings: Settings) -> None:
    assert settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'] == CONTRACT_RATES


def test_search_starts_refusing_once_the_rate_is_spent(
    api: APIClient, tight_rates: None
) -> None:
    """A malformed query still costs quota — the throttle runs before the view,
    so an attacker cannot spend the corpus by sending garbage."""
    for _ in range(TEST_LIMIT):
        assert api.get('/api/search/').status_code == 400

    response = api.get('/api/search/')

    assert response.status_code == 429
    assert response.headers['Retry-After']
    assert 'detail' in response.json()


@pytest.mark.django_db
def test_corrections_stop_after_the_rate_is_spent(
    api: APIClient, tight_rates: None, archive: Archive
) -> None:
    body = {
        'chunk_id': archive.chunks[0].pk,
        'word_start': 0,
        'word_end': 1,
        'suggested_text': 'الصبر',
    }
    for _ in range(TEST_LIMIT):
        assert api.post('/api/corrections/', body, format='json').status_code == 201

    response = api.post('/api/corrections/', body, format='json')

    assert response.status_code == 429
    assert response.headers['Retry-After']
    assert Correction.objects.count() == TEST_LIMIT


@pytest.mark.django_db
def test_clips_stop_after_the_rate_is_spent(
    api: APIClient, tight_rates: None, archive: Archive
) -> None:
    presets = ['classic', 'night', 'light']
    for index in range(TEST_LIMIT):
        body = {
            'segment_id': archive.segment.pk,
            'start_ms': 0,
            'end_ms': 20_000,
            'preset': presets[index],
        }
        assert api.post('/api/clips/', body, format='json').status_code == 202

    response = api.post(
        '/api/clips/',
        {
            'segment_id': archive.segment.pk,
            'start_ms': 60_000,
            'end_ms': 80_000,
            'preset': 'night',
        },
        format='json',
    )

    assert response.status_code == 429
    assert response.headers['Retry-After']
    assert Clip.objects.count() == TEST_LIMIT


@pytest.mark.django_db
def test_the_scopes_have_separate_budgets(
    api: APIClient, tight_rates: None, archive: Archive
) -> None:
    """Spending the search budget must not lock a reader out of corrections."""
    for _ in range(TEST_LIMIT + 1):
        api.get('/api/search/')

    response = api.post(
        '/api/corrections/',
        {
            'chunk_id': archive.chunks[0].pk,
            'word_start': 0,
            'word_end': 1,
            'suggested_text': 'الصبر',
        },
        format='json',
    )

    assert response.status_code == 201
