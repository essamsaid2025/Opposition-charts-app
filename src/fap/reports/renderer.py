"""ReportRenderer - render a ReportDocument to a chosen format via the exporter
registry. The renderer picks an exporter by format and delegates; it adds no
formatting logic of its own, so builders never learn about output formats.
"""
from __future__ import annotations

from typing import Any

from fap.core.exceptions import PluginNotFoundError
from fap.reports.exporters import RenderedReport, exporter_registry
from fap.reports.layout import LayoutEngine
from fap.reports.models import ReportDocument


class ReportRenderer:
    """Picks an exporter by format and feeds it the Layout Engine's output. The
    layout is built ONCE per render and shared, so every format is laid out
    identically and no exporter re-computes positioning."""

    def __init__(self, registry: Any = exporter_registry,
                 layout: LayoutEngine | None = None) -> None:
        self._registry = registry
        self._layout = layout or LayoutEngine()

    def formats(self) -> list[str]:
        """All registered formats, available or not."""
        return sorted({e().fmt for e in self._registry})

    def available_formats(self) -> list[str]:
        return sorted({e().fmt for e in self._registry if getattr(e, "available", True)})

    def _exporter(self, fmt: str):
        for cls in self._registry:
            if cls().fmt == fmt:
                return cls()
        raise PluginNotFoundError(f"No report exporter for format {fmt!r}")

    def render(self, document: ReportDocument, fmt: str = "html",
               branding: Any = None, image_resolver: Any = None) -> RenderedReport:
        rendered = self._layout.build(document, branding, image_resolver)
        return self._exporter(fmt).export(rendered, branding)
