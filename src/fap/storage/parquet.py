"""Local Parquet dataset storage (the default backend).

Format decision - Parquet (zstd), measured on a 50k-row canonical frame:

    format            write    read      size   dtype-exact
    parquet(zstd)     144ms     92ms   2,450KB   yes
    parquet(snappy)   165ms    136ms   2,573KB   yes
    pickle             26ms     84ms   4,038KB   yes (but fragile/unsafe)
    csv               435ms    143ms   6,731KB   NO (category -> object)

Parquet wins where it matters: the hot path is *re-opening* (fastest read),
it is the smallest, and it is dtype-exact - so a stored frame reloads exactly
as the pipeline produced it, with no re-inference and no import re-run. It is
columnar, compressed and portable (DuckDB/Spark/Arrow), so it scales to
partitioning and object storage later. CSV is disqualified: it silently loses
dtypes (categoricals become objects), which would force the import pipeline to
run again. Pickle is only a fallback: it is fast but Python/version-fragile and
unsafe to load untrusted files.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from fap.storage.base import DatasetStorage, safe_name

logger = logging.getLogger(__name__)


class ParquetDatasetStorage(DatasetStorage):
    """One file per dataset under ``root``. Falls back to pickle only when no
    parquet engine is installed or a frame cannot be encoded."""

    def __init__(self, root: str | Path, compression: str = "zstd") -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._compression = compression

    # -- paths --------------------------------------------------------
    def _parquet(self, dataset_id: str) -> Path:
        return self._root / f"{safe_name(dataset_id)}.parquet"

    def _pickle(self, dataset_id: str) -> Path:
        return self._root / f"{safe_name(dataset_id)}.pkl"

    def _existing(self, dataset_id: str) -> Path | None:
        for path in (self._parquet(dataset_id), self._pickle(dataset_id)):
            if path.is_file():
                return path
        return None

    # -- DatasetStorage -----------------------------------------------
    def save(self, dataset_id: str, frame: pd.DataFrame) -> str:
        path = self._parquet(dataset_id)
        try:
            frame.to_parquet(path, engine="pyarrow", compression=self._compression)
            self._pickle(dataset_id).unlink(missing_ok=True)   # drop any stale fallback
            return str(path)
        except Exception:
            # no parquet engine, or an exotic column: keep the data rather than lose it
            logger.warning("Parquet write failed for dataset %s; using pickle fallback",
                           dataset_id, exc_info=True)
            fallback = self._pickle(dataset_id)
            frame.to_pickle(fallback)
            path.unlink(missing_ok=True)
            return str(fallback)

    def load(self, dataset_id: str) -> pd.DataFrame | None:
        path = self._existing(dataset_id)
        if path is None:
            return None
        try:
            return (pd.read_parquet(path) if path.suffix == ".parquet"
                    else pd.read_pickle(path))
        except Exception:
            logger.exception("Could not read stored dataset %s from %s", dataset_id, path)
            return None

    def exists(self, dataset_id: str) -> bool:
        return self._existing(dataset_id) is not None

    def delete(self, dataset_id: str) -> None:
        self._parquet(dataset_id).unlink(missing_ok=True)
        self._pickle(dataset_id).unlink(missing_ok=True)

    def size_bytes(self, dataset_id: str) -> int:
        path = self._existing(dataset_id)
        return path.stat().st_size if path else 0
