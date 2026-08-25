"""Public production inference API for the Internal xG Model.

This is the ONLY module a consuming application needs to import. It wraps the
frozen model (``models/internal_xg_v1.joblib``) and delegates all feature
engineering to :mod:`xg.features` and all scoring to :mod:`xg.predict`, so
training and inference share ONE source of truth for every formula.

Typical use
-----------
    from xg import api
    scored = api.predict_xg(shots_df)          # adds an 'xg' column
    total  = api.calculate_team_xg(shots_df)    # float
    npxg   = api.calculate_npxg(shots_df)       # float
    info   = api.model_info()                   # dict of model metadata

Production inference NEVER retrains. To build a new model, run the training
scripts, which write a NEW version (internal_xg_v2.joblib); v1 stays immutable.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import config, features as F, predict as _predict

# --------------------------------------------------------------------------- #
# Frozen model location + cached loader
# --------------------------------------------------------------------------- #
DEFAULT_MODEL_PATH = config.MODELS_DIR / "internal_xg_v1.joblib"
_CACHE: dict[str, dict] = {}


def load(model_path: str | Path = DEFAULT_MODEL_PATH) -> dict:
    """Load (and cache) a model bundle. Repeated calls reuse the same object."""
    key = str(Path(model_path).resolve())
    if key not in _CACHE:
        _CACHE[key] = _predict.load_model(model_path)
    return _CACHE[key]


# --------------------------------------------------------------------------- #
# Input contract (documented, machine-readable)
# --------------------------------------------------------------------------- #
REQUIRED_COLUMNS = ("shot_x", "shot_y")
# 'penalty' is required for correct penalty handling; if absent, all shots are
# treated as non-penalty (documented).
PENALTY_COLUMN = "penalty"
OPTIONAL_COLUMNS = ("body_part", "shot_type", "assist_type", "assisted", "set_piece", "free_kick")

ACCEPTED_VALUES = {
    "body_part": ["Right Foot", "Left Foot", "Head", "Other"],
    "shot_type": ["Open Play", "Free Kick", "Corner", "Penalty"],
    "assist_type": ["none", "pass", "cross", "through_ball", "cutback"],
    "assisted": [True, False],
    "set_piece": [True, False],
    "free_kick": [True, False],
    "penalty": [True, False],
}


# --------------------------------------------------------------------------- #
# Core API
# --------------------------------------------------------------------------- #
def predict_xg(shots: pd.DataFrame, on_invalid: str = "nan",
               model_path: str | Path = DEFAULT_MODEL_PATH) -> pd.DataFrame:
    """Return a COPY of ``shots`` with an added ``xg`` column in [0, 1].

    * Coordinates are required and validated (see ``on_invalid``).
    * Penalties (``penalty == True``) get the frozen empirical penalty xG.
    * The caller's dataframe is never mutated.
    """
    return _predict.predict_xg(shots, bundle=load(model_path), on_invalid=on_invalid)


def calculate_team_xg(shots: pd.DataFrame, by: str | None = None,
                      model_path: str | Path = DEFAULT_MODEL_PATH):
    """Total xG = sum of individual shot xG (includes penalties).

    With ``by`` (e.g. 'team') returns a per-group Series. NaN xG from invalid
    rows is skipped by the sum.
    """
    return _predict.calculate_team_xg(shots, bundle=load(model_path), by=by)


def calculate_npxg(shots: pd.DataFrame, by: str | None = None,
                   model_path: str | Path = DEFAULT_MODEL_PATH):
    """Non-penalty xG = sum of xG over non-penalty shots only.

    Penalty xG never contributes. With ``by`` returns a per-group Series.
    """
    return _predict.calculate_team_npxg(shots, bundle=load(model_path), by=by)


def penalty_xg(model_path: str | Path = DEFAULT_MODEL_PATH) -> float:
    """The frozen empirical penalty xG read from the model bundle (not hard-coded)."""
    return float(load(model_path)["penalty_xg"])


def model_info(model_path: str | Path = DEFAULT_MODEL_PATH) -> dict:
    """Curated model metadata for a consuming application to display."""
    md = load(model_path)["metadata"]
    keys = [
        "model_name", "model_version", "model_type", "description", "frozen",
        "training_data_source", "n_matches_total", "n_shots_total", "n_shots_nonpenalty",
        "features", "hyperparameters", "calibration_method", "penalty_handling",
        "final_metrics_primary_test", "software_versions", "limitations",
    ]
    info = {k: md[k] for k in keys if k in md}
    # Friendly aliases some callers may expect:
    info.setdefault("training_matches", md.get("n_matches_total"))
    info.setdefault("training_shots", md.get("n_shots_total"))
    info.setdefault("penalty_xg", load(model_path)["penalty_xg"])
    info.setdefault("training_date", md.get("frozen_at"))
    return info


def input_schema() -> dict:
    """Machine-readable input contract for validation/UX in a consuming app."""
    return {
        "required": list(REQUIRED_COLUMNS),
        "penalty_column": PENALTY_COLUMN,
        "optional": list(OPTIONAL_COLUMNS),
        "accepted_values": ACCEPTED_VALUES,
        "coordinate_system": "StatsBomb 120x80, attacking toward x=120 (goal centre 120,40)",
        "missing_value_policy": {
            "assist_type": "missing -> 'none' (unassisted)",
            "body_part/shot_type": "missing -> imputed inside the frozen pipeline",
            "binary flags": "missing -> False",
            "coordinates": "missing/off-pitch -> invalid (see on_invalid)",
        },
        "features_used_by_model": list(F.FEATURES_A),
    }
