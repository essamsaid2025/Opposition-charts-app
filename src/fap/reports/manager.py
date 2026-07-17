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
from fap.reports.blocks import ChartBlockRenderer
from fap.reports.builders import DocumentBuilder
from fap.reports.exporters import RenderedReport
from fap.reports.models import ReportDocument, ReportRecord
from fap.reports.registry import load_builtin_reports
from fap.reports.renderer import ReportRenderer
from fap.reports.repository import (
    ReportDraftRepository, ReportImage, ReportImageRepository, ReportRepository,
    ReportVersion, ReportVersionRepository,
)
from fap.reports.sections import BuildContext
from fap.workspaces.audit import AuditService
from fap.workspaces.permissions import Capability, can, require
from fap.workspaces.repositories import AuditRepository


class ReportsManager:
    def __init__(self, db: Database, branding: Any = None, *,
                 frame_provider: Any = None, images: Any = None,
                 themes: Any = None, cache: Any = None) -> None:
        load_builtin_reports()
        self._db = db
        self._reports = ReportRepository(db)
        self._drafts = ReportDraftRepository(db)
        self._versions = ReportVersionRepository(db)
        self._image_repo = ReportImageRepository(db)
        self._builder = DocumentBuilder()
        self._renderer = ReportRenderer()
        self._branding = branding
        # injected platform services (reused, never re-implemented)
        self._frame_provider = frame_provider    # dataset_id -> DataFrame | None
        self._images = images                    # ImageStorage
        self._charts = ChartBlockRenderer(themes=themes, cache=cache)
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

    # ---------------------------------------------------------------- editor persistence
    def save_document(self, user: User, report_id: str, document: ReportDocument,
                      note: str = "") -> ReportRecord:
        """Persist an edited document (this IS the autosave: every change lands
        in the platform database, never session_state)."""
        rec = self._require_editable(user, report_id)
        rec.document = document.to_dict()
        rec.title = document.title or rec.title
        self._reports.save(rec)
        return rec

    def update_blocks(self, user: User, report_id: str, mutate: Any) -> ReportDocument:
        """Load -> mutate(document) -> save. The editor calls this for every
        block operation, so the document is always durable."""
        doc = self.document(report_id)
        if doc is None:
            raise ValueError(f"report {report_id!r} not found")
        mutate(doc)
        self.save_document(user, report_id, doc)
        return doc

    def save_as(self, user: User, report_id: str, title: str) -> ReportRecord:
        """Duplicate under a new title (Save As...)."""
        copy = self.duplicate(user, report_id, title=title)
        self.audit.record(user, "report.save_as", target_type="report", target_id=copy.id,
                          detail={"source": report_id, "title": title})
        return copy

    # ---------------------------------------------------------------- version history
    def save_version(self, user: User, report_id: str, note: str = "") -> ReportVersion:
        """Manual Save = an immutable snapshot the user can return to."""
        rec = self._require_editable(user, report_id)
        version = ReportVersion(id=str(uuid.uuid4()), report_id=report_id,
                                version=self._versions.next_version(report_id),
                                document=dict(rec.document), note=note,
                                created_by=user.email)
        self._versions.add(version)
        rec.version = version.version
        self._reports.save(rec)
        self.audit.record(user, "report.version", target_type="report", target_id=report_id,
                          detail={"version": version.version, "note": note})
        return version

    def list_versions(self, report_id: str) -> list[ReportVersion]:
        return self._versions.list(report_id)

    def restore_version(self, user: User, report_id: str, version: int) -> ReportRecord:
        snap = self._versions.get(report_id, version)
        if snap is None:
            raise ValueError(f"version {version} of report {report_id!r} not found")
        rec = self._require_editable(user, report_id)
        self.save_version(user, report_id, note=f"auto before restore of v{version}")
        rec.document = dict(snap.document)
        self._reports.save(rec)
        self.audit.record(user, "report.restore_version", target_type="report",
                          target_id=report_id, detail={"version": version})
        return rec

    # ---------------------------------------------------------------- image manager
    def upload_image(self, user: User, data: bytes, filename: str, mime: str,
                     workspace_id: str | None = None) -> ReportImage:
        """Store an image ONCE; reports reference it by id."""
        require(user.role, Capability.EDIT)
        if self._images is None:
            raise ValueError("Image storage is not configured.")
        image_id = str(uuid.uuid4())
        self._images.save(image_id, data, mime)
        record = ReportImage(id=image_id, filename=filename, mime=mime,
                             size_bytes=len(data), workspace_id=workspace_id,
                             owner=user.email)
        self._image_repo.add(record)
        self.audit.record(user, "report.image_upload", target_type="image",
                          target_id=image_id, detail={"filename": filename})
        return record

    def preview_chart(self, viz_id: str, frame: Any, controls: dict[str, Any] | None = None,
                      dpi: int = 110) -> bytes | None:
        """PNG preview of a registered visualization for the chart picker.
        Reuses the platform renderer - no chart code here."""
        return self._charts.render_png(viz_id, frame, controls or {}, dpi=dpi)

    def dataset_frame(self, dataset_id: str | None) -> Any:
        """The saved dataset behind a report (via the workspace's storage)."""
        if not dataset_id or self._frame_provider is None:
            return None
        return self._frame_provider(dataset_id)

    def image_bytes(self, image_id: str) -> bytes | None:
        return self._images.load(image_id) if self._images else None

    def image_mime(self, image_id: str) -> str:
        return self._images.mime(image_id) if self._images else ""

    def list_images(self, workspace_id: str | None = None) -> list[ReportImage]:
        return self._image_repo.list(workspace_id)

    def delete_image(self, user: User, image_id: str) -> None:
        require(user.role, Capability.EDIT)
        if self._images is not None:
            self._images.delete(image_id)
        self._image_repo.delete(image_id)
        self.audit.record(user, "report.image_delete", target_type="image", target_id=image_id)

    # ---------------------------------------------------------------- export
    def _materialize(self, doc: ReportDocument, record: ReportRecord | None) -> ReportDocument:
        """Regenerate chart blocks from the SAVED dataset and inline image
        assets, so the exporter only embeds. Deterministic for the same data."""
        dataset_id = (record.dataset_id if record else None) or doc.meta.get("dataset_id")
        frame = None
        if dataset_id and self._frame_provider is not None:
            frame = self._frame_provider(dataset_id)
        self._charts.materialize(doc, frame)
        if self._images is not None:
            for block in doc.blocks:
                if block.kind == "image" and not block.hidden:
                    data = self._images.load(block.payload.get("image_id", ""))
                    if data:
                        import base64
                        block.payload["image_b64"] = base64.b64encode(data).decode("ascii")
                        block.payload["mime"] = self._images.mime(block.payload["image_id"])
        return doc

    def render(self, user: User, report_id: str, fmt: str = "html") -> RenderedReport:
        doc = self.document(report_id)
        if doc is None:
            raise ValueError(f"report {report_id!r} not found")
        doc = self._materialize(doc, self._reports.get(report_id))
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
