"""Automatic data cleaning. Operates on the pipeline-owned frame (no extra
copies) and returns a log of the actions applied for the import summary."""
from __future__ import annotations

import numpy as np
import pandas as pd

from fap.pipeline import schema

EVENT_SYNONYMS: dict[str, str] = {
    "passes": "pass", "pass_completed": "pass", "completed_pass": "pass", "passing": "pass",
    "shots": "shot", "shot_on_target": "shot", "shot_off_target": "shot", "attempt": "shot",
    "goal_attempt": "shot", "miss": "shot", "attempt_saved": "shot", "post": "shot",
    "take_on": "dribble", "take-on": "dribble", "takeon": "dribble", "dribbles": "dribble",
    "carries": "carry", "ball_carry": "carry",
    "crosses": "cross", "crossing": "cross",
    "ball_recovery": "recovery", "recoveries": "recovery",
    "interceptions": "interception",
    "tackles": "tackle", "challenge": "tackle",
    "clearances": "clearance",
    "blocks": "block", "blocked": "block",
    "duels": "duel", "aerial": "duel", "aerial_duel": "duel", "ground_duel": "duel",
    "goalkeeper_save": "save", "keeper_save": "save",
    "fouls": "foul", "foul_committed": "foul",
    "throw_in": "throw-in", "throwin": "throw-in",
}

OUTCOME_MAP: dict[str, str] = {
    "successful": "successful", "success": "successful", "complete": "successful",
    "completed": "successful", "won": "successful", "accurate": "successful",
    "1": "successful", "true": "successful", "yes": "successful",
    "unsuccessful": "unsuccessful", "fail": "unsuccessful", "failed": "unsuccessful",
    "incomplete": "unsuccessful", "lost": "unsuccessful", "inaccurate": "unsuccessful",
    "0": "unsuccessful", "false": "unsuccessful", "no": "unsuccessful",
}

_TRUE = {"1", "1.0", "true", "t", "yes", "y"}


def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    log: list[str] = []

    # trim/collapse whitespace + normalize text case for categorical fields
    for col in schema.TEXT:
        df[col] = df[col].astype(str).str.strip().str.replace(r"\s+", " ", regex=True)
    for col in ("event_type", "sub_event", "outcome", "body_part", "play_pattern"):
        df[col] = df[col].str.lower()
    log.append("Trimmed whitespace and normalized text casing")

    # canonical event names
    key = df["event_type"].str.replace(" ", "_", regex=False)
    fixed = key.map(EVENT_SYNONYMS)
    n = int(fixed.notna().sum())
    df["event_type"] = fixed.fillna(df["event_type"])
    if n:
        log.append(f"Normalized {n} event names via synonym map")

    # outcomes
    mapped = df["outcome"].map(OUTCOME_MAP)
    n = int((mapped.notna() & (mapped != df["outcome"])).sum())
    df["outcome"] = mapped.fillna(df["outcome"])
    if n:
        log.append(f"Normalized {n} outcome values")

    # booleans
    for col in schema.BOOLEAN:
        if df[col].dtype != bool:
            df[col] = df[col].astype(str).str.strip().str.lower().isin(_TRUE)
    log.append("Normalized boolean flags")

    # duplicates
    before = len(df)
    df.drop_duplicates(inplace=True)
    df.reset_index(drop=True, inplace=True)
    if before - len(df):
        log.append(f"Removed {before - len(df)} duplicated rows")

    # missing numeric values stay NaN (explicit), missing text already ""
    df.replace({np.inf: np.nan, -np.inf: np.nan}, inplace=True)
    log.append("Coerced infinities to missing; types enforced by schema")
    return df, log
