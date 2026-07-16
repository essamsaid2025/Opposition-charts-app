"""Reports persistence - the only place report SQL lives (repository pattern),
over the SAME platform database (migration 6). Documents are versioned JSON."""
from __future__ import annotations

import json
from typing import Any

from fap.db.engine import Database
from fap.reports.models import ReportRecord


class ReportRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def save(self, r: ReportRecord) -> None:
        self._db.execute(
            """INSERT INTO reports (id, workspace_id, project_id, dataset_id, title,
                 template_id, owner, contributors, status, favorite, version, document)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET title=excluded.title, status=excluded.status,
                 favorite=excluded.favorite, version=excluded.version,
                 document=excluded.document, contributors=excluded.contributors,
                 project_id=excluded.project_id, dataset_id=excluded.dataset_id,
                 updated_at=datetime('now')""",
            (r.id, r.workspace_id, r.project_id, r.dataset_id, r.title, r.template_id,
             r.owner, json.dumps(r.contributors), r.status, int(r.favorite), r.version,
             json.dumps(r.document)))

    def get(self, report_id: str) -> ReportRecord | None:
        rows = self._db.query("SELECT * FROM reports WHERE id = ?", (report_id,))
        return self._row(rows[0]) if rows else None

    def list(self, *, workspace_id: str | None = None, status: str | None = None,
             favorite: bool | None = None, owner: str | None = None) -> list[ReportRecord]:
        sql, clauses, params = "SELECT * FROM reports", [], []
        if workspace_id is not None:
            clauses.append("workspace_id = ?"); params.append(workspace_id)
        if status is not None:
            clauses.append("status = ?"); params.append(status)
        if favorite is not None:
            clauses.append("favorite = ?"); params.append(int(favorite))
        if owner is not None:
            clauses.append("owner = ?"); params.append(owner)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        # rowid breaks second-resolution ties so ordering is deterministic
        sql += " ORDER BY updated_at DESC, rowid DESC"
        return [self._row(r) for r in self._db.query(sql, tuple(params))]

    def delete(self, report_id: str) -> None:
        self._db.execute("DELETE FROM reports WHERE id = ?", (report_id,))

    @staticmethod
    def _row(r: Any) -> ReportRecord:
        return ReportRecord(
            id=r["id"], title=r["title"], workspace_id=r["workspace_id"],
            project_id=r["project_id"], dataset_id=r["dataset_id"],
            template_id=r["template_id"], owner=r["owner"],
            contributors=json.loads(r["contributors"]), status=r["status"],
            favorite=bool(r["favorite"]), version=r["version"],
            document=json.loads(r["document"]), created_at=r["created_at"],
            updated_at=r["updated_at"])


class ReportDraftRepository:
    """Per-user autosave drafts for unfinished reports."""
    def __init__(self, db: Database) -> None:
        self._db = db

    def save(self, user_id: str, draft_key: str, document: dict[str, Any]) -> None:
        self._db.execute(
            """INSERT INTO report_drafts (user_id, draft_key, document, updated_at)
               VALUES (?,?,?, datetime('now'))
               ON CONFLICT(user_id, draft_key) DO UPDATE SET document=excluded.document,
                 updated_at=datetime('now')""",
            (user_id, draft_key, json.dumps(document)))

    def load(self, user_id: str, draft_key: str) -> dict[str, Any]:
        rows = self._db.query(
            "SELECT document FROM report_drafts WHERE user_id=? AND draft_key=?",
            (user_id, draft_key))
        return json.loads(rows[0]["document"]) if rows else {}

    def list_keys(self, user_id: str) -> list[str]:
        rows = self._db.query(
            "SELECT draft_key FROM report_drafts WHERE user_id=? ORDER BY updated_at DESC",
            (user_id,))
        return [r["draft_key"] for r in rows]

    def delete(self, user_id: str, draft_key: str) -> None:
        self._db.execute("DELETE FROM report_drafts WHERE user_id=? AND draft_key=?",
                         (user_id, draft_key))
