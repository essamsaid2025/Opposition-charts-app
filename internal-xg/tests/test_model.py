"""Model/pipeline tests for the Logistic Regression baseline (Checkpoint 3).

Covers: pipeline fitting, prediction range, missing assist_type, unseen
categorical values, save/load round-trip consistency, left/right symmetry,
and team-xG aggregation. Uses a small synthetic dataset so the suite is fast
and independent of the large downloaded data.
"""
from __future__ import annotations

import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xg import features as F, train  # noqa: E402
from xg import predict as P  # noqa: E402


@pytest.fixture(scope="module")
def toy_bundle():
    """Fit a real pipeline on a small synthetic dataset with signal."""
    rng = np.random.default_rng(0)
    n = 1500
    x = rng.uniform(80, 120, n)
    y = rng.uniform(10, 70, n)
    df = pd.DataFrame(
        {
            "match_id": rng.integers(0, 50, n),
            "shot_x": x,
            "shot_y": y,
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
    # Goal probability driven by distance + angle so the model learns real signal.
    lin = 3.0 - 0.18 * feat["distance"].to_numpy() + 1.5 * feat["angle"].to_numpy()
    p = 1 / (1 + np.exp(-lin))
    feat["goal"] = (rng.uniform(size=n) < p).astype(int)
    est = train.build_estimator(C=1.0, feature_set="A").fit(feat[cols], feat["goal"])
    return {"pipeline": est, "feature_set": "A", "feature_columns": cols, "penalty_xg": 0.76}, df


def test_pipeline_fits_and_predicts(toy_bundle):
    bundle, df = toy_bundle
    out = P.predict_xg(df, bundle=bundle)
    assert "xg" in out.columns
    assert len(out) == len(df)


def test_predictions_in_unit_interval(toy_bundle):
    bundle, df = toy_bundle
    out = P.predict_xg(df, bundle=bundle)
    assert out["xg"].between(0.0, 1.0).all()


def test_missing_assist_type_handled(toy_bundle):
    bundle, _ = toy_bundle
    shot = pd.DataFrame(
        [{"shot_x": 110, "shot_y": 40, "body_part": "Right Foot", "shot_type": "Open Play",
          "assist_type": np.nan, "assisted": False, "set_piece": False, "free_kick": False,
          "penalty": False}]
    )
    out = P.predict_xg(shot, bundle=bundle)
    assert 0.0 <= out["xg"].iloc[0] <= 1.0


def test_unseen_categorical_value(toy_bundle):
    bundle, _ = toy_bundle
    shot = pd.DataFrame(
        [{"shot_x": 110, "shot_y": 40, "body_part": "Chest",  # never seen in training
          "shot_type": "Corner",                              # unseen level too
          "assist_type": "flick", "assisted": True, "set_piece": True, "free_kick": False,
          "penalty": False}]
    )
    out = P.predict_xg(shot, bundle=bundle)  # must not raise
    assert 0.0 <= out["xg"].iloc[0] <= 1.0


def test_save_load_prediction_consistency(toy_bundle, tmp_path):
    bundle, df = toy_bundle
    before = P.predict_xg(df, bundle=bundle)["xg"].to_numpy()
    path = tmp_path / "toy.joblib"
    joblib.dump(bundle, path)
    loaded = P.load_model(path)
    after = P.predict_xg(df, bundle=loaded)["xg"].to_numpy()
    np.testing.assert_allclose(before, after, rtol=0, atol=1e-12)


def test_left_right_symmetry(toy_bundle):
    bundle, _ = toy_bundle
    left = pd.DataFrame([{"shot_x": 105, "shot_y": 28, "body_part": "Right Foot",
                          "shot_type": "Open Play", "assist_type": "none", "assisted": False,
                          "set_piece": False, "free_kick": False, "penalty": False}])
    right = left.copy(); right["shot_y"] = 80 - 28
    pl = P.predict_xg(left, bundle=bundle)["xg"].iloc[0]
    pr = P.predict_xg(right, bundle=bundle)["xg"].iloc[0]
    assert abs(pl - pr) < 1e-9


def test_penalty_routed_to_constant(toy_bundle):
    bundle, _ = toy_bundle
    pen = pd.DataFrame([{"shot_x": 108, "shot_y": 40, "body_part": "Right Foot",
                         "shot_type": "Penalty", "assist_type": "none", "assisted": False,
                         "set_piece": True, "free_kick": False, "penalty": True}])
    out = P.predict_xg(pen, bundle=bundle)
    assert out["xg"].iloc[0] == pytest.approx(bundle["penalty_xg"])


def test_team_xg_equals_sum(toy_bundle):
    bundle, df = toy_bundle
    scored = P.predict_xg(df, bundle=bundle)
    total = P.calculate_team_xg(df, bundle=bundle)
    assert total == pytest.approx(scored["xg"].sum(), rel=1e-9)


def test_npxg_excludes_penalties(toy_bundle):
    bundle, df = toy_bundle
    d = df.copy()
    d.loc[d.index[:5], "penalty"] = True
    d.loc[d.index[:5], "shot_type"] = "Penalty"
    scored = P.predict_xg(d, bundle=bundle)
    npxg = P.calculate_team_npxg(d, bundle=bundle)
    manual = scored.loc[~d["penalty"].astype(bool), "xg"].sum()
    assert npxg == pytest.approx(manual, rel=1e-9)


def test_saved_baseline_loads_if_present():
    """If the real baseline has been trained, it must load and predict in [0,1]."""
    path = ROOT / "models" / "logistic_baseline.joblib"
    if not path.exists():
        pytest.skip("baseline not trained yet")
    bundle = P.load_model(path)
    shot = pd.DataFrame([{"shot_x": 112, "shot_y": 40, "body_part": "Right Foot",
                          "shot_type": "Open Play", "assist_type": "pass", "assisted": True,
                          "set_piece": False, "free_kick": False, "penalty": False}])
    out = P.predict_xg(shot, bundle=bundle)
    assert 0.0 <= out["xg"].iloc[0] <= 1.0
