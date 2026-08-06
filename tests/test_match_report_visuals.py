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


def _one_team(frame):
    t = frame["team"].astype(str).str.strip().value_counts().index[0]
    return frame[frame["team"].astype(str).str.strip() == t]


def test_pass_network_scales_nodes_by_volume_and_edges_by_strength():
    """The passing network must size nodes by pass count and vary edge thickness by
    combination strength (the requested Athletic-style network), not draw them uniform."""
    from matplotlib.collections import PathCollection
    from matplotlib.lines import Line2D
    single = _one_team(_sample_frame())
    fig = visual_registry.create("pass_network").render(
        RenderContext(df=single, theme=THEME, controls={"title": "net"}))
    ax = fig.axes[0]
    # node marker sizes come from the scatter PathCollection sizes -> must vary
    node_sizes = set()
    for coll in ax.collections:
        if isinstance(coll, PathCollection):
            node_sizes.update(round(float(s), 1) for s in coll.get_sizes())
    assert len(node_sizes) >= 2, "node sizes should scale with pass volume"
    # edge line widths -> must vary with combination count
    widths = {round(ln.get_linewidth(), 2) for ln in ax.lines}
    assert len(widths) >= 2, "edge widths should scale with combination strength"
    plt.close(fig)


def test_average_positions_two_teams_are_colour_coded_with_legend():
    frame = _sample_frame()
    assert frame["team"].astype(str).str.strip().replace("", pd.NA).dropna().nunique() >= 2
    fig = visual_registry.create("average_positions").render(
        RenderContext(df=frame, theme=THEME, controls={"title": "avg", "legend": True}))
    ax = fig.axes[0]
    assert ax.get_legend() is not None
    plt.close(fig)
