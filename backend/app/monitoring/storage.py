"""Raw snapshot blobs (HTML/XML/JSON) in S3-compatible storage (MinIO)."""

import asyncio
import gzip
import io
from functools import lru_cache

from minio import Minio

from app.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


@lru_cache
def _client() -> Minio:
    c = Minio(
        settings.s3_endpoint,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
        secure=settings.s3_secure,
    )
    if not c.bucket_exists(settings.s3_bucket):
        c.make_bucket(settings.s3_bucket)
    return c


def _put(key: str, data: bytes, content_type: str) -> None:
    gz = gzip.compress(data)
    _client().put_object(
        settings.s3_bucket,
        key,
        io.BytesIO(gz),
        len(gz),
        content_type=content_type,
        metadata={"Content-Encoding": "gzip"},
    )


def _get(key: str) -> bytes:
    resp = _client().get_object(settings.s3_bucket, key)
    try:
        return gzip.decompress(resp.read())
    finally:
        resp.close()
        resp.release_conn()


async def put_blob(key: str, data: bytes, content_type: str = "text/html") -> str | None:
    if not settings.s3_enabled or not data:
        return None
    try:
        await asyncio.to_thread(_put, key, data, content_type)
        return key
    except Exception as e:  # storage outage must not break monitoring
        log.warning("storage.put_failed", key=key, error=str(e)[:200])
        return None


async def get_blob(key: str) -> bytes | None:
    try:
        return await asyncio.to_thread(_get, key)
    except Exception as e:
        log.warning("storage.get_failed", key=key, error=str(e)[:200])
        return None
