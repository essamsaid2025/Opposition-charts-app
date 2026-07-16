"""Repositories for the workspace layer - the only place its SQL lives."""
from __future__ import annotations

import json
from typing import Any

from fap.db.engine import Database
from fap.workspaces.models import (
    AuditEntry, Dataset, OrgNode, Preset, ProjectVersion,
)


class OrgRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def save(self, node: OrgNode) -> None:
        self._db.execute(
            """INSERT INTO org_nodes (id, parent_id, kind, name, document, created_by)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name, parent_id=excluded.parent_id,
               document=excluded.document""",
            (node.id, node.parent_id, node.kind, node.name,
             json.dumps(node.document), node.created_by))

    def get(self, node_id: str) -> OrgNode | None:
        rows = self._db.query("SELECT * FROM org_nodes WHERE id = ?", (node_id,))
        return self._row(rows[0]) if rows else None

    def children(self, parent_id: str | None) -> list[OrgNode]:
        if parent_id is None:
            rows = self._db.query("SELECT * FROM org_nodes WHERE parent_id IS NULL ORDER BY name")
        else:
            rows = self._db.query(
                "SELECT * FROM org_nodes WHERE parent_id = ? ORDER BY name", (parent_id,))
        return [self._row(r) for r in rows]

    def by_kind(self, kind: str) -> list[OrgNode]:
        return [self._row(r) for r in self._db.query(
            "SELECT * FROM org_nodes WHERE kind = ? ORDER BY name", (kind,))]

    def delete(self, node_id: str) -> None:
        self._db.execute("DELETE FROM org_nodes WHERE id = ?", (node_id,))

    @staticmethod
    def _row(r: Any) -> OrgNode:
        return OrgNode(id=r["id"], parent_id=r["parent_id"], kind=r["kind"], name=r["name"],
                       document=json.loads(r["document"]), created_by=r["created_by"])


class DatasetRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def save(self, ds: Dataset) -> None:
        self._db.execute(
            """INSERT INTO datasets (id, workspace_id, project_id, node_id, name, provider_id,
                 coord_system, rows, size_bytes, content_hash, season, competition, opponent,
                 match_date, document, status, created_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name,
                 workspace_id=excluded.workspace_id, project_id=excluded.project_id,
                 node_id=excluded.node_id, season=excluded.season, competition=excluded.competition,
                 opponent=excluded.opponent, match_date=excluded.match_date,
                 document=excluded.document, status=excluded.status""",
            (ds.id, ds.workspace_id, ds.project_id, ds.node_id, ds.name, ds.provider_id,
             ds.coord_system, ds.rows, ds.size_bytes, ds.content_hash, ds.season, ds.competition,
             ds.opponent, ds.match_date, json.dumps(ds.document), ds.status, ds.created_by))

    def get(self, dataset_id: str) -> Dataset | None:
        rows = self._db.query("SELECT * FROM datasets WHERE id = ?", (dataset_id,))
        return self._row(rows[0]) if rows else None

    def list(self, *, workspace_id: str | None = None, status: str | None = None) -> list[Dataset]:
        sql = "SELECT * FROM datasets"
        clauses, params = [], []
        if workspace_id is not None:
            clauses.append("workspace_id = ?"); params.append(workspace_id)
        if status is not None:
            clauses.append("status = ?"); params.append(status)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC"
        return [self._row(r) for r in self._db.query(sql, tuple(params))]

    def delete(self, dataset_id: str) -> None:
        self._db.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))

    @staticmethod
    def _row(r: Any) -> Dataset:
        return Dataset(
            id=r["id"], workspace_id=r["workspace_id"], project_id=r["project_id"],
            node_id=r["node_id"], name=r["name"], provider_id=r["provider_id"],
            coord_system=r["coord_system"], rows=r["rows"], size_bytes=r["size_bytes"],
            content_hash=r["content_hash"], season=r["season"], competition=r["competition"],
            opponent=r["opponent"], match_date=r["match_date"],
            document=json.loads(r["document"]), status=r["status"],
            created_by=r["created_by"], created_at=r["created_at"])


class PresetRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def save(self, preset: Preset) -> None:
        self._db.execute(
            """INSERT INTO presets (id, kind, name, owner_id, scope, document)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name, document=excluded.document,
                 scope=excluded.scope, updated_at=datetime('now')""",
            (preset.id, preset.kind, preset.name, preset.owner_id, preset.scope,
             json.dumps(preset.document)))

    def get(self, preset_id: str) -> Preset | None:
        rows = self._db.query("SELECT * FROM presets WHERE id = ?", (preset_id,))
        return self._row(rows[0]) if rows else None

    def list(self, *, kind: str | None = None, owner_id: str | None = None) -> list[Preset]:
        sql, clauses, params = "SELECT * FROM presets", [], []
        if kind is not None:
            clauses.append("kind = ?"); params.append(kind)
        if owner_id is not None:
            clauses.append("(owner_id = ? OR scope IN ('club','global'))"); params.append(owner_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY name"
        return [self._row(r) for r in self._db.query(sql, tuple(params))]

    def delete(self, preset_id: str) -> None:
        self._db.execute("DELETE FROM presets WHERE id = ?", (preset_id,))

    @staticmethod
    def _row(r: Any) -> Preset:
        return Preset(id=r["id"], kind=r["kind"], name=r["name"], owner_id=r["owner_id"],
                      scope=r["scope"], document=json.loads(r["document"]))


class VersionRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, version: ProjectVersion) -> None:
        self._db.execute(
            """INSERT INTO project_versions (id, project_id, version, document, note, created_by)
               VALUES (?,?,?,?,?,?)""",
            (version.id, version.project_id, version.version, json.dumps(version.document),
             version.note, version.created_by))

    def next_version(self, project_id: str) -> int:
        rows = self._db.query(
            "SELECT COALESCE(MAX(version), 0) AS v FROM project_versions WHERE project_id = ?",
            (project_id,))
        return int(rows[0]["v"]) + 1

    def list(self, project_id: str) -> list[ProjectVersion]:
        rows = self._db.query(
            "SELECT * FROM project_versions WHERE project_id = ? ORDER BY version DESC",
            (project_id,))
        return [self._row(r) for r in rows]

    def get(self, project_id: str, version: int) -> ProjectVersion | None:
        rows = self._db.query(
            "SELECT * FROM project_versions WHERE project_id = ? AND version = ?",
            (project_id, version))
        return self._row(rows[0]) if rows else None

    @staticmethod
    def _row(r: Any) -> ProjectVersion:
        return ProjectVersion(id=r["id"], project_id=r["project_id"], version=r["version"],
                              document=json.loads(r["document"]), note=r["note"],
                              created_by=r["created_by"], created_at=r["created_at"])


class AuditRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, entry: AuditEntry) -> None:
        self._db.execute(
            """INSERT INTO audit_log (id, actor, actor_role, action, target_type, target_id, detail)
               VALUES (?,?,?,?,?,?,?)""",
            (entry.id, entry.actor, entry.actor_role, entry.action, entry.target_type,
             entry.target_id, json.dumps(entry.detail)))

    def recent(self, *, actor: str | None = None, action: str | None = None,
               limit: int = 200) -> list[AuditEntry]:
        sql, clauses, params = "SELECT * FROM audit_log", [], []
        if actor is not None:
            clauses.append("actor = ?"); params.append(actor)
        if action is not None:
            clauses.append("action = ?"); params.append(action)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY ts DESC, rowid DESC LIMIT ?"
        params.append(limit)
        return [self._row(r) for r in self._db.query(sql, tuple(params))]

    @staticmethod
    def _row(r: Any) -> AuditEntry:
        return AuditEntry(id=r["id"], action=r["action"], actor=r["actor"],
                          actor_role=r["actor_role"], target_type=r["target_type"],
                          target_id=r["target_id"], detail=json.loads(r["detail"]), ts=r["ts"])


class UserStateRepository:
    """Auto-save + pins/favorites/recents, per user."""
    def __init__(self, db: Database) -> None:
        self._db = db

    # -- auto-save (kv document per scope) ----------------------------
    def save_state(self, user_id: str, scope: str, document: dict[str, Any]) -> None:
        self._db.execute(
            """INSERT INTO user_state (user_id, scope, document, updated_at)
               VALUES (?, ?, ?, datetime('now'))
               ON CONFLICT(user_id, scope) DO UPDATE SET document=excluded.document,
                 updated_at=datetime('now')""",
            (user_id, scope, json.dumps(document)))

    def load_state(self, user_id: str, scope: str) -> dict[str, Any]:
        rows = self._db.query(
            "SELECT document FROM user_state WHERE user_id = ? AND scope = ?", (user_id, scope))
        return json.loads(rows[0]["document"]) if rows else {}

    # -- pins / favorites / recents -----------------------------------
    def add_item(self, user_id: str, kind: str, target_type: str, target_id: str) -> None:
        self._db.execute(
            """INSERT INTO user_items (user_id, kind, target_type, target_id, ts)
               VALUES (?,?,?,?, datetime('now'))
               ON CONFLICT(user_id, kind, target_type, target_id) DO UPDATE SET ts=datetime('now')""",
            (user_id, kind, target_type, target_id))

    def remove_item(self, user_id: str, kind: str, target_type: str, target_id: str) -> None:
        self._db.execute(
            "DELETE FROM user_items WHERE user_id=? AND kind=? AND target_type=? AND target_id=?",
            (user_id, kind, target_type, target_id))

    def items(self, user_id: str, kind: str, limit: int = 50) -> list[tuple[str, str]]:
        # ts has second resolution; rowid breaks ties so ordering is deterministic
        rows = self._db.query(
            "SELECT target_type, target_id FROM user_items WHERE user_id=? AND kind=? "
            "ORDER BY ts DESC, rowid DESC LIMIT ?", (user_id, kind, limit))
        return [(r["target_type"], r["target_id"]) for r in rows]
