from __future__ import annotations

from io import BytesIO

from fap.core.plugin import PluginInfo
from fap.exports.base import Exporter, ExportPayload, ExportResult, export_registry
from fap.utils.text import slugify


@export_registry.register
class SvgExporter(Exporter):
    """Scalable vector export - resolution-independent for design tools."""
    info = PluginInfo(id="svg", name="SVG vector", category="image")

    def can_export(self, payload: ExportPayload) -> bool:
        return payload.figure is not None

    def export(self, payload: ExportPayload) -> ExportResult:
        assert payload.figure is not None
        buf = BytesIO()
        transparent = bool(payload.meta.get("transparent", False))
        kwargs = {} if transparent else {"facecolor": payload.figure.get_facecolor()}
        payload.figure.savefig(buf, format="svg", bbox_inches="tight",
                               transparent=transparent, **kwargs)
        return ExportResult(buf.getvalue(), "image/svg+xml", f"{slugify(payload.title)}.svg")
