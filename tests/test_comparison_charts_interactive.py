"""Optional interactive (Plotly) comparison charts
(src/fap/visuals/charts/comparisons_interactive.py).

Proves the four Plotly builders produce valid figures on the sample data, never
crash on empty data, reuse the EXACT computation helpers from comparisons.py (so
the numbers are identical to the static charts), and are completely side-effect
free - they register nothing and change no existing behavior.
"""
import pathlib

import matplotlib
matplotlib.use("Agg")

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pytest

from fap.core.types import RenderContext
from fap.openplay.transforms import add_derived_columns
from fap.pipeline import schema
from fap.themes import ThemeManager
from fap.visuals.base import load_builtin_visuals, visual_registry
from fap.visuals.charts import comparisons as CMP
from fap.visuals.charts import comparisons_interactive as CI

load_builtin_visuals()
THEME = ThemeManager("assets/themes").get("opta_light")
_SAMPLE = pathlib.Path("data/sample_open_play_data.csv")

CHART_IDS = ("player_percentile_radar", "player_comparison_bars",
             "team_radar", "rolling_form_trend")


def _sample_frame() -> pd.DataFrame:
    return add_derived_columns(schema.coerce_schema(pd.read_csv(_SAMPLE)))


def _empty_frame() -> pd.DataFrame:
    return schema.coerce_schema(pd.DataFrame({"event_type": [], "x": [], "y": []}))


def _ctx(df, controls=None) -> RenderContext:
    return RenderContext(df=df, theme=THEME, controls=controls or {})


# ---------------------------------------------------------------- valid figures
@pytest.mark.parametrize("vid", CHART_IDS)
def test_builder_returns_valid_plotly_figure_on_sample(vid):
    fig = CI.build(vid, _ctx(_sample_frame()))
    assert isinstance(fig, go.Figure)
    assert len(fig.data) >= 1                              # sample data -> real traces
    assert fig.layout.paper_bgcolor is not None            # themed, not default Plotly look


@pytest.mark.parametrize("vid", CHART_IDS)
def test_builder_does_not_crash_on_empty_dataframe(vid):
    fig = CI.build(vid, _ctx(_empty_frame()))
    assert isinstance(fig, go.Figure)                      # graceful placeholder, no raise


def test_builders_cover_exactly_the_four_comparison_charts():
    assert set(CI.BUILDERS) == set(CHART_IDS)
    assert set(CI.INTERACTIVE_CHART_IDS) == set(CHART_IDS)
    assert CI.build("shot_map", _ctx(_sample_frame())) is None   # not offered for other viz


# ---------------------------------------------------------------- edge cases mirror static
def test_percentile_radar_too_few_players_still_renders():
    frame = _sample_frame()
    one = frame[frame["player"] == frame["player"][frame["player"].str.strip().ne("")].iloc[0]]
    fig = CI.build_player_percentile_radar(_ctx(one))      # peer-scaled fallback, no crash
    assert isinstance(fig, go.Figure) and len(fig.data) == 1


def test_rolling_form_single_match_uses_sequences():
    frame = _sample_frame()
    fig = CI.build_rolling_form_trend(_ctx(frame, {"form_metric": "Progressive Passes"}))
    assert isinstance(fig, go.Figure) and len(fig.data) >= 1


# ---------------------------------------------------------------- identical numbers
def test_interactive_reuses_the_exact_static_helpers():
    # not copies - the SAME objects, so computation cannot drift from the static charts
    assert CI._population_table is CMP._population_table
    assert CI._radial_values is CMP._radial_values
    assert CI._minutes_span is CMP._minutes_span
    assert CI._palette is CMP._palette
    assert CI.PLAYER_RADAR_METRICS is CMP.PLAYER_RADAR_METRICS
    assert CI.TEAM_RADAR_METRICS is CMP.TEAM_RADAR_METRICS
    assert CI.COMPARISON_METRICS is CMP.COMPARISON_METRICS
    assert CI.FORM_METRICS is CMP.FORM_METRICS


def test_comparison_bars_numbers_match_reused_helpers():
    """The per-90 values encoded in the Plotly figure equal what the reused helpers
    compute - identical numbers, only the rendering technology differs."""
    frame = _sample_frame()
    fig = CI.build_player_comparison_bars(_ctx(frame))
    table = CMP._population_table(frame, "player", CMP.COMPARISON_METRICS, min_events=3)
    events = table.pop("_events")
    players = events.astype(float).sort_values(ascending=False).index[:3]
    labels = [label for label, _ in CMP.COMPARISON_METRICS]
    expected = {}
    for name in players:
        mins = CMP._minutes_span(frame[frame["player"] == name])
        factor = 90.0 / mins if mins >= 20 else 1.0
        expected[str(name)] = table.loc[name, labels].to_numpy(dtype=float) * factor
    assert {tr.name for tr in fig.data} == set(expected)
    for tr in fig.data:
        np.testing.assert_allclose(np.array(tr.customdata, dtype=float),
                                   expected[tr.name], rtol=1e-9)


# ---------------------------------------------------------------- side-effect free
def test_interactive_module_registers_no_visualizations():
    # importing the interactive module must not add any plugin; Comparison stays the 4
    comparison = [i for i in visual_registry.ids()
                  if visual_registry.get(i).info.category == "Comparison"]
    assert set(comparison) == set(CHART_IDS)
