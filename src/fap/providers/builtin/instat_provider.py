"""InStat event exports (CSV or Excel).

InStat ships both spreadsheet formats, so recognition allows either extension
and parsing dispatches to the matching generic reader. No InStat-specific
column handling: the mapping engine already knows the aliases.
"""
from __future__ import annotations

from typing import Any, BinaryIO

from fap.core.plugin import PluginInfo
from fap.providers.base import DataProvider, RawDataset, provider_registry
from fap.providers.builtin.csv_provider import CsvProvider
from fap.providers.builtin.excel_provider import ExcelProvider
from fap.providers.signature import ProviderSignature


@provider_registry.register
class InStatProvider(DataProvider):
    info = PluginInfo(id="instat", name="InStat events (CSV/Excel)", category="vendor",
                      description="InStat match event exports in CSV or Excel.")
    signature = ProviderSignature(
        supported_extensions=(".csv", ".xlsx", ".xls"),
        filename_patterns=("instat",),
        sheet_names=("InStat", "Events"),
        metadata_patterns=("instat",),
        provider_identifiers=("instat",),
        optional_columns=("Action", "Half", "Second", "Player", "Team", "Opponent",
                          "Pos x", "Pos y", "Dest x", "Dest y"),
        schema_version="instat-v1",
    )

    def supports(self, filename: str) -> bool:
        low = filename.lower()
        return "instat" in low and low.endswith((".csv", ".xlsx", ".xls"))

    def load(self, source: BinaryIO, filename: str,
             options: dict[str, Any] | None = None) -> RawDataset:
        reader: DataProvider = (ExcelProvider() if filename.lower().endswith((".xlsx", ".xls"))
                                else CsvProvider())
        raw = reader.load(source, filename, options)
        return RawDataset(frame=raw.frame, native_coord_system=raw.native_coord_system,
                          meta={**raw.meta, "provider": "instat"})
