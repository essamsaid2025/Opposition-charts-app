"""SQLite persistence with an explicit migration table. All persistence goes
through repositories (fap.db.repositories) - services never write SQL."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

from fap.core.exceptions import PersistenceError

MIGRATIONS: list[tuple[int, str]] = [
    (1, """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL, salt TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'analyst',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS workspaces (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, owner_id TEXT,
            document TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
            name TEXT NOT NULL, document TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_projects_workspace ON projects(workspace_id);
    """),
    (2, """
        ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0;
    """),
    # (3, "ALTER TABLE ..."),  <- future schema changes append here, never edit above
]


class Database:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    def _migrate(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)"
            )
            applied = {r[0] for r in self._conn.execute("SELECT version FROM schema_migrations")}
            for version, sql in MIGRATIONS:
                if version in applied:
                    continue
                self._conn.executescript(sql)
                self._conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))

    def execute(self, sql: str, params: Iterable[Any] = ()) -> None:
        try:
            with self._lock, self._conn:
                self._conn.execute(sql, tuple(params))
        except sqlite3.Error as exc:
            raise PersistenceError(str(exc)) from exc

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        try:
            with self._lock:
                return list(self._conn.execute(sql, tuple(params)))
        except sqlite3.Error as exc:
            raise PersistenceError(str(exc)) from exc

    def close(self) -> None:
        self._conn.close()
