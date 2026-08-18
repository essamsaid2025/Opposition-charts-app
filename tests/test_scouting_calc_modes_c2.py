"""Phase C2 — honest calculation-mode detection (fap.scouting.viz.calc_modes).

Raw always valid; Percentile needs a population; Per-90 / Per-match are offered ONLY when
an exposure column (minutes / 90s / matches) actually exists — never assumes 90', never
fabricates exposure (section 17). Pure/deterministic.
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import pandas as pd

from fap.scouting import viz


def _view(cols, players=("A",), n=6):
    frame = pd.DataFrame({"player": [f"P{i}" for i in range(n)]})
    for c in cols:
        frame[c] = list(range(n))
    frame.loc[0, "player"] = "A"
    schema = {"id_field": "player", "value_scale": viz.SCALE_RAW, "dimensions": {},
              "metrics": [{"source": c} for c in cols]}
    return viz.build_view(frame, schema, list(players))


def _mode(modes, mid):
    return next(m for m in modes if m["id"] == mid)


def test_raw_and_percentile_always_offered():
    modes = viz.calc_modes(_view(["passes"]))
    assert _mode(modes, "raw")["available"] is True
    assert _mode(modes, "percentile")["available"] is True     # population 6 >= 2


def test_percentile_unavailable_without_population():
    modes = viz.calc_modes(_view(["passes"], n=1))
    m = _mode(modes, "percentile")
    assert m["available"] is False and m["reason"]


def test_per90_only_when_minutes_present():
    without = _mode(viz.calc_modes(_view(["passes", "tackles"])), "per_90")
    assert without["available"] is False and "minutes" in without["reason"].lower()
    withmin = _mode(viz.calc_modes(_view(["passes", "minutes_played"])), "per_90")
    assert withmin["available"] is True and withmin["reason"] == ""


def test_per_match_only_when_exposure_present():
    without = _mode(viz.calc_modes(_view(["passes"])), "per_match")
    assert without["available"] is False and without["reason"]
    withapps = _mode(viz.calc_modes(_view(["passes", "appearances"])), "per_match")
    assert withapps["available"] is True


def test_never_assumes_90_minutes():
    # a dataset with NO exposure column must NOT offer per-90 (the honesty rule)
    modes = viz.calc_modes(_view(["goals", "shots", "xg"]))
    assert _mode(modes, "per_90")["available"] is False
    assert _mode(modes, "per_match")["available"] is False
