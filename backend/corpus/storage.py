"""S3-compatible object storage for audio, waveforms and clips.

MinIO in dev, Cloudflare R2 in production — same client code, configured by
``AUDIO_S3_*`` settings. Per project rules, raw storage keys never leave the
backend: API responses only ever carry URLs from :func:`presigned_url`.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any
from urllib.parse import quote

from django.conf import settings

AUDIO_PREFIX = 'audio'
WAVEFORM_PREFIX = 'waveforms'
CLIP_PREFIX = 'clips'

MAX_FILENAME_STEM = 60
"""Arabic costs 2 UTF-8 bytes a character, and the disposition is
percent-encoded twice before it reaches the wire — keep the signed URL short."""


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


def clip_key(
    segment_id: int, start_ms: int, end_ms: int, preset: str, output: str = 'video'
) -> str:
    """Object key of a rendered clip. ``output`` picks the container: ``mp4``
    for video cards, ``m4a`` for audio-only exports."""
    ext = 'm4a' if output == 'audio' else 'mp4'
    return f'{CLIP_PREFIX}/{segment_id}-{start_ms}-{end_ms}-{preset}-{output}.{ext}'


def upload_bytes(key: str, data: bytes, content_type: str) -> None:
    get_s3_client().put_object(
        Bucket=settings.AUDIO_S3_BUCKET, Key=key, Body=data, ContentType=content_type
    )


def upload_file(key: str, path: str, content_type: str) -> None:
    get_s3_client().upload_file(
        path, settings.AUDIO_S3_BUCKET, key, ExtraArgs={'ContentType': content_type}
    )


def download_file(key: str, dest_path: str) -> None:
    """Download an object to a local path (the inverse of :func:`upload_file`).

    Used to pull an audio master back out of storage — e.g. transcribing a
    corpus whose Opus files already live in R2 but were never processed locally.
    """
    get_s3_client().download_file(settings.AUDIO_S3_BUCKET, key, dest_path)


def object_exists(key: str) -> bool:
    import botocore.exceptions

    try:
        get_s3_client().head_object(Bucket=settings.AUDIO_S3_BUCKET, Key=key)
    except botocore.exceptions.ClientError:
        return False
    return True


@lru_cache(maxsize=1)
def _get_public_s3_client() -> Any:
    """A second S3 client pointed at the public endpoint, so presigned URLs
    are resolved from outside the Docker network."""
    import boto3
    from botocore.config import Config

    return boto3.client(
        's3',
        endpoint_url=settings.AUDIO_PUBLIC_ENDPOINT_URL,
        aws_access_key_id=settings.AUDIO_S3_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AUDIO_S3_SECRET_ACCESS_KEY,
        region_name=settings.AUDIO_S3_REGION,
        config=Config(signature_version='s3v4'),
    )


_UNSAFE_FILENAME = re.compile(r'[\x00-\x1f\x7f"\\/:*?<>|]+')


def content_disposition(filename: str) -> str:
    """An ``attachment`` disposition that survives a non-ASCII filename.

    RFC 6266: the bare ``filename=`` is a plain-ASCII fallback for clients that
    do not understand the RFC 5987 ``filename*=`` form, so an Arabic name needs
    both. The extension is split off before truncation — a clip that saves as
    ``....`` with no ``.mp4`` is worse than a clip with a shortened name.
    """
    cleaned = _UNSAFE_FILENAME.sub('', filename).strip(' .-')
    stem, _, ext = cleaned.rpartition('.')
    if stem == '':  # no extension to protect
        stem, ext = cleaned, ''
    stem = stem[:MAX_FILENAME_STEM]
    name = f'{stem}.{ext}' if ext else stem

    # Percent-encoding an Arabic character costs six ASCII bytes here, and
    # botocore encodes the whole value again when it signs the query string.
    # Pass the raw header value: pre-encoding it would save `%25D8%25A3`.
    quoted = quote(name, safe='')
    return f'attachment; filename="clip.{ext or "bin"}"; filename*=UTF-8\'\'{quoted}'


def presigned_url(
    key: str,
    ttl_seconds: int | None = None,
    *,
    download_as: str | None = None,
    content_type: str | None = None,
) -> str:
    """A signed GET URL for ``key``.

    ``download_as`` and ``content_type`` become ``response-content-disposition``
    and ``response-content-type`` overrides. They go through ``Params`` so that
    botocore folds them into the signature — appending them to an already-signed
    URL is a 403.
    """
    params: dict[str, Any] = {'Bucket': settings.AUDIO_S3_BUCKET, 'Key': key}
    if download_as is not None:
        params['ResponseContentDisposition'] = content_disposition(download_as)
    if content_type is not None:
        params['ResponseContentType'] = content_type

    return _get_public_s3_client().generate_presigned_url(
        'get_object',
        Params=params,
        ExpiresIn=ttl_seconds or settings.AUDIO_URL_TTL_SECONDS,
    )
