"""Repository pattern: the only place SQL for each aggregate lives.
Services depend on these classes, never on sqlite directly (DIP)."""
from __future__ import annotations

import json
from typing import Any

from fap.db.engine import Database
from fap.db.models import Project, Workspace


class WorkspaceRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def save(self, ws: Workspace) -> None:
        self._db.execute(
            """INSERT INTO workspaces (id, name, owner_id, document) VALUES (?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name,
               document=excluded.document, updated_at=datetime('now')""",
            (ws.id, ws.name, ws.owner_id, json.dumps(ws.document)),
        )

    def get(self, workspace_id: str) -> Workspace | None:
        rows = self._db.query("SELECT * FROM workspaces WHERE id = ?", (workspace_id,))
        return self._row_to_ws(rows[0]) if rows else None

    def list_all(self) -> list[Workspace]:
        return [self._row_to_ws(r) for r in self._db.query("SELECT * FROM workspaces ORDER BY name")]

    def delete(self, workspace_id: str) -> None:
        self._db.execute("DELETE FROM workspaces WHERE id = ?", (workspace_id,))

    @staticmethod
    def _row_to_ws(row: Any) -> Workspace:
        return Workspace(id=row["id"], name=row["name"], owner_id=row["owner_id"],
                         document=json.loads(row["document"]))


class ProjectRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def save(self, project: Project) -> None:
        self._db.execute(
            """INSERT INTO projects (id, workspace_id, name, document) VALUES (?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name,
               document=excluded.document, updated_at=datetime('now')""",
            (project.id, project.workspace_id, project.name, json.dumps(project.document)),
        )

    def get(self, project_id: str) -> Project | None:
        rows = self._db.query("SELECT * FROM projects WHERE id = ?", (project_id,))
        return self._row_to_project(rows[0]) if rows else None

    def list_for_workspace(self, workspace_id: str) -> list[Project]:
        rows = self._db.query(
            "SELECT * FROM projects WHERE workspace_id = ? ORDER BY updated_at DESC", (workspace_id,)
        )
        return [self._row_to_project(r) for r in rows]

    def delete(self, project_id: str) -> None:
        self._db.execute("DELETE FROM projects WHERE id = ?", (project_id,))

    @staticmethod
    def _row_to_project(row: Any) -> Project:
        return Project(id=row["id"], workspace_id=row["workspace_id"], name=row["name"],
                       document=json.loads(row["document"]))
