"""The two caps that keep smart search affordable and the site responsive.

* **Daily spend** — micro-dollars accumulated in the Django cache (Redis) under
  ``smart:spend:<UTC date>``; every provider call adds its cost, and no call
  starts once the day's total reaches ``SMART_DAILY_BUDGET_USD``.
* **In-flight requests** — a Redis sorted set of lease tokens scored by time.
  Acquiring is one Lua script (prune stale leases, count, add), so a worker
  that dies mid-request leaks nothing for longer than the lease.

Both live in the same Redis database as the throttle counters, which is also
what the test suite flushes between tests.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from functools import lru_cache
from uuid import uuid4

import redis
from django.conf import settings
from django.core.cache import cache

__all__ = [
    "add_spend",
    "inflight_count",
    "inflight_slot",
    "over_budget",
    "redis_client",
    "spend_key",
    "spend_today",
]

MICRO_USD = 1_000_000
SPEND_TTL_S = 48 * 3600
INFLIGHT_KEY = "smart:inflight"
INFLIGHT_LEASE_S = 90
"""A lease older than this is a request that never released its slot."""

_ACQUIRE = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1])
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[2]) then
  return 0
end
redis.call('ZADD', KEYS[1], ARGV[3], ARGV[4])
redis.call('EXPIRE', KEYS[1], ARGV[5])
return 1
"""


def spend_key(day: date | None = None) -> str:
    day = day or datetime.now(UTC).date()
    return f"smart:spend:{day.isoformat()}"


def add_spend(cost: Decimal | None) -> None:
    """Record ``cost`` (USD) against today's total; ``None``/zero is a no-op."""
    if cost is None or cost <= 0:
        return
    key = spend_key()
    delta = int(cost * MICRO_USD)
    cache.add(key, 0, timeout=SPEND_TTL_S)
    try:
        cache.incr(key, delta)
    except ValueError:  # the key expired between add and incr
        cache.set(key, delta, timeout=SPEND_TTL_S)


def spend_today() -> Decimal:
    return Decimal(int(cache.get(spend_key(), 0) or 0)) / MICRO_USD


def over_budget() -> bool:
    return spend_today() >= Decimal(str(settings.SMART_DAILY_BUDGET_USD))


@lru_cache(maxsize=1)
def redis_client() -> redis.Redis:
    """A raw client on the cache's Redis database (the ZSET needs commands the cache API lacks)."""
    return redis.Redis.from_url(settings.CACHES["default"]["LOCATION"])


@contextmanager
def inflight_slot(limit: int | None = None) -> Iterator[bool]:
    """Hold one of the ``limit`` concurrent smart-search slots for the block.

    Yields ``True`` when a slot was acquired (and releases it afterwards) or
    ``False`` when all slots are busy — the caller then answers 429.
    """
    limit = settings.SMART_MAX_INFLIGHT if limit is None else limit
    token = uuid4().hex
    now = time.time()
    acquired = bool(
        redis_client().eval(
            _ACQUIRE,
            1,
            INFLIGHT_KEY,
            now - INFLIGHT_LEASE_S,
            limit,
            now,
            token,
            INFLIGHT_LEASE_S * 2,
        )
    )
    try:
        yield acquired
    finally:
        if acquired:
            redis_client().zrem(INFLIGHT_KEY, token)


def inflight_count() -> int:
    client = redis_client()
    client.zremrangebyscore(INFLIGHT_KEY, "-inf", time.time() - INFLIGHT_LEASE_S)
    return int(client.zcard(INFLIGHT_KEY))
