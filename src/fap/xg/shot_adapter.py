"""Shot adapter: FAP canonical shot rows -> Internal xG API input schema.

This is the ONLY place the application's column names and value vocabulary are
mapped to the frozen model's input fields. It prepares raw *semantic* inputs
only — it NEVER computes distance / angle / distance_x / abs_y_offset / model
encodings / probabilities (the frozen ``xg`` package owns all of that).

Coordinate conversion is delegated to the already-tested
:mod:`fap.xg.coord_adapter`; no coordinate math is duplicated here.

Confirmed rules (Phase-2 Checkpoint 1 review):
  * penalty  ⇔  ``set_piece == "penalty"`` only (never inferred from location /
    outcome / distance / scoreline). Unknown ⇒ non-penalty.
  * assist   ⇔  assisted & unknown type → ``"pass"``; not assisted & unknown →
    ``"none"``; an explicitly-known assist_type is preserved. Specific types
    (cross / through_ball / cutback) are NEVER inferred.

Output is a NEW dataframe of xG-API input columns (source frame never mutated).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import coord_adapter

# --------------------------------------------------------------------------- #
# Value vocabularies (app value -> model category). All documented.
# --------------------------------------------------------------------------- #
# body_part: the app is coarse (foot / head / weak_foot). The model has
# Right Foot / Left Foot / Head / Other and treats the two feet near-identically,
# so a generic foot maps to "Right Foot" (the model's reference foot).
BODY_PART_MAP: dict[str, str] = {
    "head": "Head", "header": "Head",
    "foot": "Right Foot", "weak_foot": "Right Foot", "weak foot": "Right Foot",
    "strong_foot": "Right Foot", "strong foot": "Right Foot",
    "right foot": "Right Foot", "right_foot": "Right Foot", "right": "Right Foot",
    "left foot": "Left Foot", "left_foot": "Left Foot", "left": "Left Foot",
}
# body_part handling: known -> mapped; ""/missing -> NaN (frozen pipeline imputes);
# any other non-empty token -> "Other" (the model's genuine catch-all, not random).

ASSIST_TYPE_MAP: dict[str, str] = {
    "none": "none", "pass": "pass", "cross": "cross",
    "through_ball": "through_ball", "through ball": "through_ball", "throughball": "through_ball",
    "cutback": "cutback", "cut back": "cutback", "cut_back": "cutback",
}

# set_piece text -> dead-ball classification
_FREE_KICK = {"free kick", "free_kick", "freekick", "direct free kick", "indirect free kick"}
_CORNER = {"corner", "corner kick", "corner_kick"}
_PENALTY = {"penalty"}

_TRUTHY = frozenset({"1", "1.0", "true", "yes", "y", "t"})

REQUIRED_COLUMNS = ("x", "y")
# Feature columns the frozen API consumes (produced here); context columns are
# carried through for grouping/eval but are not model features.
XG_INPUT_FEATURES = ("shot_x", "shot_y", "body_part", "shot_type", "assist_type",
                     "assisted", "set_piece", "free_kick", "penalty")
_CONTEXT_CARRY = ("team", "opponent", "match_id", "player", "minute", "second", "period")


# --------------------------------------------------------------------------- #
# Column helpers
# --------------------------------------------------------------------------- #
def _text(df: pd.DataFrame, col: str) -> pd.Series:
    if col in df.columns:
        return df[col].fillna("").astype(str).str.strip().str.lower()
    return pd.Series([""] * len(df), index=df.index, dtype=object)


def _bool(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series([False] * len(df), index=df.index, dtype=bool)
    s = df[col]
    if s.dtype == bool:
        return s.fillna(False)
    return s.astype(str).str.strip().str.lower().isin(_TRUTHY)


# --------------------------------------------------------------------------- #
# Field derivations (each documented, each pure)
# --------------------------------------------------------------------------- #
def map_body_part(df: pd.DataFrame) -> pd.Series:
    """known -> model category; "" -> NaN (imputed by frozen pipeline);
    other non-empty -> "Other" (model catch-all)."""
    raw = _text(df, "body_part")

    def one(v: str):
        if v in BODY_PART_MAP:
            return BODY_PART_MAP[v]
        if v == "":
            return np.nan
        return "Other"

    return raw.map(one)


def derive_shot_context(df: pd.DataFrame) -> pd.DataFrame:
    """Return penalty / free_kick / set_piece(bool) / shot_type from ``set_piece``."""
    sp = _text(df, "set_piece")
    penalty = sp.isin(_PENALTY)
    free_kick = sp.isin(_FREE_KICK)
    corner = sp.isin(_CORNER)
    set_piece_bool = penalty | free_kick | corner  # corner shots: Open Play + set_piece
    shot_type = np.where(penalty, "Penalty", np.where(free_kick, "Free Kick", "Open Play"))
    return pd.DataFrame(
        {"penalty": penalty.to_numpy(bool), "free_kick": free_kick.to_numpy(bool),
         "set_piece": set_piece_bool.to_numpy(bool), "shot_type": shot_type},
        index=df.index,
    )


def derive_assist(df: pd.DataFrame) -> pd.DataFrame:
    """assisted (from assisted/assist/key_pass) + assist_type with the confirmed
    fallback (assisted→'pass', not→'none'); explicit known type preserved."""
    assisted = _bool(df, "assisted") | _bool(df, "assist") | _bool(df, "key_pass")
    raw = _text(df, "assist_type")
    mapped = raw.map(lambda v: ASSIST_TYPE_MAP.get(v))  # model value, or None if unknown/""
    fallback = pd.Series(np.where(assisted.to_numpy(), "pass", "none"), index=df.index)
    use_fallback = mapped.isna() | (mapped == "")
    assist_type = mapped.where(~use_fallback, fallback)
    return pd.DataFrame({"assisted": assisted.to_numpy(bool),
                         "assist_type": assist_type.astype(object)}, index=df.index)


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def select_shots(df: pd.DataFrame) -> pd.DataFrame:
    """Filter to shot rows (``event_type == 'shot'``) if the column exists."""
    if "event_type" in df.columns:
        return df[df["event_type"].astype(str).str.lower().eq("shot")]
    return df


def to_xg_input(df: pd.DataFrame) -> pd.DataFrame:
    """Convert canonical shot rows to the frozen xG API input schema.

    Requires ``x``/``y`` (raises ``ValueError`` otherwise). Never mutates ``df``;
    never fabricates coordinates. Returns a NEW dataframe with the model input
    features plus carried context columns (team/match/etc.) for grouping/eval.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"shot_adapter: missing required column(s) {missing}; "
                         "cannot build xG input without coordinates.")

    coords = coord_adapter.to_xg_coordinates(df)  # adds shot_x/shot_y (copy)
    ctx = derive_shot_context(df)
    assist = derive_assist(df)

    out = pd.DataFrame(index=df.index)
    out["shot_x"] = coords["shot_x"].to_numpy()
    out["shot_y"] = coords["shot_y"].to_numpy()
    out["body_part"] = map_body_part(df).to_numpy()
    out["shot_type"] = ctx["shot_type"].to_numpy()
    out["assist_type"] = assist["assist_type"].to_numpy()
    out["assisted"] = assist["assisted"].to_numpy()
    out["set_piece"] = ctx["set_piece"].to_numpy()
    out["free_kick"] = ctx["free_kick"].to_numpy()
    out["penalty"] = ctx["penalty"].to_numpy()

    for c in _CONTEXT_CARRY:
        if c in df.columns:
            out[c] = df[c].to_numpy()
    if "shot_result" in df.columns:  # eval/display convenience only, NOT a feature
        out["goal"] = _text(df, "shot_result").eq("goal").astype(int).to_numpy()
    return out
