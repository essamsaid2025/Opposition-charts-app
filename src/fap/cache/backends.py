"""Cache backends behind one interface (Strategy pattern). Adding Redis later
means adding a file here + one line in the factory - nothing else changes."""
from __future__ import annotations

import pickle
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from pathlib import Path
from typing import Any


class CacheBackend(ABC):
    @abstractmethod
    def get(self, key: str) -> Any | None: ...
    @abstractmethod
    def set(self, key: str, value: Any, ttl_seconds: int) -> None: ...
    @abstractmethod
    def delete(self, key: str) -> None: ...
    @abstractmethod
    def clear(self) -> None: ...


class MemoryCache(CacheBackend):
    """LRU + TTL in-process cache."""

    def __init__(self, max_entries: int = 256) -> None:
        self._max = max_entries
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def get(self, key: str) -> Any | None:
        item = self._data.get(key)
        if item is None:
            return None
        expires, value = item
        if expires < time.time():
            self._data.pop(key, None)
            return None
        self._data.move_to_end(key)
        return value

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        self._data[key] = (time.time() + ttl_seconds, value)
        self._data.move_to_end(key)
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def clear(self) -> None:
        self._data.clear()


class DiskCache(CacheBackend):
    """Pickle-per-key disk cache; survives app restarts. Suitable for parsed
    datasets and rendered figure bytes."""

    def __init__(self, directory: str | Path) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self._dir / f"{key}.pkl"

    def get(self, key: str) -> Any | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            expires, value = pickle.loads(path.read_bytes())
        except Exception:  # corrupt entry -> treat as miss
            path.unlink(missing_ok=True)
            return None
        if expires < time.time():
            path.unlink(missing_ok=True)
            return None
        return value

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        self._path(key).write_bytes(pickle.dumps((time.time() + ttl_seconds, value)))

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def clear(self) -> None:
        for file in self._dir.glob("*.pkl"):
            file.unlink(missing_ok=True)
