"""Tests for the FAP shot adapter (pure mapping; no frozen package needed).

Run: pythonw -m pytest src/fap/xg/test_shot_adapter.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo/src
from fap.xg import shot_adapter as SA  # noqa: E402


def _row(**kw):
    base = {"event_type": "shot", "x": 90.0, "y": 50.0}
    base.update(kw)
    return pd.DataFrame([base])


# ---- shot_type / penalty / set_piece from set_piece text ----
def test_normal_open_play():
    o = SA.to_xg_input(_row(set_piece=""))
    assert o["shot_type"].iloc[0] == "Open Play"
    assert not o["penalty"].iloc[0] and not o["set_piece"].iloc[0] and not o["free_kick"].iloc[0]


def test_penalty_only_from_label():
    o = SA.to_xg_input(_row(set_piece="penalty"))
    assert o["penalty"].iloc[0] and o["shot_type"].iloc[0] == "Penalty" and o["set_piece"].iloc[0]


def test_unlabeled_setpiece_corner_is_open_play_but_setpiece_true():
    o = SA.to_xg_input(_row(set_piece="corner"))
    assert not o["penalty"].iloc[0]
    assert o["shot_type"].iloc[0] == "Open Play" and o["set_piece"].iloc[0]


def test_free_kick():
    o = SA.to_xg_input(_row(set_piece="free kick"))
    assert o["shot_type"].iloc[0] == "Free Kick" and o["free_kick"].iloc[0] and o["set_piece"].iloc[0]


def test_penalty_not_inferred_from_location():
    # a shot sitting near the penalty spot but NOT labelled -> non-penalty
    o = SA.to_xg_input(_row(x=89.0, y=50.0, set_piece=""))
    assert not o["penalty"].iloc[0]


# ---- assist rules ----
def test_assisted_known_type_preserved():
    o = SA.to_xg_input(_row(assist_type="cross", key_pass=True))
    assert o["assisted"].iloc[0] and o["assist_type"].iloc[0] == "cross"


def test_assisted_unknown_type_becomes_pass():
    o = SA.to_xg_input(_row(key_pass=True))
    assert o["assisted"].iloc[0] and o["assist_type"].iloc[0] == "pass"


def test_unassisted_unknown_becomes_none():
    o = SA.to_xg_input(_row())
    assert not o["assisted"].iloc[0] and o["assist_type"].iloc[0] == "none"


def test_through_ball_normalised():
    o = SA.to_xg_input(_row(assist_type="through ball", assist=True))
    assert o["assist_type"].iloc[0] == "through_ball"


def test_unknown_assist_token_with_assist_falls_back_to_pass():
    o = SA.to_xg_input(_row(assist_type="lobbed", assist=True))
    assert o["assist_type"].iloc[0] == "pass"  # specific types never inferred


# ---- body part mapping ----
@pytest.mark.parametrize("val,expected", [
    ("head", "Head"), ("foot", "Right Foot"), ("weak_foot", "Right Foot"),
    ("left foot", "Left Foot"), ("right foot", "Right Foot"), ("chest", "Other"),
])
def test_body_part_map(val, expected):
    assert SA.to_xg_input(_row(body_part=val))["body_part"].iloc[0] == expected


def test_body_part_missing_is_nan():
    o = SA.to_xg_input(_row())  # no body_part column value
    assert pd.isna(o["body_part"].iloc[0])


# ---- coordinates (delegated to coord_adapter) ----
def test_coordinates_use_coord_adapter():
    o = SA.to_xg_input(_row(x=100.0, y=50.0))
    assert o["shot_x"].iloc[0] == pytest.approx(120.0)
    assert o["shot_y"].iloc[0] == pytest.approx(40.0)


def test_both_sides_and_symmetry():
    left = SA.to_xg_input(_row(x=95.0, y=30.0))
    right = SA.to_xg_input(_row(x=95.0, y=70.0))  # mirror about canonical y=50
    assert abs((left["shot_y"].iloc[0] - 40) + (right["shot_y"].iloc[0] - 40)) < 1e-9
    assert left["shot_x"].iloc[0] == pytest.approx(right["shot_x"].iloc[0])


def test_boundary_and_center_coordinates():
    for cx, cy in [(0, 0), (100, 100), (50, 50), (0, 100), (100, 0)]:
        o = SA.to_xg_input(_row(x=cx, y=cy))
        assert np.isfinite(o["shot_x"].iloc[0]) and np.isfinite(o["shot_y"].iloc[0])


# ---- required data + immutability ----
def test_missing_coordinates_raises():
    with pytest.raises(ValueError):
        SA.to_xg_input(pd.DataFrame([{"event_type": "shot", "y": 50.0}]))  # no x


def test_does_not_mutate_input():
    df = _row(set_piece="penalty", body_part="head", key_pass=True)
    before = df.copy()
    SA.to_xg_input(df)
    pd.testing.assert_frame_equal(df, before)


def test_context_columns_carried():
    df = _row(team="Team A", match_id="M1", player="P1", shot_result="Goal")
    o = SA.to_xg_input(df)
    assert o["team"].iloc[0] == "Team A" and o["goal"].iloc[0] == 1


def test_select_shots_filters_event_type():
    df = pd.DataFrame([{"event_type": "shot", "x": 90, "y": 50},
                       {"event_type": "pass", "x": 50, "y": 50}])
    assert len(SA.select_shots(df)) == 1
