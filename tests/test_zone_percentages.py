"""Partitioned zone/lane percentages must total EXACTLY 100.

Independent rounding made Def/Mid/Final thirds (and the L/C/R lanes) read 99 or 101
(the reported 32+49+20=101). Largest-remainder rounding fixes it everywhere the
shares are a true partition: the app.py Zone % chart and the fap.visuals lane charts.
"""
import os
os.environ["FAP_TEST"] = "1"
import matplotlib
matplotlib.use("Agg")
import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import matplotlib.pyplot as plt
import pandas as pd

from fap.visuals.analysis import largest_remainder_pct
from fap.visuals.base import load_builtin_visuals, visual_registry

load_builtin_visuals()


# ================================================================ the helper
def test_largest_remainder_always_sums_to_100():
    for counts in ([1, 1, 1], [451, 691, 282], [0, 0, 5], [10, 0, 0],
                   [7, 7, 7, 7], [1, 2, 3, 4, 5]):
        assert sum(largest_remainder_pct(counts)) == 100


def test_fixes_the_reported_101_case():
    # counts that naively round to 32 + 49 + 20 = 101
    counts = [451, 691, 282]
    naive = [round(c / sum(counts) * 100) for c in counts]
    assert sum(naive) == 101                              # the bug
    fixed = largest_remainder_pct(counts)
    assert sum(fixed) == 100                              # the fix
    assert fixed == [32, 48, 20]                          # smallest remainder loses the point


def test_zero_total_is_all_zero():
    assert largest_remainder_pct([0, 0, 0]) == [0, 0, 0]
    assert largest_remainder_pct([]) == []


# ================================================================ fap.visuals lanes
def _lctx(df):
    from fap.visuals.context import LayerContext
    from fap.visuals.legend import LegendEngine
    from fap.visuals.pitch import get_spec
    from fap.visuals.tokens import StyleTokens
    from fap.themes.theme import ThemeManager
    from matplotlib.figure import Figure
    theme = ThemeManager("assets/themes").get("opta_dark")
    fig = Figure(); ax = fig.add_subplot(111)
    return LayerContext(fig=fig, ax=ax, df=df, theme=theme,
                        tokens=StyleTokens.from_theme(theme), controls={},
                        pitch_spec=get_spec("uefa"), legend=LegendEngine())


def _pass_df():
    ys = [5, 10, 20, 25, 40, 50, 55, 60, 80, 90, 95, 15, 45, 70]  # spread across lanes
    return pd.DataFrame({"event_type": ["pass"] * len(ys), "x": [30] * len(ys), "y": ys,
                         "end_x": [70] * len(ys), "end_y": ys, "outcome": ["successful"] * len(ys)})


def _lane_pcts(viz_id):
    viz = visual_registry.create(viz_id)
    zones = next(l for l in viz.layers(_lctx(_pass_df())) if l.info.id == "zones").params["zones"]
    return [int(m.group(1)) for z in zones
            for m in [re.search(r"(\d+)%", str(z[4]) + " " + str(z[5]))] if m]


def test_passing_lanes_sum_to_100():
    assert sum(_lane_pcts("passing_lanes")) == 100


def test_progressive_lanes_sum_to_100():
    pcts = _lane_pcts("progressive_pass_lanes")
    if pcts:                                              # only when progressive passes exist
        assert sum(pcts) == 100


# ================================================================ app.py zone chart
def test_app_zone_pct_sums_to_100():
    import app
    from fap.openplay.engine import default_ctx
    # 451 def + 691 mid + 282 final -> naive 32+49+20 = 101
    xs = [10] * 451 + [50] * 691 + [90] * 282
    df = pd.DataFrame({"x": xs, "y": [40] * len(xs), "event_type": ["pass"] * len(xs)})
    ctx = default_ctx(app.VIZ_THEMES["Opta Analyst"], app.PitchSpec())
    fig = plt.figure(); ax = fig.add_subplot(111)
    app.panel_zone_pct(ax, df, ctx, "Pitch Thirds")
    pcts = [int(m.group(1)) for t in ax.texts
            for m in [re.search(r"^(\d+)%$", t.get_text())] if m]
    plt.close(fig)
    assert len(pcts) == 3 and sum(pcts) == 100
