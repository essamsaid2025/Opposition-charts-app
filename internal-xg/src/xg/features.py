"""Feature engineering for the Internal xG model (Checkpoint 2).

Design principles enforced here
-------------------------------
1. **Penalties are a separate process.** They are *not* fed to the main model.
   ``split_penalties`` separates them; ``estimate_penalty_xg`` gives an
   empirical penalty xG from the training data. This lets the system later
   expose both xG and npxG (non-penalty xG).

2. **Feature availability A/B.** Every candidate feature is classified:
     * ``A`` — reliably reproducible from our future *internal* shot data.
     * ``B`` — present in StatsBomb but NOT guaranteed internally.
   Only ``FEATURES_A`` are eligible for the production model. ``FEATURES_ALL``
   (A+B) exists only for offline experimentation/comparison.

3. **Geometry is symmetric.** Lateral position enters only through
   ``abs_y_offset`` and through the post-subtended ``angle`` — both invariant
   to a left/right mirror. Two mirror-image shots therefore get identical
   features, as an xG model should.

4. **No leakage.** ``goal``, ``outcome`` and ``statsbomb_xg`` can never enter
   the feature matrix; ``assert_no_leakage`` guards this.

Coordinates: we keep the raw StatsBomb 120x80 system in the stored dataset and
*derive* the modelling features from it. Distances are reported in metres
(StatsBomb units treated as yards, x0.9144); angles are in radians. See
DATASET.md and the docstrings below for every transformation.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config

# --------------------------------------------------------------------------- #
# Geometry constants (from config)
# --------------------------------------------------------------------------- #
_GX = config.GOAL_X                 # 120
_GC = config.GOAL_CENTER_Y          # 40
_LP = config.GOAL_LEFT_POST_Y       # 36
_RP = config.GOAL_RIGHT_POST_Y      # 44
_Y2M = config.YARDS_TO_METRES       # 0.9144
_EPS = 1e-9

# Columns that must NEVER be used as features (target / label-derived / provider)
LEAKY_COLUMNS = {"goal", "outcome", "statsbomb_xg"}


# --------------------------------------------------------------------------- #
# Numerical geometry features
# --------------------------------------------------------------------------- #
def shot_distance(x, y):
    """Euclidean distance from the shot to the goal centre (120, 40), in metres.

    distance = sqrt((120 - x)^2 + (40 - y)^2) * 0.9144
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    return np.hypot(_GX - x, _GC - y) * _Y2M


def distance_x(x):
    """Longitudinal distance to the goal line, in metres:  (120 - x) * 0.9144."""
    x = np.asarray(x, dtype=float)
    return (_GX - x) * _Y2M


def abs_y_offset(y):
    """Absolute lateral offset from the goal centre line, in metres:

    |y - 40| * 0.9144.  Using the absolute value makes the feature symmetric:
    a shot on the left and its mirror on the right share the same offset.
    """
    y = np.asarray(y, dtype=float)
    return np.abs(y - _GC) * _Y2M


