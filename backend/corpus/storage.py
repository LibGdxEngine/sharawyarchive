"""S3-compatible object storage for audio, waveforms and clips.

MinIO in dev, Cloudflare R2 in production — same client code, configured by
``AUDIO_S3_*`` settings. Per project rules, raw storage keys never leave the
backend: API responses only ever carry URLs from :func:`presigned_url`.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from django.conf import settings

AUDIO_PREFIX = 'audio'
WAVEFORM_PREFIX = 'waveforms'
CLIP_PREFIX = 'clips'


@lru_cache(maxsize=1)
def get_s3_client() -> Any:
    import boto3
    from botocore.config import Config

    return boto3.client(
        's3',
        endpoint_url=settings.AUDIO_S3_ENDPOINT_URL,
        aws_access_key_id=settings.AUDIO_S3_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AUDIO_S3_SECRET_ACCESS_KEY,
        region_name=settings.AUDIO_S3_REGION,
        config=Config(signature_version='s3v4'),
    )


def audio_key(sha256: str) -> str:
    return f'{AUDIO_PREFIX}/{sha256}.opus'


def waveform_key(sha256: str) -> str:
    return f'{WAVEFORM_PREFIX}/{sha256}.json'


def clip_key(segment_id: int, start_ms: int, end_ms: int, preset: str) -> str:
    return f'{CLIP_PREFIX}/{segment_id}-{start_ms}-{end_ms}-{preset}.mp4'


def upload_bytes(key: str, data: bytes, content_type: str) -> None:
    get_s3_client().put_object(
        Bucket=settings.AUDIO_S3_BUCKET, Key=key, Body=data, ContentType=content_type
    )


def upload_file(key: str, path: str, content_type: str) -> None:
    get_s3_client().upload_file(
        path, settings.AUDIO_S3_BUCKET, key, ExtraArgs={'ContentType': content_type}
    )


def object_exists(key: str) -> bool:
    import botocore.exceptions

    try:
        get_s3_client().head_object(Bucket=settings.AUDIO_S3_BUCKET, Key=key)
    except botocore.exceptions.ClientError:
        return False
    return True


def presigned_url(key: str, ttl_seconds: int | None = None) -> str:
    return get_s3_client().generate_presigned_url(
        'get_object',
        Params={'Bucket': settings.AUDIO_S3_BUCKET, 'Key': key},
        ExpiresIn=ttl_seconds or settings.AUDIO_URL_TTL_SECONDS,
    )
