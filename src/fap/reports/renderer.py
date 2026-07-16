"""ReportRenderer - render a ReportDocument to a chosen format via the exporter
registry. The renderer picks an exporter by format and delegates; it adds no
formatting logic of its own, so builders never learn about output formats.
"""
from __future__ import annotations

from typing import Any

from fap.core.exceptions import PluginNotFoundError
from fap.reports.exporters import RenderedReport, exporter_registry
from fap.reports.models import ReportDocument


class ReportRenderer:
    def __init__(self, registry: Any = exporter_registry) -> None:
        self._registry = registry

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
               branding: Any = None) -> RenderedReport:
        return self._exporter(fmt).render(document, branding)
