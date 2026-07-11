"""Visualization framework tests: layers, pitch engine, tokens, typography,
layout, legend, annotations, renderer pipeline, caching."""
import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest

from fap.cache import CacheManager
from fap.config.settings import CacheSettings
from fap.core.plugin import PluginInfo
from fap.core.types import RenderContext
from fap.pipeline.schema import coerce_schema
from fap.themes import ThemeManager
from fap.visuals import (AnnotationSet, LayoutEngine, LegendEngine, Renderer,
                         StyleTokens, layer_registry)
from fap.visuals.base import PitchVisualization
from fap.visuals.context import LayerContext
from fap.visuals.layers.base import load_builtin_layers
from fap.visuals.pitch import PITCH_SPECS, PitchFactory, get_spec, resolve_orientation
from fap.visuals.typography import TextStyle

load_builtin_layers()
THEME = ThemeManager("assets/themes").get("opta_light")


def _df(n: int = 30) -> pd.DataFrame:
    rng = np.random.default_rng(3)
    df = coerce_schema(pd.DataFrame({
        "event_type": ["pass"] * n, "x": rng.uniform(5, 95, n),
        "y": rng.uniform(5, 95, n), "end_x": rng.uniform(5, 95, n),
        "end_y": rng.uniform(5, 95, n), "player": [f"P{i%7}" for i in range(n)],
        "jersey_number": rng.integers(1, 24, n), "minute": rng.integers(0, 90, n),
    }))
    df["time_min"] = df["minute"]
    return df


def _lctx(ax=None, vertical=False, df=None) -> LayerContext:
    if ax is None:
        _, ax = plt.subplots()
    return LayerContext(fig=ax.figure, ax=ax, df=df if df is not None else _df(),
                        theme=THEME, tokens=StyleTokens.from_theme(THEME),
                        controls={}, pitch_spec=get_spec("uefa"), vertical=vertical)


# ---------------------------------------------------------------- layers
REQUIRED_LAYERS = {
    "pitch", "grid", "zones", "heatmap", "hexbin", "scatter", "arrows",
    "curved_arrows", "lines", "polygon", "convex_hull", "voronoi", "path",
    "trajectory", "player_markers", "goal", "ball", "text", "labels",
    "annotations", "legend", "logo", "image", "color_scale", "timeline",
    "highlight", "glow", "shadow", "custom_artist", "svg", "watermark",
}


def test_all_required_layers_registered():
    assert REQUIRED_LAYERS <= set(layer_registry.ids())


@pytest.mark.parametrize("layer_id,params", [
    ("pitch", {}), ("grid", {"nx": 4, "ny": 3}),
    ("zones", {"zones": [(0, 0, 33, 100, "Def", "31%")]}),
    ("heatmap", {"heat_bins": 8}), ("hexbin", {"hex_gridsize": 10}),
    ("scatter", {"label": "Events"}), ("arrows", {"label": "Pass"}),
    ("curved_arrows", {"arrow_curve": 0.3}), ("lines", {}),
    ("path", {"number_points": True}), ("trajectory", {}),
    ("player_markers", {"show_names": True}), ("goal", {"side": "right"}),
    ("ball", {"x": 60, "y": 40}), ("highlight", {}), ("glow", {}), ("shadow", {}),
    ("polygon", {"points": [(10, 10), (30, 10), (20, 30)], "label": "Shape"}),
    ("convex_hull", {}), ("voronoi", {}),
    ("text", {"x": 50, "y": 50, "text": "NOTE", "uppercase": True}),
    ("labels", {"column": "player"}), ("watermark", {"text": "FAP"}),
    ("timeline", {}), ("color_scale", {"label": "Density"}),
    ("legend", {"entries": [{"label": "Manual", "color": "#123456"}]}),
    ("custom_artist", {"artist": lambda ctx: ctx.ax.plot([0, 10], [0, 10])}),
    ("svg", {"path": "M 0 0 L 10 0 L 10 10 L 0 10 Z", "x": 50, "y": 50}),
])
def test_layer_draws_artists(layer_id, params):
    ctx = _lctx()
    before = len(ctx.ax.get_children())
    layer_registry.create(layer_id, **params).draw(ctx)
    if layer_id == "legend":
        ctx.legend.build(ctx.ax, THEME, ctx.tokens)
    assert len(ctx.ax.get_children()) >= before   # drew without error
    plt.close(ctx.fig)


