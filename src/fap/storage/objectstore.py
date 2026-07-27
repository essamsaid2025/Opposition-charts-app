"""Object-storage backends (Phase 11.2).

Every uploaded asset — player/club/team logos, report images, generated chart
PNGs, PDF assets, uploaded documents, video thumbnails and dataset frames — can
move off local disk to S3-compatible object storage (AWS S3 / Cloudflare R2 /
Backblaze B2 / MinIO) with **no change to any consumer**: these classes implement
the very same ``ImageStorage`` / ``FileStorage`` / ``DatasetStorage`` interfaces
the services already depend on. Selection is a bootstrap config detail.

Design:

* ``ObjectStore`` — a tiny key/bytes interface (put/get/exists/delete/size/
  content_type). ``S3ObjectStore`` is the production driver (boto3, lazy-imported
  and guarded); ``MemoryObjectStore`` is an in-process implementation used for
  tests/dev so the three storage adapters are verifiable without a network.
* The three adapters keep assets under stable, prefixed keys and carry the mime
  type in object metadata (Content-Type) — no per-load LIST, no suffix guessing.
"""
from __future__ import annotations

import io
import logging
from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

from fap.config.settings import StorageSettings
from fap.core.exceptions import ConfigurationError
from fap.storage.base import DatasetStorage, safe_name
from fap.storage.files import FileStorage, _suffix_for
from fap.storage.images import ALLOWED_MIME, EXT_BY_SUFFIX, ImageStorage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- object store
class ObjectStore(ABC):
    """A minimal blob interface: bytes in, bytes out, addressed by key."""

    @abstractmethod
    def put(self, key: str, data: bytes, content_type: str = "") -> None: ...
    @abstractmethod
    def get(self, key: str) -> bytes | None: ...
    @abstractmethod
    def exists(self, key: str) -> bool: ...
    @abstractmethod
    def delete(self, key: str) -> None: ...
    @abstractmethod
    def size(self, key: str) -> int: ...
    @abstractmethod
    def content_type(self, key: str) -> str: ...


