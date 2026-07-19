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
    Block, Chart, Cover, Insight, KPI, ReportDocument, ReportRecord, Section, Table,
)
from fap.reports.blocks import (
    BLOCK_KINDS, ChartBlockRenderer, add_block, chart_block, delete_block,
    duplicate_block, image_block, move_block, reorder_blocks, set_hidden,
    text_block, visible_blocks,
)
# report studio (editable page/layout overlay - phase 6A)
from fap.reports.studio import (
    Align, Axis, BlockLayout, Edge, EditorState, Page, PageSize, ReportStudio,
    A4, LETTER, PAGE_SIZES, new_page, page_size,
)
from fap.reports import editor_ops
from fap.reports.sections import BuildContext, SectionBuilder, section_builder_registry
from fap.reports.templates import CustomTemplate, ReportTemplate, template_registry
from fap.reports.exporters import RenderedReport, ReportExporter, exporter_registry
# publishing & layout engine (phase 6C)
from fap.reports.publishing import (
    CoverDesign, Margins, MasterPage, PageNumbering, PrintSettings, PublishSettings,
    Watermark, Zone, preset as publish_preset, PRESETS,
)
from fap.reports.layout import (
    LayoutEngine, RenderedDocument, RenderedElement, RenderedPage,
)
from fap.reports.builders import DocumentBuilder
from fap.reports.renderer import ReportRenderer
from fap.reports.manager import ReportsManager
from fap.reports.registry import load_builtin_reports

__all__ = [
    # legacy
    "ReportBuilder", "ReportSection", "ReportSpec", "section_registry",
    # models
    "ReportDocument", "ReportRecord", "Section", "Cover", "KPI", "Table", "Insight", "Chart",
    "Block", "BLOCK_KINDS", "text_block", "image_block", "chart_block", "add_block",
    "delete_block", "duplicate_block", "move_block", "reorder_blocks", "set_hidden",
    "visible_blocks", "ChartBlockRenderer",
    # report studio (phase 6A)
    "ReportStudio", "Page", "PageSize", "BlockLayout", "EditorState",
    "Align", "Edge", "Axis", "A4", "LETTER", "PAGE_SIZES", "new_page", "page_size",
    "editor_ops",
    # engine
    "BuildContext", "SectionBuilder", "section_builder_registry",
    "ReportTemplate", "CustomTemplate", "template_registry",
    "ReportExporter", "RenderedReport", "exporter_registry",
    "DocumentBuilder", "ReportRenderer", "ReportsManager", "load_builtin_reports",
    # publishing & layout (phase 6C)
    "LayoutEngine", "RenderedDocument", "RenderedPage", "RenderedElement",
    "PublishSettings", "CoverDesign", "MasterPage", "Watermark", "Zone",
    "PageNumbering", "PrintSettings", "Margins", "publish_preset", "PRESETS",
]
