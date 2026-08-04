"""Comparison charts (src/fap/visuals/charts/comparisons.py).

Proves the four new non-pitch charts are auto-discovered/registered, render
end-to-end through the framework on the real sample dataset, and never raise on
empty or degenerate data (the house rule for every chart artist).
"""
import pathlib

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
import pytest

from fap.core.types import RenderContext
from fap.openplay.transforms import add_derived_columns
from fap.pipeline import schema
from fap.themes import ThemeManager
from fap.visuals import StyleTokens, layer_registry
from fap.visuals.base import load_builtin_visuals, visual_registry
from fap.visuals.charts import comparisons as CMP
from fap.visuals.context import LayerContext
from fap.visuals.layers.base import load_builtin_layers
from fap.visuals.pitch import get_spec

load_builtin_layers()
load_builtin_visuals()
THEME = ThemeManager("assets/themes").get("opta_light")
_SAMPLE = pathlib.Path("data/sample_open_play_data.csv")

NEW_CHARTS = ("player_percentile_radar", "player_comparison_bars",
              "team_radar", "rolling_form_trend")
ARTISTS = (CMP._player_percentile_radar, CMP._player_comparison_bars,
           CMP._team_radar, CMP._rolling_form)


def _sample_frame() -> pd.DataFrame:
    raw = pd.read_csv(_SAMPLE)
    return add_derived_columns(schema.coerce_schema(raw))


def _empty_frame() -> pd.DataFrame:
    return schema.coerce_schema(pd.DataFrame({"event_type": [], "x": [], "y": []}))


def _lctx(df: pd.DataFrame, controls=None) -> LayerContext:
    _, ax = plt.subplots()
    return LayerContext(fig=ax.figure, ax=ax, df=df, theme=THEME,
                        tokens=StyleTokens.from_theme(THEME), controls=controls or {},
                        pitch_spec=get_spec("uefa"))


# ---------------------------------------------------------------- registration
def test_new_charts_are_discovered_and_registered():
    ids = set(visual_registry.ids())
    assert set(NEW_CHARTS) <= ids
    for cid in NEW_CHARTS:
        assert visual_registry.get(cid).info.category == "Comparison"


# ---------------------------------------------------------------- end-to-end render
@pytest.mark.parametrize("chart_id", NEW_CHARTS)
def test_chart_renders_on_sample_data(chart_id):
    viz = visual_registry.create(chart_id)
    fig = viz.render(RenderContext(df=_sample_frame(), theme=THEME,
                                   controls={"title": chart_id}))
    assert fig.axes                                   # produced a drawable figure
    plt.close(fig)


# ---------------------------------------------------------------- artist robustness
@pytest.mark.parametrize("artist", ARTISTS)
def test_artist_runs_on_sample_data(artist):
    ctx = _lctx(_sample_frame())
    artist(ctx.ax, ctx)                               # must not raise
    plt.close(ctx.fig)


@pytest.mark.parametrize("artist", ARTISTS)
def test_artist_does_not_crash_on_empty_dataframe(artist):
    ctx = _lctx(_empty_frame())
    artist(ctx.ax, ctx)                               # graceful early return, no raise
    plt.close(ctx.fig)


# ---------------------------------------------------------------- controls / branches
def test_rolling_form_honours_metric_and_window_controls():
    ctx = _lctx(_sample_frame(),
                controls={"form_metric": "Progressive Passes", "form_window": 2})
    CMP._rolling_form(ctx.ax, ctx)
    assert ctx.ax.get_ylabel() == "Progressive Passes"
    plt.close(ctx.fig)


def test_percentile_radar_falls_back_when_too_few_players():
    # a single player -> percentiles impossible; must still draw, not crash
    frame = _sample_frame()
    one = frame[frame["player"] == frame["player"][frame["player"].str.strip().ne("")].iloc[0]]
    ctx = _lctx(one)
    CMP._player_percentile_radar(ctx.ax, ctx)
    assert ctx.ax.patches                             # radar rings/polygon drawn
    plt.close(ctx.fig)
