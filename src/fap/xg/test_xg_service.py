"""Tests for the xG service (delegates to the frozen Internal xG Model v1.0).

Run: pythonw -m pytest src/fap/xg/test_xg_service.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo/src
from fap.xg import shot_adapter as SA  # noqa: E402
from fap.xg.services import xg_service as SVC  # noqa: E402

# frozen package is importable via the service's path insertion
from xg import api as _xg_api  # noqa: E402

_MODEL = Path(SVC._INTERNAL_XG_SRC).parents[0] / "models" / "internal_xg_v1.joblib"
pytestmark = pytest.mark.skipif(not _MODEL.exists(), reason="frozen v1 model not present")


def _shots():
    return pd.DataFrame([
        {"event_type": "shot", "team": "A", "x": 94, "y": 50, "body_part": "foot",
         "set_piece": "", "key_pass": True, "shot_result": "Saved"},
        {"event_type": "shot", "team": "A", "x": 88, "y": 60, "body_part": "head",
         "set_piece": "corner", "key_pass": True, "shot_result": "Goal"},
        {"event_type": "shot", "team": "A", "x": 89, "y": 50, "body_part": "foot",
         "set_piece": "penalty", "shot_result": "Goal"},
        {"event_type": "shot", "team": "B", "x": 80, "y": 40, "body_part": "foot",
         "set_piece": "", "shot_result": "Off Target"},
    ])


# ---- basic ----
def test_score_shots_adds_column_in_range():
    out = SVC.score_shots(_shots())
    assert SVC.OUTPUT_COLUMN in out.columns
    vals = out[SVC.OUTPUT_COLUMN].dropna()
    assert vals.between(0, 1).all()


def test_does_not_mutate_caller():
    df = _shots()
    before = df.copy()
    SVC.score_shots(df)
    pd.testing.assert_frame_equal(df, before)


def test_no_existing_columns_removed_or_renamed():
    df = _shots()
    out = SVC.score_shots(df)
    assert set(df.columns).issubset(set(out.columns))
    assert list(out.columns)[: len(df.columns)] == list(df.columns)


# ---- penalty ----
def test_penalty_uses_frozen_value():
    out = SVC.score_shots(_shots())
    pen_row = out[out["set_piece"] == "penalty"]
    assert pen_row[SVC.OUTPUT_COLUMN].iloc[0] == pytest.approx(SVC.penalty_xg())


# ---- matches direct frozen API on the same adapted inputs ----
def test_service_matches_direct_frozen_api():
    df = _shots()
    adapted = SA.to_xg_input(df)
    direct = _xg_api.predict_xg(adapted)["xg"].to_numpy()
    via_service = SVC.score_shots(df)[SVC.OUTPUT_COLUMN].to_numpy()
    np.testing.assert_allclose(via_service, direct, rtol=0, atol=1e-12, equal_nan=True)


# ---- team xG / npxG ----
def test_team_xg_equals_sum():
    df = _shots()
    out = SVC.score_shots(df)
    assert SVC.calculate_team_xg(df) == pytest.approx(np.nansum(out[SVC.OUTPUT_COLUMN].to_numpy()))


def test_npxg_excludes_penalty():
    df = _shots()
    total = SVC.calculate_team_xg(df)
    npxg = SVC.calculate_npxg(df)
    assert total > npxg
    assert (total - npxg) == pytest.approx(SVC.penalty_xg(), abs=1e-9)


def test_team_xg_grouped_multiple_teams():
    df = _shots()
    by_team = SVC.calculate_team_xg(df, by="team")
    assert set(by_team.index) == {"A", "B"}
    out = SVC.score_shots(df)
    assert by_team["B"] == pytest.approx(np.nansum(out.loc[out["team"] == "B", SVC.OUTPUT_COLUMN]))


# ---- invalid / mixed / symmetry / determinism ----
def test_invalid_coordinates_become_nan():
    df = pd.DataFrame([{"event_type": "shot", "x": 9999, "y": 50}])  # off-pitch after scaling
    out = SVC.score_shots(df)
    assert np.isnan(out[SVC.OUTPUT_COLUMN].iloc[0])


def test_mixed_valid_invalid():
    df = pd.DataFrame([{"event_type": "shot", "x": 94, "y": 50},
                       {"event_type": "shot", "x": 9999, "y": 50}])
    out = SVC.score_shots(df)
    assert 0 <= out[SVC.OUTPUT_COLUMN].iloc[0] <= 1 and np.isnan(out[SVC.OUTPUT_COLUMN].iloc[1])


def test_left_right_symmetry():
    left = pd.DataFrame([{"event_type": "shot", "x": 92, "y": 35, "body_part": "foot"}])
    right = pd.DataFrame([{"event_type": "shot", "x": 92, "y": 65, "body_part": "foot"}])
    a = SVC.score_shots(left)[SVC.OUTPUT_COLUMN].iloc[0]
    b = SVC.score_shots(right)[SVC.OUTPUT_COLUMN].iloc[0]
    assert abs(a - b) < 1e-9


def test_deterministic_repeated_calls():
    df = _shots()
    a = SVC.score_shots(df)[SVC.OUTPUT_COLUMN].to_numpy()
    b = SVC.score_shots(df)[SVC.OUTPUT_COLUMN].to_numpy()
    np.testing.assert_array_equal(a, b)


# ---- metadata ----
def test_model_info_is_plain_dict():
    info = SVC.get_xg_model_info()
    assert isinstance(info, dict)
    assert info["model_version"] == "v1.0" and info["frozen"] is True
    assert "features" in info and "penalty_xg" in info
