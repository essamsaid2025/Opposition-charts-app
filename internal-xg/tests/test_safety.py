"""Production-safety suite for the frozen Internal xG Model v1.0 (Checkpoint 6).

Does NOT retrain or modify the frozen model. Verifies safe, sensible inference
behavior: integrity, coordinates, geometry, missing data, penalties, extremes,
and failure modes.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xg import config, features as F, predict as P, validation  # noqa: E402

V1 = config.MODELS_DIR / "internal_xg_v1.joblib"
pytestmark = pytest.mark.skipif(not V1.exists(), reason="frozen v1 model not present")


@pytest.fixture(scope="module")
def model():
    return P.load_model(V1)


def _shot(**kw):
    base = dict(shot_x=110.0, shot_y=40.0, body_part="Right Foot", shot_type="Open Play",
                assist_type="none", assisted=False, set_piece=False, free_kick=False, penalty=False)
    base.update(kw)
    return pd.DataFrame([base])


def _shots(n, **kw):
    return pd.concat([_shot(**kw)] * n, ignore_index=True)


# ---------------- 1. integrity ----------------
def test_integrity_metadata(model):
    md = model["metadata"]
    assert md["model_version"] == "v1.0" and md["frozen"] is True
    assert md["features"] == model["feature_columns"]
    assert model["feature_columns"] == F.FEATURES_A


def test_predictions_deterministic(model):
    d = _shots(20, shot_x=112, shot_y=44)
    a = P.predict_xg(d, bundle=model)["xg"].to_numpy()
    b = P.predict_xg(d, bundle=model)["xg"].to_numpy()
    np.testing.assert_array_equal(a, b)


def test_predictions_in_unit_interval(model):
    rng = np.random.default_rng(0)
    d = pd.DataFrame({"shot_x": rng.uniform(0, 120, 500), "shot_y": rng.uniform(0, 80, 500),
                      "body_part": "Right Foot", "shot_type": "Open Play", "assist_type": "none",
                      "assisted": False, "set_piece": False, "free_kick": False, "penalty": False})
    xg = P.predict_xg(d, bundle=model)["xg"]
    assert xg.between(0, 1).all()


# ---------------- 2. coordinates ----------------
@pytest.mark.parametrize("y", [0.0, 5.0, 20.0, 36.0, 40.0, 80.0])
@pytest.mark.parametrize("x", [60.0, 100.0, 115.0, 120.0])
def test_symmetry_all_positions(model, x, y):
    a = P.predict_xg(_shot(shot_x=x, shot_y=y), bundle=model)["xg"].iloc[0]
    b = P.predict_xg(_shot(shot_x=x, shot_y=80 - y), bundle=model)["xg"].iloc[0]
    assert abs(a - b) < 1e-9


@pytest.mark.parametrize("x,y", [(-5, 40), (150, 40), (60, -3), (60, 90),
                                 (np.nan, 40), (60, np.nan), (np.inf, 40), (60, np.inf)])
def test_invalid_coords_flagged(model, x, y):
    d = _shot(shot_x=x, shot_y=y)
    assert validation.invalid_mask(d)[0]
    # default: NaN for the invalid row (no misleading number)
    out = P.predict_xg(d, bundle=model, on_invalid="nan")
    assert np.isnan(out["xg"].iloc[0])
    # strict: raises
    with pytest.raises(ValueError):
        P.predict_xg(d, bundle=model, on_invalid="error")


def test_valid_row_survives_alongside_invalid(model):
    d = pd.concat([_shot(shot_x=112, shot_y=40), _shot(shot_x=999, shot_y=40)], ignore_index=True)
    out = P.predict_xg(d, bundle=model, on_invalid="nan")
    assert 0 <= out["xg"].iloc[0] <= 1
    assert np.isnan(out["xg"].iloc[1])


def test_near_boundary_overshoot_allowed(model):
    # real StatsBomb data has x like 120.2 -> valid (within tolerance), scored raw
    out = P.predict_xg(_shot(shot_x=120.2, shot_y=40), bundle=model)
    assert 0 <= out["xg"].iloc[0] <= 1


# ---------------- 3. geometry ----------------
def test_distance_angle_finite_everywhere():
    d = pd.DataFrame({"shot_x": np.linspace(0, 120, 50), "shot_y": np.linspace(0, 80, 50)})
    g = F.add_geometry(d)
    assert np.isfinite(g["distance"]).all()
    assert np.isfinite(g["angle"]).all()
    assert (g["angle"] >= 0).all() and (g["angle"] <= np.pi).all()


def test_closer_shots_higher_central(model):
    xs = [70, 85, 95, 105, 112, 118]
    xg = [P.predict_xg(_shot(shot_x=x, shot_y=40), bundle=model)["xg"].iloc[0] for x in xs]
    assert all(xg[i] <= xg[i + 1] + 1e-9 for i in range(len(xg) - 1))


def test_wider_angle_higher_same_distance_x(model):
    # same distance_x (x=108), central vs wide -> central has larger angle
    central = P.predict_xg(_shot(shot_x=108, shot_y=40), bundle=model)["xg"].iloc[0]
    wide = P.predict_xg(_shot(shot_x=108, shot_y=18), bundle=model)["xg"].iloc[0]
    assert central > wide


# ---------------- 4/5. shot types & missing data ----------------
@pytest.mark.parametrize("kw", [
    {}, {"body_part": "Head"}, {"shot_type": "Free Kick", "free_kick": True, "set_piece": True},
    {"shot_type": "Corner", "set_piece": True}, {"assisted": True, "assist_type": "through_ball"},
    {"assist_type": np.nan}, {"body_part": np.nan}, {"assist_type": np.nan, "body_part": np.nan},
])
def test_shot_types_and_missing_do_not_crash(model, kw):
    out = P.predict_xg(_shot(**kw), bundle=model)
    assert 0 <= out["xg"].iloc[0] <= 1


def test_missing_optional_columns_entirely(model):
    # only coordinates provided; optional feature columns absent
    d = pd.DataFrame([{"shot_x": 110, "shot_y": 40, "penalty": False}])
    out = P.predict_xg(d, bundle=model)
    assert 0 <= out["xg"].iloc[0] <= 1


# ---------------- 6. penalties ----------------
def test_penalty_equals_frozen_constant(model):
    out = P.predict_xg(_shot(shot_x=108, shot_y=40, shot_type="Penalty", penalty=True), bundle=model)
    assert out["xg"].iloc[0] == pytest.approx(model["penalty_xg"])
    assert model["penalty_xg"] == pytest.approx(0.7255, abs=1e-3)


def test_xg_includes_npxg_excludes_penalty(model):
    d = pd.concat([_shot(shot_x=112, shot_y=40),
                   _shot(shot_x=108, shot_y=40, shot_type="Penalty", penalty=True)], ignore_index=True)
    xg = P.calculate_team_xg(d, bundle=model)
    npxg = P.calculate_team_npxg(d, bundle=model)
    scored = P.predict_xg(d, bundle=model)
    assert xg == pytest.approx(scored["xg"].sum())
    assert npxg == pytest.approx(scored["xg"].iloc[0])
    assert xg > npxg


# ---------------- 7. extreme shots ----------------
def test_extreme_shots_safe(model):
    cases = [(119, 40), (119, 62), (114, 40), (110, 40), (105, 40), (98, 40),
             (85, 40), (70, 40), (60, 40), (120, 55)]
    d = pd.DataFrame([{"shot_x": x, "shot_y": y, "body_part": "Right Foot",
                       "shot_type": "Open Play", "assist_type": "none", "assisted": False,
                       "set_piece": False, "free_kick": False, "penalty": False} for x, y in cases])
    xg = P.predict_xg(d, bundle=model)["xg"]
    assert np.isfinite(xg).all()
    assert (xg >= 0).all() and (xg <= 1).all()


def test_extreme_central_monotonic(model):
    xs = np.linspace(119.5, 60, 40)
    d = pd.DataFrame({"shot_x": xs, "shot_y": 40.0, "body_part": "Right Foot",
                      "shot_type": "Open Play", "assist_type": "none", "assisted": False,
                      "set_piece": False, "free_kick": False, "penalty": False})
    xg = P.predict_xg(d, bundle=model)["xg"].to_numpy()
    assert np.all(np.diff(xg) <= 1e-9)  # non-increasing as distance grows


# ---------------- 9. failure modes ----------------
def test_empty_dataframe(model):
    out = P.predict_xg(pd.DataFrame(columns=["shot_x", "shot_y", "penalty"]), bundle=model)
    assert "xg" in out.columns and len(out) == 0
    assert P.calculate_team_xg(pd.DataFrame(columns=["shot_x", "shot_y", "penalty"]), bundle=model) == 0.0


def test_single_and_many(model):
    assert len(P.predict_xg(_shot(), bundle=model)) == 1
    assert len(P.predict_xg(_shots(5000, shot_x=110, shot_y=40), bundle=model)) == 5000


def test_duplicated_shots_identical(model):
    d = _shots(10, shot_x=112, shot_y=44)
    xg = P.predict_xg(d, bundle=model)["xg"].to_numpy()
    assert np.allclose(xg, xg[0])


def test_unseen_categorical_values(model):
    out = P.predict_xg(_shot(body_part="Elbow", shot_type="Bicycle", assist_type="lob"), bundle=model)
    assert 0 <= out["xg"].iloc[0] <= 1
