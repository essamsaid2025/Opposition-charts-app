from __future__ import annotations

import json
from typing import Any, BinaryIO

import pandas as pd

from fap.core.exceptions import ProviderError
from fap.core.plugin import PluginInfo
from fap.providers.base import DataProvider, RawDataset, provider_registry


@provider_registry.register
class SecondSpectrumProvider(DataProvider):
    info = PluginInfo(id="second_spectrum_events", name="Second Spectrum events (JSON/JSONL)",
                      category="vendor",
                      description="Second Spectrum event exports (centered meters).")

    def supports(self, filename: str) -> bool:
        low = filename.lower()
        return ("secondspectrum" in low or "second_spectrum" in low) and \
            low.endswith((".json", ".jsonl"))

    def load(self, source: BinaryIO, filename: str,
             options: dict[str, Any] | None = None) -> RawDataset:
        data = source.read().decode("utf-8", errors="replace").strip()
        try:
            if filename.lower().endswith(".jsonl") or "\n{" in data:
                events = [json.loads(line) for line in data.splitlines() if line.strip()]
            else:
                payload = json.loads(data)
                events = payload.get("events", payload) if isinstance(payload, dict) else payload
        except Exception as exc:
            raise ProviderError(f"Invalid Second Spectrum file {filename!r}: {exc}") from exc
        frame = pd.json_normalize(events, sep="_")
        return RawDataset(frame=frame, native_coord_system="second_spectrum")
