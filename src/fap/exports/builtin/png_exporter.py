from __future__ import annotations

from io import BytesIO

from fap.core.plugin import PluginInfo
from fap.exports.base import Exporter, ExportPayload, ExportResult, export_registry
from fap.utils.text import slugify


@export_registry.register
class PngExporter(Exporter):
    info = PluginInfo(id="png", name="PNG image", category="image")

    def can_export(self, payload: ExportPayload) -> bool:
        return payload.figure is not None

    def export(self, payload: ExportPayload) -> ExportResult:
        assert payload.figure is not None
        buf = BytesIO()
        payload.figure.savefig(buf, format="png", dpi=240, bbox_inches="tight",
                               facecolor=payload.figure.get_facecolor())
        return ExportResult(buf.getvalue(), "image/png", f"{slugify(payload.title)}.png")
