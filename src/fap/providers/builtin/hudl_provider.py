from __future__ import annotations

from typing import Any, BinaryIO

from fap.core.plugin import PluginInfo
from fap.providers.base import RawDataset, provider_registry
from fap.providers.builtin.csv_provider import CsvProvider


@provider_registry.register
class HudlProvider(CsvProvider):
    """Hudl CSV exports: same parsing as CSV; column aliases and the wizard's
    mapping step handle Hudl's naming."""
    info = PluginInfo(id="hudl", name="Hudl export (CSV)", category="vendor",
                      description="Hudl match/event CSV exports.")

    def supports(self, filename: str) -> bool:
        return "hudl" in filename.lower() and filename.lower().endswith(".csv")

    def load(self, source: BinaryIO, filename: str,
             options: dict[str, Any] | None = None) -> RawDataset:
        raw = super().load(source, filename, options)
        return RawDataset(frame=raw.frame, native_coord_system="0-100", meta=raw.meta)
