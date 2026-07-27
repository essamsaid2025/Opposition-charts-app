"""Database connection layer (Phase 11.1).

The repository layer talks only to :class:`fap.db.engine.Database`
(``execute`` / ``query``); this module is what makes that class backend-agnostic.
It provides:

* ``open_raw(settings)`` — a configured connection for the selected backend.
  ``sqlite`` (default) returns a real ``sqlite3.Connection`` (identical to the
  pre-Phase-11 behaviour). ``libsql`` returns an adapter over the libSQL / Turso
  driver that presents the exact ``sqlite3.Connection`` subset the engine uses
  (``execute`` returning name-addressable rows, ``executescript``, context-manager
  commit/rollback, ``close``) — so nothing above the engine changes.
* ``ConnectionPool`` — a bounded, thread-safe pool over any connection factory.
  It is backend-neutral (tested with sqlite) and used for remote/libSQL where
  real pooling matters; a pool of size 1 is the classic single serialized
  connection.
* ``split_statements`` — splits a migration script into atomic statements so a
  migration can run inside one transaction and roll back cleanly on failure.

libSQL/boto3/redis are optional: the driver is imported lazily and, if missing,
we fail loudly in production or fall back to sqlite in development — the same
"implemented + guarded + degrade" pattern the codebase already uses for optional
exporters and email providers.
"""
from __future__ import annotations

import logging
import queue
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable, Iterable

from fap.config.settings import DatabaseSettings
from fap.core.exceptions import ConfigurationError, PersistenceError

logger = logging.getLogger(__name__)

_LINE_COMMENT = re.compile(r"--[^\n]*")


# ---------------------------------------------------------------- SQL utilities
def split_statements(script: str) -> list[str]:
    """Split a DDL migration script into individual statements so it can run in
    one explicit transaction (enabling clean rollback on failure). Line comments
    (``-- …``) are stripped first; the project's migrations contain no semicolons
    inside string literals, so a ``;`` split is safe and is guarded by a unit
    test that applies every real migration through this path."""
    cleaned = _LINE_COMMENT.sub("", script)
    return [s.strip() for s in cleaned.split(";") if s.strip()]


# ---------------------------------------------------------------- sqlite backend
def _open_sqlite(settings: DatabaseSettings) -> sqlite3.Connection:
    path = Path(settings.path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {int(settings.busy_timeout_ms)}")
    if settings.wal:
        try:
            conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.Error:                       # e.g. :memory: — non-fatal
            logger.debug("WAL not available for %s", settings.path)
    return conn


# ---------------------------------------------------------------- libSQL backend
class _Row(dict):
    """A row that answers to both ``row[0]`` (position) and ``row['col']`` (name),
    matching ``sqlite3.Row`` closely enough for the repositories and the engine."""

    __slots__ = ("_order",)

    def __init__(self, columns: list[str], values: Iterable[Any]) -> None:
        vals = list(values)
        super().__init__(zip(columns, vals))
        self._order = vals

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return self._order[key]
        return super().__getitem__(key)

    def keys(self) -> Any:                           # sqlite3.Row parity
        return list(super().keys())


class _LibsqlCursorResult:
    """Iterable/list-like result of an adapter ``execute``: the engine does
    ``list(conn.execute(...))`` and indexes rows by name, so we return _Row objs."""

    def __init__(self, rows: list[_Row]) -> None:
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)

    def fetchall(self) -> list[_Row]:
        return list(self._rows)


class _LibsqlConnection:
    """Adapter presenting the ``sqlite3.Connection`` subset the engine relies on,
    backed by the libSQL driver (Turso remote or embedded replica)."""

    def __init__(self, raw: Any) -> None:
        self._raw = raw

    # -- the surface fap.db.engine.Database uses -------------------------
    def execute(self, sql: str, params: Iterable[Any] = ()) -> _LibsqlCursorResult:
        cur = self._raw.execute(sql, tuple(params))
        try:
            desc = cur.description or []
            cols = [d[0] for d in desc]
            rows = [_Row(cols, r) for r in cur.fetchall()] if cols else []
        except Exception:                            # non-SELECT statements
            rows = []
        return _LibsqlCursorResult(rows)

    def executescript(self, sql: str) -> None:
        runner = getattr(self._raw, "executescript", None)
        if callable(runner):
            runner(sql)
        else:                                        # driver without executescript
            for stmt in split_statements(sql):
                self._raw.execute(stmt)

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        try:
            self._raw.rollback()
        except Exception:
            logger.debug("libSQL rollback no-op", exc_info=True)

    def close(self) -> None:
        try:
            self._raw.close()
        except Exception:
            pass

    # context manager == sqlite3.Connection semantics (commit / rollback)
    def __enter__(self) -> "_LibsqlConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False


