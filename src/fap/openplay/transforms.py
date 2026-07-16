"""Open Play data transforms - the derived-column and coordinate logic.

Pure functions (no Streamlit, no matplotlib). Migrated verbatim from app.py so
behaviour is byte-for-byte identical; the Open Play charts depend on these exact
columns and thresholds, so nothing here is reconciled with fap.pipeline.transforms
(that would change behaviour, which this phase forbids).
"""
from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd

from fap.openplay.config import REQUIRED_MINIMUM, SUCCESS_WORDS


def clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    return df


def ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = clean_columns(df)
    for col in ["x", "y", "x2", "y2", "minute", "second", "shirt_number", "period"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ["event_type", "phase", "team", "opponent", "player", "receiver", "outcome",
                "shot_result", "body_part", "direction", "competition", "date", "match_id",
                "zone", "sequence_id", "notes"]:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str).str.strip()
    if "period" not in df.columns:
        df["period"] = 1
    df["period"] = pd.to_numeric(df["period"], errors="coerce").fillna(1)
    for col in ["x2", "y2", "minute", "second"]:
        if col not in df.columns:
            df[col] = np.nan
    return df


def validate_data(df: pd.DataFrame) -> List[str]:
    missing = [c for c in REQUIRED_MINIMUM if c not in df.columns]
    return [f"Missing required columns: {', '.join(missing)}"] if missing else []


def normalize_coordinates(df: pd.DataFrame, mode: str) -> pd.DataFrame:
    df = df.copy()
    if mode == "120 x 80":
        for a in ["x", "x2"]:
            df[a] = df[a] / 120 * 100
        for a in ["y", "y2"]:
            df[a] = df[a] / 80 * 100
    for col in ["x", "y", "x2", "y2"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").clip(0, 100)
    return df


def flip_attacking_direction(df: pd.DataFrame, attack_direction: str) -> pd.DataFrame:
    df = df.copy()
    if attack_direction.startswith("Team attacks right-to-left"):
        for col in ["x", "x2"]:
            df[col] = 100 - df[col]
    return df


def add_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    dx = df["x2"] - df["x"]
    dy = df["y2"] - df["y"]
    df["distance"] = np.sqrt(dx**2 + dy**2)
    df["is_forward"] = dx > 8
    df["is_backward"] = dx < -8
    df["is_lateral"] = (~df["is_forward"]) & (~df["is_backward"])
    df["is_progressive"] = (dx >= 10) & ((100 - df["x2"]) <= 0.75 * (100 - df["x"]))
    df["into_final_third"] = (df["x"] < 66.67) & (df["x2"] >= 66.67)
    df["into_box"] = (df["x2"] >= 83) & (df["y2"].between(21, 79))
    df["in_box"] = (df["x"] >= 83) & (df["y"].between(21, 79))
    df["start_third"] = pd.cut(df["x"], bins=[-0.1, 33.33, 66.67, 100.1],
                               labels=["Defensive Third", "Middle Third", "Final Third"])
    df["lane"] = pd.cut(df["y"], bins=[-0.1, 33.33, 66.67, 100.1],
                        labels=["Left Lane", "Central Lane", "Right Lane"])
    df["time_min"] = pd.to_numeric(df["minute"], errors="coerce").fillna(0) + \
        pd.to_numeric(df["second"], errors="coerce").fillna(0) / 60
    df["shot_distance"] = np.sqrt((100 - df["x"]) ** 2 + (50 - df["y"]) ** 2)
    return df


def pct(n: float, d: float) -> str:
    return "0%" if d == 0 else f"{(n / d * 100):.0f}%"


def safe_count(df: pd.DataFrame, col: str, value: str) -> int:
    if col not in df.columns:
        return 0
    return int(df[col].astype(str).str.lower().eq(value.lower()).sum())


def is_success(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().isin(SUCCESS_WORDS)
