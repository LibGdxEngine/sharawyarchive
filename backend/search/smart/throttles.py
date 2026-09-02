"""Rate limiting for the smart endpoints.

DRF's :class:`ScopedRateThrottle` keyed by the raw client address would write
IPs into Redis; this one hashes the address first (daily salt, see
:func:`search.smart.cache.ip_hash`). The concurrency cap is *not* a throttle
class: DRF evaluates every throttle before the view runs and a slot must be
held for the whole request, so it lives in the view as a context manager.
"""

from __future__ import annotations

from rest_framework.request import Request
from rest_framework.throttling import ScopedRateThrottle

from .cache import ip_hash

__all__ = ["SmartRateThrottle"]


class SmartRateThrottle(ScopedRateThrottle):
    def get_ident(self, request: Request) -> str:
        return ip_hash(super().get_ident(request))
