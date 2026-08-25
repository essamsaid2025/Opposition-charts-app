"""Inference API for the Internal xG model.

Contains NO training logic. Loads a saved model bundle and turns shot features
into probabilities, routing penalties to their separate empirical value so the
API can expose both xG and non-penalty xG (npxG).

A saved bundle (joblib) is a dict:
    {
        "pipeline":        fitted sklearn pipeline (preprocess + estimator),
        "feature_set":     "A",
        "feature_columns": [...],
        "penalty_xg":      float,          # empirical, from training data
        "metadata":        {...},
    }
"""
from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from . import config, features as F, validation


def load_model(path: str | Path):
    return joblib.load(Path(path))


def _predict_raw(bundle, feat: pd.DataFrame) -> np.ndarray:
    cols = bundle["feature_columns"]
    return bundle["pipeline"].predict_proba(feat[cols])[:, 1]


def predict_xg(
    shots: pd.DataFrame,
    bundle=None,
    model_path: str | Path | None = None,
    on_invalid: str = "nan",
) -> pd.DataFrame:
    """Return the input shots plus an ``xg`` column in [0, 1].

    Penalties (``penalty == True``) are assigned the model's stored empirical
    penalty xG rather than the open-play model's output.

    Invalid coordinates (see ``validation``) are never silently scored:
      * ``on_invalid="nan"``   -> those rows get ``xg = NaN`` (default),
      * ``on_invalid="error"`` -> raise ``ValueError``.
    """
    if bundle is None:
        bundle = load_model(model_path or (config.MODELS_DIR / "internal_xg_v1.joblib"))

    out = shots.copy()
    # Empty input -> return an empty frame with the xg column (no crash).
    if len(out) == 0:
        out["xg"] = pd.Series(dtype=float)
        return out

    if on_invalid == "error":
        validation.validate(shots)
        bad = np.zeros(len(shots), dtype=bool)
    elif on_invalid == "nan":
        bad = validation.invalid_mask(shots)
    else:
        raise ValueError(f"on_invalid must be 'nan' or 'error', got {on_invalid!r}")

    # Invalid rows are NEVER fed to the pipeline (malformed coords such as inf
    # would otherwise crash preprocessing). They receive xg = NaN.
    out["xg"] = np.nan
    valid_idx = out.index[~bad]
    if len(valid_idx):
        feat, _ = F.build_features(shots.loc[valid_idx], bundle.get("feature_set", "A"))
        xg = np.clip(_predict_raw(bundle, feat), 0.0, 1.0)
        if "penalty" in feat.columns:
            pen_mask = feat["penalty"].to_numpy(dtype=bool)
            if pen_mask.any():
                xg = xg.copy()
                xg[pen_mask] = float(bundle["penalty_xg"])
        out.loc[valid_idx, "xg"] = xg
    return out


def calculate_team_xg(shots: pd.DataFrame, bundle=None, model_path=None, by: str | None = None):
    """Total xG. If ``by`` is given (e.g. 'team'), return a per-group Series."""
    scored = predict_xg(shots, bundle=bundle, model_path=model_path)
    if by is None:
        return float(scored["xg"].sum())
    return scored.groupby(by)["xg"].sum()


def calculate_team_npxg(shots: pd.DataFrame, bundle=None, model_path=None, by: str | None = None):
    """Non-penalty xG: sum of xG over non-penalty shots only."""
    scored = predict_xg(shots, bundle=bundle, model_path=model_path)
    if "penalty" in scored.columns:
        scored = scored[~scored["penalty"].astype(bool)]
    if by is None:
        return float(scored["xg"].sum())
    return scored.groupby(by)["xg"].sum()
