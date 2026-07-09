from __future__ import annotations

import hashlib
import logging
from functools import wraps
from typing import Any, Callable, ParamSpec, TypeVar

import pandas as pd

from fap.cache.backends import CacheBackend, DiskCache, MemoryCache
from fap.config.settings import CacheSettings

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


def hash_dataframe(df: pd.DataFrame) -> str:
    """Stable content hash - the backbone of every data-derived cache key."""
    h = hashlib.sha256()
    h.update(pd.util.hash_pandas_object(df, index=True).values.tobytes())
    h.update(",".join(map(str, df.columns)).encode())
    return h.hexdigest()[:32]


def make_key(*parts: Any) -> str:
    raw = "|".join(repr(p) for p in parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:40]


class CacheManager:
    """Facade the rest of the app uses. Backend chosen from configuration."""

    def __init__(self, settings: CacheSettings) -> None:
        self._ttl = settings.ttl_seconds
        self._backend: CacheBackend = (
            DiskCache(settings.directory) if settings.backend == "disk"
            else MemoryCache(settings.max_entries)
        )

    def get(self, key: str) -> Any | None:
        return self._backend.get(key)

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        self._backend.set(key, value, ttl_seconds or self._ttl)

    def get_or_compute(self, key: str, compute: Callable[[], R], ttl_seconds: int | None = None) -> R:
        hit = self._backend.get(key)
        if hit is not None:
            return hit  # type: ignore[return-value]
        value = compute()
        self._backend.set(key, value, ttl_seconds or self._ttl)
        return value

    def invalidate(self, key: str) -> None:
        self._backend.delete(key)

    def clear(self) -> None:
        self._backend.clear()


def cached(manager: CacheManager, prefix: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator for pure, expensive functions. DataFrames in args are hashed
    by content, so identical data + params = cache hit across reruns."""

    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        @wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            parts: list[Any] = [prefix, fn.__qualname__]
            for value in list(args) + sorted(kwargs.items()):
                v = value[1] if isinstance(value, tuple) else value
                parts.append(hash_dataframe(v) if isinstance(v, pd.DataFrame) else v)
            key = make_key(*parts)
            return manager.get_or_compute(key, lambda: fn(*args, **kwargs))
        return wrapper
    return decorator
