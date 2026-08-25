"""Unit tests for coordinate geometry and feature engineering (Checkpoint 2).

Covered: distance, angle correctness + symmetry, feature assembly,
missing-value semantics, penalty split/estimate, and the leakage guard.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xg import config, features as F  # noqa: E402


# --------------------------------------------------------------------------- #
# Distance
# --------------------------------------------------------------------------- #
def test_distance_at_goal_centre_is_zero():
    assert F.shot_distance(120, 40) == pytest.approx(0.0, abs=1e-9)


def test_distance_known_value():
    # 12 units straight out from goal centre -> 12 yards -> 12*0.9144 m
    assert F.shot_distance(108, 40) == pytest.approx(12 * config.YARDS_TO_METRES, rel=1e-9)


def test_distance_monotonic_further_is_larger():
    assert F.shot_distance(100, 40) > F.shot_distance(110, 40)


def test_distance_x_and_offset():
    assert F.distance_x(110) == pytest.approx(10 * config.YARDS_TO_METRES)
    assert F.abs_y_offset(30) == pytest.approx(10 * config.YARDS_TO_METRES)
    assert F.abs_y_offset(50) == pytest.approx(10 * config.YARDS_TO_METRES)


# --------------------------------------------------------------------------- #
# Angle
# --------------------------------------------------------------------------- #
def test_angle_symmetry_mirror_about_centre():
    """The required property: equal distance + equal lateral angle from either
    side of the pitch must yield equivalent angles. y and 80-y are mirrors."""
    for x in (90.0, 100.0, 110.0, 115.0):
        for y in (20.0, 30.0, 36.0, 40.0, 44.0, 50.0):
            a = float(F.shot_angle(x, y))
            b = float(F.shot_angle(x, 80.0 - y))
            assert a == pytest.approx(b, abs=1e-12), f"asymmetry at x={x}, y={y}"


def test_angle_central_greater_than_wide_same_distance_x():
    # Same longitudinal distance; central should see a wider goal opening.
    central = F.shot_angle(108, 40)
    wide = F.shot_angle(108, 20)
    assert central > wide


def test_angle_closer_greater_than_farther_central():
    assert F.shot_angle(114, 40) > F.shot_angle(95, 40)


def test_angle_matches_manual_formula():
    # Independent computation via atan2 of the two post bearings.
    x, y = 104.0, 46.0
    a1 = math.atan2(config.GOAL_LEFT_POST_Y - y, config.GOAL_X - x)
    a2 = math.atan2(config.GOAL_RIGHT_POST_Y - y, config.GOAL_X - x)
    expected = abs(a1 - a2)
    assert float(F.shot_angle(x, y)) == pytest.approx(expected, abs=1e-9)


def test_angle_is_finite_on_goal_line_and_posts():
    for x, y in [(120, 40), (120, 36), (120, 44), (120.2, 40), (120, 0), (120, 80)]:
        val = float(F.shot_angle(x, y))
        assert np.isfinite(val)
        assert 0.0 <= val <= math.pi


def test_angle_vectorised_matches_scalar():
    xs = np.array([90.0, 100.0, 110.0])
    ys = np.array([30.0, 40.0, 50.0])
    vec = F.shot_angle(xs, ys)
    for i in range(len(xs)):
        assert vec[i] == pytest.approx(float(F.shot_angle(xs[i], ys[i])), abs=1e-12)


# --------------------------------------------------------------------------- #
# Feature assembly / geometry columns
# --------------------------------------------------------------------------- #
def _toy_df():
    return pd.DataFrame(
        {
            "shot_x": [108.0, 100.0, 90.0],
            "shot_y": [40.0, 30.0, 55.0],
            "body_part": ["Right Foot", "Head", "Left Foot"],
            "shot_type": ["Open Play", "Open Play", "Free Kick"],
            "assist_type": [np.nan, "cross", "pass"],
            "assisted": [False, True, True],
            "set_piece": [False, False, True],
            "free_kick": [False, False, True],
            "penalty": [False, False, False],
            "goal": [1, 0, 0],
        }
    )


def test_add_geometry_creates_expected_columns():
    df = F.add_geometry(_toy_df())
    for c in ["distance", "distance_x", "abs_y_offset", "angle"]:
        assert c in df.columns
        assert df[c].notna().all()


def test_build_features_A_has_no_leaky_columns():
    df, cols = F.build_features(_toy_df(), feature_set="A")
    assert not F.LEAKY_COLUMNS.intersection(cols)
    # every declared feature exists in the frame
    for c in cols:
        assert c in df.columns


def test_missing_assist_type_becomes_none_category():
    df, _ = F.build_features(_toy_df(), feature_set="A")
    assert df.loc[0, "assist_type"] == "none"
    assert df["assist_type"].isna().sum() == 0


def test_availability_map_all_A_features_marked_A():
    for f in F.FEATURES_A:
        assert F.AVAILABILITY[f] == "A"
    for f in F.FEATURES_B:
        assert F.AVAILABILITY[f] == "B"


def test_leakage_guard_raises():
    with pytest.raises(ValueError):
        F.assert_no_leakage(["distance", "goal"])
    with pytest.raises(ValueError):
        F.assert_no_leakage(["angle", "statsbomb_xg"])


# --------------------------------------------------------------------------- #
# Penalty handling
# --------------------------------------------------------------------------- #
def test_split_penalties():
    df = _toy_df()
    df.loc[1, "penalty"] = True
    non_pen, pen = F.split_penalties(df)
    assert len(pen) == 1 and len(non_pen) == 2
    assert bool(pen["penalty"].all())


def test_estimate_penalty_xg_matches_manual_rate():
    df = pd.DataFrame(
        {
            "penalty": [True, True, True, True, False],
            "goal": [1, 1, 1, 0, 1],
        }
    )
    est = F.estimate_penalty_xg(df)
    assert est["n_penalties"] == 4
    assert est["penalty_xg"] == pytest.approx(0.75)
    assert est["wilson95_lo"] < 0.75 < est["wilson95_hi"]


def test_production_feature_set_is_all_A():
    df, cols = F.build_features(_toy_df(), feature_set="A")
    assert all(F.AVAILABILITY[c] == "A" for c in cols)
