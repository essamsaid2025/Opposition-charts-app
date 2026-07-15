from __future__ import annotations

import json
from typing import Any, BinaryIO

import pandas as pd

from fap.core.exceptions import ProviderError
from fap.core.plugin import PluginInfo
from fap.providers.base import DataProvider, RawDataset, provider_registry
from fap.providers.signature import ProviderSignature


def _get(d: dict, *path: str, default: Any = None) -> Any:
    for key in path:
        if not isinstance(d, dict) or key not in d:
            return default
        d = d[key]
    return d


@provider_registry.register
class StatsBombProvider(DataProvider):
    info = PluginInfo(id="statsbomb", name="StatsBomb events (JSON)", category="vendor",
                      description="StatsBomb open-data / API event files.")
    signature = ProviderSignature(
        supported_extensions=(".json",),
        filename_patterns=("statsbomb", "sb_events"),
        json_patterns=("possession_team", "play_pattern"),
        nested_object_patterns=("type.name", "pass.end_location", "possession_team.name",
                                "play_pattern.name"),
        provider_identifiers=("statsbomb_xg", "possession_team", "play_pattern",
                              "under_pressure"),
        optional_columns=("location", "minute", "second", "period", "possession"),
        schema_version="statsbomb-v4",
    )

    def supports(self, filename: str) -> bool:
        return "statsbomb" in filename.lower() and filename.lower().endswith(".json")

    def load(self, source: BinaryIO, filename: str,
             options: dict[str, Any] | None = None) -> RawDataset:
        try:
            events = json.load(source)
        except Exception as exc:
            raise ProviderError(f"Invalid StatsBomb JSON {filename!r}: {exc}") from exc
        if not isinstance(events, list):
            raise ProviderError("StatsBomb file must be a JSON array of events")

        rows: list[dict[str, Any]] = []
        for e in events:
            loc = e.get("location") or [None, None]
            detail = e.get("pass") or e.get("shot") or e.get("carry") or {}
            end = detail.get("end_location") or [None, None]
            rows.append({
                "event_type": _get(e, "type", "name", default=""),
                "sub_event": _get(e, "pass", "type", "name", default="") or
                             _get(e, "shot", "type", "name", default=""),
                "team": _get(e, "team", "name", default=""),
                "player": _get(e, "player", "name", default=""),
                "position": _get(e, "position", "name", default=""),
                "minute": e.get("minute"), "second": e.get("second"),
                "period": e.get("period", 1),
                "x": loc[0], "y": loc[1] if len(loc) > 1 else None,
                "end_x": end[0], "end_y": end[1] if len(end) > 1 else None,
                "outcome": _get(detail, "outcome", "name", default=""),
                "shot_result": _get(e, "shot", "outcome", "name", default=""),
                "shot_xg": _get(e, "shot", "statsbomb_xg"),
                "pass_length": _get(e, "pass", "length"),
                "pass_angle": _get(e, "pass", "angle"),
                "pass_height": _get(e, "pass", "height", "name", default=""),
                "body_part": _get(detail, "body_part", "name", default=""),
                "play_pattern": _get(e, "play_pattern", "name", default=""),
                "under_pressure": bool(e.get("under_pressure", False)),
                "receiver": _get(e, "pass", "recipient", "name", default=""),
                "sequence_id": e.get("possession", ""),
                "match_id": e.get("match_id", ""),
            })
        return RawDataset(frame=pd.DataFrame(rows), native_coord_system="statsbomb")
