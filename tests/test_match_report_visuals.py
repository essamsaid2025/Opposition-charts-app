"""New match-report visuals: Player Voronoi, Match Momentum (xT), Shot Profile,
Pass End Zone.

Proves they are auto-discovered/registered (so they surface in Open Play Studio
via the registry bridge AND in the Players/Scouting workspace, both of which read
``visual_registry``), render end-to-end on the sample dataset, and never raise on
an empty dataframe.
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
from fap.visuals.base import load_builtin_visuals, visual_registry
from fap.visuals.layers.base import load_builtin_layers

load_builtin_layers()
load_builtin_visuals()
THEME = ThemeManager("assets/themes").get("opta_light")
_SAMPLE = pathlib.Path("data/sample_open_play_data.csv")

# id -> expected category
NEW_VISUALS = {
    "player_voronoi": "Team",
    "momentum_xt": "Team",
    "shot_profile": "Attacking",
    "pass_end_zones": "Passing",
    "chance_creating_zones": "Attacking",
    "progressive_pass_lanes": "Passing",
    "match_stats_table": "Team",
}


def _sample_frame() -> pd.DataFrame:
    return add_derived_columns(schema.coerce_schema(pd.read_csv(_SAMPLE)))


def _empty_frame() -> pd.DataFrame:
    return schema.coerce_schema(pd.DataFrame({"event_type": [], "x": [], "y": []}))


def test_new_visuals_registered_with_categories():
    ids = set(visual_registry.ids())
    assert set(NEW_VISUALS) <= ids
    for vid, cat in NEW_VISUALS.items():
        assert visual_registry.get(vid).info.category == cat


@pytest.mark.parametrize("vid", list(NEW_VISUALS))
def test_new_visual_renders_on_sample_data(vid):
    viz = visual_registry.create(vid)
    fig = viz.render(RenderContext(df=_sample_frame(), theme=THEME, controls={"title": vid}))
    assert fig.axes
    plt.close(fig)


@pytest.mark.parametrize("vid", list(NEW_VISUALS))
def test_new_visual_does_not_crash_on_empty_dataframe(vid):
    viz = visual_registry.create(vid)
    fig = viz.render(RenderContext(df=_empty_frame(), theme=THEME, controls={}))
    assert fig is not None
    plt.close(fig)


def test_player_voronoi_is_distinct_from_team_voronoi():
    # both exist; the new one is the per-player coloured variant
    assert {"player_voronoi", "team_voronoi"} <= set(visual_registry.ids())
    assert visual_registry.get("player_voronoi").info.name != \
        visual_registry.get("team_voronoi").info.name


def test_player_voronoi_colours_two_teams_distinctly():
    """Two teams -> the pitch-control cells and dots must use two different team
    colours (not one colour for everyone), and a team legend is offered."""
    frame = _sample_frame()
    assert frame["team"].astype(str).str.strip().replace("", pd.NA).dropna().nunique() >= 2
    viz = visual_registry.create("player_voronoi")
    fig = viz.render(RenderContext(df=frame, theme=THEME,
                                   controls={"title": "PV", "legend": True}))
    ax = fig.axes[0]
    # voronoi cells are matplotlib Polygons; collect their face colours
    from matplotlib.patches import Polygon as MplPolygon
    fills = {tuple(round(v, 3) for v in p.get_facecolor())
             for p in ax.patches if isinstance(p, MplPolygon)}
    assert len(fills) >= 2, "two-team Voronoi should use more than one cell colour"
    assert ax.get_legend() is not None                    # team legend rendered
    plt.close(fig)


def test_player_voronoi_single_team_and_labels_render():
    frame = _sample_frame()
    one_team = sorted(frame["team"].astype(str).str.strip().unique())[-1]
    single = frame[frame["team"].astype(str).str.strip() == one_team]
    viz = visual_registry.create("player_voronoi")
    fig = viz.render(RenderContext(df=single, theme=THEME,
                                   controls={"show_labels": True}))   # opt-in surnames
    assert fig.axes
    plt.close(fig)
