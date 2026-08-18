"""The client's real address, behind the reverse proxy.

``REMOTE_ADDR`` is the proxy in a deployed setup, so every correction would be
filed against Caddy's address and every per-IP throttle would be one global
budget. ``X-Forwarded-For`` has the real address in it, but the header is
append-only and the *client* writes the left-hand end of it — so trusting the
first entry lets anyone forge an address and dodge the throttle.

The only trustworthy part is the tail our own infrastructure appended, which is
why this reads ``REST_FRAMEWORK['NUM_PROXIES']`` (one Caddy hop in this
deployment) and counts back from the right, exactly as DRF's throttles do.
"""

from __future__ import annotations

from django.conf import settings
from rest_framework.request import Request

__all__ = ['client_ip', 'num_proxies']


def num_proxies() -> int:
    """How many reverse-proxy hops sit in front of this process."""
    configured = settings.REST_FRAMEWORK.get('NUM_PROXIES')
    return 0 if configured is None else int(configured)


def client_ip(request: Request) -> str | None:
    """The address to attribute this request to, or ``None`` if there is none.

    With ``NUM_PROXIES = n``, the ``n`` right-most ``X-Forwarded-For`` entries
    were written by our own hops, so entry ``-n`` is the address the outermost
    one saw. With no proxies configured, or no header, ``REMOTE_ADDR`` is the
    answer.
    """
    proxies = num_proxies()
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if proxies and forwarded:
        addresses = [part.strip() for part in forwarded.split(',') if part.strip()]
        if addresses:
            return addresses[-min(proxies, len(addresses))]
    return request.META.get('REMOTE_ADDR')