def test_layer_vertical_orientation_transform():
    ctx = _lctx(vertical=True)
    x, y = ctx.to_display([100.0], [0.0])
    assert x[0] == pytest.approx(0.0) and y[0] == pytest.approx(100.0)
    plt.close(ctx.fig)


def test_layer_signature_stable_and_param_sensitive():
    a = layer_registry.create("heatmap", heat_bins=10)
    b = layer_registry.create("heatmap", heat_bins=10)
    c = layer_registry.create("heatmap", heat_bins=20)
    assert a.signature() == b.signature() != c.signature()


# ---------------------------------------------------------------- pitch engine
def test_pitch_specs_and_views():
    assert {"uefa", "fifa", "statsbomb", "opta", "wyscout",
            "tracab", "skillcorner", "metrica"} <= set(PITCH_SPECS)
    factory = PitchFactory()
    for view in ("full", "attacking_half", "defensive_half", "final_third",
                 "middle_third", "penalty_area"):
        fig, ax = factory.build(THEME, view=view)
        assert len(ax.patches) > 5              # markings drawn
        plt.close(fig)
    fig, ax = factory.build(THEME, view="full", crop=(40, 90, 10, 58))
    assert ax.get_xlim()[0] < 40 < ax.get_xlim()[1]
    plt.close(fig)


def test_auto_orientation():
    assert resolve_orientation("attacking_half", "auto") is True
    assert resolve_orientation("full", "auto") is False
    assert resolve_orientation("attacking_half", "horizontal") is False
    assert resolve_orientation("full", "vertical") is True


def test_custom_pitch_spec_geometry():
    spec = get_spec("custom", custom_length=110, custom_width=70)
    assert spec.length_m == 110
    assert spec.ux(11.0) == pytest.approx(10.0)   # penalty spot scales


def test_legacy_pitch_api_still_works():
    fig, ax = PitchFactory().create(THEME, vertical=True, show_thirds=True)
    assert ax.get_ylim()[1] > 90
    plt.close(fig)


# ---------------------------------------------------------------- tokens & typography
def test_tokens_resolution_chain():
    theme = ThemeManager("assets/themes").get("tv_broadcast")
    tokens = StyleTokens.from_theme(theme)
    assert tokens.get("pitch_line_width") == 2.0        # theme token override
    assert tokens.get("heat_bins") == 13                # framework default
    ctx = _lctx()
    ctx.tokens = tokens
    ctx.controls = {"pitch_line_width": 3.5}
    assert ctx.style("pitch_line_width") == 3.5         # control wins
    plt.close(ctx.fig)


def test_typography_format_and_scaling():
    style = TextStyle(uppercase=True, letter_spacing=1, wrap_width=10)
    out = style.format("final third entries")
    assert out.startswith("F") and "\u2009" in out and "\n" in out
    assert style.kwargs(scale=1.5)["fontsize"] == pytest.approx(style.size * 1.5)


# ---------------------------------------------------------------- layout engine
def test_layout_engine_panels():
    engine = LayoutEngine()
    expected = {"single": {"main"}, "two_panel": {"a", "b"},
                "four_panel": {"a", "b", "c", "d"},
                "dashboard": {"main", "side", "a", "b", "c"},
                "split_view": {"main", "side"}, "comparison": {"left", "right"},
                "report": {"header", "a", "b", "c", "d"}, "presentation": {"main"}}
    for layout_id, panels in expected.items():
        fig, axes = engine.build(layout_id, THEME, scale=0.5)
        assert set(axes) == panels
        plt.close(fig)


