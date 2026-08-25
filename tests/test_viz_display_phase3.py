"""Phase 3 — the shared display + methodology model extended to the two standalone
matplotlib systems via a thin adapter: fap.scouting.charts and
fap.openplay.team_compare. Same guarantees as Phase 1/2: strict capability gating,
toggles change the matplotlib output (not the data), dynamic honest notes, and
defaults that reproduce current output.
"""
import os
os.environ["FAP_TEST"] = "1"
import matplotlib
matplotlib.use("Agg")
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import matplotlib.pyplot as plt
import pandas as pd

from fap.datahub.scouting_schema import analyze_player_scouting
from fap.datahub.team_stats_schema import analyze_team_stats
from fap.openplay import team_compare as TC
from fap.scouting import charts as SC
from fap.scouting import viz as SV
from fap.themes.theme import ThemeManager
from fap.visuals.display import display_controls_for, reset_display

_THEME = ThemeManager("assets/themes").get("opta_dark")


# ---------------------------------------------------------------- fixtures
def _scouting_view(players=("P0",)):
    rows = []
    for i in range(14):
        rows.append({"Player": f"P{i}", "Team": f"Club {i%4}", "Position": "CF",
                     "Goals per 90": (i % 10) / 10, "xG per 90": (i % 7) / 10,
                     "Progressive passes per 90": (i % 9) / 10, "Duels won, %": (i % 8) * 10})
    frame = pd.DataFrame(rows)
    schema = analyze_player_scouting(frame).schema.to_dict()
    view = SV.build_view(frame, schema, list(players), dataset_name="Scout DB")
    return view, frame


def _team_cmp():
    csv = ("Category,Statistic,FC MASAR,ABU QIR\n"
           "Summary,Possessions,56%,44%\nSummary,Shots in total,6,11\n"
           "Summary,Corners,5,2\nDistribution,Successful passes,372,240\n"
           "Distribution,Pass accuracy,72%,62%\n")
    import io
    schema = analyze_team_stats(pd.read_csv(io.StringIO(csv))).schema
    return TC.TeamComparison.from_schema(schema, dataset_name="Masar vs Abu Qir")


def _ax_texts(fig):
    return [t.get_text() for ax in fig.axes for t in ax.texts]


# ================================================================ scouting capabilities
def test_scouting_capability_declarations():
    bar = SC.capabilities_for("bar")
    assert bar.values and bar.grid and bar.axes and not bar.legend
    assert not bar.xg and not bar.xg_values             # scouting never encodes xG
    scat = SC.capabilities_for("scatter")
    assert scat.player_names and not scat.legend        # scatter draws no ax.legend
    assert SC.capabilities_for("comparison").legend
    hm = SC.capabilities_for("heatmap")
    assert hm.values and hm.legend
    # strict gate: no Scouting chart exposes xG controls
    for ct in SC.CHART_CAPS:
        keys = {c.key for c in display_controls_for(SC.capabilities_for(ct))}
        assert "show_xg" not in keys and "show_xg_values" not in keys


def test_scouting_defaults_reproduce_output():
    bar = SC.display_defaults_for("bar")
    assert bar["show_values"] is True and bar["show_grid"] is True and bar["show_axes"] is True
    assert SC.display_defaults_for("scatter")["show_player_names"] is True
    assert SC.display_defaults_for("radar")["legend"] is True


# ================================================================ scouting rendering honours toggles
def test_bar_show_values_toggles_text():
    view, _ = _scouting_view()
    srcs = view.sources()
    on = SC.render("bar", view, _THEME, {"metrics": srcs, "display": {"show_values": True}})
    off = SC.render("bar", view, _THEME, {"metrics": srcs, "display": {"show_values": False}})
    assert len(_ax_texts(on)) > 0 and len(_ax_texts(off)) == 0
    plt.close(on); plt.close(off)


def test_bar_show_grid_toggles_gridlines():
    view, _ = _scouting_view()
    srcs = view.sources()
    on = SC.render("bar", view, _THEME, {"metrics": srcs, "display": {"show_grid": True}})
    off = SC.render("bar", view, _THEME, {"metrics": srcs, "display": {"show_grid": False}})
    assert any(g.get_visible() for g in on.axes[0].get_xgridlines())
    assert not any(g.get_visible() for g in off.axes[0].get_xgridlines())
    plt.close(on); plt.close(off)


