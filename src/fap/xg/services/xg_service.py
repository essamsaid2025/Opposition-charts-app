"""xG service — the ONLY bridge between the FAP app and the frozen standalone
Internal xG Model v1.0.

Isolation contract:
  * This module performs the single, isolated ``sys.path`` insertion needed to
    import the standalone ``xg`` package from ``internal-xg/src``.
  * The frozen package/model is NOT modified, NOT vendored, NOT copied.
  * The rest of the application imports ONLY from here — never ``xg.api`` /
    ``xg.predict`` / ``xg.features`` directly. Internal ``xg`` objects are never
    returned; only plain dataframes / floats / dicts cross this boundary.

Public API (app-native):
    score_shots(shots_df)          -> shots_df + 'internal_xg' column
    calculate_team_xg(shots_df)    -> float (or per-group Series with by=)
    calculate_npxg(shots_df)       -> float (or per-group Series with by=)
    get_xg_model_info()            -> dict of model metadata

All scoring/aggregation is delegated to the frozen API; nothing is recomputed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from fap.xg import shot_adapter

# --------------------------------------------------------------------------- #
# Isolated import of the standalone frozen package
# --------------------------------------------------------------------------- #
# repo/src/fap/xg/services/xg_service.py -> parents[4] == repo root
_INTERNAL_XG_SRC = Path(__file__).resolve().parents[4] / "internal-xg" / "src"
if _INTERNAL_XG_SRC.is_dir() and str(_INTERNAL_XG_SRC) not in sys.path:
    sys.path.insert(0, str(_INTERNAL_XG_SRC))

from xg import api as _xg_api  # noqa: E402  (frozen standalone package)

# The output column name. Deliberately NOT 'xg'/'shot_xg' to avoid colliding
# with any provider xG already present on the app's frames.
OUTPUT_COLUMN = "internal_xg"


# --------------------------------------------------------------------------- #
# Public, app-native functions
# --------------------------------------------------------------------------- #
def score_shots(shots_df: pd.DataFrame, on_invalid: str = "nan") -> pd.DataFrame:
    """Return a COPY of ``shots_df`` with an added ``internal_xg`` column.

    The caller's dataframe is never mutated and its existing columns are neither
    removed nor renamed. Invalid coordinates yield ``NaN`` (see ``on_invalid``);
    penalties (``set_piece == 'penalty'``) get the frozen penalty xG.
    """
    xg_input = shot_adapter.to_xg_input(shots_df)
    scored = _xg_api.predict_xg(xg_input, on_invalid=on_invalid)
    result = shots_df.copy()
    result[OUTPUT_COLUMN] = scored["xg"].to_numpy()  # positional; xg_input keeps order
    return result


def calculate_team_xg(shots_df: pd.DataFrame, by: str | None = None):
    """Total xG = sum of shot xG (incl. penalties), delegated to the frozen API.
    With ``by`` (e.g. 'team') returns a per-group Series."""
    return _xg_api.calculate_team_xg(shot_adapter.to_xg_input(shots_df), by=by)


def calculate_npxg(shots_df: pd.DataFrame, by: str | None = None):
    """Non-penalty xG = sum of xG over non-penalty shots only, delegated to the
    frozen API. With ``by`` returns a per-group Series."""
    return _xg_api.calculate_npxg(shot_adapter.to_xg_input(shots_df), by=by)


def get_xg_model_info() -> dict:
    """Plain dict of frozen-model metadata (version, type, features, metrics,
    penalty xG, package versions, limitations) for the app to display."""
    return dict(_xg_api.model_info())


def penalty_xg() -> float:
    """The frozen empirical penalty xG (read from model metadata)."""
    return float(_xg_api.penalty_xg())