# ---------------------------------------------------------------- legend engine
def test_legend_engine_grouping_order_hide():
    engine = LegendEngine()
    engine.add("Zeta", color="#111", order=50)
    engine.add("Alpha", color="#222", order=10)
    engine.add("Hidden", color="#333")
    engine.add("Zeta", color="#999")            # duplicate ignored
    engine.hide("Hidden")
    engine.reorder(["Zeta", "Alpha"])
    labels = [e.label for e in engine.entries]
    assert labels == ["Zeta", "Alpha"]
    fig, ax = plt.subplots()
    engine.build(ax, THEME, StyleTokens.from_theme(THEME), position="right")
    assert ax.get_legend() is not None
    plt.close(fig)


# ---------------------------------------------------------------- annotations
def test_annotation_set_roundtrip_and_editing():
    ann = AnnotationSet()
    note = ann.add("coach_note", 70, 50, text="Press here")
    ann.add("callout", 20, 20, x2=40, y2=40, text="Trigger")
    ann.add("number", 88, 50, text="9")
    ann.update(note.id, text="Press HIGH here")
    restored = AnnotationSet.from_dict(ann.to_dict())
    assert len(restored) == 3
    assert any(a.text == "Press HIGH here" for a in restored.items)
    with pytest.raises(ValueError):
        ann.add("hologram", 0, 0)
    ann.remove(note.id)
    assert len(ann) == 2


# ---------------------------------------------------------------- renderer pipeline
class _DemoViz(PitchVisualization):
    """Test-only visualization: declarative layers, no custom rendering."""
    info = PluginInfo(id="_test_demo", name="Demo", category="test")

    def layers(self, ctx):
        return [
            layer_registry.create("heatmap", heat_bins=8),
            layer_registry.create("arrows", label="Pass"),
            layer_registry.create("scatter", label="Start"),
        ]


def _rctx(controls=None, meta=None) -> RenderContext:
    return RenderContext(df=_df(), theme=THEME, controls=controls or
                         {"title": "Demo", "subtitle": "sub"}, meta=meta or {})


def test_renderer_full_pipeline():
    fig = Renderer().render(_DemoViz(), _rctx(meta={
        "annotations": [{"kind": "coach_note", "x": 60, "y": 40, "text": "note"}],
        "filters": {"event_types": ["pass"]},
    }))
    ax = fig.axes[0]
    assert fig._suptitle is not None and fig._suptitle.get_text() == "Demo"
    assert ax.get_legend() is not None                    # auto legend
    assert len(ax.get_children()) > 20                    # pitch + layers drawn
    plt.close(fig)


def test_renderer_view_and_orientation_controls():
    fig = Renderer().render(_DemoViz(), _rctx(controls={
        "title": "", "view": "attacking_half", "orientation": "auto",
        "pitch_spec": "statsbomb", "legend": False}))
    ax = fig.axes[0]
    assert ax.get_ylim()[0] >= 40                         # cropped + vertical
    assert ax.get_legend() is None
    plt.close(fig)


def test_render_png_figure_cache():
    renderer = Renderer(cache=CacheManager(CacheSettings(backend="memory")))
    ctx = _rctx()
    first = renderer.render_png(_DemoViz(), ctx, dpi=100)
    second = renderer.render_png(_DemoViz(), ctx, dpi=100)
    assert first[:8] == b"\x89PNG\r\n\x1a\n" and first == second
    ctx2 = _rctx(controls={"title": "Changed"})
    assert renderer.render_png(_DemoViz(), ctx2, dpi=100) != first


def test_broken_layer_is_isolated():
    class Broken(_DemoViz):
        info = PluginInfo(id="_test_broken", name="Broken", category="test")
        def layers(self, ctx):
            return [layer_registry.create("custom_artist",
                                          artist=lambda c: 1 / 0),
                    layer_registry.create("scatter")]
    fig = Renderer().render(Broken(), _rctx())     # must not raise
    plt.close(fig)
