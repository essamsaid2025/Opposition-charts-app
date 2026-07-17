"""Persistent dataset storage layer.

    Workspace -> Dataset -> DatasetStorage (source of truth) -> CacheManager (accelerator)

Imported match data is persisted here once, so it survives cache expiry,
restarts, deployments, logout and reboots - and re-opens without re-running the
import pipeline. Consumers never touch this: they keep calling
``WorkspaceManager.active_frame()``.
"""
from fap.storage.base import DatasetStorage, safe_name
from fap.storage.parquet import ParquetDatasetStorage
from fap.storage.images import ALLOWED_MIME, ImageStorage, LocalImageStorage

__all__ = ["DatasetStorage", "ParquetDatasetStorage", "safe_name",
           "ImageStorage", "LocalImageStorage", "ALLOWED_MIME"]
