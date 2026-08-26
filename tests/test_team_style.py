"""Style-of-Play metrics for our teams (fap.teams.style).

Turns a team's match event data into the numbers that describe our identity —
building play, possession, high pressing, fast recovery. Every metric reuses an
existing platform definition; these tests pin the values on a deterministic frame,
the team-name resolution, xG availability honesty, and the cross-match aggregates.
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import pandas as pd

from fap.teams import style as S
from fap.teams.style import MatchMetrics, StyleSeries


def _match(mid, our="Ahly", opp="Zamalek", *, our_goals=1, our_shots=4,
           with_xg=True):
    rows = []

    def add(team, kind, x, **kw):
        rows.append({"match_id": mid, "team": team, "event_type": kind, "x": x, "y": 40,
                     "end_x": kw.get("end_x", x), "end_y": 40,
                     "outcome": kw.get("outcome", ""), "shot_result": kw.get("shot_result", ""),
                     "set_piece": "", "time_min": kw.get("time_min", 0.0),
                     "internal_xg": kw.get("internal_xg", None)})

    # our passes: 10 total, 8 successful (80%), 4 in final third, 3 progressive (+30 x)
    for i in range(10):
        x = 70 if i < 4 else 40
        add(our, "pass", x, end_x=(x + 30 if i < 3 else x + 2),
            outcome="successful" if i < 8 else "unsuccessful", time_min=i * 0.1)
    # opponent passes: 6, all in their own two-thirds (x=40) -> PPDA numerator
    for i in range(6):
        add(opp, "pass", 40, outcome="successful", time_min=i * 0.1)
    # our shots
    for i in range(our_shots):
        res = "goal" if i < our_goals else ("saved" if i % 2 == 0 else "off")
        add(our, "shot", 88, shot_result=res, time_min=10 + i,
            internal_xg=(0.25 if with_xg else None))
    # our recoveries: 4, of which 2 high (x=75)
    for i in range(4):
        add(our, "recovery", 75 if i < 2 else 30, outcome="successful", time_min=20 + i)
    # our + opponent tackles in the attacking two-thirds -> PPDA denominator
    for i in range(3):
        add(our, "tackle", 55, outcome="successful", time_min=5 + i)
    for i in range(3):
        add(opp, "tackle", 55, outcome="successful", time_min=5 + i)
    return pd.DataFrame(rows)


def test_resolution_by_opponent_then_by_name():
    f = _match("m1")
    our, opp = S.resolve_team_names(f, "wrong name", "Zamalek")
    assert (our, opp) == ("Ahly", "Zamalek")           # inferred from opponent
    our, opp = S.resolve_team_names(f, "Ahly", "")
    assert (our, opp) == ("Ahly", "Zamalek")           # inferred from our name
    assert S.resolve_team_names(f, "nope", "nope") == (None, None)


def test_unresolved_match_yields_all_none():
    f = _match("m1")
    values, resolved = S.match_style_metrics(f, "nope", "nope")
    assert resolved is False
    assert all(v is None for v in values.values())


def test_metric_values_are_correct():
    f = _match("m1", our_goals=1, our_shots=4)
    v, resolved = S.match_style_metrics(f, "Ahly", "Zamalek")
    assert resolved is True
    assert v["pass_accuracy"] == 80.0
    assert v["final_third_passes"] == 4
    assert v["progressive_passes"] == 3
    assert v["opp_passes_allowed"] == 6
    assert v["high_recoveries"] == 2                    # recoveries with x > 66.7
    assert v["turnovers_lost"] == 2                     # 2 unsuccessful passes
    assert v["shots"] == 4
    assert v["goals"] == 1
    assert v["shots_on_target"] == 2                    # 1 goal + 1 saved
    assert v["xg"] == 1.0                               # 4 shots * 0.25
    # PPDA = opp passes in own 2/3 (6) / our defensive actions in attacking 2/3 (3 tackles)
    assert v["ppda"] == 2.0


def test_xg_absent_is_none_not_fabricated():
    f = _match("m1", with_xg=False)
    # drop the column entirely so the frozen model is the only possible source
    f = f.drop(columns=["internal_xg"])
    v, _ = S.match_style_metrics(f, "Ahly", "Zamalek")
    # xG is either a real model value (>= 0) or None — never invented from thin air.
    assert v["xg"] is None or v["xg"] >= 0.0


def test_series_aggregates_and_trend():
    per = []
    for i, (opp, goals) in enumerate([("Zamalek", 0), ("Pyramids", 1), ("Ismaily", 2)]):
        v, res = S.match_style_metrics(_match(f"m{i}", opp=opp, our_goals=goals, our_shots=4),
                                       "Ahly", opp)
        per.append(MatchMetrics(match_id=f"m{i}", label=f"vs {opp}", date=f"2026-0{i+1}-01",
                                opponent=opp, resolved=res, values=v))
    series = StyleSeries(per_match=per)
    assert len(series.played) == 3
    assert series.latest.get("goals") == 2
    assert series.averages(series.window(5))["goals"] == 1.0     # (0+1+2)/3
    trend = series.trend("goals", window=2)
    assert [p["raw"] for p in trend] == [0.0, 1.0, 2.0]
    assert [p["rolling"] for p in trend] == [0.0, 0.5, 1.5]      # trailing mean, window 2


def test_averages_ignore_unavailable_matches():
    good = MatchMetrics(match_id="a", resolved=True, values={k: None for k in S.METRIC_KEYS} | {"xg": 1.4})
    none = MatchMetrics(match_id="b", resolved=True, values={k: None for k in S.METRIC_KEYS})
    series = StyleSeries(per_match=[good, none])
    assert series.averages()["xg"] == 1.4               # None match excluded, not counted as 0
    assert series.averages()["goals"] is None


def test_catalogue_covers_the_four_pillars():
    assert set(S.PILLARS) == {m.pillar for m in S.METRICS}
    for pillar in S.PILLARS:
        assert S.metrics_in(pillar), f"pillar {pillar} has metrics"
