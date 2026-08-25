"""Show-xG-values across every chart that genuinely renders xG.

fap.visuals: the hand-written shot maps (attacking._ShotMapBase variants), the xG
colour-scale map (GoalProbabilityMap) and the goal-mouth maps (goalkeeper) now
declare xg + xg_values and honour them independently. Open Play (app.py): panel_shots
prints the canonical internal_xg next to every shot when show_xg_values is on. Defaults
preserve current output; the xG data is never changed.
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

from fap.core.types import RenderContext
from fap.visuals.base import load_builtin_visuals, visual_registry
from fap.visuals.display import display_controls_for
from fap.visuals.renderer import Renderer
from fap.themes.theme import ThemeManager

load_builtin_visuals()
_THEME = ThemeManager("assets/themes").get("opta_dark")


def _shots_df():
    return pd.DataFrame({
        "event_type": ["shot"] * 5,
        "x": [80, 85, 90, 88, 78], "y": [40, 45, 50, 30, 60],
        "end_x": [100] * 5, "end_y": [48, 52, 44, 56, 50],
        "shot_result": ["goal", "saved", "off_target", "blocked", "goal"],
        "shot_xg": [0.12, 0.34, 0.55, 0.08, 0.42],
        "player": ["A", "B", "C", "D", "E"]})


def _ax_texts(fig):
    return [t.get_text() for ax in fig.axes for t in ax.texts]


# ================================================================ fap.visuals capabilities
def test_shot_maps_declare_xg_capabilities():
    for vid in ("shot_map", "expected_goals_map", "goal_probability"):
        caps = visual_registry.create(vid).capabilities
        keys = {c.key for c in display_controls_for(caps)}
        assert caps.xg and caps.xg_values
        assert "show_xg" in keys and "show_xg_values" in keys, vid


def test_shot_map_xg_values_toggle():
    viz = visual_registry.create("shot_map")
    df = _shots_df()
    on = Renderer().render(viz, RenderContext(df=df, theme=_THEME,
                                              controls={"show_xg_values": True}))
    off = Renderer().render(viz, RenderContext(df=df, theme=_THEME,
                                               controls={"show_xg_values": False}))
    assert "0.55" in _ax_texts(on) and "0.34" in _ax_texts(on)   # xG numbers printed
    assert "0.55" not in _ax_texts(off)
    # data integrity: the xG column is unchanged
    assert list(df["shot_xg"]) == [0.12, 0.34, 0.55, 0.08, 0.42]
    plt.close(on); plt.close(off)


def test_show_xg_gates_size_encoding_not_data():
    from fap.visuals.context import LayerContext
    from fap.visuals.legend import LegendEngine
    from fap.visuals.pitch import get_spec
    from fap.visuals.tokens import StyleTokens
    from matplotlib.figure import Figure
    viz = visual_registry.create("shot_map")
    df = _shots_df()

    def _scatter_sizes(show_xg):
        fig = Figure(); ax = fig.add_subplot(111)
        ctx = LayerContext(fig=fig, ax=ax, df=df, theme=_THEME,
                           tokens=StyleTokens.from_theme(_THEME),
                           controls={"show_xg": show_xg}, pitch_spec=get_spec("uefa"),
                           legend=LegendEngine())
        scat = [l for l in viz.layers(ctx) if l.info.id == "scatter"]
        return [l.params.get("sizes") for l in scat]

    assert all(s is not None for s in _scatter_sizes(True))    # xG-sized
    assert all(s is None for s in _scatter_sizes(False))       # uniform (encoding off)


def test_goal_probability_xg_values():
    viz = visual_registry.create("goal_probability")
    df = _shots_df()
    on = Renderer().render(viz, RenderContext(df=df, theme=_THEME,
                                              controls={"show_xg_values": True}))
    assert any(t in ("0.55", "0.42") for t in _ax_texts(on))
    plt.close(on)


def test_goal_mouth_map_xg_values():
    viz = visual_registry.create("goal_mouth_map")
    df = _shots_df()
    on = Renderer().render(viz, RenderContext(df=df, theme=_THEME,
                                              controls={"show_xg_values": True}))
    off = Renderer().render(viz, RenderContext(df=df, theme=_THEME,
                                               controls={"show_xg_values": False}))
    assert any(t in ("0.34", "0.42", "0.12") for t in _ax_texts(on))
    assert not any(t in ("0.34", "0.42", "0.12") for t in _ax_texts(off))
    plt.close(on); plt.close(off)


# ================================================================ Open Play engine (app.py)
def _app_ctx(app, show_xg_values):
    vt = app.VIZ_THEMES["Opta Analyst"]
    spec = app.PitchSpec()
    from fap.openplay.engine import default_ctx
    df = pd.DataFrame({
        "event_type": ["shot"] * 3, "x": [80, 88, 90], "y": [40, 45, 50],
        "x_plot": [80, 88, 90], "y_plot": [27, 30, 34], "x2_plot": [0, 0, 0],
        "y2_plot": [0, 0, 0], "shot_result": ["goal", "saved", "off_target"],
        "internal_xg": [0.30, 0.17, 0.63], "shot_distance": [8, 12, 6],
        "player": ["A", "B", "C"]})
    ctx = default_ctx(vt, spec, aux={"df_all": df}, show_xg_values=show_xg_values)
    return df, ctx


def test_app_panel_shots_xg_values_toggle():
    import app
    df, ctx_on = _app_ctx(app, True)
    _, ctx_off = _app_ctx(app, False)
    fig = plt.figure(); ax = fig.add_subplot(111)
    app.panel_shots(ax, df, ctx_on)
    texts_on = [t.get_text() for t in ax.texts]
    plt.close(fig)
    fig2 = plt.figure(); ax2 = fig2.add_subplot(111)
    app.panel_shots(ax2, df, ctx_off)
    texts_off = [t.get_text() for t in ax2.texts]
    plt.close(fig2)
    assert "0.63" in texts_on and "0.30" in texts_on          # xG printed per shot
    assert "0.63" not in texts_off                            # off by default
    # data untouched
    assert list(df["internal_xg"]) == [0.30, 0.17, 0.63]
