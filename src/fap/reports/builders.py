"""DocumentBuilder - compose a ReportDocument from a template + a BuildContext.

It resolves the template's ordered section ids against the section-builder
registry, invokes each builder (lazily - only the template's sections run), and
assembles the cover. Pure: it returns objects, never rendered output. A faulty
section is captured as a placeholder, never fatal.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fap.reports.models import Cover, ReportDocument, Section
from fap.reports.sections import BuildContext, section_builder_registry
from fap.reports.templates import ReportTemplate, template_registry

logger = logging.getLogger(__name__)


class DocumentBuilder:
    def __init__(self, sections: Any = section_builder_registry,
                 templates: Any = template_registry) -> None:
        self._sections = sections
        self._templates = templates

    # -- template resolution -----------------------------------------
    def _template(self, template: "str | ReportTemplate | Any") -> Any:
        if isinstance(template, str):
            return self._templates.create(template)
        return template          # a ReportTemplate instance or a CustomTemplate

    def available_templates(self) -> list[Any]:
        return [self._templates.create(t) for t in self._templates.ids()]

    def available_sections(self) -> list[str]:
        return self._sections.ids()

    # -- build --------------------------------------------------------
    def build(self, template: "str | ReportTemplate | Any", ctx: BuildContext, *,
              title: str = "", report_id: str | None = None) -> ReportDocument:
        tpl = self._template(template)
        tpl_id = tpl.info.id
        cover = self._cover(tpl, ctx, title)
        sections: list[Section] = []
        for sid in tpl.section_ids:
            sections.append(self._build_section(sid, ctx))
        return ReportDocument(
            id=report_id or str(uuid.uuid4()),
            title=title or cover.title, template_id=tpl_id, cover=cover,
            sections=sections,
            meta={"workspace_id": ctx.workspace_id, "project_id": ctx.project_id,
                  "dataset_id": ctx.dataset_id, "rows": int(0 if ctx.empty else len(ctx.df))})

    def _build_section(self, section_id: str, ctx: BuildContext) -> Section:
        if section_id not in self._sections:
            return Section(id=section_id, title=section_id.replace("_", " ").title(),
                           markdown="_Section not available._")
        try:
            return self._sections.create(section_id).build(ctx)
        except Exception:               # a bad section must never break the report
            logger.exception("Report section %s failed", section_id)
            return Section(id=section_id, title=section_id.replace("_", " ").title(),
                           notes="This section could not be generated.")

    def _cover(self, tpl: Any, ctx: BuildContext, title: str) -> Cover:
        cov = {**tpl.cover_defaults(), **ctx.cover}
        brand = ctx.branding
        opponent = cov.get("opponent", "")
        default_title = f"{tpl.info.name}" + (f" — {opponent}" if opponent else "")
        return Cover(
            title=title or cov.get("title") or default_title,
            subtitle=cov.get("subtitle") or getattr(tpl, "subtitle", ""),
            club=cov.get("club") or getattr(brand, "club_name", ""),
            organization=cov.get("organization") or getattr(brand, "organization_name", ""),
            competition=cov.get("competition", ""), season=cov.get("season", ""),
            opponent=opponent, match_date=cov.get("match_date", ""),
            analyst=ctx.analyst or cov.get("analyst", ""),
            generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            version=str(cov.get("version", "1.0")), template_id=tpl.info.id,
            club_logo=cov.get("club_logo") or getattr(brand, "primary_logo", ""),
            organization_logo=cov.get("organization_logo") or getattr(brand, "secondary_logo", ""))