def shot_angle(x, y):
    """Angle (radians) subtended by the goal mouth at the shot location.

    Uses the two goal posts P_left = (120, 36) and P_right = (120, 44):

        v1 = P_left  - shot
        v2 = P_right - shot
        angle = arccos( (v1 . v2) / (|v1| |v2|) )

    Properties:
      * Geometrically correct: it is the visual opening of the goal.
      * Symmetric: angle(x, y) == angle(x, 80 - y) exactly, so mirror-image
        shots from either side of the pitch get equal angles.
      * Larger when central and close; smaller from tight angles / long range.

    cos is clipped to [-1, 1] and denominators are epsilon-guarded so shots on
    the goal line or exactly at a post never produce NaN.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    v1x = _GX - x
    v1y = _LP - y
    v2x = _GX - x
    v2y = _RP - y
    dot = v1x * v2x + v1y * v2y
    n1 = np.hypot(v1x, v1y)
    n2 = np.hypot(v2x, v2y)
    cos = dot / (n1 * n2 + _EPS)
    cos = np.clip(cos, -1.0, 1.0)
    return np.arccos(cos)


def add_geometry(df: pd.DataFrame) -> pd.DataFrame:
    """Attach the derived geometry columns. Requires ``shot_x``/``shot_y``."""
    df = df.copy()
    x = df["shot_x"].to_numpy(dtype=float)
    y = df["shot_y"].to_numpy(dtype=float)
    df["distance"] = shot_distance(x, y)
    df["distance_x"] = distance_x(x)
    df["abs_y_offset"] = abs_y_offset(y)
    df["angle"] = shot_angle(x, y)
    # Interpretability helper only (NOT a model feature):
    df["angle_deg"] = np.degrees(df["angle"])
    return df


# --------------------------------------------------------------------------- #
# Context / categorical feature preparation
# --------------------------------------------------------------------------- #
_BOOL_COLS = [
    "assisted", "set_piece", "open_play", "free_kick", "penalty",
    "one_on_one", "first_time", "open_goal", "aerial_won", "follows_dribble",
    "assist_cross", "assist_through_ball", "assist_cutback",
]


def add_context(df: pd.DataFrame) -> pd.DataFrame:
    """Semantic (non-statistical) cleaning of categorical/flag features.

    - ``assist_type`` NaN means *unassisted* -> mapped to the explicit category
      ``"none"`` (a meaningful value, not missing data).
    - Boolean flags are coerced to real bools (CSV round-trips can yield
      strings) so downstream one-hot / passthrough is stable.

    Statistical imputation of any remaining gaps is deliberately left to the
    saved preprocessing pipeline (Checkpoint 3) so it travels with the model.
    """
    df = df.copy()
    if "assist_type" in df:
        df["assist_type"] = df["assist_type"].fillna("none").replace({np.nan: "none"})
    for c in _BOOL_COLS:
        if c in df:
            df[c] = (
                df[c].map({True: True, False: False, "True": True, "False": False})
                .fillna(False)
                .astype(bool)
            )
    return df


# --------------------------------------------------------------------------- #
# Feature groups + A/B availability classification
# --------------------------------------------------------------------------- #
# --- Group A: reliably reproducible from our future internal shot data -------
NUMERIC_A = ["distance", "angle", "distance_x", "abs_y_offset"]
CATEGORICAL_A = ["body_part", "shot_type", "assist_type"]
BINARY_A = ["assisted", "set_piece", "free_kick"]

# --- Group B: available in StatsBomb, NOT guaranteed internally ---------------
NUMERIC_B: list[str] = []
CATEGORICAL_B = ["technique", "play_pattern"]
BINARY_B = ["one_on_one", "first_time", "open_goal", "aerial_won", "follows_dribble"]

FEATURES_A = NUMERIC_A + CATEGORICAL_A + BINARY_A
FEATURES_B = NUMERIC_B + CATEGORICAL_B + BINARY_B
FEATURES_ALL = FEATURES_A + FEATURES_B

# Machine-readable availability map (feature -> "A"/"B") for reporting/metadata.
AVAILABILITY: dict[str, str] = {**{f: "A" for f in FEATURES_A}, **{f: "B" for f in FEATURES_B}}


def numeric_features(feature_set: str = "A") -> list[str]:
    return NUMERIC_A if feature_set == "A" else NUMERIC_A + NUMERIC_B


def categorical_features(feature_set: str = "A") -> list[str]:
    return CATEGORICAL_A if feature_set == "A" else CATEGORICAL_A + CATEGORICAL_B


def binary_features(feature_set: str = "A") -> list[str]:
    return BINARY_A if feature_set == "A" else BINARY_A + BINARY_B


def feature_columns(feature_set: str = "A") -> list[str]:
    """Ordered feature column list for a given set ('A' = production, 'ALL')."""
    cols = FEATURES_A if feature_set == "A" else FEATURES_ALL
    assert_no_leakage(cols)
    return list(cols)


def assert_no_leakage(cols) -> None:
    """Raise if any leaky column (target/label/provider xG) is in ``cols``."""
    bad = LEAKY_COLUMNS.intersection(set(cols))
    if bad:
        raise ValueError(f"Leakage: feature list contains forbidden columns {sorted(bad)}")


# --------------------------------------------------------------------------- #
# Penalty handling
# --------------------------------------------------------------------------- #
def split_penalties(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split into (non_penalty, penalty) frames.

    Penalties are a distinct process (fixed spot, ~73% conversion) and must not
    distort the open-play/general model. The main model trains and predicts on
    the non-penalty frame; penalties get a separate constant xG.
    """
    pen_mask = df["penalty"].astype(bool) if "penalty" in df else pd.Series(False, index=df.index)
    return df[~pen_mask].copy(), df[pen_mask].copy()


def estimate_penalty_xg(df: pd.DataFrame) -> dict:
    """Empirical penalty xG from the training data (NOT hard-coded).

    Returns the point estimate and a Wilson 95% CI. Store this in the model
    metadata so ``predict`` can assign penalties a data-driven value.
    """
    _, pen = split_penalties(df)
    n = int(len(pen))
    goals = int(pen["goal"].sum()) if n else 0
    p = goals / n if n else float("nan")
    z = 1.96
    if n:
        denom = 1 + z * z / n
        centre = (p + z * z / (2 * n)) / denom
        half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
        lo, hi = centre - half, centre + half
    else:
        lo = hi = float("nan")
    return {"penalty_xg": p, "n_penalties": n, "goals": goals, "wilson95_lo": lo, "wilson95_hi": hi}


# --------------------------------------------------------------------------- #
# Top-level builder
# --------------------------------------------------------------------------- #
def build_features(df: pd.DataFrame, feature_set: str = "A") -> tuple[pd.DataFrame, list[str]]:
    """Return (dataframe_with_features, feature_column_list).

    Applies geometry + context. Does NOT drop penalties (caller decides via
    ``split_penalties``) and does NOT touch the target.
    """
    out = add_geometry(df)
    out = add_context(out)
    cols = feature_columns(feature_set)
    # Guarantee every requested feature exists (B columns may be absent on
    # internal data -> create as neutral defaults so the same code path works).
    for c in cols:
        if c not in out.columns:
            if c in CATEGORICAL_A + CATEGORICAL_B:
                out[c] = "missing"
            elif c in NUMERIC_A + NUMERIC_B:
                out[c] = np.nan
            else:  # binary
                out[c] = False
    return out, cols