def _open_libsql(settings: DatabaseSettings):
    """Open a libSQL / Turso connection. Prefers an embedded replica (local
    ``path`` synced from ``url``/``sync_url``) so reads stay local; falls back to
    a direct remote connection. Import-guarded."""
    try:
        import libsql_experimental as libsql          # type: ignore
    except Exception:
        try:
            import libsql                              # type: ignore
        except Exception as exc:                       # driver not installed
            raise ConfigurationError(
                "database.backend='libsql' requires the libSQL driver "
                "(`pip install libsql-experimental`). Install it, or use "
                "database.backend='sqlite'.") from exc

    url = settings.sync_url or settings.url
    kwargs: dict[str, Any] = {}
    if settings.auth_token:
        kwargs["auth_token"] = settings.auth_token
    if settings.encryption_key:
        kwargs["encryption_key"] = settings.encryption_key
    if url:
        kwargs["sync_url"] = url                       # embedded replica at ``path``
    Path(settings.path).parent.mkdir(parents=True, exist_ok=True)
    raw = libsql.connect(settings.path, **kwargs)
    for pragma in ("PRAGMA foreign_keys = ON",
                   f"PRAGMA busy_timeout = {int(settings.busy_timeout_ms)}"):
        try:
            raw.execute(pragma)
        except Exception:
            logger.debug("libSQL PRAGMA not supported: %s", pragma)
    return _LibsqlConnection(raw)


# ---------------------------------------------------------------- factory
def open_raw(settings: DatabaseSettings, *, production: bool = True):
    """A configured connection for the selected backend. On a libSQL failure in
    development we degrade to sqlite (so local dev never breaks); in production we
    fail loud so a misconfiguration is caught at boot, not at first write."""
    backend = (settings.backend or "sqlite").lower()
    if backend in ("sqlite", "", "local"):
        return _open_sqlite(settings)
    if backend in ("libsql", "turso"):
        try:
            return _open_libsql(settings)
        except ConfigurationError:
            if production:
                raise
            logger.warning("libSQL unavailable; falling back to sqlite for development.")
            return _open_sqlite(settings)
    raise ConfigurationError(f"Unknown database backend {settings.backend!r} "
                             f"(expected 'sqlite' or 'libsql').")


# ---------------------------------------------------------------- pooling
class ConnectionPool:
    """A bounded, thread-safe connection pool over any ``factory`` callable.

    Backend-neutral: it works for sqlite (verified) and libSQL alike. Connections
    are created lazily up to ``size`` and reused; ``acquire()`` is a context
    manager that returns the connection to the pool afterwards. A pool of size 1
    is exactly the classic single serialized connection.
    """

    def __init__(self, factory: Callable[[], Any], size: int = 4) -> None:
        self._factory = factory
        self._size = max(1, int(size))
        self._pool: "queue.LifoQueue[Any]" = queue.LifoQueue(maxsize=self._size)
        self._created = 0
        self._lock = threading.Lock()
        self._closed = False

    def _new(self) -> Any:
        with self._lock:
            self._created += 1
        return self._factory()

    def _get(self) -> Any:
        if self._closed:
            raise PersistenceError("connection pool is closed")
        try:
            return self._pool.get_nowait()
        except queue.Empty:
            with self._lock:
                room = self._created < self._size
            if room:
                return self._new()
            return self._pool.get()                  # block until one frees up

    def _put(self, conn: Any) -> None:
        if self._closed:
            _safe_close(conn)
            return
        try:
            self._pool.put_nowait(conn)
        except queue.Full:                           # over capacity -> drop
            _safe_close(conn)

    class _Lease:
        def __init__(self, pool: "ConnectionPool") -> None:
            self._pool = pool
            self._conn: Any = None

        def __enter__(self) -> Any:
            self._conn = self._pool._get()
            return self._conn

        def __exit__(self, exc_type, exc, tb) -> bool:
            if self._conn is not None:
                self._pool._put(self._conn)
                self._conn = None
            return False

    def acquire(self) -> "ConnectionPool._Lease":
        return ConnectionPool._Lease(self)

    def size(self) -> int:
        return self._size

    def close(self) -> None:
        self._closed = True
        while True:
            try:
                _safe_close(self._pool.get_nowait())
            except queue.Empty:
                break


def _safe_close(conn: Any) -> None:
    try:
        conn.close()
    except Exception:
        pass
