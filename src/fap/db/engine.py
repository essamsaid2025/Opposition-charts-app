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
    (3, """
        CREATE TABLE IF NOT EXISTS mapping_templates (
            id TEXT PRIMARY KEY, name TEXT NOT NULL,
            provider_id TEXT NOT NULL DEFAULT '',
            signature TEXT NOT NULL,
            mapping TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_templates_signature ON mapping_templates(signature);
    """),
    (4, """
        CREATE TABLE IF NOT EXISTS custom_providers (
            id TEXT PRIMARY KEY, name TEXT NOT NULL,
            base_provider_id TEXT NOT NULL,
            signature TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """),
    # Phase 3B - Workspace & Data Management. Additive only; existing projects
    # and workspaces keep loading unchanged (new project columns are nullable
    # with defaults).
    (5, """
        -- club hierarchy as an adjacency tree: club > season > competition >
        -- team > opponent > match. One table, unlimited depth, no rigid joins.
        CREATE TABLE IF NOT EXISTS org_nodes (
            id TEXT PRIMARY KEY,
            parent_id TEXT,
            kind TEXT NOT NULL,                 -- club|season|competition|team|opponent|match
            name TEXT NOT NULL,
            document TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            created_by TEXT,
            FOREIGN KEY (parent_id) REFERENCES org_nodes(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_org_parent ON org_nodes(parent_id);
        CREATE INDEX IF NOT EXISTS idx_org_kind ON org_nodes(kind);

        -- the Data Manager: one row per imported dataset + its metadata
        CREATE TABLE IF NOT EXISTS datasets (
            id TEXT PRIMARY KEY,
            workspace_id TEXT,
            project_id TEXT,
            node_id TEXT,                       -- optional link into org_nodes
            name TEXT NOT NULL,
            provider_id TEXT NOT NULL DEFAULT '',
            coord_system TEXT NOT NULL DEFAULT '',
            rows INTEGER NOT NULL DEFAULT 0,
            size_bytes INTEGER NOT NULL DEFAULT 0,
            content_hash TEXT NOT NULL DEFAULT '',
            season TEXT NOT NULL DEFAULT '',
            competition TEXT NOT NULL DEFAULT '',
            opponent TEXT NOT NULL DEFAULT '',
            match_date TEXT NOT NULL DEFAULT '',
            document TEXT NOT NULL DEFAULT '{}', -- columns, mapping, validation, quality
            status TEXT NOT NULL DEFAULT 'active',  -- active|archived
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            created_by TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_datasets_workspace ON datasets(workspace_id);
        CREATE INDEX IF NOT EXISTS idx_datasets_status ON datasets(status);

        -- reusable presets: chart | filter | export | dashboard (import mappings
        -- keep their own mapping_templates table)
        CREATE TABLE IF NOT EXISTS presets (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            name TEXT NOT NULL,
            owner_id TEXT,
            scope TEXT NOT NULL DEFAULT 'user',  -- user|club|global
            document TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_presets_kind ON presets(kind);

        -- immutable project version snapshots
        CREATE TABLE IF NOT EXISTS project_versions (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            document TEXT NOT NULL DEFAULT '{}',
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            created_by TEXT,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_versions_project ON project_versions(project_id);

        -- append-only audit trail
        CREATE TABLE IF NOT EXISTS audit_log (
            id TEXT PRIMARY KEY,
            ts TEXT NOT NULL DEFAULT (datetime('now')),
            actor TEXT NOT NULL DEFAULT '',
            actor_role TEXT NOT NULL DEFAULT '',
            action TEXT NOT NULL,
            target_type TEXT NOT NULL DEFAULT '',
            target_id TEXT NOT NULL DEFAULT '',
            detail TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);
        CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_log(actor);

        -- per-user auto-save (session state persisted without a Save button)
        CREATE TABLE IF NOT EXISTS user_state (
            user_id TEXT NOT NULL,
            scope TEXT NOT NULL DEFAULT 'session',
            document TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (user_id, scope)
        );

        -- per-user pins / favorites / recents
        CREATE TABLE IF NOT EXISTS user_items (
            user_id TEXT NOT NULL,
            kind TEXT NOT NULL,                 -- pin|favorite|recent
            target_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            ts TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (user_id, kind, target_type, target_id)
        );
        CREATE INDEX IF NOT EXISTS idx_user_items ON user_items(user_id, kind);

        -- enrich projects (nullable/defaulted -> old rows still load)
        ALTER TABLE projects ADD COLUMN owner_id TEXT;
        ALTER TABLE projects ADD COLUMN status TEXT NOT NULL DEFAULT 'active';
        ALTER TABLE projects ADD COLUMN tags TEXT NOT NULL DEFAULT '[]';
        ALTER TABLE projects ADD COLUMN contributors TEXT NOT NULL DEFAULT '[]';
    """),
    # Phase 5.2 - Reports Engine. Additive; a report belongs to a workspace/
    # project/dataset and stores its document as versioned JSON.
    (6, """
        CREATE TABLE IF NOT EXISTS reports (
            id TEXT PRIMARY KEY,
            workspace_id TEXT,
            project_id TEXT,
            dataset_id TEXT,
            title TEXT NOT NULL,
            template_id TEXT NOT NULL DEFAULT '',
            owner TEXT NOT NULL DEFAULT '',
            contributors TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'active',   -- active|archived|draft
            favorite INTEGER NOT NULL DEFAULT 0,
            version INTEGER NOT NULL DEFAULT 1,
            document TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_reports_workspace ON reports(workspace_id);
        CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status);
        CREATE INDEX IF NOT EXISTS idx_reports_owner ON reports(owner);
        -- per-user report autosave drafts (recover unfinished reports)
        CREATE TABLE IF NOT EXISTS report_drafts (
            user_id TEXT NOT NULL,
            draft_key TEXT NOT NULL,
            document TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (user_id, draft_key)
        );
    """),
    # Phase 5.3 - Persistent Report Builder. Additive: report version history and
    # managed image assets (bytes live in storage; this is the catalogue).
    (7, """
        CREATE TABLE IF NOT EXISTS report_versions (
            id TEXT PRIMARY KEY,
            report_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            document TEXT NOT NULL DEFAULT '{}',
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            created_by TEXT,
            FOREIGN KEY (report_id) REFERENCES reports(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_report_versions ON report_versions(report_id);

        CREATE TABLE IF NOT EXISTS report_images (
            id TEXT PRIMARY KEY,
            workspace_id TEXT,
            filename TEXT NOT NULL DEFAULT '',
            mime TEXT NOT NULL DEFAULT '',
            size_bytes INTEGER NOT NULL DEFAULT 0,
            owner TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_report_images_ws ON report_images(workspace_id);
    """),
    # Phase 7.1 - Enterprise Identity, Administration & Permissions. Additive only:
    # a persisted user directory, configurable capability-based roles, scoped
    # permission grants, invitations and session tracking. Existing auth, roles
    # and audit are untouched; these tables are new.
    (8, """
        -- roles as configurable capability sets (built-ins seeded, customs added)
        CREATE TABLE IF NOT EXISTS role_definitions (
            slug TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            capabilities TEXT NOT NULL DEFAULT '[]',
            superuser INTEGER NOT NULL DEFAULT 0,
            builtin INTEGER NOT NULL DEFAULT 0,
            rank INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            created_by TEXT
        );

        -- the persisted directory of platform users (SSO identities are owned by
        -- the provider; this row holds the platform's assignment + status)
        CREATE TABLE IF NOT EXISTS platform_users (
            email TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            position TEXT NOT NULL DEFAULT '',
            role_slug TEXT NOT NULL DEFAULT 'read_only',
            org_id TEXT, club_id TEXT, team_id TEXT, workspace_id TEXT,
            status TEXT NOT NULL DEFAULT 'active',   -- active|suspended|disabled
            provider_id TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_login_at TEXT,
            invited_by TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_platform_users_role ON platform_users(role_slug);
        CREATE INDEX IF NOT EXISTS idx_platform_users_status ON platform_users(status);

        -- scoped permission grants: extra capabilities for a user on one org node
        -- (inherited down the org_nodes tree). effect allow|deny.
        CREATE TABLE IF NOT EXISTS permission_grants (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            scope_kind TEXT NOT NULL DEFAULT 'workspace',  -- organization|club|team|workspace|project
            scope_id TEXT NOT NULL DEFAULT '',
            capabilities TEXT NOT NULL DEFAULT '[]',
            effect TEXT NOT NULL DEFAULT 'allow',           -- allow|deny
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            created_by TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_grants_email ON permission_grants(email);
        CREATE INDEX IF NOT EXISTS idx_grants_scope ON permission_grants(scope_kind, scope_id);

        -- invitations: super/club admin invites -> user accepts via SSO login
        CREATE TABLE IF NOT EXISTS invitations (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            role_slug TEXT NOT NULL DEFAULT 'read_only',
            position TEXT NOT NULL DEFAULT '',
            scope_kind TEXT NOT NULL DEFAULT '',
            scope_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',   -- pending|accepted|revoked|expired
            token TEXT NOT NULL DEFAULT '',
            invited_by TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            accepted_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_invites_email ON invitations(email);
        CREATE INDEX IF NOT EXISTS idx_invites_status ON invitations(status);

        -- session tracking for the admin sessions view / force-logout
        CREATE TABLE IF NOT EXISTS user_sessions (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            provider_id TEXT NOT NULL DEFAULT '',
            started_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
            status TEXT NOT NULL DEFAULT 'active',    -- active|expired|forced_out
            revoked INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_email ON user_sessions(email);
        CREATE INDEX IF NOT EXISTS idx_sessions_status ON user_sessions(status);
    """),
    # (9, "ALTER TABLE ..."),  <- future schema changes append here, never edit above
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
