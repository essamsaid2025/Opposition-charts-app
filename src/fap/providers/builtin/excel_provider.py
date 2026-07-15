from __future__ import annotations

from typing import Any, BinaryIO

import pandas as pd
from dataclasses import asdict

from fap.core.exceptions import ProviderError
from fap.core.plugin import PluginInfo
from fap.providers.base import DataProvider, RawDataset, provider_registry
from fap.providers.detection import detect_format
from fap.providers.signature import ProviderSignature


@provider_registry.register
class ExcelProvider(DataProvider):
    info = PluginInfo(id="generic_excel", name="Excel / custom spreadsheet", category="file",
                      description="Any .xlsx/.xls workbook; sheet selectable in the wizard.")
    signature = ProviderSignature(
        supported_extensions=(".xlsx", ".xls"),
        generic=True, priority=-100, schema_version="generic",
    )

    def supports(self, filename: str) -> bool:
        return filename.lower().endswith((".xlsx", ".xls"))

    def load(self, source: BinaryIO, filename: str,
             options: dict[str, Any] | None = None) -> RawDataset:
        options = options or {}
        data = source.read()
        fmt = detect_format(data, filename)
        try:
            frame = pd.read_excel(pd.io.common.BytesIO(data),
                                  sheet_name=options.get("sheet", 0),
                                  header=options.get("header_row", 0))
        except Exception as exc:
            raise ProviderError(f"Could not parse Excel {filename!r}: {exc}") from exc
        return RawDataset(frame=frame, meta={"format": asdict(fmt)})
