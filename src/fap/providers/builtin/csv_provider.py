from __future__ import annotations

from typing import BinaryIO

import pandas as pd

from fap.core.exceptions import ProviderError
from fap.core.plugin import PluginInfo
from fap.providers.base import DataProvider, RawDataset, provider_registry


@provider_registry.register
class CsvProvider(DataProvider):
    info = PluginInfo(id="generic_csv", name="Generic CSV", category="file",
                      description="Manually-tagged event CSVs (canonical column names).")

    def supports(self, filename: str) -> bool:
        return filename.lower().endswith(".csv")

    def load(self, source: BinaryIO, filename: str) -> RawDataset:
        try:
            frame = pd.read_csv(source)
        except Exception as exc:
            raise ProviderError(f"Could not parse CSV {filename!r}: {exc}") from exc
        return RawDataset(frame=frame, native_coord_system="0-100")
