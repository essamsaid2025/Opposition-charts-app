from __future__ import annotations

from fap.core.plugin import PluginInfo
from fap.exports.base import Exporter, ExportPayload, ExportResult, export_registry
from fap.utils.text import slugify


@export_registry.register
class CsvExporter(Exporter):
    info = PluginInfo(id="csv", name="CSV data", category="data")

    def can_export(self, payload: ExportPayload) -> bool:
        return payload.frame is not None

    def export(self, payload: ExportPayload) -> ExportResult:
        assert payload.frame is not None
        data = payload.frame.to_csv(index=False).encode("utf-8")
        return ExportResult(data, "text/csv", f"{slugify(payload.title)}.csv")
