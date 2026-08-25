"""Input validation for xG inference (Checkpoint 6 — production safety).

This is an INFERENCE-LAYER guard, not part of the frozen model. It does not
change the model's features, preprocessing, hyperparameters, or artifact; it
only decides which input rows are safe to score.

Policy
------
A shot's coordinates are the only hard requirement (everything else is optional
and handled by the pipeline's imputers). Coordinates are INVALID when:

  * shot_x or shot_y is missing (NaN) or non-finite (±inf), or
  * they fall outside the pitch beyond a small tolerance:
        x in [0, 120], y in [0, 80], tolerance = 1.0 unit.

The tolerance admits legitimate on-line/rounding values (real StatsBomb data
contains e.g. x = 120.2) without clipping — values are passed through RAW so
inference stays consistent with how the model was trained. Anything beyond the
tolerance (x = 150, x = -5, y = 90, NaN, inf) is flagged invalid.

Invalid rows are never fed a misleading number: callers choose to either raise
(`on_invalid="error"`) or receive `xg = NaN` for those rows (`on_invalid="nan"`).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config

PITCH_X = (0.0, config.PITCH_LENGTH)   # (0, 120)
PITCH_Y = (0.0, config.PITCH_WIDTH)    # (0, 80)
COORD_TOL = 1.0
REQUIRED_COORD_COLS = ("shot_x", "shot_y")


def coordinate_issues(df: pd.DataFrame, tol: float = COORD_TOL) -> pd.Series:
    """Return a Series (indexed like df) of issue strings; empty string = OK."""
    reasons = pd.Series("", index=df.index, dtype=object)
    for col in REQUIRED_COORD_COLS:
        if col not in df.columns:
            reasons = reasons.mask(reasons == "", f"missing column '{col}'")
    if any(c not in df.columns for c in REQUIRED_COORD_COLS):
        return reasons

    for col, (lo, hi) in zip(REQUIRED_COORD_COLS, (PITCH_X, PITCH_Y)):
        v = pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=float)
        nan = ~np.isfinite(v)
        oob = (~nan) & ((v < lo - tol) | (v > hi + tol))
        reasons = reasons.mask((reasons == "") & nan, f"{col} is NaN/non-finite")
        reasons = reasons.mask((reasons == "") & oob, f"{col} out of pitch bounds")
    return reasons


def invalid_mask(df: pd.DataFrame, tol: float = COORD_TOL) -> np.ndarray:
    return (coordinate_issues(df, tol) != "").to_numpy()


def validate(df: pd.DataFrame, tol: float = COORD_TOL) -> None:
    """Raise ValueError if any row has invalid coordinates."""
    issues = coordinate_issues(df, tol)
    bad = issues[issues != ""]
    if len(bad):
        preview = "; ".join(f"row {i}: {r}" for i, r in list(bad.items())[:10])
        raise ValueError(f"{len(bad)} shot(s) have invalid coordinates. {preview}")
