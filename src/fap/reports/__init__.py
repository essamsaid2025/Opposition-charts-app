"""Professional Reports Engine.

Builds on the platform: sections/templates/exporters are plugin families, a
DocumentBuilder composes a pure ReportDocument from a template + dataset (reusing
platform metrics, insights and visualizations), a ReportRenderer exports it
(HTML/Markdown now; PDF/DOCX/PPTX architecture-ready), and a ReportsManager owns
the lifecycle with identity permissions and audit. Nothing here modifies the
visualization engine, analytics, imports, providers, workspaces or identity.

The original lightweight ReportSection/ReportBuilder (figure rendering) is kept
untouched for backward compatibility.
"""
# legacy (unchanged)
from fap.reports.builder import ReportBuilder, ReportSection, ReportSpec, section_registry
from fap.reports import visual_section  # noqa: F401  (registers the visuals section)

# reports engine
from fap.reports.models import (
    Chart, Cover, Insight, KPI, ReportDocument, ReportRecord, Section, Table,
)
from fap.reports.sections import BuildContext, SectionBuilder, section_builder_registry
from fap.reports.templates import CustomTemplate, ReportTemplate, template_registry
from fap.reports.exporters import RenderedReport, ReportExporter, exporter_registry
from fap.reports.builders import DocumentBuilder
from fap.reports.renderer import ReportRenderer
from fap.reports.manager import ReportsManager
from fap.reports.registry import load_builtin_reports

__all__ = [
    # legacy
    "ReportBuilder", "ReportSection", "ReportSpec", "section_registry",
    # models
    "ReportDocument", "ReportRecord", "Section", "Cover", "KPI", "Table", "Insight", "Chart",
    # engine
    "BuildContext", "SectionBuilder", "section_builder_registry",
    "ReportTemplate", "CustomTemplate", "template_registry",
    "ReportExporter", "RenderedReport", "exporter_registry",
    "DocumentBuilder", "ReportRenderer", "ReportsManager", "load_builtin_reports",
]
