from __future__ import annotations

import json
from typing import Any, BinaryIO

import pandas as pd

from fap.core.exceptions import ProviderError
from fap.core.plugin import PluginInfo
from fap.providers.base import DataProvider, RawDataset, provider_registry


@provider_registry.register
class SkillCornerProvider(DataProvider):
    info = PluginInfo(id="skillcorner_events", name="SkillCorner events (JSON)", category="vendor",
                      description="SkillCorner event/dynamic-events exports (centered meters).")

    def supports(self, filename: str) -> bool:
        return "skillcorner" in filename.lower() and filename.lower().endswith(".json")

    def load(self, source: BinaryIO, filename: str,
             options: dict[str, Any] | None = None) -> RawDataset:
        try:
            payload = json.load(source)
        except Exception as exc:
            raise ProviderError(f"Invalid SkillCorner JSON {filename!r}: {exc}") from exc
        events = payload.get("data", payload) if isinstance(payload, dict) else payload
        frame = pd.json_normalize(events, sep="_")
        return RawDataset(frame=frame, native_coord_system="skillcorner")
