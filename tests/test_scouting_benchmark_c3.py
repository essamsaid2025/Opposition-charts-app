"""Phase C3 — benchmark population + per-90, reusing build_view (no second engine).

Correctness focus (section 11): a Same-Position percentile is computed against the
same-position subset, NOT the whole dataset. Plus honest availability (section 8) and
honest per-90 that never assumes minutes and never divides a rate metric (section 4/17).
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import pandas as pd

from fap.scouting import viz


def _frame():
    # 6 players: 3 CM (Liverpool) + 3 ST (Arsenal). Target = "Star" (CM) has the TOP progressive
    # passes among ALL players, but is MID among CMs — so the benchmark choice must change the pct.
    return pd.DataFrame({
        "player":   ["Star", "CM_hi", "CM_lo", "ST1", "ST2", "ST3"],
        "position": ["CM", "CM", "CM", "ST", "ST", "ST"],
        "team":     ["Liverpool", "Liverpool", "Liverpool", "Arsenal", "Arsenal", "Arsenal"],
        "prog_passes": [50, 60, 40, 5, 6, 7],
        "minutes_played": [900, 900, 900, 900, 900, 900],
        "pass_pct": [80, 82, 78, 60, 61, 62],
    })


def _schema():
    return {"id_field": "player", "value_scale": viz.SCALE_RAW,
            "dimensions": {"position": "position", "team": "team"},
            "metrics": [{"source": "prog_passes"}, {"source": "minutes_played"},
                        {"source": "pass_pct", "unit": "%"}]}


def _pct(frame, metric="prog_passes", player="Star"):
    v = viz.build_view(frame, _schema(), [player])
    m = next(mm for mm in v.metrics if mm.source == metric)
    return m.percentiles[player], v.population


# ---------------------------------------------------------------- benchmark CORRECTNESS
def test_same_position_percentile_uses_subset_not_whole():
    f = _frame()
    whole_pct, whole_pop = _pct(f)
    sub = viz.benchmark_frame(f, _schema(), "Star", "position")
    pos_pct, pos_pop = _pct(sub)
    assert whole_pop == 6 and pos_pop == 3            # benchmarked vs the 3 CMs, not all 6
    # Star is HIGH vs everyone (many weak STs) but only MIDDLE among CMs -> lower percentile
    assert pos_pct < whole_pct


def test_benchmark_frame_always_includes_primary():
    f = _frame()
    for mode in ("whole", "position", "team", "selected"):
        sub = viz.benchmark_frame(f, _schema(), "Star", mode, selected=["ST1"])
        assert "Star" in set(sub["player"])


def test_selected_players_benchmark():
    f = _frame()
    sub = viz.benchmark_frame(f, _schema(), "Star", "selected", selected=["CM_hi"])
    assert set(sub["player"]) == {"Star", "CM_hi"}


# ---------------------------------------------------------------- honest availability
def test_benchmark_modes_report_populations_and_gaps():
    modes = {m["id"]: m for m in viz.benchmark_modes(_frame(), _schema(), "Star")}
    assert modes["whole"]["available"] and modes["whole"]["population"] == 6
    assert modes["position"]["available"] and modes["position"]["population"] == 3
    assert modes["team"]["available"] and modes["team"]["population"] == 3


def test_missing_position_field_is_honest():
    schema = {**_schema(), "dimensions": {"team": "team"}}
    modes = {m["id"]: m for m in viz.benchmark_modes(_frame(), schema, "Star")}
    assert modes["position"]["available"] is False and "not present" in modes["position"]["reason"]


def test_player_without_position_value_is_honest():
    f = _frame(); f.loc[f["player"] == "Star", "position"] = ""
    modes = {m["id"]: m for m in viz.benchmark_modes(f, _schema(), "Star")}
    assert modes["position"]["available"] is False and "no position" in modes["position"]["reason"]


# ---------------------------------------------------------------- honest per-90
def test_per90_transforms_counts_but_not_rates():
    f = _frame()
    p90 = viz.per90_frame(f, _schema())
    assert p90 is not None
    # prog_passes is a count -> divided by minutes*90 (900 min -> value*0.1)
    assert abs(p90.loc[0, "prog_passes"] - 50 / 900 * 90) < 1e-6
    # pass_pct is a rate (unit %) -> UNCHANGED
    assert p90.loc[0, "pass_pct"] == 80


def test_per90_none_without_minutes():
    schema = {**_schema(), "metrics": [{"source": "prog_passes"}, {"source": "pass_pct", "unit": "%"}]}
    f = _frame().drop(columns=["minutes_played"])
    assert viz.per90_frame(f, schema) is None       # no minutes -> honestly unavailable
