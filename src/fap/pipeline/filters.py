"""Declarative, serializable filters. Because FilterSet is a plain dataclass,
it round-trips into project documents (save/load) for free."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

_SUCCESS = ("successful", "success", "complete", "won")


@dataclass(slots=True)
class FilterSet:
    team: str = "All"
    opponent: str = "All"
    match_id: str = "All"
    event_types: tuple[str, ...] = ()
    phases: tuple[str, ...] = ()
    players: tuple[str, ...] = ()
    minute_range: tuple[float, float] = (0.0, 120.0)
    only_successful: bool = False

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df
        if self.team != "All":
            out = out[out["team"] == self.team]
        if self.opponent != "All":
            out = out[out["opponent"] == self.opponent]
        if self.match_id != "All":
            out = out[out["match_id"].astype(str) == self.match_id]
        if self.event_types:
            out = out[out["event_type"].str.lower().isin([e.lower() for e in self.event_types])]
        if self.phases:
            out = out[out["phase"].str.lower().isin([p.lower() for p in self.phases])]
        if self.players:
            out = out[out["player"].isin(self.players)]
        lo, hi = self.minute_range
        out = out[(out["time_min"] >= lo) & (out["time_min"] <= hi)]
        if self.only_successful:
            out = out[out["outcome"].str.lower().isin(_SUCCESS)]
        return out

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FilterSet":
        data = dict(data)
        for key in ("event_types", "phases", "players", "minute_range"):
            if key in data and isinstance(data[key], list):
                data[key] = tuple(data[key])
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
