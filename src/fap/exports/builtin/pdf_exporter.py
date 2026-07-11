from __future__ import annotations

from io import BytesIO

from fap.core.plugin import PluginInfo
from fap.exports.base import Exporter, ExportPayload, ExportResult, export_registry
from fap.utils.text import slugify


@export_registry.register
class PdfExporter(Exporter):
    """PDF-ready export for match reports and print workflows."""
    info = PluginInfo(id="pdf", name="PDF document", category="document")

    def can_export(self, payload: ExportPayload) -> bool:
        return payload.figure is not None

    def export(self, payload: ExportPayload) -> ExportResult:
        assert payload.figure is not None
        buf = BytesIO()
        payload.figure.savefig(buf, format="pdf", bbox_inches="tight",
                               dpi=int(payload.meta.get("dpi", 300)),
                               facecolor=payload.figure.get_facecolor())
        return ExportResult(buf.getvalue(), "application/pdf", f"{slugify(payload.title)}.pdf")
