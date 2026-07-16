"""ReportsManager - the reports facade the app talks to.

Owns report lifecycle (create/open/rename/duplicate/archive/delete/restore/
favorite/recent), export, and autosave drafts. Every mutation is permission-
checked against the identity Role (reusing fap.workspaces.permissions) and
recorded in the audit log (reusing the platform AuditService). It builds on the
platform DB, DocumentBuilder, ReportRenderer and fap.theme branding - it does
not modify any of them.
"""
from __future__ import annotations

import uuid
from typing import Any

import pandas as pd

from fap.core.exceptions import AuthError
from fap.db.engine import Database
from fap.identity.models import User
from fap.reports.builders import DocumentBuilder
from fap.reports.exporters import RenderedReport
from fap.reports.models import ReportDocument, ReportRecord
from fap.reports.registry import load_builtin_reports
from fap.reports.renderer import ReportRenderer
from fap.reports.repository import ReportDraftRepository, ReportRepository
from fap.reports.sections import BuildContext
from fap.workspaces.audit import AuditService
from fap.workspaces.permissions import Capability, can, require
from fap.workspaces.repositories import AuditRepository


class ReportsManager:
    def __init__(self, db: Database, branding: Any = None) -> None:
        load_builtin_reports()
        self._db = db
        self._reports = ReportRepository(db)
        self._drafts = ReportDraftRepository(db)
        self._builder = DocumentBuilder()
        self._renderer = ReportRenderer()
        self._branding = branding
        self.audit = AuditService(AuditRepository(db))

    # ---------------------------------------------------------------- catalog
    def templates(self) -> list[Any]:
        return self._builder.available_templates()

    def sections(self) -> list[str]:
        return self._builder.available_sections()

    def formats(self) -> list[str]:
        return self._renderer.formats()

    def available_formats(self) -> list[str]:
        return self._renderer.available_formats()

    # ---------------------------------------------------------------- create
    def create(self, user: User, *, template: str, df: pd.DataFrame,
               title: str = "", workspace_id: str | None = None,
               project_id: str | None = None, dataset_id: str | None = None,
               cover: dict[str, Any] | None = None,
               contributors: list[str] | None = None) -> ReportRecord:
        require(user.role, Capability.EDIT)
        ctx = BuildContext(df=df, branding=self._branding, workspace_id=workspace_id,
                           project_id=project_id, dataset_id=dataset_id,
                           analyst=user.name, cover=cover or {})
        document = self._builder.build(template, ctx, title=title)
        record = ReportRecord(
            id=document.id, title=document.title, workspace_id=workspace_id,
            project_id=project_id, dataset_id=dataset_id, template_id=template,
            owner=user.email, contributors=contributors or [], status="active",
            version=1, document=document.to_dict())
        self._reports.save(record)
        self.audit.record(user, "report.create", target_type="report", target_id=record.id,
                          detail={"template": template, "title": document.title})
        return record

    # ---------------------------------------------------------------- read
    def get(self, report_id: str) -> ReportRecord | None:
        return self._reports.get(report_id)

    def document(self, report_id: str) -> ReportDocument | None:
        rec = self._reports.get(report_id)
        return ReportDocument.from_dict(rec.document) if rec else None

    def list(self, user: User, *, workspace_id: str | None = None, status: str = "active",
             favorite: bool | None = None, query: str = "") -> list[ReportRecord]:
        records = self._reports.list(workspace_id=workspace_id, status=status, favorite=favorite)
        q = query.strip().lower()
        if q:
            records = [r for r in records if q in r.title.lower()
                       or q in r.template_id.lower() or q in r.owner.lower()]
        return records

    def recent(self, user: User, *, workspace_id: str | None = None, limit: int = 10) -> list[ReportRecord]:
        return self.list(user, workspace_id=workspace_id)[:limit]

    def favorites(self, user: User, *, workspace_id: str | None = None) -> list[ReportRecord]:
        return self.list(user, workspace_id=workspace_id, favorite=True)

    # ---------------------------------------------------------------- mutate
    def rename(self, user: User, report_id: str, title: str) -> None:
        rec = self._require_editable(user, report_id)
        rec.title = title
        rec.document["title"] = title
        self._reports.save(rec)
        self.audit.record(user, "report.rename", target_type="report", target_id=report_id,
                          detail={"title": title})

    def duplicate(self, user: User, report_id: str, title: str | None = None) -> ReportRecord:
        require(user.role, Capability.EDIT)
        src = self._get_or_raise(report_id)
        copy = ReportRecord(
            id=str(uuid.uuid4()), title=title or f"{src.title} (copy)",
            workspace_id=src.workspace_id, project_id=src.project_id, dataset_id=src.dataset_id,
            template_id=src.template_id, owner=user.email, contributors=list(src.contributors),
            status="active", version=1, document={**src.document, "id": None})
        copy.document["id"] = copy.id
        copy.document["title"] = copy.title
        self._reports.save(copy)
        self.audit.record(user, "report.duplicate", target_type="report", target_id=copy.id,
                          detail={"source": report_id})
        return copy

    def archive(self, user: User, report_id: str, archived: bool = True) -> None:
        rec = self._require_editable(user, report_id)
        rec.status = "archived" if archived else "active"
        self._reports.save(rec)
        self.audit.record(user, "report.archive" if archived else "report.restore",
                          target_type="report", target_id=report_id)

    def restore(self, user: User, report_id: str) -> None:
        self.archive(user, report_id, archived=False)

    def favorite(self, user: User, report_id: str, on: bool = True) -> None:
        rec = self._get_or_raise(report_id)
        rec.favorite = on
        self._reports.save(rec)

    def delete(self, user: User, report_id: str) -> None:
        require(user.role, Capability.DELETE_PROJECT)     # destructive: admins only
        self._get_or_raise(report_id)
        self._reports.delete(report_id)
        self.audit.record(user, "report.delete", target_type="report", target_id=report_id)

    # ---------------------------------------------------------------- export
    def render(self, user: User, report_id: str, fmt: str = "html") -> RenderedReport:
        doc = self.document(report_id)
        if doc is None:
            raise ValueError(f"report {report_id!r} not found")
        rendered = self._renderer.render(doc, fmt, self._branding)
        self.audit.record(user, "report.export", target_type="report", target_id=report_id,
                          detail={"format": fmt})
        return rendered

    def render_document(self, document: ReportDocument, fmt: str = "html") -> RenderedReport:
        return self._renderer.render(document, fmt, self._branding)

    # ---------------------------------------------------------------- autosave drafts
    def autosave(self, user: User, draft_key: str, document: dict[str, Any]) -> None:
        self._drafts.save(user.email, draft_key, document)

    def load_draft(self, user: User, draft_key: str) -> dict[str, Any]:
        return self._drafts.load(user.email, draft_key)

    def draft_keys(self, user: User) -> list[str]:
        return self._drafts.list_keys(user.email)

    def discard_draft(self, user: User, draft_key: str) -> None:
        self._drafts.delete(user.email, draft_key)

    # ---------------------------------------------------------------- permissions
    def _get_or_raise(self, report_id: str) -> ReportRecord:
        rec = self._reports.get(report_id)
        if rec is None:
            raise ValueError(f"report {report_id!r} not found")
        return rec

    def _require_editable(self, user: User, report_id: str) -> ReportRecord:
        rec = self._get_or_raise(report_id)
        require(user.role, Capability.EDIT)
        is_member = user.email == rec.owner or user.email in rec.contributors
        if not is_member and not can(user.role, Capability.MANAGE_CLUB):
            raise AuthError(
                f"{user.role.label} may not edit a report they do not own "
                f"(owner: {rec.owner or 'unknown'}).")
        return rec
