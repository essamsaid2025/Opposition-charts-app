from __future__ import annotations

import json
from typing import Any, BinaryIO

import pandas as pd

from fap.core.exceptions import ProviderError
from fap.core.plugin import PluginInfo
from fap.providers.base import DataProvider, RawDataset, provider_registry
from fap.providers.signature import ProviderSignature

_PERIODS = {"1H": 1, "2H": 2, "E1": 3, "E2": 4, "P": 5}
_ACCURATE, _INACCURATE = 1801, 1802


@provider_registry.register
class WyscoutProvider(DataProvider):
    info = PluginInfo(id="wyscout", name="Wyscout events (JSON)", category="vendor",
                      description="Wyscout v2/v3 event exports.")

    signature = ProviderSignature(
        supported_extensions=(".json",),
        filename_patterns=("wyscout",),
        # deliberately NOT json_patterns=("events",): plenty of non-Wyscout
        # exports wrap their records in an "events" key. Wyscout is recognized
        # by its own field names and its positions[]/tags[] shape instead.
        nested_object_patterns=("positions.x", "tags.id"),
        provider_identifiers=("eventName", "matchPeriod", "eventSec", "subEventName"),
        optional_columns=("eventName", "teamId", "playerId", "matchPeriod", "positions"),
        schema_version="wyscout-v2",
    )

    def supports(self, filename: str) -> bool:
        return "wyscout" in filename.lower() and filename.lower().endswith(".json")

    def load(self, source: BinaryIO, filename: str,
             options: dict[str, Any] | None = None) -> RawDataset:
        try:
            payload = json.load(source)
        except Exception as exc:
            raise ProviderError(f"Invalid Wyscout JSON {filename!r}: {exc}") from exc
        events = payload.get("events", payload) if isinstance(payload, dict) else payload

        rows: list[dict[str, Any]] = []
        for e in events:
            positions = e.get("positions") or [{}]
            start = positions[0] if positions else {}
            end = positions[1] if len(positions) > 1 else {}
            tags = {t.get("id") for t in e.get("tags", [])}
            outcome = ("successful" if _ACCURATE in tags
                       else "unsuccessful" if _INACCURATE in tags else "")
            sec = e.get("eventSec")
            rows.append({
                "event_type": e.get("eventName", ""),
                "sub_event": e.get("subEventName", ""),
                "team": str(e.get("teamId", "")),
                "player": str(e.get("playerId", "")),
                "period": _PERIODS.get(str(e.get("matchPeriod", "1H")), 1),
                "timestamp": sec,
                "minute": int(sec // 60) if sec is not None else None,
                "second": (sec % 60) if sec is not None else None,
                "x": start.get("x"), "y": start.get("y"),
                "end_x": end.get("x"), "end_y": end.get("y"),
                "outcome": outcome,
                "match_id": str(e.get("matchId", "")),
                "sequence_id": str(e.get("possessionId", "")),
            })
        return RawDataset(frame=pd.DataFrame(rows), native_coord_system="wyscout")
