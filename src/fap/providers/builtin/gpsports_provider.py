"""GPSports (Team AMS) GPS exports - signature recognition + generic CSV load."""
from __future__ import annotations

from typing import Any, BinaryIO

from fap.core.plugin import PluginInfo
from fap.providers.base import RawDataset, provider_registry
from fap.providers.builtin.csv_provider import CsvProvider
from fap.providers.signature import ProviderSignature


@provider_registry.register
class GpSportsProvider(CsvProvider):
    info = PluginInfo(id="gpsports", name="GPSports export (CSV)", category="vendor",
                      description="GPSports / Team AMS athlete CSV exports.")
    signature = ProviderSignature(
        supported_extensions=(".csv",),
        filename_patterns=("gpsports", "teamams", "team_ams"),
        provider_identifiers=("gpsports", "team ams", "teamams"),
        optional_columns=("Athlete", "Speed (m/s)", "Distance (m)", "Heart Rate",
                          "Impacts", "Session", "Split Name"),
        schema_version="gpsports-v1",
    )

    def supports(self, filename: str) -> bool:
        low = filename.lower()
        return ("gpsports" in low or "teamams" in low or "team_ams" in low) and low.endswith(".csv")

    def load(self, source: BinaryIO, filename: str,
             options: dict[str, Any] | None = None) -> RawDataset:
        raw = super().load(source, filename, options)
        return RawDataset(frame=raw.frame, native_coord_system=raw.native_coord_system,
                          meta={**raw.meta, "provider": "gpsports"})
