"""Copy every object from the configured source bucket to Cloudflare R2.

Source is whatever ``AUDIO_S3_*`` currently points at (MinIO in dev).
Destination credentials come from ``R2_ACCESS_KEY_ID`` / ``R2_SECRET_ACCESS_KEY``
env vars; endpoint and bucket from ``--dest-endpoint`` / ``--dest-bucket``.

Idempotent and resumable per project rule 6: keys are content-hash derived, so
an object that already exists at the destination with the same size is skipped.
Re-running after an interruption copies only what is missing.
"""

from __future__ import annotations

import os
import tempfile
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from corpus.models import AudioAsset
from corpus.storage import audio_key, get_s3_client, waveform_key

R2_ENDPOINT_DEFAULT = 'https://6452da3166483560913682a6dd5a5b77.r2.cloudflarestorage.com'


def build_dest_client(endpoint_url: str) -> Any:
    import boto3
    from botocore.config import Config

    access_key = os.environ.get('R2_ACCESS_KEY_ID', '')
    secret_key = os.environ.get('R2_SECRET_ACCESS_KEY', '')
    if not access_key or not secret_key:
        raise CommandError('R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY must be set')
    if len(access_key) != 32:
        raise CommandError(
            f'R2_ACCESS_KEY_ID has length {len(access_key)}, expected 32. '
            'Use the S3 access key of an R2 API token, not a Cloudflare API token id.'
        )
    return boto3.client(
        's3',
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name='auto',
        config=Config(signature_version='s3v4'),
    )


def dest_size(client: Any, bucket: str, key: str) -> int | None:
    import botocore.exceptions

    try:
        head = client.head_object(Bucket=bucket, Key=key)
    except botocore.exceptions.ClientError:
        return None
    return int(head['ContentLength'])


class Command(BaseCommand):
    help = 'Sync all objects from the configured source bucket to Cloudflare R2.'

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument('--dest-endpoint', default=R2_ENDPOINT_DEFAULT)
        parser.add_argument('--dest-bucket', default='shaarawy')
        parser.add_argument('--prefix', default='', help='Only sync keys under this prefix')
        parser.add_argument(
            '--verify-only',
            action='store_true',
            help='Skip copying; only check AudioAsset keys exist at the destination',
        )

    def handle(self, *args: Any, **options: Any) -> None:
        source = get_s3_client()
        source_bucket = settings.AUDIO_S3_BUCKET
        dest = build_dest_client(options['dest_endpoint'])
        dest_bucket = options['dest_bucket']

        if not options['verify_only']:
            self._sync(source, source_bucket, dest, dest_bucket, options['prefix'])
        self._verify(dest, dest_bucket)

    def _sync(
        self, source: Any, source_bucket: str, dest: Any, dest_bucket: str, prefix: str
    ) -> None:
        copied = skipped = 0
        paginator = source.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=source_bucket, Prefix=prefix):
            for obj in page.get('Contents', []):
                key, size = obj['Key'], obj['Size']
                if dest_size(dest, dest_bucket, key) == size:
                    skipped += 1
                    continue
                head = source.head_object(Bucket=source_bucket, Key=key)
                content_type = head.get('ContentType', 'application/octet-stream')
                with tempfile.TemporaryFile() as buffer:
                    source.download_fileobj(source_bucket, key, buffer)
                    buffer.seek(0)
                    dest.upload_fileobj(
                        buffer, dest_bucket, key, ExtraArgs={'ContentType': content_type}
                    )
                if dest_size(dest, dest_bucket, key) != size:
                    raise CommandError(f'size mismatch after upload: {key}')
                copied += 1
                if copied % 25 == 0:
                    self.stdout.write(f'copied {copied}, skipped {skipped}...')
        self.stdout.write(self.style.SUCCESS(f'sync done: {copied} copied, {skipped} skipped'))

    def _verify(self, dest: Any, dest_bucket: str) -> None:
        missing: list[str] = []
        checked = 0
        for asset in AudioAsset.objects.all().iterator():
            for key in (asset.storage_key, waveform_key(asset.sha256)):
                checked += 1
                if dest_size(dest, dest_bucket, key) is None:
                    missing.append(key)
            expected = audio_key(asset.sha256)
            if asset.storage_key != expected:
                self.stdout.write(
                    self.style.WARNING(f'non-canonical storage_key: {asset.storage_key}')
                )
        if missing:
            for key in missing:
                self.stdout.write(self.style.ERROR(f'missing at destination: {key}'))
            raise CommandError(f'{len(missing)} of {checked} expected keys missing in R2')
        self.stdout.write(self.style.SUCCESS(f'verified {checked} keys present in R2'))
