"""STATS Perform (Opta SD / MA feeds) JSON exports.

Recognition is signature-driven; parsing reuses the generic JSON reader, which
flattens nested event objects into columns the mapping engine understands. The
older Opta F24 XML feed keeps its own dedicated provider.
"""
from __future__ import annotations

from typing import Any, BinaryIO

from fap.core.plugin import PluginInfo
from fap.providers.base import RawDataset, provider_registry
from fap.providers.builtin.json_provider import JsonProvider
from fap.providers.signature import ProviderSignature


@provider_registry.register
class StatsPerformProvider(JsonProvider):
    info = PluginInfo(id="stats_perform", name="STATS Perform events (JSON)", category="vendor",
                      description="STATS Perform / Opta SD event feeds (MA1/MA3-style JSON).")
    signature = ProviderSignature(
        supported_extensions=(".json",),
        filename_patterns=("statsperform", "stats_perform", "opta_sd", "ma3", "ma1"),
        json_patterns=("liveData", "matchInfo", "matchDetails"),
        nested_object_patterns=("matchInfo.id", "liveData.event"),
        # only names that are genuinely STATS Perform's; "outcome"/"typeId" are
        # common enough to appear in unrelated feeds, so they stay advisory
        # (optional_columns) rather than acting as a fingerprint.
        provider_identifiers=("statsperform", "stats_perform", "liveData", "contestantId"),
        optional_columns=("contestantId", "playerId", "periodId", "timeMin", "timeSec",
                          "typeId", "x", "y"),
        schema_version="stats-perform-ma3",
    )

    def supports(self, filename: str) -> bool:
        low = filename.lower()
        return low.endswith(".json") and any(
            token in low for token in ("statsperform", "stats_perform", "opta_sd", "ma3", "ma1"))

    def load(self, source: BinaryIO, filename: str,
             options: dict[str, Any] | None = None) -> RawDataset:
        raw = super().load(source, filename, options)
        return RawDataset(frame=raw.frame, native_coord_system="0-100",
                          meta={**raw.meta, "provider": "stats_perform"})
