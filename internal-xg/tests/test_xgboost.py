"""Tests for the XGBoost candidate pipeline (Checkpoint 4).

Mirrors the baseline model tests: prediction range, missing values, unseen
categories, save/load consistency, symmetry, penalty exclusion, team xG.
Uses a small synthetic dataset so it is fast and self-contained.
"""
from __future__ import annotations

import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.pipeline import Pipeline
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xg import features as F, config  # noqa: E402
from xg import predict as P  # noqa: E402
from xg.preprocessing import build_preprocessor_for  # noqa: E402


@pytest.fixture(scope="module")
def xgb_bundle():
    rng = np.random.default_rng(1)
    n = 2000
    df = pd.DataFrame(
        {
            "shot_x": rng.uniform(80, 120, n),
            "shot_y": rng.uniform(10, 70, n),
            "body_part": rng.choice(["Right Foot", "Left Foot", "Head"], n),
            "shot_type": rng.choice(["Open Play", "Free Kick"], n, p=[0.9, 0.1]),
            "assist_type": rng.choice(["none", "pass", "cross", "through_ball"], n),
            "assisted": rng.choice([True, False], n),
            "set_piece": rng.choice([True, False], n, p=[0.2, 0.8]),
            "free_kick": False,
            "penalty": False,
        }
    )
    feat, cols = F.build_features(df, "A")
    lin = 3.0 - 0.18 * feat["distance"].to_numpy() + 1.5 * feat["angle"].to_numpy()
    feat["goal"] = (rng.uniform(size=n) < 1 / (1 + np.exp(-lin))).astype(int)
    pipe = Pipeline(
        [
            ("pre", build_preprocessor_for(cols)),
            ("clf", XGBClassifier(max_depth=4, learning_rate=0.1, n_estimators=60,
                                  min_child_weight=5, subsample=0.8, colsample_bytree=0.8,
                                  reg_lambda=5.0, objective="binary:logistic",
                                  tree_method="hist", random_state=0)),
        ]
    ).fit(feat[cols], feat["goal"])
    return {"pipeline": pipe, "feature_set": "A", "feature_columns": cols, "penalty_xg": 0.76}, df


def test_xgb_prediction_range(xgb_bundle):
    bundle, df = xgb_bundle
    out = P.predict_xg(df, bundle=bundle)
    assert out["xg"].between(0.0, 1.0).all()


def test_xgb_missing_values(xgb_bundle):
    bundle, _ = xgb_bundle
    shot = pd.DataFrame([{"shot_x": 110, "shot_y": 40, "body_part": np.nan,
                          "shot_type": "Open Play", "assist_type": np.nan, "assisted": False,
                          "set_piece": False, "free_kick": False, "penalty": False}])
    out = P.predict_xg(shot, bundle=bundle)
    assert 0.0 <= out["xg"].iloc[0] <= 1.0


def test_xgb_unseen_category(xgb_bundle):
    bundle, _ = xgb_bundle
    shot = pd.DataFrame([{"shot_x": 110, "shot_y": 40, "body_part": "Knee",
                          "shot_type": "Corner", "assist_type": "flick", "assisted": True,
                          "set_piece": True, "free_kick": False, "penalty": False}])
    out = P.predict_xg(shot, bundle=bundle)
    assert 0.0 <= out["xg"].iloc[0] <= 1.0


def test_xgb_save_load_consistency(xgb_bundle, tmp_path):
    bundle, df = xgb_bundle
    before = P.predict_xg(df, bundle=bundle)["xg"].to_numpy()
    path = tmp_path / "xgb.joblib"
    joblib.dump(bundle, path)
    after = P.predict_xg(df, bundle=P.load_model(path))["xg"].to_numpy()
    np.testing.assert_allclose(before, after, rtol=0, atol=1e-12)


def test_xgb_symmetry(xgb_bundle):
    bundle, _ = xgb_bundle
    left = pd.DataFrame([{"shot_x": 105, "shot_y": 28, "body_part": "Right Foot",
                          "shot_type": "Open Play", "assist_type": "none", "assisted": False,
                          "set_piece": False, "free_kick": False, "penalty": False}])
    right = left.copy(); right["shot_y"] = 52
    pl = P.predict_xg(left, bundle=bundle)["xg"].iloc[0]
    pr = P.predict_xg(right, bundle=bundle)["xg"].iloc[0]
    assert abs(pl - pr) < 1e-9


def test_xgb_penalty_excluded(xgb_bundle):
    bundle, _ = xgb_bundle
    pen = pd.DataFrame([{"shot_x": 108, "shot_y": 40, "body_part": "Right Foot",
                         "shot_type": "Penalty", "assist_type": "none", "assisted": False,
                         "set_piece": True, "free_kick": False, "penalty": True}])
    out = P.predict_xg(pen, bundle=bundle)
    assert out["xg"].iloc[0] == pytest.approx(bundle["penalty_xg"])


def test_xgb_team_xg_sum(xgb_bundle):
    bundle, df = xgb_bundle
    scored = P.predict_xg(df, bundle=bundle)
    assert P.calculate_team_xg(df, bundle=bundle) == pytest.approx(scored["xg"].sum(), rel=1e-9)


def test_saved_xgb_candidate_loads_if_present():
    path = config.MODELS_DIR / "xgboost_candidate.joblib"
    if not path.exists():
        pytest.skip("xgb candidate not trained yet")
    bundle = P.load_model(path)
    shot = pd.DataFrame([{"shot_x": 112, "shot_y": 40, "body_part": "Right Foot",
                          "shot_type": "Open Play", "assist_type": "pass", "assisted": True,
                          "set_piece": False, "free_kick": False, "penalty": False}])
    assert 0.0 <= P.predict_xg(shot, bundle=bundle)["xg"].iloc[0] <= 1.0
