#!/usr/bin/env python3
"""Copy a specific set of object keys from a source S3 bucket to Cloudflare R2.

This is the manifest-driven companion to ``manage.py sync_storage_to_r2``. Where
that command walks the whole source bucket and needs the Django app + DB, this
one is standalone (boto3 only) and copies exactly the keys listed in a manifest
— e.g. the ``missing_r2_keys.txt`` that ``import_segments --verify-r2`` writes.
Run it on the machine that HAS the audio (dev, where the source bucket is the
local MinIO) to backfill only what R2 is missing.

Idempotent and resumable (CLAUDE.md rule 6): a key already at the destination
with the same size is skipped, so re-running after an interruption copies only
what is still missing.

Source config (the bucket that HAS the files), first set wins:
    --source-endpoint / SRC_S3_ENDPOINT_URL / AUDIO_S3_ENDPOINT_URL
    --source-bucket   / SRC_S3_BUCKET       / AUDIO_S3_BUCKET
    SRC_S3_ACCESS_KEY_ID     / AUDIO_S3_ACCESS_KEY_ID
    SRC_S3_SECRET_ACCESS_KEY / AUDIO_S3_SECRET_ACCESS_KEY

Destination config (Cloudflare R2):
    --dest-endpoint / R2_ENDPOINT_URL (default below)
    --dest-bucket   / R2_BUCKET (default 'shaarawy')
    R2_ACCESS_KEY_ID     (falls back to R2_ACCESS_KEY)
    R2_SECRET_ACCESS_KEY (falls back to R2_SECRET)

Usage:
    # load dev + real secrets, then sync the missing keys:
    set -a; . .env.dev; . .env.local; set +a
    python scripts/sync_missing_to_r2.py --manifest scripts/missing_r2_keys.txt

    python scripts/sync_missing_to_r2.py --manifest scripts/missing_r2_keys.txt --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from typing import Any

R2_ENDPOINT_DEFAULT = 'https://6452da3166483560913682a6dd5a5b77.r2.cloudflarestorage.com'


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


def _size(client: Any, bucket: str, key: str) -> int | None:
    import botocore.exceptions

    try:
        head = client.head_object(Bucket=bucket, Key=key)
    except botocore.exceptions.ClientError:
        return None
    return int(head['ContentLength'])


def _load_manifest(path: str) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            key = line.strip()
            if key and key not in seen:
                seen.add(key)
                keys.append(key)
    return keys


def _guess_content_type(key: str, source_ct: str | None) -> str:
    if source_ct and source_ct != 'application/octet-stream':
        return source_ct
    if key.endswith('.opus'):
        return 'audio/opus'
    if key.endswith('.json'):
        return 'application/json'
    if key.endswith('.mp4'):
        return 'video/mp4'
    if key.endswith('.m4a'):
        return 'audio/mp4'
    return 'application/octet-stream'


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--manifest',
        default='scripts/missing_r2_keys.txt',
        help='File of object keys to copy, one per line (default: %(default)s).',
    )
    parser.add_argument('--source-endpoint', default=None)
    parser.add_argument('--source-bucket', default=None)
    parser.add_argument('--dest-endpoint', default=None)
    parser.add_argument('--dest-bucket', default=None)
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Report what would copy without transferring anything.',
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    src_endpoint = _first(args.source_endpoint, os.environ.get('SRC_S3_ENDPOINT_URL'),
                          os.environ.get('AUDIO_S3_ENDPOINT_URL'))
    src_bucket = _first(args.source_bucket, os.environ.get('SRC_S3_BUCKET'),
                       os.environ.get('AUDIO_S3_BUCKET'))
    src_access = _first(os.environ.get('SRC_S3_ACCESS_KEY_ID'),
                       os.environ.get('AUDIO_S3_ACCESS_KEY_ID'))
    src_secret = _first(os.environ.get('SRC_S3_SECRET_ACCESS_KEY'),
                       os.environ.get('AUDIO_S3_SECRET_ACCESS_KEY'))

    dest_endpoint = _first(args.dest_endpoint, os.environ.get('R2_ENDPOINT_URL'),
                          R2_ENDPOINT_DEFAULT)
    dest_bucket = _first(args.dest_bucket, os.environ.get('R2_BUCKET'), 'shaarawy')
    dest_access = _first(os.environ.get('R2_ACCESS_KEY_ID'), os.environ.get('R2_ACCESS_KEY'))
    dest_secret = _first(os.environ.get('R2_SECRET_ACCESS_KEY'), os.environ.get('R2_SECRET'))

    missing_cfg = []
    if not src_endpoint or not src_access or not src_secret:
        missing_cfg.append('source (SRC_S3_* or AUDIO_S3_*)')
    if not dest_access or not dest_secret:
        missing_cfg.append('destination (R2_ACCESS_KEY_ID/R2_SECRET_ACCESS_KEY)')
    if missing_cfg:
        print(f'ERROR: missing credentials for: {", ".join(missing_cfg)}', file=sys.stderr)
        return 2

    if src_endpoint == dest_endpoint and src_bucket == dest_bucket:
        print(
            'ERROR: source and destination are the same bucket — run this on the '
            'machine that HAS the audio (dev), not against R2 itself.',
            file=sys.stderr,
        )
        return 2

    keys = _load_manifest(args.manifest)
    print(f'manifest: {len(keys)} key(s) from {args.manifest}')
    print(f'source:   {src_bucket} @ {src_endpoint}')
    print(f'dest:     {dest_bucket} @ {dest_endpoint}')
    if args.dry_run:
        print('(dry run — nothing will be transferred)')

    source = _build_client(src_endpoint, src_access, src_secret)
    dest = _build_client(dest_endpoint, dest_access, dest_secret)

    copied = skipped = absent_at_source = failed = 0
    for i, key in enumerate(keys, start=1):
        src_size = _size(source, src_bucket, key)
        if src_size is None:
            absent_at_source += 1
            print(f'  MISSING AT SOURCE: {key}', file=sys.stderr)
            continue
        if _size(dest, dest_bucket, key) == src_size:
            skipped += 1
            continue
        if args.dry_run:
            copied += 1
            continue
        head = source.head_object(Bucket=src_bucket, Key=key)
        content_type = _guess_content_type(key, head.get('ContentType'))
        try:
            with tempfile.TemporaryFile() as buffer:
                source.download_fileobj(src_bucket, key, buffer)
                buffer.seek(0)
                dest.upload_fileobj(
                    buffer, dest_bucket, key, ExtraArgs={'ContentType': content_type}
                )
            if _size(dest, dest_bucket, key) != src_size:
                failed += 1
                print(f'  SIZE MISMATCH AFTER UPLOAD: {key}', file=sys.stderr)
                continue
        except Exception as exc:  # noqa: BLE001 — report and continue, resumable
            failed += 1
            print(f'  FAILED: {key}: {exc}', file=sys.stderr)
            continue
        copied += 1
        if copied % 50 == 0:
            print(f'  ...{copied} copied, {skipped} skipped ({i}/{len(keys)})')

    verb = 'would copy' if args.dry_run else 'copied'
    print(
        f'done: {verb} {copied}, skipped {skipped} (already present), '
        f'{absent_at_source} missing at source, {failed} failed'
    )
    # Non-zero exit if anything could not be delivered, so callers/cron notice.
    return 1 if (absent_at_source or failed) else 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
