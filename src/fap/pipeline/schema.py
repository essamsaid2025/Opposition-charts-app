"""Canonical event schema - the ONE contract every future visualization and
metric consumes, regardless of the original provider.

Legacy aliases x2/y2 are kept in sync with end_x/end_y so existing code
(PitchFactory, transforms) keeps working unchanged.
"""
from __future__ import annotations

import pandas as pd

from fap.core.exceptions import DataValidationError

REQUIRED: tuple[str, ...] = ("event_type", "x", "y")

NUMERIC: tuple[str, ...] = (
    "x", "y", "end_x", "end_y", "x2", "y2",
    "minute", "second", "period", "timestamp",
    "jersey_number", "shirt_number",
    "shot_xg", "pass_length", "pass_angle", "carry_distance",
)

TEXT: tuple[str, ...] = (
    "match_id", "competition", "season", "date",
    "team", "opponent", "player", "receiver", "position",
    "event_type", "sub_event", "outcome", "shot_result",
    "body_part", "play_pattern", "set_piece", "pass_height",
    "phase", "direction", "zone", "sequence_id", "notes",
)

BOOLEAN: tuple[str, ...] = ("under_pressure", "pressure", "assist", "key_pass")

CANONICAL: tuple[str, ...] = tuple(dict.fromkeys(NUMERIC + TEXT + BOOLEAN))


def clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    return df


def coerce_schema(df: pd.DataFrame) -> pd.DataFrame:
    """One controlled copy; every column of the canonical contract exists and
    has the right dtype afterwards."""
    df = clean_columns(df)
    for col in NUMERIC:
        df[col] = pd.to_numeric(df[col], errors="coerce") if col in df.columns else float("nan")
    for col in TEXT:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str).str.strip()
    for col in BOOLEAN:
        if col not in df.columns:
            df[col] = False
    df["period"] = pd.to_numeric(df["period"], errors="coerce").fillna(1)

    # legacy alias sync: end_x/end_y are canonical, x2/y2 kept identical
    if df["end_x"].isna().all() and df["x2"].notna().any():
        df["end_x"], df["end_y"] = df["x2"], df["y2"]
    df["x2"], df["y2"] = df["end_x"], df["end_y"]
    if df["jersey_number"].isna().all() and df["shirt_number"].notna().any():
        df["jersey_number"] = df["shirt_number"]
    df["shirt_number"] = df["jersey_number"]
    return df


def validate(df: pd.DataFrame) -> None:
    problems = [f"Missing required column: {c}" for c in REQUIRED if c not in df.columns]
    if problems:
        raise DataValidationError(problems)
