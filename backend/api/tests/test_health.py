"""GET /healthz and GET /readyz (API_CONTRACT.md, "Health")."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from django.test import Client

from api import views

DEPENDENCIES = ('db', 'redis', 'meilisearch')


@pytest.fixture
def client() -> Client:
    return Client()


@pytest.fixture
def all_checks_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in DEPENDENCIES:
        monkeypatch.setitem(views.CHECKS, name, lambda: True)


def _fail(name: str, check: Callable[[], bool], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(views.CHECKS, name, check)


# --- liveness ----------------------------------------------------------------


def test_healthz_answers_without_any_dependency(client: Client) -> None:
    """No ``db`` fixture: pytest-django would raise if this view hit Postgres."""
    response = client.get('/healthz')

    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}
    assert response.headers['Content-Type'] == 'application/json'


def test_healthz_is_get_only(client: Client) -> None:
    assert client.post('/healthz').status_code == 405


# --- readiness ---------------------------------------------------------------


def test_readyz_is_200_when_every_dependency_answers(
    client: Client, all_checks_pass: None
) -> None:
    response = client.get('/readyz')

    assert response.status_code == 200
    assert response.json() == {'db': True, 'redis': True, 'meilisearch': True}


@pytest.mark.parametrize('broken', DEPENDENCIES)
def test_readyz_is_503_and_names_the_dependency_that_is_down(
    client: Client, all_checks_pass: None, monkeypatch: pytest.MonkeyPatch, broken: str
) -> None:
    _fail(broken, lambda: False, monkeypatch)

    response = client.get('/readyz')

    assert response.status_code == 503
    body = response.json()
    assert body[broken] is False
    assert all(body[name] for name in DEPENDENCIES if name != broken)


def test_readyz_treats_a_raising_check_as_down(
    client: Client, all_checks_pass: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode() -> bool:
        raise ConnectionError('redis is not listening')

    _fail('redis', explode, monkeypatch)

    response = client.get('/readyz')

    assert response.status_code == 503
    assert response.json()['redis'] is False


def test_readyz_is_get_only(client: Client, all_checks_pass: None) -> None:
    assert client.post('/readyz').status_code == 405


@pytest.mark.django_db
def test_the_database_check_runs_a_real_query() -> None:
    assert views.CHECKS['db']() is True
