"""Image asset storage - upload once, reference many times.

Report blocks (and covers) store an ``image_id``; the bytes live here exactly
once, on the same persistent tier as datasets, so images survive cache expiry,
restarts and redeploys. Same strategy pattern as DatasetStorage: swap for
object storage without touching reports.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path

from fap.storage.base import safe_name

logger = logging.getLogger(__name__)

#: what the image manager accepts
ALLOWED_MIME = {
    "image/png": ".png", "image/jpeg": ".jpg", "image/jpg": ".jpg",
    "image/svg+xml": ".svg", "image/webp": ".webp",
}
EXT_BY_SUFFIX = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                 ".svg": "image/svg+xml", ".webp": "image/webp"}


class ImageStorage(ABC):
    @abstractmethod
    def save(self, image_id: str, data: bytes, mime: str) -> str: ...
    @abstractmethod
    def load(self, image_id: str) -> bytes | None: ...
    @abstractmethod
    def mime(self, image_id: str) -> str: ...
    @abstractmethod
    def exists(self, image_id: str) -> bool: ...
    @abstractmethod
    def delete(self, image_id: str) -> None: ...


class LocalImageStorage(ImageStorage):
    """One file per image under ``root``; the suffix carries the mime type."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _find(self, image_id: str) -> Path | None:
        stem = safe_name(image_id)
        for path in self._root.glob(f"{stem}.*"):
            if path.is_file():
                return path
        return None

    def save(self, image_id: str, data: bytes, mime: str) -> str:
        suffix = ALLOWED_MIME.get(mime.lower())
        if suffix is None:
            raise ValueError(f"Unsupported image type {mime!r}. "
                             f"Allowed: {', '.join(sorted(ALLOWED_MIME))}")
        existing = self._find(image_id)
        if existing:
            existing.unlink(missing_ok=True)
        path = self._root / f"{safe_name(image_id)}{suffix}"
        path.write_bytes(data)
        return str(path)

    def load(self, image_id: str) -> bytes | None:
        path = self._find(image_id)
        return path.read_bytes() if path else None

    def mime(self, image_id: str) -> str:
        path = self._find(image_id)
        return EXT_BY_SUFFIX.get(path.suffix.lower(), "application/octet-stream") if path else ""

    def exists(self, image_id: str) -> bool:
        return self._find(image_id) is not None

    def delete(self, image_id: str) -> None:
        path = self._find(image_id)
        if path:
            path.unlink(missing_ok=True)
