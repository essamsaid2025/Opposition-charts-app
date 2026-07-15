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
class CsvProvider(DataProvider):
    info = PluginInfo(id="generic_csv", name="CSV / custom spreadsheet", category="file",
                      description="Any CSV: delimiter, encoding and header row auto-detected.")
    signature = ProviderSignature(
        supported_extensions=(".csv", ".txt", ".tsv"),
        generic=True, priority=-100, schema_version="generic",
    )

    def supports(self, filename: str) -> bool:
        return filename.lower().endswith((".csv", ".txt", ".tsv"))

    def load(self, source: BinaryIO, filename: str,
             options: dict[str, Any] | None = None) -> RawDataset:
        options = options or {}
        data = source.read()
        fmt = detect_format(data, filename)
        try:
            frame = pd.read_csv(
                pd.io.common.BytesIO(data),
                sep=options.get("delimiter", fmt.delimiter),
                encoding=options.get("encoding", fmt.encoding),
                header=options.get("header_row", fmt.header_row),
            )
        except Exception as exc:
            raise ProviderError(f"Could not parse CSV {filename!r}: {exc}") from exc
        return RawDataset(frame=frame, meta={"format": asdict(fmt)})
