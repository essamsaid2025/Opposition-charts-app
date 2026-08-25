"""Integration-flow tests: app derived frame -> internal_xg (Checkpoint 3).

Exercises the real centralized seam
``fap.openplay.transforms.add_derived_columns`` and verifies the attached
``internal_xg`` matches direct ``xg_service`` scoring.

Run: pythonw -m pytest src/fap/xg/test_integration_flow.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo/src
from fap.openplay.transforms import add_derived_columns, ensure_columns  # noqa: E402
from fap.xg.services import xg_service as SVC  # noqa: E402

_MODEL = Path(SVC._INTERNAL_XG_SRC).parents[0] / "models" / "internal_xg_v1.joblib"
pytestmark = pytest.mark.skipif(not _MODEL.exists(), reason="frozen v1 model not present")

COL = "internal_xg"


def _frame(rows):
    return ensure_columns(pd.DataFrame(rows))


def _sample():
    return _frame([
        {"event_type": "pass", "team": "A", "x": 40, "y": 50, "x2": 60, "y2": 55},
        {"event_type": "shot", "team": "A", "x": 94, "y": 50, "body_part": "foot",
         "shot_result": "Saved", "shot_xg": 0.11},                       # provider xG present
        {"event_type": "shot", "team": "A", "x": 88, "y": 60, "body_part": "head",
         "set_piece": "corner", "shot_result": "Goal", "shot_xg": 0.15},
        {"event_type": "shot", "team": "A", "x": 89, "y": 50, "set_piece": "penalty",
         "shot_result": "Goal", "shot_xg": 0.79},                        # penalty
        {"event_type": "shot", "team": "B", "x": 80, "y": 40, "shot_result": "Off Target"},
    ])


# 1. derived frame gets internal_xg on shots only
def test_internal_xg_added_on_shots_only():
    out = add_derived_columns(_sample())
    assert COL in out.columns
    assert np.isnan(out.loc[0, COL])                       # the pass row
    assert out.loc[out["event_type"] == "shot", COL].notna().all()


# 2. existing columns preserved
def test_existing_columns_preserved():
    src = _sample()
    out = add_derived_columns(src)
    assert set(src.columns).issubset(set(out.columns))


# 3. provider xG preserved, never overwritten
def test_provider_xg_preserved():
    out = add_derived_columns(_sample())
    assert "shot_xg" in out.columns
    assert out.loc[1, "shot_xg"] == pytest.approx(0.11)   # unchanged
    assert COL != "shot_xg" and out.loc[1, COL] != out.loc[1, "shot_xg"]


# 4. added exactly once, no suffix collisions
def test_added_exactly_once():
    out = add_derived_columns(_sample())
    assert list(out.columns).count(COL) == 1
    assert "internal_xg_x" not in out.columns and "internal_xg_y" not in out.columns


# 5. idempotent repeated processing
def test_idempotent_repeated_processing():
    once = add_derived_columns(_sample())
    twice = add_derived_columns(once)
    assert list(twice.columns).count(COL) == 1
    pd.testing.assert_series_equal(once[COL], twice[COL])


# 6/7. team aggregation & npxG from the shot-level column
def test_team_and_npxg_from_column():
    out = add_derived_columns(_sample())
    shots = out[out["event_type"] == "shot"]
    team_a = shots[shots["team"] == "A"]
    total_a = np.nansum(team_a[COL].to_numpy())
    pen_val = SVC.penalty_xg()
    npxg_a = np.nansum(team_a.loc[team_a["set_piece"] != "penalty", COL].to_numpy())
    assert total_a == pytest.approx(npxg_a + pen_val, abs=1e-9)


# 8. penalty uses frozen value
def test_penalty_value():
    out = add_derived_columns(_sample())
    pen = out[out["set_piece"] == "penalty"]
    assert pen[COL].iloc[0] == pytest.approx(SVC.penalty_xg())


# 9. malformed coordinate row -> NaN, others fine, no crash
def test_malformed_coordinate_row():
    frame = _frame([
        {"event_type": "shot", "team": "A", "x": 94, "y": 50},
        {"event_type": "shot", "team": "A", "x": np.nan, "y": 50},
    ])
    out = add_derived_columns(frame)
    assert 0 <= out.loc[0, COL] <= 1 and np.isnan(out.loc[1, COL])


# 10. missing optional fields
def test_missing_optional_fields():
    out = add_derived_columns(_frame([{"event_type": "shot", "x": 90, "y": 50}]))
    assert 0 <= out[COL].iloc[0] <= 1


# 11. deterministic
def test_deterministic():
    a = add_derived_columns(_sample())[COL].to_numpy()
    b = add_derived_columns(_sample())[COL].to_numpy()
    np.testing.assert_array_equal(a, b)


# 12. empty shot dataframe (schema-correct, zero rows)
def test_empty_frame():
    empty = ensure_columns(pd.DataFrame({c: [] for c in ["event_type", "x", "y", "x2", "y2", "minute", "second"]}))
    out = add_derived_columns(empty)
    assert COL in out.columns and len(out) == 0


# 13/14. multi-match, multi-team
def test_multi_match_and_team():
    frame = _frame([
        {"event_type": "shot", "team": "A", "match_id": "M1", "x": 92, "y": 48},
        {"event_type": "shot", "team": "B", "match_id": "M1", "x": 85, "y": 55},
        {"event_type": "shot", "team": "A", "match_id": "M2", "x": 96, "y": 50},
    ])
    out = add_derived_columns(frame)
    by = out.groupby("team")[COL].sum()
    assert set(by.index) == {"A", "B"} and out[COL].notna().all()


# MOST IMPORTANT: app internal_xg == direct xg_service on the same shot rows
def test_matches_direct_service():
    src = _sample()
    out = add_derived_columns(src)
    shot_rows = src[src["event_type"].str.lower() == "shot"]
    direct = SVC.score_shots(shot_rows)[SVC.OUTPUT_COLUMN].to_numpy()
    via_app = out.loc[out["event_type"] == "shot", COL].to_numpy()
    np.testing.assert_allclose(via_app, direct, rtol=0, atol=1e-12, equal_nan=True)
