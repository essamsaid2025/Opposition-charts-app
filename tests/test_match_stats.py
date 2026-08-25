"""Event match -> team match-stats comparison aggregator (build_match_stats).

Turns a two-team canonical event frame into the TeamStatsSchema the team_compare
charts consume, reusing fap.visuals.analysis selectors. Correctness is the whole
point, so a small deterministic frame pins every derived value (goals, pass
accuracy, final-third share = Field Tilt, and the standard zone PPDA).
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import pandas as pd

from fap.openplay.match_stats import build_match_stats


def _rows(team, kind, xs, outcome="", shot_result=""):
    return [{"team": team, "event_type": kind, "x": x, "y": 40, "end_x": x, "end_y": 40,
             "outcome": outcome, "shot_result": shot_result} for x in xs]


def _frame():
    rows = []
    # Team A: 5 passes (4 ok), 2 in final third; 2 shots (goal+saved); 2 interceptions
    rows += _rows("A", "pass", [10, 20, 70, 80, 50], outcome="successful")
    rows[-1]["outcome"] = "unsuccessful"                    # last A pass unsuccessful
    rows += _rows("A", "shot", [85, 88], shot_result="goal")
    rows[-1]["shot_result"] = "saved"                       # 1 goal, 1 saved -> both on target
    rows += _rows("A", "interception", [40, 80])
    # Team B: 3 passes (all ok), 1 in final third; 1 shot (off target); 1 interception
    rows += _rows("B", "pass", [30, 40, 90], outcome="successful")
    rows += _rows("B", "shot", [86], shot_result="off t")
    rows += _rows("B", "interception", [50])
    return pd.DataFrame(rows)


def _named(schema):
    return {s.name: s for s in schema.stats}


def test_core_counts_are_correct():
    sch = build_match_stats(_frame())
    assert sch is not None and sch.teams == ["A", "B"]
    s = _named(sch)
    assert s["Goals"].values == {"A": 1.0, "B": 0.0}
    assert s["Shots"].values == {"A": 2.0, "B": 1.0}
    assert s["Shots on target"].values == {"A": 2.0, "B": 0.0}
    assert s["Passes"].values == {"A": 5.0, "B": 3.0}
    assert s["Interceptions"].values == {"A": 2.0, "B": 1.0}


def test_pass_accuracy_and_final_third():
    s = _named(build_match_stats(_frame()))
    assert s["Pass accuracy"].values == {"A": 80.0, "B": 100.0}      # 4/5 vs 3/3
    assert s["Passes in final third"].values == {"A": 2.0, "B": 1.0}  # x>66.67


def test_field_tilt_is_final_third_share():
    ft = _named(build_match_stats(_frame()))["Field Tilt"]
    assert ft.unit == "percent"
    assert ft.values == {"A": 67.0, "B": 33.0}      # 2/(2+1)=67%, 1/3=33%
    assert ft.category == "Advanced (derived)"


def test_ppda_standard_zone_formula():
    # PPDA_A = B passes in own 2/3 (x<=66.67: 30,40 -> 2) / A def actions in att 2/3
    #          (x>=33.33: 40,80 -> 2) = 2/2 = 1.0
    # PPDA_B = A passes in own 2/3 (10,20,50 -> 3) / B def actions (x>=33.33: 50 -> 1) = 3.0
    pp = _named(build_match_stats(_frame()))["PPDA"]
    assert pp.values == {"A": 1.0, "B": 3.0}


def test_possession_is_on_ball_share():
    # movement = passes here: A5 / (A5+B3) = 62.5 -> 62, B 38
    pos = _named(build_match_stats(_frame()))["Possession"]
    assert pos.values == {"A": 62.0, "B": 38.0} and pos.unit == "percent"


def test_no_fabrication_for_absent_stats():
    s = _named(build_match_stats(_frame()))
    # no fouls / corners / tackles(duels) / take-ons in the frame -> those stats are absent
    assert "Fouls" not in s and "Corners" not in s and "Tackles" not in s
    assert "Successful take ons" not in s


def test_requires_exactly_two_teams():
    one = pd.DataFrame(_rows("A", "pass", [10, 20]))
    assert build_match_stats(one) is None
    three = pd.DataFrame(_rows("A", "pass", [10]) + _rows("B", "pass", [20])
                         + _rows("C", "pass", [30]))
    assert build_match_stats(three) is None


def test_feeds_team_compare():
    from fap.openplay.team_compare import TeamComparison
    cmp = TeamComparison.from_schema(build_match_stats(_frame()), dataset_name="A vs B")
    labels = cmp.stat_labels()
    assert "PPDA" in labels and "Field Tilt" in labels and "Goals" in labels
    assert cmp.teams == ("A", "B")
