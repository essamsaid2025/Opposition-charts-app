"""Scouting Player-Map semantic filters (Phase C4) — PURE, reuse-only.

The semantic controls a scouting Map Studio needs (progressive / final-third / penalty-area /
direction / lane / outcome) are NOT reinvented here: they map 1:1 onto the platform's CANONICAL
derived columns from ``fap.openplay.add_derived_columns`` (``is_progressive``, ``into_final_third``,
``into_box``, ``is_forward``/``is_backward``/``is_lateral``, ``lane``, ``start_third``) and the
canonical normalized ``outcome`` column. This module only:

  * derives those columns on a COPY of the player's event frame (never mutates the source),
  * reports which semantic filters are AVAILABLE for a given map + dataset (data-driven), and
  * composes the selected filters into one boolean mask (filters compose; count == filtered rows).

No second event taxonomy, no second zone system, no second progressive formula, no rendering, no
Streamlit. The event frame is already player-scoped upstream (``player_event_frame``).
"""
from __future__ import annotations

from typing import Any

import pandas as pd

# which semantic filters make sense for each map FAMILY (section 18 — controls are semantic:
# a shot map never shows a pass-direction control; a defensive map never shows "progressive").
_PASS = ("outcome", "progressive", "zone", "direction", "lane")
_CARRY = ("outcome", "progressive", "zone", "direction")
_SHOT = ("outcome", "zone")
_DEFEND = ("outcome", "zone", "lane")

_MAP_FAMILY: dict[str, tuple[str, ...]] = {}
for _i in ("pass_map", "pass_direction_map", "final_third_map", "penalty_area_map",
           "progressive_pass_lanes", "passing_options", "key_pass", "chance_creation"):
    _MAP_FAMILY[_i] = _PASS
for _i in ("carry_map", "carry_network", "progressive_carries", "half_space_entries"):
    _MAP_FAMILY[_i] = _CARRY
for _i in ("shot", "shot_map", "shot_heatmap", "hexbin", "goal_probability", "chance_creating_zones"):
    _MAP_FAMILY[_i] = _SHOT
for _i in ("tackle", "interception", "recovery", "pressure", "block", "clearance"):
    _MAP_FAMILY[_i] = _DEFEND

# derived columns each semantic filter needs present to be offered
_NEEDS = {"progressive": ("is_progressive",), "direction": ("is_forward",),
          "lane": ("lane",), "zone": ("start_third",), "outcome": ("outcome",)}

_DERIVE_INPUTS = ("x", "y", "x2", "y2", "minute", "second")


def derive(df: pd.DataFrame) -> pd.DataFrame:
    """A COPY of ``df`` with the canonical derived columns added when the inputs exist. If the
    frame lacks the movement/coordinate inputs, it is returned unchanged (those filters then
    read as unavailable). Never mutates the caller's frame."""
    if df is None or getattr(df, "empty", True):
        return df
    if not all(c in df.columns for c in _DERIVE_INPUTS):
        return df.copy()
    from fap.openplay.transforms import add_derived_columns   # canonical — single source of truth
    try:
        return add_derived_columns(df.copy())
    except Exception:
        return df.copy()


def applicable_filters(map_id: str) -> tuple[str, ...]:
    """The semantic filters that are meaningful for this map family (before data checks)."""
    return _MAP_FAMILY.get(str(map_id or "").lower(), ("outcome", "zone"))


def available_filters(df: pd.DataFrame, map_id: str) -> dict[str, dict[str, Any]]:
    """For each filter meaningful to ``map_id``: whether it is available on THIS derived frame,
    plus its option list — honest reasons when a required field is absent (section 17)."""
    d = derive(df)
    cols = set(getattr(d, "columns", []))
    out: dict[str, dict[str, Any]] = {}
    for f in applicable_filters(map_id):
        needs = _NEEDS.get(f, ())
        ok = bool(needs) and all(c in cols for c in needs)
        opts = {
            "outcome": ["All", "Successful", "Unsuccessful"],
            "progressive": ["All", "Progressive only"],
            "direction": ["All", "Forward", "Backward", "Lateral"],
            "lane": ["All", "Left", "Central", "Right"],
            "zone": ["All", "Defensive third", "Middle third", "Final third", "Penalty area"],
        }.get(f, ["All"])
        out[f] = {"available": ok, "options": opts,
                  "reason": "" if ok else "required event field not present in this dataset"}
    return out


def apply(df: pd.DataFrame, selections: dict[str, str]) -> pd.DataFrame:
    """Return the rows matching ALL selected semantic filters (filters compose). Selections are
    ``{filter_id: option}``; "All"/missing/unavailable are no-ops. Reuses only canonical columns;
    returns a filtered COPY — never mutates the source, never fabricates rows (section 12)."""
    d = derive(df)
    if d is None or getattr(d, "empty", True):
        return d
    mask = pd.Series(True, index=d.index)
    sel = {k: v for k, v in (selections or {}).items() if v and v != "All"}

    if "outcome" in sel and "outcome" in d.columns:
        oc = d["outcome"].astype(str).str.lower()
        mask &= (oc == "successful") if sel["outcome"] == "Successful" else (oc == "unsuccessful")
    if sel.get("progressive") == "Progressive only" and "is_progressive" in d.columns:
        mask &= d["is_progressive"].fillna(False).astype(bool)
    if "direction" in sel:
        col = {"Forward": "is_forward", "Backward": "is_backward", "Lateral": "is_lateral"}.get(sel["direction"])
        if col and col in d.columns:
            mask &= d[col].fillna(False).astype(bool)
    if "lane" in sel and "lane" in d.columns:
        want = {"Left": "Left Lane", "Central": "Central Lane", "Right": "Right Lane"}.get(sel["lane"])
        if want:
            mask &= d["lane"].astype(str) == want
    if "zone" in sel:
        z = sel["zone"]
        # Final third / Penalty area use ENTRY semantics (canonical into_final_third / into_box),
        # matching "which events entered that area"; the thirds use start location (start_third).
        if z == "Penalty area":
            col = "into_box" if "into_box" in d.columns else ("in_box" if "in_box" in d.columns else None)
            if col:
                mask &= d[col].fillna(False).astype(bool)
        elif z == "Final third":
            if "into_final_third" in d.columns:
                mask &= d["into_final_third"].fillna(False).astype(bool)
            elif "start_third" in d.columns:
                mask &= d["start_third"].astype(str) == "Attacking"
        elif "start_third" in d.columns:
            third = {"Defensive third": "Defensive", "Middle third": "Middle"}.get(z)
            if third:
                mask &= d["start_third"].astype(str) == third
    return d[mask]


def summarize(df: pd.DataFrame, selections: dict[str, str]) -> dict[str, Any]:
    """Honest scope line for a filtered map (section 14/15): filtered event count + the active
    filters. Count comes from the FILTERED rows, never the unfiltered dataset."""
    filtered = apply(df, selections)
    active = [f"{k}: {v}" for k, v in (selections or {}).items() if v and v != "All"]
    n = 0 if filtered is None else int(len(filtered))
    return {"events": n, "filters": active or ["All events"],
            "empty": n == 0}
