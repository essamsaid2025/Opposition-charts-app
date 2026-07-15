from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, BinaryIO

import pandas as pd

from fap.core.exceptions import ProviderError
from fap.core.plugin import PluginInfo
from fap.providers.base import DataProvider, RawDataset, provider_registry
from fap.providers.signature import ProviderSignature


@provider_registry.register
class SportscodeProvider(DataProvider):
    info = PluginInfo(id="sportscode", name="Hudl Sportscode timeline (XML)", category="vendor",
                      description="Sportscode instance exports; codes become event types, "
                                  "labels become player/team/notes.")

    signature = ProviderSignature(
        supported_extensions=(".xml",),
        filename_patterns=("sportscode", "timeline"),
        json_patterns=("ALL_INSTANCES", "instance"),
        provider_identifiers=("ALL_INSTANCES", "sportscode"),
        optional_columns=("code", "start", "end"),
        schema_version="sportscode-timeline",
    )

    def supports(self, filename: str) -> bool:
        low = filename.lower()
        return low.endswith(".xml") and ("sportscode" in low or "timeline" in low)

    def load(self, source: BinaryIO, filename: str,
             options: dict[str, Any] | None = None) -> RawDataset:
        try:
            root = ET.parse(source).getroot()
        except ET.ParseError as exc:
            raise ProviderError(f"Invalid Sportscode XML {filename!r}: {exc}") from exc

        rows: list[dict[str, Any]] = []
        for inst in root.iter("instance"):
            start = float(inst.findtext("start", "0") or 0)
            labels: dict[str, str] = {}
            notes: list[str] = []
            for label in inst.findall("label"):
                group = (label.findtext("group") or "").strip().lower()
                text = (label.findtext("text") or "").strip()
                if group:
                    labels[group] = text
                elif text:
                    notes.append(text)
            rows.append({
                "event_type": (inst.findtext("code") or "").strip(),
                "timestamp": start,
                "minute": int(start // 60), "second": start % 60,
                "player": labels.get("player", ""),
                "team": labels.get("team", ""),
                "outcome": labels.get("outcome", ""),
                "phase": labels.get("phase", ""),
                "x": labels.get("x"), "y": labels.get("y"),
                "notes": "; ".join(notes),
                "sequence_id": inst.findtext("ID", "") or "",
            })
        return RawDataset(frame=pd.DataFrame(rows), native_coord_system="0-100")
