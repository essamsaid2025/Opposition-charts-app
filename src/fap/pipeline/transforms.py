"""Composable transform steps (Chain of Responsibility). Each step is a pure
function DataFrame -> DataFrame, unit-testable in isolation."""
from __future__ import annotations

import numpy as np
import pandas as pd

from fap.core.types import PitchDims

_PITCH = PitchDims()


def clip_canonical(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in ("x", "y", "x2", "y2"):
        df[col] = pd.to_numeric(df[col], errors="coerce").clip(0, 100)
    return df


def flip_left_to_right(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in ("x", "x2"):
        df[col] = 100 - df[col]
    return df


def derive_movement(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    dx, dy = df["x2"] - df["x"], df["y2"] - df["y"]
    df["distance"] = np.sqrt(dx ** 2 + dy ** 2)
    df["is_forward"] = dx > 8
    df["is_backward"] = dx < -8
    df["is_lateral"] = (~df["is_forward"]) & (~df["is_backward"])
    return df


def derive_zones(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["into_final_third"] = (df["x"] < _PITCH.final_third_x) & (df["x2"] >= _PITCH.final_third_x)
    df["into_box"] = (df["x2"] >= _PITCH.box_x) & (df["y2"].between(_PITCH.box_y_min, _PITCH.box_y_max))
    df["start_third"] = pd.cut(df["x"], bins=[-0.1, 33.33, 66.67, 100.1],
                               labels=["Defensive Third", "Middle Third", "Final Third"])
    df["lane"] = pd.cut(df["y"], bins=[-0.1, 33.33, 66.67, 100.1],
                        labels=["Left Lane", "Central Lane", "Right Lane"])
    return df


def derive_time(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["time_min"] = (
        pd.to_numeric(df["minute"], errors="coerce").fillna(0)
        + pd.to_numeric(df["second"], errors="coerce").fillna(0) / 60
    )
    return df


def derive_plot_coords(df: pd.DataFrame) -> pd.DataFrame:
    """Project canonical 0-100 space onto the metric pitch used for plotting."""
    df = df.copy()
    df["x_plot"], df["x2_plot"] = df["x"], df["x2"]
    df["y_plot"] = df["y"] * _PITCH.width / 100
    df["y2_plot"] = df["y2"] * _PITCH.width / 100
    df["shot_distance"] = np.sqrt((100 - df["x"]) ** 2 + (50 - df["y"]) ** 2)
    return df