def test_scatter_player_names_toggle():
    view, frame = _scouting_view()
    srcs = view.sources()
    opts = {"x": srcs[0], "y": srcs[1], "frame": frame}
    on = SC.render("scatter", view, _THEME, {**opts, "display": {"show_player_names": True}})
    off = SC.render("scatter", view, _THEME, {**opts, "display": {"show_player_names": False}})
    assert "P0" in _ax_texts(on) and "P0" not in _ax_texts(off)
    plt.close(on); plt.close(off)


def test_comparison_legend_toggle():
    view, _ = _scouting_view(players=("P0", "P1"))
    srcs = view.sources()
    on = SC.render("comparison", view, _THEME, {"metrics": srcs, "display": {"legend": True}})
    off = SC.render("comparison", view, _THEME, {"metrics": srcs, "display": {"legend": False}})
    assert on.axes[0].get_legend() is not None
    assert off.axes[0].get_legend() is None
    plt.close(on); plt.close(off)


def test_display_toggles_do_not_change_data():
    view, frame = _scouting_view()
    before = frame.copy(deep=True)
    src = view.sources()[0]
    val_before = view.metric(src).value(view.primary)
    fig = SC.render("bar", view, _THEME, {"metrics": view.sources(),
                                          "display": {"show_values": False}})
    plt.close(fig)
    pd.testing.assert_frame_equal(frame, before)                 # dataframe untouched
    assert view.metric(src).value(view.primary) == val_before    # metric untouched


# ================================================================ scouting methodology
def test_scouting_note_reports_fields_and_reference():
    from fap.ui.components.scouting_viz_workspace import _chart_fields, _scouting_note  # noqa
    view, _ = _scouting_view()
    fields = _chart_fields(view, "percentile_bar", {"metrics": view.sources()[:2]})
    assert fields and all(isinstance(f, str) for f in fields)
    # build the note the way the UI does and inspect its rows
    from fap.visuals.methodology import build_note
    note = build_note(dataset="player_scouting", fields=fields, filters=None,
                      metric="Percentile Profile · percentile vs dataset",
                      pitch_based=False, scope=f"Player · {view.primary}",
                      population=f"{view.population} players")
    rows = dict(note.rows())
    assert rows["Dataset"] == "player_scouting"
    assert rows["Fields"] == ", ".join(fields)
    assert "percentile" in rows["Metric"]
    assert rows["Reference"] == f"{view.population} players"
    assert rows["Coordinates"] == "n/a (non-spatial chart)"


# ================================================================ team compare
def test_team_compare_capabilities():
    assert TC.capabilities_for("comparison").values and TC.capabilities_for("comparison").legend
    share = TC.capabilities_for("share")
    assert share.percentages and share.legend and not share.values
    assert TC.capabilities_for("radar").legend
    for ct in TC.CHART_CAPS:
        keys = {c.key for c in display_controls_for(TC.capabilities_for(ct))}
        assert "show_xg" not in keys                    # team stats never encode xG


def test_team_compare_share_percentages_toggle():
    cmp = _team_cmp()
    stats = cmp.stat_labels()[:4]
    on = TC.render("share", cmp, _THEME, {"stats": stats, "display": {"show_percentages": True}})
    off = TC.render("share", cmp, _THEME, {"stats": stats, "display": {"show_percentages": False}})
    assert any("%" in t for t in _ax_texts(on))
    assert not any("%" in t for t in _ax_texts(off))
    plt.close(on); plt.close(off)


def test_team_compare_comparison_legend_toggle():
    cmp = _team_cmp()
    stats = cmp.stat_labels()[:4]
    on = TC.render("comparison", cmp, _THEME, {"stats": stats, "display": {"legend": True}})
    off = TC.render("comparison", cmp, _THEME, {"stats": stats, "display": {"legend": False}})
    assert on.axes[0].get_legend() is not None and off.axes[0].get_legend() is None
    plt.close(on); plt.close(off)


def test_team_compare_defaults_reproduce_output():
    cmp = _team_cmp()
    stats = cmp.stat_labels()[:4]
    # default (no display) shows values on comparison bars, exactly as before
    fig = TC.render("comparison", cmp, _THEME, {"stats": stats})
    assert len(_ax_texts(fig)) > 0
    plt.close(fig)


# ================================================================ reset
def test_reset_only_touches_display():
    caps = SC.capabilities_for("bar")
    controls = {"show_values": False, "show_grid": False,
                "metrics": ["a", "b"], "benchmark": "position", "player": "P0"}
    reset_display(controls, caps, SC.CHART_DEFAULTS["bar"])
    assert controls["show_values"] is True and controls["show_grid"] is True
    assert controls["metrics"] == ["a", "b"] and controls["benchmark"] == "position"
    assert controls["player"] == "P0"
