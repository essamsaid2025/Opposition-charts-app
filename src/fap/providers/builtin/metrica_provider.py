from __future__ import annotations

from typing import Any, BinaryIO

import pandas as pd

from fap.core.exceptions import ProviderError
from fap.core.plugin import PluginInfo
from fap.providers.base import DataProvider, RawDataset, provider_registry
from fap.providers.signature import ProviderSignature

_MAPPING = {
    "type": "event_type", "subtype": "sub_event", "team": "team",
    "from": "player", "to": "receiver", "period": "period",
    "start_time_[s]": "timestamp", "end_time_[s]": "notes_end_time",
    "start_x": "x", "start_y": "y", "end_x": "end_x", "end_y": "end_y",
}


@provider_registry.register
class MetricaProvider(DataProvider):
    info = PluginInfo(id="metrica", name="Metrica Sports events (CSV)", category="vendor",
                      description="Metrica Sports sample-data event CSVs (0-1 coordinates).")

    signature = ProviderSignature(
        supported_extensions=(".csv",),
        filename_patterns=("metrica",),
        provider_identifiers=("Start Frame", "Start Time [s]", "End Frame"),
        optional_columns=("Team", "Type", "Subtype", "Period", "From", "To",
                          "Start X", "Start Y", "End X", "End Y"),
        schema_version="metrica-v1",
    )

    def supports(self, filename: str) -> bool:
        return "metrica" in filename.lower() and filename.lower().endswith(".csv")

    def load(self, source: BinaryIO, filename: str,
             options: dict[str, Any] | None = None) -> RawDataset:
        try:
            frame = pd.read_csv(source)
        except Exception as exc:
            raise ProviderError(f"Could not parse Metrica CSV {filename!r}: {exc}") from exc
        return RawDataset(frame=frame, column_mapping=dict(_MAPPING),
                          native_coord_system="metrica")
