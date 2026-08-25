"""UI-surfacing tests (Checkpoint 4): xG/NPxG aggregation + Match Stats table.

Pure/headless: exercises the aggregation helpers and the Match Stats team-metric
builder without importing Streamlit. Verifies xG comes from the canonical
``internal_xg`` column (never provider xG / goals / counts).

Run: pythonw -m pytest src/fap/xg/test_ui_surfacing.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo/src
from fap.xg import enrichment as E  # noqa: E402
from fap.visuals.charts.match_flow import _team_metrics  # noqa: E402
from fap.pipeline.schema import coerce_schema  # noqa: E402


def _shots():
    return pd.DataFrame([
        {"event_type": "shot", "team": "A", "internal_xg": 0.10, "set_piece": ""},
        {"event_type": "shot", "team": "A", "internal_xg": 0.20, "set_piece": "corner"},
        {"event_type": "shot", "team": "A", "internal_xg": 0.7255, "set_piece": "penalty"},
    ])


def test_sum_xg_includes_penalties():
    assert E.sum_xg(_shots()) == pytest.approx(0.10 + 0.20 + 0.7255)


def test_sum_npxg_excludes_penalties():
    assert E.sum_npxg(_shots()) == pytest.approx(0.10 + 0.20)


def test_sum_xg_nan_safe():
    df = pd.DataFrame({"internal_xg": [0.1, float("nan")], "set_piece": ["", ""]})
    assert E.sum_xg(df) == pytest.approx(0.1)


def test_sum_xg_missing_column_is_zero():
    assert E.sum_xg(pd.DataFrame({"team": ["A"]})) == 0.0


def test_match_stats_uses_internal_xg_not_provider():
    d = coerce_schema(pd.DataFrame([
        {"event_type": "shot", "team": "A", "x": 90, "y": 50, "set_piece": "",
         "shot_result": "Goal", "shot_xg": 0.99},   # provider value must be IGNORED
        {"event_type": "shot", "team": "A", "x": 89, "y": 50, "set_piece": "penalty",
         "shot_result": "Goal", "shot_xg": 0.99},
    ]))
    d["internal_xg"] = [0.30, 0.7255]
    m = _team_metrics(d)
    assert "xG" in m and "NPxG" in m
    assert m["xG"] == pytest.approx(round(0.30 + 0.7255, 2))   # includes penalty
    assert m["NPxG"] == pytest.approx(round(0.30, 2))          # excludes penalty
    assert m["xG"] != pytest.approx(round(0.99 + 0.99, 2))     # not provider xG
