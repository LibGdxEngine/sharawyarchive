"""Resolving the client's address behind the reverse proxy (``api.ip``)."""

from __future__ import annotations

import pytest
from django.test import RequestFactory
from pytest_django.fixtures import Settings
from rest_framework.request import Request

from api.ip import client_ip, num_proxies

PROXY = '10.0.0.2'
"""What REMOTE_ADDR is in a deployed setup: Caddy, not a reader."""

CADDY_SAW = '203.0.113.9'
CLIENT_CLAIMED = '198.51.100.7'
"""A value the client put in X-Forwarded-For itself. Forgeable, so unusable."""


def _request(**meta: str) -> Request:
    return Request(RequestFactory().get('/api/corrections/', REMOTE_ADDR=PROXY, **meta))


@pytest.fixture
def proxies(settings: Settings) -> None:
    """One hop, which is the deployed topology (Caddy → gunicorn)."""
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, 'NUM_PROXIES': 1}


def test_the_deployed_topology_is_one_hop(settings: Settings) -> None:
    assert num_proxies() == 1


def test_the_hop_our_proxy_wrote_is_the_one_trusted(proxies: None) -> None:
    """Caddy appends the address it saw, so the right-most entry is ours and
    everything to the left of it is the client talking about itself."""
    address = client_ip(
        _request(HTTP_X_FORWARDED_FOR=f'{CLIENT_CLAIMED}, {CADDY_SAW}')
    )

    assert address == CADDY_SAW


def test_a_forged_header_cannot_move_the_address(proxies: None) -> None:
    """Otherwise one reader spends everyone's throttle budget, or nobody's."""
    forged = client_ip(
        _request(HTTP_X_FORWARDED_FOR=f'1.1.1.1, 2.2.2.2, 3.3.3.3, {CADDY_SAW}')
    )

    assert forged == CADDY_SAW


def test_a_single_entry_is_taken_as_written(proxies: None) -> None:
    assert client_ip(_request(HTTP_X_FORWARDED_FOR=CADDY_SAW)) == CADDY_SAW


def test_no_forwarded_header_falls_back_to_the_peer(proxies: None) -> None:
    """A request that did not come through the proxy at all — a health probe on
    the pod network, say."""
    assert client_ip(_request()) == PROXY


def test_without_proxies_the_header_is_ignored_entirely(settings: Settings) -> None:
    """Zero hops means nothing in front of us wrote that header, so every entry
    in it is the client's own claim."""
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, 'NUM_PROXIES': 0}

    assert client_ip(_request(HTTP_X_FORWARDED_FOR=CLIENT_CLAIMED)) == PROXY


def test_whitespace_and_empty_entries_do_not_shift_the_count(proxies: None) -> None:
    address = client_ip(
        _request(HTTP_X_FORWARDED_FOR=f' {CLIENT_CLAIMED} , , {CADDY_SAW} ')
    )

    assert address == CADDY_SAW
