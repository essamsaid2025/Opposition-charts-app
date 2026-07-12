"""Composable transform steps. PERFORMANCE CONTRACT: the pipeline owns the
frame and makes exactly one copy at ingestion; every step mutates that frame
in place and returns it. Steps stay individually unit-testable."""
from __future__ import annotations

import numpy as np
import pandas as pd

from fap.core.types import PitchDims

_PITCH = PitchDims()


def clip_canonical(df: pd.DataFrame) -> pd.DataFrame:
    for col in ("x", "y", "end_x", "end_y", "x2", "y2"):
        df[col] = pd.to_numeric(df[col], errors="coerce").clip(0, 100)
    return df


def flip_left_to_right(df: pd.DataFrame) -> pd.DataFrame:
    for col in ("x", "end_x", "x2"):
        df[col] = 100 - df[col]
    return df


def derive_movement(df: pd.DataFrame) -> pd.DataFrame:
    dx, dy = df["end_x"] - df["x"], df["end_y"] - df["y"]
    df["distance"] = np.sqrt(dx ** 2 + dy ** 2)
    df["is_forward"] = dx > 8
    df["is_backward"] = dx < -8
    df["is_lateral"] = (~df["is_forward"]) & (~df["is_backward"])
    # fill vendor metrics when absent (meters on a 105x68 pitch)
    length_m = np.sqrt((dx * 1.05) ** 2 + (dy * 0.68) ** 2)
    df["pass_length"] = df["pass_length"].fillna(length_m.where(df["event_type"].eq("pass")))
    df["carry_distance"] = df["carry_distance"].fillna(length_m.where(df["event_type"].eq("carry")))
    df["pass_angle"] = df["pass_angle"].fillna(np.arctan2(dy * 0.68, dx * 1.05))
    return df


def derive_zones(df: pd.DataFrame) -> pd.DataFrame:
    df["into_final_third"] = (df["x"] < _PITCH.final_third_x) & (df["end_x"] >= _PITCH.final_third_x)
    df["into_box"] = (df["end_x"] >= _PITCH.box_x) & (df["end_y"].between(_PITCH.box_y_min, _PITCH.box_y_max))
    df["start_third"] = pd.cut(df["x"], bins=[-0.1, 33.33, 66.67, 100.1],
                               labels=["Defensive Third", "Middle Third", "Final Third"])
    df["lane"] = pd.cut(df["y"], bins=[-0.1, 33.33, 66.67, 100.1],
                        labels=["Left Lane", "Central Lane", "Right Lane"])
    return df


def derive_time(df: pd.DataFrame) -> pd.DataFrame:
    minute = pd.to_numeric(df["minute"], errors="coerce")
    ts = pd.to_numeric(df["timestamp"], errors="coerce")
    minute = minute.fillna(ts / 60)     # fall back to timestamp seconds
    df["minute"] = minute
    df["time_min"] = minute.fillna(0) + pd.to_numeric(df["second"], errors="coerce").fillna(0) / 60
    return df


def derive_plot_coords(df: pd.DataFrame) -> pd.DataFrame:
    """Project canonical 0-100 space onto the metric pitch used for plotting."""
    df["x_plot"], df["x2_plot"] = df["x"], df["end_x"]
    df["y_plot"] = df["y"] * _PITCH.width / 100
    df["y2_plot"] = df["end_y"] * _PITCH.width / 100
    df["shot_distance"] = np.sqrt((100 - df["x"]) ** 2 + (50 - df["y"]) ** 2)
    df["x2"], df["y2"] = df["end_x"], df["end_y"]     # keep legacy aliases in sync
    return df


def derive_score_state(df: pd.DataFrame) -> pd.DataFrame:
    """Running score state from the row team's perspective, per match.
    Rows before any goal are 'drawing'; matches without goal info stay 'drawing'."""
    df["score_state"] = "drawing"
    goals = df[(df["event_type"].str.lower().eq("shot"))
               & (df["shot_result"].str.lower().eq("goal"))]
    if goals.empty or df["team"].str.strip().eq("").all():
        return df
    order = df["time_min"].fillna(0) + df["period"].fillna(1) * 1000
    for match_id, idx in df.groupby(df["match_id"].astype(str)).groups.items():
        sub = df.loc[idx]
        sub_order = order.loc[idx]
        g = goals[goals["match_id"].astype(str) == match_id]
        if g.empty:
            continue
        g_order = order.loc[g.index]
        for row_i in idx:
            scored = g[(g_order < sub_order.loc[row_i])]
            if scored.empty:
                continue
            own = int((scored["team"] == sub.loc[row_i, "team"]).sum())
            other = len(scored) - own
            df.loc[row_i, "score_state"] = ("winning" if own > other
                                            else "losing" if own < other else "drawing")
    return df
