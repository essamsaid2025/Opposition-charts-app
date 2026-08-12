"""Shared analytical context for the Tactical Insight Engine.

Built ONCE from the (already-filtered) canonical frame; every rule consumes the
common aggregates instead of re-scanning the DataFrame. Football semantics are
reused, never re-implemented: derived flags come from
``fap.openplay.add_derived_columns`` (``is_progressive``, ``into_final_third``,
``into_box``, ``lane``, ``start_third``, ``time_min`` …) and the data-quality
score from ``fap.pipeline.quality`` — the same definitions the rest of the app
uses. Coordinates stay on the existing normalized 0-100 grid; no new coordinate
system is introduced.

The context holds DataFrame subsets only for the lifetime of ``analyze()``; the
serializable insights it feeds carry scalars and bounded id lists, never frames.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from fap.analytics.tactical.transitions import (
    RECOVERY_EVENTS, build_recovery_transitions, build_turnovers,
)
from fap.openplay.config import ARROW_EVENTS
from fap.openplay.transforms import add_derived_columns
from fap.pipeline.quality import score as quality_score
from fap.pipeline.schema import coerce_schema

# RECOVERY_EVENTS is defined once in transitions.py and re-exported here so existing
# imports (and the recovery rules) keep working unchanged.
__all__ = ["InsightContext", "RECOVERY_EVENTS", "channel_of", "counts_and_total",
           "event_ids", "CHANNEL_NAMES"]

# 5-channel vertical corridors on the 0-100 width grid (attacking left->right):
# left wing, left half-space, central, right half-space, right wing.
CHANNEL_BOUNDS = (20.0, 40.0, 60.0, 80.0)
CHANNEL_NAMES = ("Left Wing", "Left Half-space", "Central Channel",
                 "Right Half-space", "Right Wing")
_MAX_EVENT_IDS = 50


def channel_of(y: pd.Series) -> pd.Series:
    """Map a width coordinate (0-100) to one of the five vertical corridors."""
    return pd.cut(y, bins=[-0.1, *CHANNEL_BOUNDS, 100.1], labels=list(CHANNEL_NAMES))


def _has_derived(df: pd.DataFrame) -> bool:
    return {"is_progressive", "into_final_third", "into_box", "lane", "start_third"} \
        .issubset(df.columns)


def _frac_filled(df: pd.DataFrame, col: str) -> float:
    if col not in df.columns:
        return 0.0
    s = df[col]
    filled = s.notna() if s.dtype.kind in "fiu" else s.astype(str).str.strip().ne("")
    return float(filled.mean()) if len(s) else 0.0


def counts_and_total(series: pd.Series) -> tuple[dict[str, int], int]:
    """value_counts as an ordered dict plus the total (empty/NaN excluded)."""
    s = series.dropna().astype(str)
    s = s[s.str.strip().ne("")]
    vc = s.value_counts()
    return {str(k): int(v) for k, v in vc.items()}, int(vc.sum())


def event_ids(df: pd.DataFrame) -> tuple[str, ...]:
    """A bounded list of supporting event references (the ``id`` column if the
    feed has one, else the row index) — enough to trace evidence, never a frame."""
    if df.empty:
        return ()
    col = df["id"] if "id" in df.columns else df.index.to_series()
    return tuple(str(v) for v in col.head(_MAX_EVENT_IDS))


@dataclass
class InsightContext:
    """Precomputed aggregates shared by every rule. Construct via :meth:`build`."""
    df: pd.DataFrame
    n_events: int
    subject: str
    quality: float
    caps: dict[str, bool] = field(default_factory=dict)

    # cached event subsets (movement / progression / entries / recoveries)
    movement: pd.DataFrame = field(default_factory=lambda: pd.DataFrame())
    progressive: pd.DataFrame = field(default_factory=lambda: pd.DataFrame())
    final_third_entries: pd.DataFrame = field(default_factory=lambda: pd.DataFrame())
    box_entries: pd.DataFrame = field(default_factory=lambda: pd.DataFrame())
    recoveries: pd.DataFrame = field(default_factory=lambda: pd.DataFrame())
    turnovers: pd.DataFrame = field(default_factory=lambda: pd.DataFrame())
    rec_transitions: pd.DataFrame = field(default_factory=lambda: pd.DataFrame())
    speed_available: bool = False

    @classmethod
    def build(cls, frame: pd.DataFrame) -> "InsightContext":
        # Reuse the app's own normalization + derived-flag logic. A frame from the
        # Studio is already canonical+derived (skip). A raw/partial frame is run
        # through the canonical coerce_schema (guarantees every canonical column,
        # incl. x2/y2 and jersey_number, so quality scoring and add_derived_columns
        # are both safe) — no new normalization is introduced.
        df = frame if _has_derived(frame) else add_derived_columns(coerce_schema(frame))
        n = int(len(df))
        if n == 0:
            return cls(df=df, n_events=0, subject="the selected events", quality=0.0,
                       caps={k: False for k in _CAP_KEYS})

        subject = _subject(df)
        try:
            quality = float(quality_score(df).overall)
        except Exception:
            quality = 0.0

        etype = df["event_type"].astype(str).str.lower()
        movement = df[etype.isin(ARROW_EVENTS)]
        progressive = movement[movement["is_progressive"].fillna(False).astype(bool)]
        ft_entries = movement[movement["into_final_third"].fillna(False).astype(bool)]
        box_entries = movement[movement["into_box"].fillna(False).astype(bool)]
        recoveries = df[etype.isin(RECOVERY_EVENTS)]

        caps = {
            "coords": _frac_filled(df, "x") > 0.5 and _frac_filled(df, "y") > 0.5,
            "end_coords": _frac_filled(df, "x2") > 0.3 and _frac_filled(df, "y2") > 0.3,
            "players": _frac_filled(df, "player") > 0.3,
            "timestamps": _frac_filled(df, "minute") > 0.3,
            "sequence": _frac_filled(df, "sequence_id") > 0.3,
            "recovery_events": len(recoveries) > 0,
            "movement_events": len(movement) > 0,
        }
        turnovers = build_turnovers(df)
        # transitions need a way to order the follow-up (sequence OR timestamps) plus
        # recoveries and end coordinates; otherwise they stay unavailable (no fabrication)
        can_transition = (caps["recovery_events"] and caps["end_coords"]
                          and (caps["sequence"] or caps["timestamps"]))
        rec_trans = (build_recovery_transitions(df, use_sequence=caps["sequence"],
                                                use_time=caps["timestamps"])
                     if can_transition else pd.DataFrame())
        return cls(df=df, n_events=n, subject=subject, quality=quality, caps=caps,
                   movement=movement, progressive=progressive,
                   final_third_entries=ft_entries, box_entries=box_entries,
                   recoveries=recoveries, turnovers=turnovers, rec_transitions=rec_trans,
                   speed_available=caps["timestamps"])


_CAP_KEYS = ("coords", "end_coords", "players", "timestamps", "sequence",
             "recovery_events", "movement_events")


def _subject(df: pd.DataFrame) -> str:
    """Name the side the frame is about when one team clearly dominates it; else a
    neutral phrase. Never over-attributes a mixed frame to a single team."""
    if "team" not in df.columns:
        return "the selected events"
    teams = df["team"].astype(str).str.strip()
    teams = teams[teams.ne("")]
    if teams.empty:
        return "the selected events"
    vc = teams.value_counts(normalize=True)
    if len(vc) == 1 or vc.iloc[0] >= 0.8:
        return str(vc.index[0])
    return "the selected events"
