"""Tests for core.logging.JSONFormatter."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

import pytest

from core.logging import JSONFormatter


@pytest.fixture()
def formatter() -> JSONFormatter:
    return JSONFormatter()


def _make_record(
    msg: str = "hello",
    level: int = logging.INFO,
    exc_info: bool = False,
    request_id: str | None = None,
) -> logging.LogRecord:
    logger = logging.getLogger("test.logger")
    record = logger.makeRecord(
        name="test.logger",
        level=level,
        fn="test_logging.py",
        lno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )
    if exc_info:
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            record.exc_info = sys.exc_info()
    if request_id is not None:
        record.request_id = request_id  # type: ignore[attr-defined]
    return record


class TestJSONFormatter:
    def test_basic_keys_present(self, formatter: JSONFormatter) -> None:
        record = _make_record("test message")
        output = formatter.format(record)
        data = json.loads(output)
        assert data["level"] == "INFO"
        assert data["logger"] == "test.logger"
        assert data["message"] == "test message"
        assert "timestamp" in data

    def test_timestamp_is_a_parseable_utc_instant(self, formatter: JSONFormatter) -> None:
        """A log line's timestamp has to survive a round trip through a log
        pipeline. ``formatTime`` used to be given a ``%f`` that ``time.strftime``
        does not understand, so every record carried a literal ``"%f"`` where
        its sub-second digits should have been, and nothing could parse it."""
        record = _make_record("timed")

        stamp = json.loads(formatter.format(record))["timestamp"]

        parsed = datetime.fromisoformat(stamp)  # must not raise
        assert parsed.utcoffset() == UTC.utcoffset(None)
        assert parsed == datetime.fromtimestamp(record.created, tz=UTC)
        assert "%" not in stamp

    def test_valid_json(self, formatter: JSONFormatter) -> None:
        record = _make_record("valid json check")
        output = formatter.format(record)
        data = json.loads(output)  # must not raise
        assert isinstance(data, dict)

    def test_exception_produces_exc_info_key(self, formatter: JSONFormatter) -> None:
        record = _make_record("oops", exc_info=True)
        output = formatter.format(record)
        data = json.loads(output)
        assert "exc_info" in data
        assert "ValueError" in data["exc_info"]
        assert "boom" in data["exc_info"]

    def test_no_exc_info_key_without_exception(self, formatter: JSONFormatter) -> None:
        record = _make_record("clean record")
        output = formatter.format(record)
        data = json.loads(output)
        assert "exc_info" not in data

    def test_request_id_attached(self, formatter: JSONFormatter) -> None:
        record = _make_record("with request id", request_id="req-abc-123")
        output = formatter.format(record)
        data = json.loads(output)
        assert data["request_id"] == "req-abc-123"

    def test_no_request_id_key_when_absent(self, formatter: JSONFormatter) -> None:
        record = _make_record("no request id")
        output = formatter.format(record)
        data = json.loads(output)
        assert "request_id" not in data

    def test_warning_level(self, formatter: JSONFormatter) -> None:
        record = _make_record("warn msg", level=logging.WARNING)
        data = json.loads(formatter.format(record))
        assert data["level"] == "WARNING"
