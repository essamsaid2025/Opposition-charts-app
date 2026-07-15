"""Catapult GPS exports.

Recognition is signature-driven; parsing reuses the generic CSV reader and the
platform's mapping engine, exactly like the Hudl provider. Catapult ships event
and 10Hz athlete exports whose column names vary by template, so this provider
deliberately does not hard-code a column mapping - fap.pipeline.columns maps
what it recognizes and the mapping dialog covers the rest.
"""
from __future__ import annotations

from typing import Any, BinaryIO

from fap.core.plugin import PluginInfo
from fap.providers.base import RawDataset, provider_registry
from fap.providers.builtin.csv_provider import CsvProvider
from fap.providers.signature import ProviderSignature


@provider_registry.register
class CatapultProvider(CsvProvider):
    info = PluginInfo(id="catapult", name="Catapult GPS export (CSV)", category="vendor",
                      description="Catapult athlete/event CSV exports.")
    signature = ProviderSignature(
        supported_extensions=(".csv",),
        filename_patterns=("catapult", "openfield"),
        provider_identifiers=("catapult", "openfield", "player load", "playerload"),
        # both, not just "Player Name": that column alone appears in half the
        # club exports in football and would let Catapult claim a generic CSV.
        required_columns=("Player Name", "Player Load"),
        optional_columns=("Odometer", "Velocity", "Acceleration",
                          "Heart Rate", "Latitude", "Longitude", "Period Name"),
        schema_version="catapult-openfield",
    )

    def supports(self, filename: str) -> bool:
        low = filename.lower()
        return ("catapult" in low or "openfield" in low) and low.endswith(".csv")

    def load(self, source: BinaryIO, filename: str,
             options: dict[str, Any] | None = None) -> RawDataset:
        raw = super().load(source, filename, options)
        return RawDataset(frame=raw.frame, native_coord_system=raw.native_coord_system,
                          meta={**raw.meta, "provider": "catapult"})
