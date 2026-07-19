"""Local file storage - the persistent tier for large binary assets (videos and
attachments). Same strategy pattern as DatasetStorage/ImageStorage: one file per
id under a root, the original suffix preserved, swappable for object storage
later without touching any consumer.

This is the single new storage abstraction added in Phase 8.0. It is generic
(any mime), so uploaded videos live in ``user_data/videos`` and attachments in
``user_data/attachments`` through two instances of the SAME class - no per-type
storage zoo. External videos (YouTube/Vimeo/Hudl/...) store metadata only and
never touch this tier.
"""
from __future__ import annotations

import mimetypes
from abc import ABC, abstractmethod
from pathlib import Path

from fap.storage.base import safe_name


class FileStorage(ABC):
    @abstractmethod
    def save(self, file_id: str, data: bytes, filename: str = "", mime: str = "") -> str: ...
    @abstractmethod
    def load(self, file_id: str) -> bytes | None: ...
    @abstractmethod
    def path(self, file_id: str) -> str: ...
    @abstractmethod
    def mime(self, file_id: str) -> str: ...
    @abstractmethod
    def exists(self, file_id: str) -> bool: ...
    @abstractmethod
    def size_bytes(self, file_id: str) -> int: ...
    @abstractmethod
    def delete(self, file_id: str) -> None: ...


def _suffix_for(filename: str, mime: str) -> str:
    if filename and "." in filename:
        return "." + filename.rsplit(".", 1)[1].lower()
    guessed = mimetypes.guess_extension(mime or "") or ""
    return guessed.lower()


class LocalFileStorage(FileStorage):
    """One file per id under ``root``; the original suffix is preserved so the
    asset re-downloads with the right type. Stored once, referenced many times."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _find(self, file_id: str) -> Path | None:
        stem = safe_name(file_id)
        for path in self._root.glob(f"{stem}.*"):
            if path.is_file():
                return path
        exact = self._root / stem
        return exact if exact.is_file() else None

    def save(self, file_id: str, data: bytes, filename: str = "", mime: str = "") -> str:
        existing = self._find(file_id)
        if existing:
            existing.unlink(missing_ok=True)
        suffix = _suffix_for(filename, mime)
        path = self._root / f"{safe_name(file_id)}{suffix}"
        path.write_bytes(data)
        return str(path)

    def load(self, file_id: str) -> bytes | None:
        path = self._find(file_id)
        return path.read_bytes() if path else None

    def path(self, file_id: str) -> str:
        path = self._find(file_id)
        return str(path) if path else ""

    def mime(self, file_id: str) -> str:
        path = self._find(file_id)
        if not path:
            return ""
        return mimetypes.guess_type(str(path))[0] or "application/octet-stream"

    def exists(self, file_id: str) -> bool:
        return self._find(file_id) is not None

    def size_bytes(self, file_id: str) -> int:
        path = self._find(file_id)
        return path.stat().st_size if path else 0

    def delete(self, file_id: str) -> None:
        path = self._find(file_id)
        if path:
            path.unlink(missing_ok=True)
