from __future__ import annotations

from typing import Any, BinaryIO

import pandas as pd

from fap.core.exceptions import ProviderError
from fap.core.plugin import PluginInfo
from fap.providers.base import DataProvider, RawDataset, provider_registry


@provider_registry.register
class TracabProvider(DataProvider):
    info = PluginInfo(id="tracab_events", name="Tracab event export (CSV)", category="vendor",
                      description="Tracab/ChyronHego event CSVs (centered centimeters).")

    def supports(self, filename: str) -> bool:
        return "tracab" in filename.lower() and filename.lower().endswith(".csv")

    def load(self, source: BinaryIO, filename: str,
             options: dict[str, Any] | None = None) -> RawDataset:
        try:
            frame = pd.read_csv(source)
        except Exception as exc:
            raise ProviderError(f"Could not parse Tracab CSV {filename!r}: {exc}") from exc
        return RawDataset(frame=frame, native_coord_system="tracab")
