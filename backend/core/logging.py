"""Dependency-free JSON log formatter for production.

Each log record is emitted as a single-line JSON object with these keys:
  timestamp  — ISO-8601 UTC, e.g. "2024-01-15T12:34:56.789123+00:00"
  level      — "INFO", "WARNING", …
  logger     — logger name ("django.request", "celery.task", …)
  message    — the formatted message string
  exc_info   — formatted traceback string, present only when an exception is
                attached to the record
  request_id — present only when set on the record (attach via middleware that
                calls ``record.request_id = <id>`` before emitting)

Usage in LOGGING dict::

    "formatters": {
        "json": {
            "()": "core.logging.JSONFormatter",
        }
    }
"""

from __future__ import annotations

import json
import logging


class JSONFormatter(logging.Formatter):
    """Format a :class:`logging.LogRecord` as a compact JSON line."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: A002
        # Ensure record.message is populated (sets record.message from args).
        record.getMessage()

        payload: dict[str, object] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S.%f+00:00"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        elif record.exc_text:
            payload["exc_info"] = record.exc_text

        request_id = getattr(record, "request_id", None)
        if request_id is not None:
            payload["request_id"] = request_id

        return json.dumps(payload, ensure_ascii=False)
