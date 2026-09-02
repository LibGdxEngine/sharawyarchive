#!/usr/bin/env python3
"""Put the browser CORS policy on the Cloudflare R2 audio bucket.

The site fetches bucket objects from JavaScript in two places, and both are
silently broken while the bucket has no CORS policy at all:

* the clip composer reads ``segment.waveform_url`` to draw the overview strip,
  and a rejected fetch degrades every reader to a peakless fallback;
* offline saving (``frontend/src/lib/offline.ts``) fetches the audio and the
  waveform to put them in the Cache API.

Ordinary ``<audio src>`` / ``<video src>`` playback is *not* affected — that is
not a CORS request — which is why this went unnoticed. Nothing here grants
write access: only ``GET``/``HEAD``, and only to the site's own origins.

Idempotent (CLAUDE.md rule 6): the live policy is read first and the bucket is
only written when it differs, so re-running is a no-op that prints "unchanged".

Config, first set wins:
    --origin (repeatable) / CORS_ALLOWED_ORIGINS (comma-separated) / SITE_BASE_URL
    --endpoint / R2_ENDPOINT_URL (default below)
    --bucket   / R2_BUCKET / AUDIO_S3_BUCKET (default 'shaarawy')
    R2_ACCESS_KEY_ID     (falls back to R2_ACCESS_KEY)
    R2_SECRET_ACCESS_KEY (falls back to R2_SECRET)

Usage:
    set -a; . .env.prod; set +a
    python scripts/r2_cors.py --dry-run
    python scripts/r2_cors.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

R2_ENDPOINT_DEFAULT = 'https://6452da3166483560913682a6dd5a5b77.r2.cloudflarestorage.com'

# One hour: long enough that a reader saving a whole segment offline does not
# re-preflight per object, short enough that fixing a wrong origin list here
# takes effect the same afternoon.
MAX_AGE_SECONDS = 3600

# `Content-Range` and `Content-Length` are what make a ranged fetch of a
# 90-minute opus file readable from script; without them the browser hands
# JavaScript a response whose headers are stripped.
EXPOSE_HEADERS = ['Content-Length', 'Content-Range', 'Content-Type', 'ETag']

# Range is the one request header the audio fetches send.
ALLOWED_HEADERS = ['Range']


def _first(*values: str | None) -> str:
    for value in values:
        if value:
            return value
    return ''


def _build_client(endpoint: str, access_key: str, secret_key: str) -> Any:
    import boto3
    from botocore.config import Config

    return boto3.client(
        's3',
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name='auto',
        config=Config(signature_version='s3v4'),
    )


def _origins(explicit: list[str] | None) -> list[str]:
    """Site origins allowed to read the bucket from script.

    Deliberately never ``*``: these are presigned URLs, and a wildcard would let
    any page that gets hold of one read the bytes with credentials attached.
    """
    raw = explicit or [
        origin
        for source in (
            os.environ.get('CORS_ALLOWED_ORIGINS', ''),
            os.environ.get('SITE_BASE_URL', ''),
        )
        for origin in source.split(',')
    ]
    seen: dict[str, None] = {}
    for origin in raw:
        cleaned = origin.strip().rstrip('/')
        if cleaned and cleaned != '*':
            seen.setdefault(cleaned, None)
    return list(seen)


def cors_rules(origins: list[str]) -> list[dict[str, Any]]:
    """The policy this script maintains — read-only, and nothing else."""
    return [
        {
            'AllowedOrigins': origins,
            'AllowedMethods': ['GET', 'HEAD'],
            'AllowedHeaders': ALLOWED_HEADERS,
            'ExposeHeaders': EXPOSE_HEADERS,
            'MaxAgeSeconds': MAX_AGE_SECONDS,
        }
    ]


def _current_rules(client: Any, bucket: str) -> list[dict[str, Any]]:
    import botocore.exceptions

    try:
        return list(client.get_bucket_cors(Bucket=bucket)['CORSRules'])
    except botocore.exceptions.ClientError as exc:
        # A bucket that has never had a policy answers NoSuchCORSConfiguration
        # rather than an empty list; anything else is a real failure.
        if exc.response.get('Error', {}).get('Code') in {
            'NoSuchCORSConfiguration',
            'NoSuchCORSConfigurationError',
        }:
            return []
        raise


def _normalise(rules: list[dict[str, Any]]) -> str:
    """A comparable form: R2 echoes keys back in its own order, and omits the
    ones that are empty, so the raw dicts never compare equal to ours."""
    return json.dumps(
        [
            {
                'AllowedOrigins': sorted(rule.get('AllowedOrigins', [])),
                'AllowedMethods': sorted(rule.get('AllowedMethods', [])),
                'AllowedHeaders': sorted(rule.get('AllowedHeaders', [])),
                'ExposeHeaders': sorted(rule.get('ExposeHeaders', [])),
                'MaxAgeSeconds': rule.get('MaxAgeSeconds'),
            }
            for rule in rules
        ],
        sort_keys=True,
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--origin',
        action='append',
        default=None,
        help='Allowed site origin, repeatable. Defaults to CORS_ALLOWED_ORIGINS '
             'then SITE_BASE_URL.',
    )
    parser.add_argument('--endpoint', default=None)
    parser.add_argument('--bucket', default=None)
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Report the difference without writing the bucket.',
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    endpoint = _first(args.endpoint, os.environ.get('R2_ENDPOINT_URL'), R2_ENDPOINT_DEFAULT)
    bucket = _first(
        args.bucket, os.environ.get('R2_BUCKET'), os.environ.get('AUDIO_S3_BUCKET'), 'shaarawy'
    )
    access = _first(os.environ.get('R2_ACCESS_KEY_ID'), os.environ.get('R2_ACCESS_KEY'))
    secret = _first(os.environ.get('R2_SECRET_ACCESS_KEY'), os.environ.get('R2_SECRET'))
    origins = _origins(args.origin)

    if not access or not secret:
        print(
            'ERROR: missing R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY',
            file=sys.stderr,
        )
        return 2
    if not origins:
        print(
            'ERROR: no origins — pass --origin, or set CORS_ALLOWED_ORIGINS / '
            'SITE_BASE_URL. Refusing to write a policy nobody can use.',
            file=sys.stderr,
        )
        return 2

    print(f'bucket:  {bucket} @ {endpoint}')
    print(f'origins: {", ".join(origins)}')

    client = _build_client(endpoint, access, secret)
    wanted = cors_rules(origins)
    current = _current_rules(client, bucket)

    if _normalise(current) == _normalise(wanted):
        print('unchanged: the bucket already carries this policy')
        return 0

    print('current:', json.dumps(current, ensure_ascii=False) if current else '(none)')
    print('wanted: ', json.dumps(wanted, ensure_ascii=False))
    if args.dry_run:
        print('(dry run — nothing was written)')
        return 0

    client.put_bucket_cors(Bucket=bucket, CORSConfiguration={'CORSRules': wanted})
    print('written')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
