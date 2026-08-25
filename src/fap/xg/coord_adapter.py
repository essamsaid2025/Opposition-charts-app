"""Coordinate adapter: FAP canonical space -> Internal xG model space.

The FAP application stores every event in ONE canonical coordinate space
(see ``fap.pipeline.coordinates``):

    x in [0, 100], attacking left -> right (attacked goal at x = 100)
    y in [0, 100], 0 = right touchline (from the attacking view)
    attacked-goal centre = (100, 50)

The frozen Internal xG Model v1.0 expects StatsBomb-compatible coordinates:

    x in [0, 120], attacking toward x = 120 (attacked goal at x = 120)
    y in [0, 80],  attacked-goal centre = (120, 40)

The app's StatsBomb->canonical rule is ``x/120*100, (80-y)/80*100``; this adapter
is its EXACT inverse, so a StatsBomb-sourced event round-trips to itself:

    shot_x = x_canonical * 1.2
    shot_y = 80 - y_canonical * 0.8

Properties (unit-tested):
  * canonical goal centre (100, 50) -> (120, 40)
  * pitch centre (50, 50) -> (60, 40)
  * own-goal line x=0 -> x=0; attacked-goal line x=100 -> x=120
  * left/right mirror preserved (mirror about canonical y=50 -> mirror about SB y=40)

This module is PURE (no fap imports, no app state). It does NOT change the
application's own coordinate system; it only produces model-space columns for
the xG API, leaving the source columns untouched.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Canonical (app) reference points
CANON_LENGTH = 100.0
CANON_WIDTH = 100.0
CANON_GOAL = (100.0, 50.0)

# StatsBomb (model) reference points
SB_LENGTH = 120.0
SB_WIDTH = 80.0
SB_GOAL = (120.0, 40.0)

_X_SCALE = SB_LENGTH / CANON_LENGTH   # 1.2
_Y_SCALE = SB_WIDTH / CANON_WIDTH     # 0.8


def canonical_x_to_sb(x):
    """Canonical x (0-100, goal at 100) -> StatsBomb x (0-120, goal at 120)."""
    return np.asarray(x, dtype=float) * _X_SCALE


def canonical_y_to_sb(y):
    """Canonical y (0=right touchline) -> StatsBomb y (0-80). Inverts + rescales."""
    return SB_WIDTH - np.asarray(y, dtype=float) * _Y_SCALE


def canonical_xy_to_sb(x, y) -> tuple:
    """Scalar/array helper: return (shot_x, shot_y) in StatsBomb space."""
    return canonical_x_to_sb(x), canonical_y_to_sb(y)


def to_xg_coordinates(
    df: pd.DataFrame,
    x_col: str = "x",
    y_col: str = "y",
    out_cols: tuple[str, str] = ("shot_x", "shot_y"),
) -> pd.DataFrame:
    """Return a COPY of ``df`` with StatsBomb-space ``shot_x``/``shot_y`` added.

    The source ``x``/``y`` columns are left untouched (the app's coordinate
    system is never mutated). Non-numeric coordinates become NaN, which the xG
    API's own validation layer then treats as invalid — this adapter does not
    invent or clip values.
    """
    out = df.copy()
    sx, sy = out_cols
    out[sx] = canonical_x_to_sb(pd.to_numeric(out[x_col], errors="coerce"))
    out[sy] = canonical_y_to_sb(pd.to_numeric(out[y_col], errors="coerce"))
    return out
