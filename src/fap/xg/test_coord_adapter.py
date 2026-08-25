"""Unit tests for the FAP-canonical -> Internal-xG coordinate adapter.

Isolated: imports only the pure adapter module (no app bootstrap). Run with:
    pythonw -m pytest src/fap/xg/test_coord_adapter.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo/src
from fap.xg import coord_adapter as CA  # noqa: E402


def test_attacked_goal_centre_maps_to_sb_goal():
    x, y = CA.canonical_xy_to_sb(100, 50)
    assert (float(x), float(y)) == pytest.approx((120.0, 40.0))


def test_pitch_centre():
    x, y = CA.canonical_xy_to_sb(50, 50)
    assert (float(x), float(y)) == pytest.approx((60.0, 40.0))


def test_goal_lines():
    # attacked goal line x=100 -> 120 ; own goal line x=0 -> 0
    assert float(CA.canonical_x_to_sb(100)) == pytest.approx(120.0)
    assert float(CA.canonical_x_to_sb(0)) == pytest.approx(0.0)


def test_both_touchlines():
    # canonical y=0 (right touchline) -> SB y=80 ; y=100 (left) -> SB y=0
    assert float(CA.canonical_y_to_sb(0)) == pytest.approx(80.0)
    assert float(CA.canonical_y_to_sb(100)) == pytest.approx(0.0)


def test_attacking_direction_increases_x():
    # advancing toward the attacked goal (higher canonical x) -> higher SB x
    xs = CA.canonical_x_to_sb([10, 50, 90, 100])
    assert np.all(np.diff(xs) > 0)


def test_left_right_symmetry_about_centre():
    # mirror about canonical y=50 must mirror about SB y=40 (equal |y-40|)
    for y in (10.0, 30.0, 45.0, 50.0, 70.0, 100.0):
        a = float(CA.canonical_y_to_sb(y))
        b = float(CA.canonical_y_to_sb(100 - y))
        assert abs(a - 40.0) == pytest.approx(abs(b - 40.0))


def test_boundary_coordinates_finite():
    for cx, cy in [(0, 0), (0, 100), (100, 0), (100, 100), (50, 50)]:
        x, y = CA.canonical_xy_to_sb(cx, cy)
        assert np.isfinite(float(x)) and np.isfinite(float(y))
        assert 0 <= float(x) <= 120 and 0 <= float(y) <= 80


def test_round_trip_matches_statsbomb_rule():
    # inverse of the app's StatsBomb->canonical rule (x/120*100, (80-y)/80*100)
    for sb_x, sb_y in [(0, 0), (60, 20), (120, 40), (108, 44), (95, 62)]:
        cx = sb_x / 120 * 100
        cy = (80 - sb_y) / 80 * 100
        rx, ry = CA.canonical_xy_to_sb(cx, cy)
        assert float(rx) == pytest.approx(sb_x) and float(ry) == pytest.approx(sb_y)


def test_dataframe_adapter_adds_columns_and_preserves_source():
    df = pd.DataFrame({"x": [100.0, 50.0, "bad"], "y": [50.0, 50.0, 20.0], "other": [1, 2, 3]})
    out = CA.to_xg_coordinates(df)
    # source untouched
    assert list(out["x"])[:2] == [100.0, 50.0] and "other" in out.columns
    # new columns present and correct
    assert out["shot_x"].iloc[0] == pytest.approx(120.0)
    assert out["shot_y"].iloc[0] == pytest.approx(40.0)
    # non-numeric coordinate -> NaN (not invented/clipped)
    assert np.isnan(out["shot_x"].iloc[2])


def test_does_not_mutate_input():
    df = pd.DataFrame({"x": [100.0], "y": [50.0]})
    before = df.copy()
    CA.to_xg_coordinates(df)
    pd.testing.assert_frame_equal(df, before)
