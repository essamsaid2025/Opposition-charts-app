"""Attack-direction arrow on all pitch charts + the Left/Right channel-label fix.

Canonical y is 0 = RIGHT touchline, 100 = LEFT touchline (fap.pipeline.coordinates),
so a zone at y<33.33 is the RIGHT channel — several charts labelled it "Left". These
tests pin the corrected labels and the new attack arrow (left->right horizontal,
bottom->top vertical) across fap.visuals; a smoke test covers the app.py engine arrow.
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
from fap.visuals.maps import _builders as B
from fap.visuals.renderer import Renderer
from fap.themes.theme import ThemeManager

load_builtin_visuals()
_THEME = ThemeManager("assets/themes").get("opta_dark")


def _pass_df():
    # spread passes across the width so every channel has events; big progression so
    # they count as progressive (for the progressive-lane chart)
    ys = [5, 10, 20, 40, 50, 60, 80, 90, 95]
    return pd.DataFrame({"event_type": ["pass"] * len(ys),
                         "x": [10] * len(ys), "y": ys,
                         "end_x": [80] * len(ys), "end_y": ys,
                         "outcome": ["successful"] * len(ys), "player": ["P"] * len(ys)})


def _lctx(df):
    from fap.visuals.context import LayerContext
    from fap.visuals.legend import LegendEngine
    from fap.visuals.pitch import get_spec
    from fap.visuals.tokens import StyleTokens
    from matplotlib.figure import Figure
    fig = Figure(); ax = fig.add_subplot(111)
    return LayerContext(fig=fig, ax=ax, df=df, theme=_THEME,
                        tokens=StyleTokens.from_theme(_THEME), controls={},
                        pitch_spec=get_spec("uefa"), legend=LegendEngine())


def _zones_of(viz_id, df):
    viz = visual_registry.create(viz_id)
    layers = viz.layers(_lctx(df))
    z = next(l for l in layers if l.info.id == "zones")
    return z.params["zones"]


# ================================================================ label correctness
# canonical y: 0 = RIGHT touchline, 100 = LEFT touchline. So the y<33 lane is RIGHT.
def test_passing_lanes_channel_labels_corrected():
    zones = _zones_of("passing_lanes", _pass_df())          # (x0,y0,x1,y1,label,pct)
    low = next(z for z in zones if z[1] == 0.0)
    high = next(z for z in zones if abs(z[1] - 66.67) < 0.1)
    assert low[4] == "Right" and high[4] == "Left"


def test_progressive_lane_split_labels_corrected():
    zones = _zones_of("progressive_pass_lanes", _pass_df())  # label = "<Side>: n (x%)"
    low = next(z for z in zones if z[1] == 0.0)
    high = next(z for z in zones if abs(z[1] - 66.67) < 0.1)
    assert low[4].startswith("Right") and high[4].startswith("Left")


# ================================================================ attack arrow
def test_attack_arrow_present_on_pitch_map_by_default():
    cls = B.scatter_map("ad_shot", "Shot Map", lambda df, c: df, category="Shooting")
    fig = Renderer().render(cls(), RenderContext(df=_pass_df(), theme=_THEME, controls={}))
    assert "ATTACK" in [t.get_text() for t in fig.axes[0].texts]
    plt.close(fig)


def test_attack_arrow_can_be_disabled():
    cls = B.scatter_map("ad_shot2", "Shot Map", lambda df, c: df, category="Shooting")
    fig = Renderer().render(cls(), RenderContext(df=_pass_df(), theme=_THEME,
                                                 controls={"attack_direction": False}))
    assert "ATTACK" not in [t.get_text() for t in fig.axes[0].texts]
    plt.close(fig)


def test_attack_arrow_points_right_horizontal_up_vertical():
    from matplotlib.text import Annotation

    from fap.visuals.layers.pitch_layers import AttackArrowLayer

    def _delta(vertical):
        ctx = _lctx(_pass_df()); ctx.vertical = vertical
        AttackArrowLayer().draw(ctx)
        ann = next(a for a in ctx.ax.texts if isinstance(a, Annotation))
        (ex, ey), (sx, sy) = ann.xy, ann.xyann       # arrow head (xy) vs tail (xytext)
        assert any(t.get_text() == "ATTACK" for t in ctx.ax.texts)
        return ex - sx, ey - sy

    hdx, hdy = _delta(False)
    vdx, vdy = _delta(True)
    assert hdx > abs(hdy) and hdx > 0                # horizontal: points right (+x)
    assert vdy > abs(vdx) and vdy > 0                # vertical: points up (+y)


# ================================================================ app.py engine smoke
def test_app_engine_attack_arrow_helper():
    import app
    fig = plt.figure(); ax = fig.add_subplot(111)
    vt = app.VIZ_THEMES["Opta Analyst"]
    app.draw_attack_arrow(ax, app.PitchSpec(), vt, -3, 103, -3, app.W + 3)
    assert "ATTACK" in [t.get_text() for t in ax.texts]
    plt.close(fig)


def test_engine_default_omits_arrow_but_accepts_override():
    # the engine default stays byte-identical (no arrow key); the UIs opt in explicitly
    from fap.openplay.engine import default_ctx
    import app
    base = default_ctx(app.VIZ_THEMES["Opta Analyst"], app.PitchSpec())
    assert "attack_arrow" not in base
    over = default_ctx(app.VIZ_THEMES["Opta Analyst"], app.PitchSpec(), attack_arrow=True)
    assert over["attack_arrow"] is True


def test_new_pitch_fig_honours_attack_arrow_flag():
    import app
    vt = app.VIZ_THEMES["Opta Analyst"]
    on = app.new_pitch_fig(vt, app.PitchSpec(), {"attack_arrow": True})[1]
    off = app.new_pitch_fig(vt, app.PitchSpec(), {})[1]      # default off (baseline-safe)
    assert "ATTACK" in [t.get_text() for t in on.texts]
    assert "ATTACK" not in [t.get_text() for t in off.texts]
    plt.close("all")
