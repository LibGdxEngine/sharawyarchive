"""Tests for core.observability.maybe_init_sentry."""

from __future__ import annotations

from unittest import mock


def test_no_dsn_is_noop(monkeypatch: mock.Any) -> None:
    """Without SENTRY_DSN, sentry_sdk.init must not be called."""
    monkeypatch.delenv("SENTRY_DSN", raising=False)

    with mock.patch("sentry_sdk.init") as mock_init:
        # Re-import to get a fresh call; function is pure so direct call is fine.
        from core.observability import maybe_init_sentry

        maybe_init_sentry()
        mock_init.assert_not_called()


def test_empty_dsn_is_noop(monkeypatch: mock.Any) -> None:
    monkeypatch.setenv("SENTRY_DSN", "")

    with mock.patch("sentry_sdk.init") as mock_init:
        from core.observability import maybe_init_sentry

        maybe_init_sentry()
        mock_init.assert_not_called()


def test_dsn_calls_init(monkeypatch: mock.Any) -> None:
    monkeypatch.setenv("SENTRY_DSN", "https://key@o123.ingest.sentry.io/456")
    monkeypatch.delenv("SENTRY_TRACES_SAMPLE_RATE", raising=False)

    with (
        mock.patch("sentry_sdk.init") as mock_init,
        mock.patch("sentry_sdk.integrations.django.DjangoIntegration", autospec=True),
        mock.patch("sentry_sdk.integrations.celery.CeleryIntegration", autospec=True),
    ):
        from core.observability import maybe_init_sentry

        maybe_init_sentry()
        mock_init.assert_called_once()
        _args, kwargs = mock_init.call_args
        assert kwargs["dsn"] == "https://key@o123.ingest.sentry.io/456"
        assert kwargs["traces_sample_rate"] == 0.0


def test_traces_sample_rate_from_env(monkeypatch: mock.Any) -> None:
    monkeypatch.setenv("SENTRY_DSN", "https://key@o123.ingest.sentry.io/456")
    monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "0.25")

    with (
        mock.patch("sentry_sdk.init") as mock_init,
        mock.patch("sentry_sdk.integrations.django.DjangoIntegration", autospec=True),
        mock.patch("sentry_sdk.integrations.celery.CeleryIntegration", autospec=True),
    ):
        from core.observability import maybe_init_sentry

        maybe_init_sentry()
        _args, kwargs = mock_init.call_args
        assert kwargs["traces_sample_rate"] == 0.25
