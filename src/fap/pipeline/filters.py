"""Reusable filter engine over the canonical event model.

FilterSet is declarative and JSON-serializable, so it round-trips into saved
projects for free. Every future chart consumes df AFTER FilterSet.apply and
therefore never implements its own filtering.

Custom filters: tuples of (column, op, value) with ops
eq, ne, in, not_in, gt, gte, lt, lte, between, contains.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

_SUCCESS = ("successful", "success", "complete", "won")
_TUPLE_FIELDS = ("event_types", "phases", "players", "minute_range", "competitions",
                 "seasons", "periods", "outcomes", "body_parts", "play_patterns",
                 "set_pieces", "positions", "score_states", "venues", "custom")


def _lower_in(series: pd.Series, values: tuple[str, ...]) -> pd.Series:
    return series.astype(str).str.lower().isin([str(v).lower() for v in values])


@dataclass(slots=True)
class FilterSet:
    # match context
    team: str = "All"
    opponent: str = "All"
    match_id: str = "All"
    competitions: tuple[str, ...] = ()
    seasons: tuple[str, ...] = ()
    # who / what
    event_types: tuple[str, ...] = ()
    phases: tuple[str, ...] = ()
    players: tuple[str, ...] = ()
    outcomes: tuple[str, ...] = ()
    body_parts: tuple[str, ...] = ()
    play_patterns: tuple[str, ...] = ()
    set_pieces: tuple[str, ...] = ()
    positions: tuple[str, ...] = ()
    score_states: tuple[str, ...] = ()        # winning | drawing | losing
    venues: tuple[str, ...] = ()              # home | away
    pressure_state: str = "any"               # any | under_pressure | no_pressure
    # when
    periods: tuple[int, ...] = ()
    minute_range: tuple[float, float] = (0.0, 120.0)
    only_successful: bool = False
    # escape hatch
    custom: tuple[tuple[str, str, Any], ...] = ()

    # ------------------------------------------------------------ apply
    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        mask = pd.Series(True, index=df.index)
        if self.team != "All":
            mask &= df["team"] == self.team
        if self.opponent != "All":
            mask &= df["opponent"] == self.opponent
        if self.match_id != "All":
            mask &= df["match_id"].astype(str) == self.match_id
        for values, col in ((self.competitions, "competition"), (self.seasons, "season"),
                            (self.event_types, "event_type"), (self.phases, "phase"),
                            (self.outcomes, "outcome"), (self.body_parts, "body_part"),
                            (self.play_patterns, "play_pattern"), (self.set_pieces, "set_piece"),
                            (self.positions, "position"), (self.score_states, "score_state"),
                            (self.venues, "venue")):
            if values:
                mask &= _lower_in(df[col], tuple(values))
        if self.players:
            mask &= df["player"].isin(self.players)
        if self.periods:
            mask &= df["period"].isin(list(self.periods))
        lo, hi = self.minute_range
        mask &= (df["time_min"] >= lo) & (df["time_min"] <= hi)
        if self.only_successful:
            mask &= df["outcome"].str.lower().isin(_SUCCESS)
        if self.pressure_state == "under_pressure":
            mask &= df["under_pressure"].astype(bool)
        elif self.pressure_state == "no_pressure":
            mask &= ~df["under_pressure"].astype(bool)
        for col, op, value in self.custom:
            mask &= _custom_mask(df, col, op, value)
        return df[mask]

    # ------------------------------------------------------------ persistence
    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in _TUPLE_FIELDS:
            data[key] = [list(v) if isinstance(v, tuple) else v for v in data[key]] \
                if key == "custom" else list(data[key])
        data["minute_range"] = list(data["minute_range"])
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FilterSet":
        data = dict(data)
        for key in _TUPLE_FIELDS:
            if key in data and isinstance(data[key], list):
                data[key] = tuple(tuple(v) if isinstance(v, list) else v for v in data[key]) \
                    if key == "custom" else tuple(data[key])
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


def _custom_mask(df: pd.DataFrame, col: str, op: str, value: Any) -> pd.Series:
    if col not in df.columns:
        return pd.Series(True, index=df.index)
    s = df[col]
    if op == "eq":
        return s == value
    if op == "ne":
        return s != value
    if op == "in":
        return s.isin(list(value))
    if op == "not_in":
        return ~s.isin(list(value))
    if op == "gt":
        return pd.to_numeric(s, errors="coerce") > value
    if op == "gte":
        return pd.to_numeric(s, errors="coerce") >= value
    if op == "lt":
        return pd.to_numeric(s, errors="coerce") < value
    if op == "lte":
        return pd.to_numeric(s, errors="coerce") <= value
    if op == "between":
        n = pd.to_numeric(s, errors="coerce")
        return (n >= value[0]) & (n <= value[1])
    if op == "contains":
        return s.astype(str).str.contains(str(value), case=False, na=False)
    raise ValueError(f"Unknown custom filter op: {op!r}")
