"""Transition & turnover semantics for the Tactical Insight Engine (P2).

Pure functions over the canonical + derived event frame. Football semantics are
REUSED, never re-implemented: turnovers come from
``fap.visuals.analysis.turnovers`` (unsuccessful movement + dispossessions), and
the transition follow-up is built from possession runs over the existing
``sequence_id`` / ``time_min`` fields and the existing derived flags
(``is_progressive`` / ``into_final_third`` / ``lane`` / ``start_third``). No new
coordinate system, no new event model.

A *transition* here = a ball recovery followed, within the same possession, by the
team's next actions (progression / final-third entry / shot). Possession is the
existing ``sequence_id`` when the feed carries it, otherwise a team-possession run
in time order. "Rapid" is only computed when timestamps are available.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from fap.openplay.config import ARROW_EVENTS
from fap.visuals import analysis as A

# Ball-recovery family — a defensive regain of possession (kept here so context and
# rules share ONE definition; re-exported by context for backwards compatibility).
RECOVERY_EVENTS = ("recovery", "ball recovery", "ball_recovery", "interception", "tackle")

_FINAL_THIRD_X = 66.67


def build_turnovers(df: pd.DataFrame) -> pd.DataFrame:
    """Normalised turnovers = the app's own turnover definition (unsuccessful
    passes/carries + dispossessions/errors/miscontrols), de-duplicated. Carries the
    derived ``lane`` / ``start_third`` columns for zone analysis."""
    if df.empty:
        return df.iloc[0:0]
    to = A.turnovers(df)
    return to[~to.index.duplicated(keep="first")]     # never double-count one event


def build_recovery_transitions(df: pd.DataFrame, *, use_sequence: bool, use_time: bool) -> pd.DataFrame:
    """One row per ball recovery describing what the SAME possession did next:
    ``led_prog`` (a progressive action followed), ``led_ft`` (reached the final third
    from outside it), ``led_shot`` (a shot followed), ``prog_lane`` (direction of the
    first progressive action), ``delay_s`` (seconds to the first attacking action, or
    NaN when timestamps are unavailable)."""
    n = len(df)
    if n == 0:
        return pd.DataFrame(columns=["rec_lane", "rec_third", "led_prog", "led_ft",
                                     "led_shot", "prog_lane", "delay_s"])
    d = df.copy()
    et = d["event_type"].astype(str).str.lower()
    d["_is_rec"] = et.isin(RECOVERY_EVENTS)
    d["_is_move"] = et.isin(ARROW_EVENTS)
    d["_is_shot"] = et.eq("shot")
    d["_prog"] = d["_is_move"] & d["is_progressive"].fillna(False).astype(bool)
    d["_ord"] = pd.to_numeric(d["time_min"], errors="coerce").fillna(0.0) if use_time \
        else np.arange(n, dtype=float)
    d["_row"] = np.arange(n)
    d = d.sort_values(["match_id", "_ord", "_row"], kind="stable")
    if use_sequence:
        d["_poss"] = d["match_id"].astype(str) + "|" + d["sequence_id"].astype(str)
    else:
        boundary = d["team"].ne(d["team"].shift()) | d["match_id"].ne(d["match_id"].shift())
        d["_poss"] = boundary.cumsum()

    rows: list[dict] = []
    for _, g in d.groupby("_poss", sort=False):
        recs = g[g["_is_rec"]]
        if recs.empty:
            continue
        for _, r in recs.iterrows():
            after = g[(g["_ord"] > r["_ord"]) & (g["team"] == r["team"])]
            rec_x = float(r["x"]) if pd.notna(r["x"]) else 0.0
            if after.empty:
                reached_ft = False
                prog_after = after
            else:
                reached_ft = bool((after[["x", "end_x"]].max(axis=1) >= _FINAL_THIRD_X).any())
                prog_after = after[after["_prog"]]
            led_prog = not prog_after.empty
            led_shot = bool(after["_is_shot"].any()) if not after.empty else False
            prog_lane = str(prog_after.iloc[0]["lane"]) if led_prog else str(r["lane"])
            delay_s = np.nan
            if use_time and not after.empty:
                meaningful = after[after["_prog"] | after["_is_shot"]]
                if not meaningful.empty:
                    delay_s = float((meaningful.iloc[0]["_ord"] - r["_ord"]) * 60.0)
            rows.append({"rec_lane": str(r["lane"]), "rec_third": str(r["start_third"]),
                         "led_prog": led_prog, "led_ft": bool(rec_x < _FINAL_THIRD_X and reached_ft),
                         "led_shot": led_shot, "prog_lane": prog_lane, "delay_s": delay_s})
    return pd.DataFrame(rows)
