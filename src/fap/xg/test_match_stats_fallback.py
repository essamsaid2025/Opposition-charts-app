"""Match Stats Comparison xG/NPxG fallback (bug fix).

When the frame reaching the Match Stats chart has no ``internal_xg`` column, the
team metrics must DERIVE xG from the shot rows via the canonical xg_service -
not display 0. When the column is present it must be reused. Tests _team_metrics
directly (headless; frames coerced like production).

Run: pythonw -m pytest src/fap/xg/test_match_stats_fallback.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo/src
from fap.visuals.charts.match_flow import _team_metrics  # noqa: E402
from fap.pipeline.schema import coerce_schema  # noqa: E402
from fap.xg.services import xg_service  # noqa: E402

pytestmark = pytest.mark.skipif(
    not (Path(xg_service._INTERNAL_XG_SRC).parents[0] / "models" / "internal_xg_v1.joblib").exists(),
    reason="frozen v1 model not present",
)


def _frame(rows):
    """A coerced canonical frame WITHOUT an internal_xg column (unless a row sets it)."""
    return coerce_schema(pd.DataFrame(rows))


def _shots(team="A", extra=None):
    rows = [
        {"event_type": "shot", "team": team, "x": 95.0, "y": 50.0, "set_piece": "", "shot_result": "Goal"},
        {"event_type": "shot", "team": team, "x": 88.0, "y": 60.0, "set_piece": "", "shot_result": "Saved"},
        {"event_type": "pass", "team": team, "x": 40.0, "y": 50.0, "set_piece": "", "outcome": "successful"},
    ]
    if extra:
        rows.extend(extra)
    return _frame(rows)


# 1 & 2 & 4: no xG/NPxG column, no provider xG -> derived from shots (not 0)
def test_missing_internal_xg_is_calculated_from_shots():
    d = _shots()
    assert "internal_xg" not in d.columns or d["internal_xg"].isna().all()
    m = _team_metrics(d)
    assert m["xG"] > 0.0          # NOT zero despite no precomputed xG
    assert m["NPxG"] > 0.0        # NPxG likewise derived


# 3: internal_xg present -> reused, not recalculated
def test_present_internal_xg_is_reused():
    d = _shots()
    shots_mask = d["event_type"] == "shot"
    d.loc[shots_mask, "internal_xg"] = [0.40, 0.10]   # sentinels != model output
    m = _team_metrics(d)
    assert m["xG"] == pytest.approx(0.50, abs=0.005)   # reused sum, not recomputed


# 5: provider xG present -> ignored; internal_xg used instead
def test_provider_xg_not_used():
    d = _shots()
    d.loc[d["event_type"] == "shot", "shot_xg"] = [0.99, 0.99]   # provider values
    m = _team_metrics(d)
    assert m["xG"] != pytest.approx(round(0.99 + 0.99, 2))       # not provider sum
    assert m["xG"] > 0.0                                          # computed from shots


# 6 & 7: penalty included in xG, excluded from NPxG
def test_penalty_included_in_xg_excluded_from_npxg():
    d = _shots(extra=[{"event_type": "shot", "team": "A", "x": 89.0, "y": 50.0,
                       "set_piece": "penalty", "shot_result": "Goal"}])
    m = _team_metrics(d)
    frozen = xg_service.penalty_xg()
    assert m["xG"] > m["NPxG"]
    assert (m["xG"] - m["NPxG"]) == pytest.approx(round(frozen, 2), abs=0.011)


# 8: two teams each get their own values
def test_two_teams_independent():
    d = _shots("A", extra=[{"event_type": "shot", "team": "B", "x": 70.0, "y": 40.0,
                            "set_piece": "", "shot_result": "Off Target"}])
    ma = _team_metrics(d[d["team"] == "A"])
    mb = _team_metrics(d[d["team"] == "B"])
    assert ma["xG"] > 0 and mb["xG"] > 0
    assert ma["xG"] != mb["xG"]


# 9: filters -> only filtered shots aggregated
def test_filter_scope_respected():
    d = _shots()
    d.loc[d["event_type"] == "shot", "period"] = [1, 2]
    full = _team_metrics(d)["xG"]
    first = _team_metrics(d[d["period"] == 1])["xG"]
    assert 0 < first < full


# 10: empty shot set -> 0
def test_empty_shot_set_is_zero():
    d = _frame([{"event_type": "pass", "team": "A", "x": 40.0, "y": 50.0, "outcome": "successful"}])
    m = _team_metrics(d)
    assert m["xG"] == 0.0 and m["NPxG"] == 0.0


# 11: deterministic
def test_deterministic():
    assert _team_metrics(_shots())["xG"] == _team_metrics(_shots())["xG"]


# 12: existing Match Stats rows unchanged
def test_existing_rows_unchanged():
    m = _team_metrics(_shots())
    for row in ["Passes", "Pass Acc %", "Prog Passes", "Final 3rd Entries", "Crosses",
                "Shots", "On Target", "xG", "NPxG", "Tackles", "Interceptions"]:
        assert row in m
