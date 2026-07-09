"""Canonical event schema. Every provider's output is normalized into this
one contract; every metric and visualization consumes ONLY this contract."""
from __future__ import annotations

import pandas as pd

from fap.core.exceptions import DataValidationError

REQUIRED: tuple[str, ...] = ("event_type", "x", "y")

NUMERIC: tuple[str, ...] = ("x", "y", "x2", "y2", "minute", "second", "shirt_number", "period")

TEXT: tuple[str, ...] = (
    "event_type", "phase", "team", "opponent", "player", "receiver", "outcome",
    "shot_result", "body_part", "direction", "competition", "date", "match_id",
    "zone", "sequence_id", "notes",
)


def clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    return df


def coerce_schema(df: pd.DataFrame) -> pd.DataFrame:
    df = clean_columns(df)
    for col in NUMERIC:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        elif col in ("x2", "y2", "minute", "second"):
            df[col] = float("nan")
    for col in TEXT:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str).str.strip()
    if "period" not in df.columns:
        df["period"] = 1
    df["period"] = pd.to_numeric(df["period"], errors="coerce").fillna(1)
    return df


def validate(df: pd.DataFrame) -> None:
    problems = [f"Missing required column: {c}" for c in REQUIRED if c not in df.columns]
    if problems:
        raise DataValidationError(problems)
