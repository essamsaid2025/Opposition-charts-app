from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, BinaryIO

import pandas as pd

from fap.core.exceptions import ProviderError
from fap.core.plugin import PluginInfo
from fap.providers.base import DataProvider, RawDataset, provider_registry

TYPE_NAMES: dict[int, str] = {
    1: "pass", 2: "offside pass", 3: "dribble", 4: "foul", 5: "out", 6: "corner",
    7: "tackle", 8: "interception", 10: "save", 12: "clearance", 13: "shot",
    14: "shot", 15: "shot", 16: "shot", 17: "card", 44: "duel", 49: "recovery",
    50: "dispossessed", 51: "error", 61: "ball touch", 74: "block",
}
_GOAL_TYPE = 16
_END_X_Q, _END_Y_Q = "140", "141"


@provider_registry.register
class OptaF24Provider(DataProvider):
    info = PluginInfo(id="opta_f24", name="Opta F24 events (XML)", category="vendor",
                      description="Opta / Stats Perform F24 match event feeds.")

    def supports(self, filename: str) -> bool:
        low = filename.lower()
        return low.endswith(".xml") and ("opta" in low or "f24" in low)

    def load(self, source: BinaryIO, filename: str,
             options: dict[str, Any] | None = None) -> RawDataset:
        try:
            root = ET.parse(source).getroot()
        except ET.ParseError as exc:
            raise ProviderError(f"Invalid Opta XML {filename!r}: {exc}") from exc

        game = root.find(".//Game") if root.tag != "Game" else root
        if game is None:
            raise ProviderError("No <Game> element found in Opta file")

        rows: list[dict[str, Any]] = []
        for e in game.findall("Event"):
            type_id = int(e.get("type_id", 0))
            qualifiers = {q.get("qualifier_id"): q.get("value")
                          for q in e.findall("Q")}
            rows.append({
                "event_type": TYPE_NAMES.get(type_id, f"opta_type_{type_id}"),
                "sub_event": str(type_id),
                "team": e.get("team_id", ""),
                "player": e.get("player_id", ""),
                "minute": int(e.get("min", 0)), "second": int(e.get("sec", 0)),
                "period": int(e.get("period_id", 1)),
                "x": float(e.get("x", "nan")), "y": float(e.get("y", "nan")),
                "end_x": float(qualifiers[_END_X_Q]) if _END_X_Q in qualifiers else None,
                "end_y": float(qualifiers[_END_Y_Q]) if _END_Y_Q in qualifiers else None,
                "outcome": "successful" if e.get("outcome") == "1" else "unsuccessful",
                "shot_result": "Goal" if type_id == _GOAL_TYPE else "",
                "match_id": game.get("id", ""),
                "competition": game.get("competition_name", ""),
                "season": game.get("season_name", ""),
                "date": game.get("game_date", ""),
            })
        return RawDataset(frame=pd.DataFrame(rows), native_coord_system="opta")
