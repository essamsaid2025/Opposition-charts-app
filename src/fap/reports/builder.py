"""Report composition. A report is an ordered list of section plugin ids; each
section renders content (text, metrics, figures) from the same RenderContext.
Output formats reuse the export plugin family (pdf/pptx/docx exporters)."""
from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Any

from fap.core.plugin import Plugin, PluginRegistry
from fap.core.types import RenderContext


@dataclass(slots=True)
class SectionOutput:
    title: str
    markdown: str = ""
    figures: list[Any] = field(default_factory=list)
    tables: list[Any] = field(default_factory=list)


class ReportSection(Plugin):
    @abstractmethod
    def build(self, ctx: RenderContext) -> SectionOutput: ...


section_registry: PluginRegistry[ReportSection] = PluginRegistry("report_section")


@dataclass(slots=True)
class ReportSpec:
    title: str
    section_ids: list[str]
    meta: dict[str, Any] = field(default_factory=dict)


class ReportBuilder:
    def __init__(self, registry: PluginRegistry[ReportSection] = section_registry) -> None:
        self._registry = registry

    def build(self, spec: ReportSpec, ctx: RenderContext) -> list[SectionOutput]:
        return [self._registry.create(sid).build(ctx) for sid in spec.section_ids]
