"""Report plugin registries + discovery.

Three families, all decorator-registered so the engine discovers them and never
hard-codes a section, template or export format:

    section_builder_registry  SectionBuilder  (dataset -> Section)
    template_registry         ReportTemplate  (ordered section ids + cover)
    exporter_registry         ReportExporter  (ReportDocument -> bytes)

Kept separate from the legacy ``fap.reports.builder.section_registry`` (the
figure-rendering ReportSection family), which is left untouched.
"""
from __future__ import annotations

from fap.reports.exporters import exporter_registry, load_builtin_exporters
from fap.reports.sections import section_builder_registry
from fap.reports.templates import template_registry


def load_builtin_reports() -> None:
    """Import the built-in sections, templates and exporters so they register."""
    from fap.core.discovery import discover_plugins
    from fap.reports import builtin
    discover_plugins(builtin)          # section builders + templates live here
    load_builtin_exporters()           # html / markdown / stubs


__all__ = ["section_builder_registry", "template_registry", "exporter_registry",
           "load_builtin_reports"]
