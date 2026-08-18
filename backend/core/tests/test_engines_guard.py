"""The production guard against the stub ASR/embedding engines.

Tested against a plain mapping rather than by importing production settings:
the point is the decision, and a real ``core.settings.prod`` import would drag
in a SECRET_KEY, a database and Sentry to get at it.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured

from core.engines_guard import ALLOW_VAR, check_engines

REAL = {'ASR_BACKEND': 'faster-whisper', 'EMBEDDING_BACKEND': 'e5'}


def test_real_backends_pass() -> None:
    check_engines(REAL)  # must not raise


def test_an_environment_that_names_neither_backend_is_refused() -> None:
    """Unset is the dangerous case, not a stray ``=stub``: base.py defaults
    both to the stub, so an operator who follows DEPLOY.md and exports nothing
    would boot a production process that fabricates transcripts."""
    with pytest.raises(ImproperlyConfigured) as caught:
        check_engines({})

    assert 'ASR_BACKEND' in str(caught.value)
    assert 'EMBEDDING_BACKEND' in str(caught.value)


@pytest.mark.parametrize('stubbed', ['ASR_BACKEND', 'EMBEDDING_BACKEND'])
def test_one_stub_backend_is_enough_to_refuse(stubbed: str) -> None:
    with pytest.raises(ImproperlyConfigured) as caught:
        check_engines({**REAL, stubbed: 'stub'})

    message = str(caught.value)
    assert stubbed in message
    assert ALLOW_VAR in message  # the message says how to override it


def test_an_empty_value_counts_as_stub() -> None:
    """``ASR_BACKEND=`` in a .env file reads as unset to base.py's default."""
    with pytest.raises(ImproperlyConfigured):
        check_engines({**REAL, 'ASR_BACKEND': ''})


@pytest.mark.parametrize('allow', ['true', 'TRUE', ' true '])
def test_a_staging_box_can_opt_in_deliberately(allow: str) -> None:
    check_engines({ALLOW_VAR: allow})  # must not raise


@pytest.mark.parametrize('allow', ['1', 'yes', 'True ish', ''])
def test_the_opt_in_takes_nothing_but_true(allow: str) -> None:
    with pytest.raises(ImproperlyConfigured):
        check_engines({ALLOW_VAR: allow})
