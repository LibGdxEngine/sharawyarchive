"""Response-cache keys and the request-side hashes.

The cache key carries the prompt version and the embedding model tag, so a
prompt bump or a model change invalidates every cached answer without any
flush. Client addresses are only ever stored as a daily-salted hash.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any

from django.conf import settings
from django.core.cache import cache

from corpus.arabic import normalize_for_index

from . import embedding_model_tag
from .prompts import PROMPT_VERSION

__all__ = ["get_response", "ip_hash", "question_hash", "response_key", "set_response"]


def question_hash(question: str, filters: Mapping[str, Any] | None = None) -> str:
    """sha256 of the normalized question plus any non-empty filters.

    Diacritics, hamza forms and whitespace differences collapse (CLAUDE.md
    rule 2), so «ما رأي الشيخ» and «ما رأى الشيخ» share one cache entry.
    """
    clean_filters = {key: value for key, value in (filters or {}).items() if value is not None}
    payload = json.dumps(
        {"q": normalize_for_index(question), "f": clean_filters},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def response_key(qhash: str) -> str:
    return f"smart:{PROMPT_VERSION}:{embedding_model_tag()}:{qhash}"


def get_response(qhash: str) -> dict[str, Any] | None:
    value = cache.get(response_key(qhash))
    return value if isinstance(value, dict) else None


def set_response(qhash: str, payload: Mapping[str, Any]) -> None:
    cache.set(response_key(qhash), dict(payload), timeout=settings.SMART_CACHE_TTL_S)


def ip_hash(ip: str | None, *, day: date | None = None) -> str:
    """A 32-hex digest of the client address, salted with the secret and the day.

    Good enough to count a client's requests within a day and to spot abuse
    in the logs; useless for identifying anyone after the day has passed.
    """
    if not ip:
        return ""
    day = day or datetime.now(UTC).date()
    material = f"{settings.SECRET_KEY}:{day.isoformat()}:{ip}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]
