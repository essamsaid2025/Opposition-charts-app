"""Flattened-StatsBomb CSV adapter.

A StatsBomb *event export* flattened to CSV carries dotted columns (``type.name``,
``player.name``, ``team.name``) and stores coordinates as a stringified list in a single
``location`` column (and ``pass.end_location`` / ``carry.end_location`` / ``shot.end_location``
for the end point) — NOT the platform's canonical ``x`` / ``y`` / ``event_type`` columns. Such a
file was therefore classified as ``player_scouting`` (no x/y) and could not be used as event data
(maps, video click-to-seek, match evidence).

This adapter reshapes that specific shape into the canonical event columns BEFORE classification
and import, so it is recognized as an EVENT dataset and flows through the existing pipeline
unchanged. It is strictly GUARDED — it only fires on the flattened-StatsBomb shape (``type.name``
+ ``location`` and no ``x``/``y``), so every other provider/format is untouched. StatsBomb's pitch
is 120x80; coordinates are scaled to the platform's 0-100 plane. Pure/deterministic, no I/O.
"""
from __future__ import annotations

import ast
from typing import Any

import pandas as pd

_END_COLS = ("pass.end_location", "carry.end_location", "shot.end_location")


def looks_like_statsbomb_csv(df: pd.DataFrame) -> bool:
    """True only for a flattened-StatsBomb event CSV that still needs reshaping."""
    if df is None or not hasattr(df, "columns"):
        return False
    cols = set(df.columns)
    return {"type.name", "location"} <= cols and "x" not in cols and "y" not in cols


def _xy(val: Any) -> tuple[float | None, float | None]:
    """Parse a StatsBomb ``[x, y]`` (0-120 / 0-80) into the 0-100 plane. NaN-safe."""
    try:
        pair = val if isinstance(val, (list, tuple)) else ast.literal_eval(str(val).strip())
        return (float(pair[0]) * 100.0 / 120.0, float(pair[1]) * 100.0 / 80.0)
    except Exception:
        return (None, None)


def reshape(df: pd.DataFrame) -> pd.DataFrame:
    """Return a COPY reshaped to canonical event columns, or the frame unchanged when it is not a
    flattened-StatsBomb CSV. Original columns are preserved alongside the added canonical ones."""
    if not looks_like_statsbomb_csv(df):
        return df
    out = df.copy()
    xy = out["location"].map(_xy)
    out["x"] = [p[0] for p in xy]
    out["y"] = [p[1] for p in xy]
    # end point: whichever of pass/carry/shot end-location the row carries (coalesced)
    endx = pd.Series([None] * len(out), index=out.index, dtype=object)
    endy = pd.Series([None] * len(out), index=out.index, dtype=object)
    for c in _END_COLS:
        if c in out.columns:
            e = out[c].map(_xy)
            ex = pd.Series([p[0] for p in e], index=out.index)
            ey = pd.Series([p[1] for p in e], index=out.index)
            endx = endx.where(endx.notna(), ex)
            endy = endy.where(endy.notna(), ey)
    out["x2"] = pd.to_numeric(endx, errors="coerce")
    out["y2"] = pd.to_numeric(endy, errors="coerce")
    out["event_type"] = out["type.name"].astype(str)
    if "player.name" in out.columns and "player" not in out.columns:
        out["player"] = out["player.name"]
    if "team.name" in out.columns and "team" not in out.columns:
        out["team"] = out["team.name"]
    # Canonical outcome — ONLY for passes, where StatsBomb's convention is reliable (a completed
    # pass has a blank pass.outcome.name; a failed one names the failure). Other event types are
    # left as NA rather than fabricating a success/fail they do not cleanly encode.
    if "pass.outcome.name" in out.columns:
        is_pass = out["event_type"].astype(str).str.lower().eq("pass")
        po = out["pass.outcome.name"]
        outcome = pd.Series(pd.NA, index=out.index, dtype=object)
        outcome[is_pass & po.isna()] = "successful"
        outcome[is_pass & po.notna()] = "unsuccessful"
        out["outcome"] = outcome
    return out
