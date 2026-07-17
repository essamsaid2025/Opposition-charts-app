"""Persistent dataset storage - the source of truth for imported match data.

A dataset's normalized frame is written here once at import and re-opened
directly afterwards, so the data survives cache expiry, restarts, deployments,
logout and reboots without re-running the import pipeline. The CacheManager
sits in front of this purely as an accelerator.

Storage is a strategy: swap the backend (local parquet today, object storage
tomorrow) without touching WorkspaceManager or any consumer.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path

import pandas as pd

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_name(dataset_id: str) -> str:
    """Dataset ids are uuids, but never trust an id as a filename."""
    return _UNSAFE.sub("_", str(dataset_id))[:80] or "dataset"


class DatasetStorage(ABC):
    """Persist and re-open a dataset's normalized frame."""

    @abstractmethod
    def save(self, dataset_id: str, frame: pd.DataFrame) -> str:
        """Persist the frame; return a locator (path/uri) for diagnostics."""

    @abstractmethod
    def load(self, dataset_id: str) -> pd.DataFrame | None:
        """Re-open the frame, or None when this dataset was never stored."""

    @abstractmethod
    def exists(self, dataset_id: str) -> bool: ...

    @abstractmethod
    def delete(self, dataset_id: str) -> None: ...

    @abstractmethod
    def size_bytes(self, dataset_id: str) -> int: ...