class MemoryObjectStore(ObjectStore):
    """In-process object store (dict of key -> (bytes, content_type)). For tests,
    development, and as the reference the S3 driver is checked against."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[bytes, str]] = {}

    def put(self, key: str, data: bytes, content_type: str = "") -> None:
        self._data[key] = (bytes(data), content_type or "application/octet-stream")

    def get(self, key: str) -> bytes | None:
        item = self._data.get(key)
        return item[0] if item else None

    def exists(self, key: str) -> bool:
        return key in self._data

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def size(self, key: str) -> int:
        item = self._data.get(key)
        return len(item[0]) if item else 0

    def content_type(self, key: str) -> str:
        item = self._data.get(key)
        return item[1] if item else ""


class S3ObjectStore(ObjectStore):
    """S3-compatible object store (AWS S3 / R2 / B2 / MinIO) via boto3. The driver
    is lazy-imported and guarded; construction fails loudly with actionable text
    when boto3 or the bucket is missing, so a misconfiguration surfaces at boot."""

    def __init__(self, settings: StorageSettings) -> None:
        if not settings.bucket:
            raise ConfigurationError("storage.backend='s3' requires storage.bucket.")
        try:
            import boto3                              # type: ignore
            from botocore.config import Config        # type: ignore
        except Exception as exc:
            raise ConfigurationError(
                "storage.backend='s3' requires boto3 (`pip install boto3`). "
                "Install it, or use storage.backend='local'.") from exc
        self._bucket = settings.bucket
        client_kw: dict[str, Any] = {
            "region_name": settings.region or None,
            "use_ssl": settings.use_ssl,
            "config": Config(retries={"max_attempts": 3, "mode": "standard"}),
        }
        if settings.endpoint_url:
            client_kw["endpoint_url"] = settings.endpoint_url
        if settings.access_key_id and settings.secret_access_key:
            client_kw["aws_access_key_id"] = settings.access_key_id
            client_kw["aws_secret_access_key"] = settings.secret_access_key
        self._s3 = boto3.client("s3", **client_kw)

    def put(self, key: str, data: bytes, content_type: str = "") -> None:
        self._s3.put_object(Bucket=self._bucket, Key=key, Body=bytes(data),
                            ContentType=content_type or "application/octet-stream")

    def get(self, key: str) -> bytes | None:
        try:
            obj = self._s3.get_object(Bucket=self._bucket, Key=key)
            return obj["Body"].read()
        except Exception:
            return None

    def _head(self, key: str) -> dict[str, Any] | None:
        try:
            return self._s3.head_object(Bucket=self._bucket, Key=key)
        except Exception:
            return None

    def exists(self, key: str) -> bool:
        return self._head(key) is not None

    def delete(self, key: str) -> None:
        try:
            self._s3.delete_object(Bucket=self._bucket, Key=key)
        except Exception:
            logger.warning("delete failed for %s", key, exc_info=True)

    def size(self, key: str) -> int:
        head = self._head(key)
        return int(head.get("ContentLength", 0)) if head else 0

    def content_type(self, key: str) -> str:
        head = self._head(key)
        return str(head.get("ContentType", "")) if head else ""


def make_object_store(settings: StorageSettings) -> ObjectStore:
    """Build the object store for the configured storage backend (S3 today)."""
    return S3ObjectStore(settings)


# ---------------------------------------------------------------- adapters
def _join(prefix: str, *parts: str) -> str:
    segments = [p.strip("/") for p in (prefix, *parts) if p]
    return "/".join(segments)


class ObjectImageStorage(ImageStorage):
    """``ImageStorage`` over an object store. Mime is carried as the object's
    Content-Type (no suffix guessing, no LIST on read)."""

    def __init__(self, store: ObjectStore, prefix: str = "") -> None:
        self._store = store
        self._prefix = prefix

    def _key(self, image_id: str) -> str:
        return _join(self._prefix, "images", safe_name(image_id))

    def save(self, image_id: str, data: bytes, mime: str) -> str:
        if mime.lower() not in ALLOWED_MIME:
            raise ValueError(f"Unsupported image type {mime!r}. "
                             f"Allowed: {', '.join(sorted(ALLOWED_MIME))}")
        key = self._key(image_id)
        self._store.put(key, data, mime.lower())
        return key

    def load(self, image_id: str) -> bytes | None:
        return self._store.get(self._key(image_id))

    def mime(self, image_id: str) -> str:
        return self._store.content_type(self._key(image_id))

    def exists(self, image_id: str) -> bool:
        return self._store.exists(self._key(image_id))

    def delete(self, image_id: str) -> None:
        self._store.delete(self._key(image_id))


class ObjectFileStorage(FileStorage):
    """``FileStorage`` over an object store for large binaries (videos,
    attachments, PDFs, documents, thumbnails)."""

    def __init__(self, store: ObjectStore, prefix: str = "", namespace: str = "files") -> None:
        self._store = store
        self._prefix = prefix
        self._ns = namespace

    def _key(self, file_id: str) -> str:
        return _join(self._prefix, self._ns, safe_name(file_id))

    def save(self, file_id: str, data: bytes, filename: str = "", mime: str = "") -> str:
        import mimetypes
        ctype = mime or mimetypes.guess_type(filename or "")[0] or "application/octet-stream"
        key = self._key(file_id)
        self._store.put(key, data, ctype)
        return key

    def load(self, file_id: str) -> bytes | None:
        return self._store.get(self._key(file_id))

    def path(self, file_id: str) -> str:
        # object storage has no local path; the key is the durable locator
        return self._key(file_id) if self._store.exists(self._key(file_id)) else ""

    def mime(self, file_id: str) -> str:
        return self._store.content_type(self._key(file_id))

    def exists(self, file_id: str) -> bool:
        return self._store.exists(self._key(file_id))

    def size_bytes(self, file_id: str) -> int:
        return self._store.size(self._key(file_id))

    def delete(self, file_id: str) -> None:
        self._store.delete(self._key(file_id))


class ObjectDatasetStorage(DatasetStorage):
    """``DatasetStorage`` over an object store. Frames serialise to Parquet bytes
    (zstd) and stream to/from the bucket; pickle is the same last-resort fallback
    the local backend uses when no Parquet engine is available."""

    def __init__(self, store: ObjectStore, prefix: str = "", compression: str = "zstd") -> None:
        self._store = store
        self._prefix = prefix
        self._compression = compression

    def _key(self, dataset_id: str, kind: str = "parquet") -> str:
        return _join(self._prefix, "datasets", f"{safe_name(dataset_id)}.{kind}")

    def _existing_key(self, dataset_id: str) -> str | None:
        for kind in ("parquet", "pkl"):
            key = self._key(dataset_id, kind)
            if self._store.exists(key):
                return key
        return None

    def save(self, dataset_id: str, frame: pd.DataFrame) -> str:
        buf = io.BytesIO()
        try:
            frame.to_parquet(buf, engine="pyarrow", compression=self._compression)
            key = self._key(dataset_id, "parquet")
            self._store.put(key, buf.getvalue(), "application/vnd.apache.parquet")
            self._store.delete(self._key(dataset_id, "pkl"))
            return key
        except Exception:
            logger.warning("Parquet encode failed for %s; pickle fallback", dataset_id,
                           exc_info=True)
            buf = io.BytesIO()
            frame.to_pickle(buf)
            key = self._key(dataset_id, "pkl")
            self._store.put(key, buf.getvalue(), "application/octet-stream")
            self._store.delete(self._key(dataset_id, "parquet"))
            return key

    def load(self, dataset_id: str) -> pd.DataFrame | None:
        key = self._existing_key(dataset_id)
        if key is None:
            return None
        data = self._store.get(key)
        if data is None:
            return None
        try:
            buf = io.BytesIO(data)
            return pd.read_parquet(buf) if key.endswith(".parquet") else pd.read_pickle(buf)
        except Exception:
            logger.exception("Could not read stored dataset %s", dataset_id)
            return None

    def exists(self, dataset_id: str) -> bool:
        return self._existing_key(dataset_id) is not None

    def delete(self, dataset_id: str) -> None:
        self._store.delete(self._key(dataset_id, "parquet"))
        self._store.delete(self._key(dataset_id, "pkl"))

    def size_bytes(self, dataset_id: str) -> int:
        key = self._existing_key(dataset_id)
        return self._store.size(key) if key else 0
