from __future__ import annotations

from typing import Any, BinaryIO

from fap.core.plugin import PluginInfo
from fap.providers.base import RawDataset, provider_registry
from fap.providers.builtin.csv_provider import CsvProvider
from fap.providers.signature import ProviderSignature


@provider_registry.register
class ManualTaggingProvider(CsvProvider):
    """Manually tagged data (the club's own tagging sheets). Identical parsing
    to CSV, kept as its own plugin so templates and defaults can specialize."""
    info = PluginInfo(id="manual", name="Manual tagged data (CSV)", category="manual",
                      description="The club's own tagging convention; canonical column names "
                                  "or wizard mapping.")

    signature = ProviderSignature(
        supported_extensions=(".csv",),
        filename_patterns=("manual",),
        schema_version="manual-tagging",
    )

    def supports(self, filename: str) -> bool:
        return "manual" in filename.lower() and filename.lower().endswith(".csv")

    def load(self, source: BinaryIO, filename: str,
             options: dict[str, Any] | None = None) -> RawDataset:
        return super().load(source, filename, options)
