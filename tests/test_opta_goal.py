"""Canonical Opta-style goal renderer (fap.visuals.goal) + integration.

Covers the ONE reusable goal geometry, the shot/save/goal markers, and that every
goal-based map (Goal-Mouth, Save Zones, Penalty placement/zones, GK reach) draws
that same geometry — while pitch-based maps stay pitch-based.
"""
import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest
from matplotlib.colors import to_rgba
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, Rectangle

from fap.core.types import RenderContext
from fap.themes import ThemeManager
from fap.visuals import Renderer, visual_registry
from fap.visuals import goal as G
from fap.visuals.base import load_builtin_visuals

import fap.visuals.setpieces.library  # noqa: F401 - registers the penalty/goal viz

load_builtin_visuals()
THEMES = ThemeManager("assets/themes")
THEME = THEMES.get("opta_light")


def _ax():
    fig, ax = plt.subplots()
    return fig, ax


def _rects(ax):
    return [p for p in ax.patches if isinstance(p, Rectangle)]


# ------------------------------------------------------------------ geometry
def test_goal_has_two_posts_and_a_crossbar():
    fig, ax = _ax()
    G.draw_goal(ax, THEME)
    rects = _rects(ax)
    assert len(rects) == 3                                  # exactly posts + crossbar, no net
    left = [r for r in rects if r.get_x() < 0 and r.get_height() > G.GOAL_HEIGHT]
    right = [r for r in rects if r.get_x() >= G.GOAL_WIDTH and r.get_height() > G.GOAL_HEIGHT]
    crossbar = [r for r in rects if r.get_y() >= G.GOAL_HEIGHT - 0.01
                and r.get_width() > G.GOAL_WIDTH]
    assert left and right and crossbar, "need left post, right post, crossbar"
    # identical thickness: both posts and the crossbar share the same thickness
    assert abs(left[0].get_width() - right[0].get_width()) < 1e-9
    assert abs(left[0].get_width() - crossbar[0].get_height()) < 1e-9
    plt.close(fig)


def test_ground_line_exists_and_extends_beyond_posts():
    fig, ax = _ax()
    G.draw_goal(ax, THEME)
    ground = [ln for ln in ax.lines if isinstance(ln, Line2D)
              and np.allclose(ln.get_ydata(), 0.0)]
    assert ground, "a ground line at y=0 must exist"
    xd = ground[0].get_xdata()
    assert min(xd) < -G.POST and max(xd) > G.GOAL_WIDTH + G.POST
    plt.close(fig)


def test_bottom_is_open():
    """No rectangle/line closes the interior bottom between the posts (open goal)."""
    fig, ax = _ax()
    G.draw_goal(ax, THEME)
    # no filled rectangle sits along the interior bottom
    for r in _rects(ax):
        interior_bottom = (r.get_y() <= 0.01 and r.get_height() < G.GOAL_HEIGHT / 2
                           and 0 < r.get_x() < G.GOAL_WIDTH)
        assert not interior_bottom
    # the only y=0 line is the ground line, and it extends OUTSIDE the posts
    for ln in ax.lines:
        if np.allclose(ln.get_ydata(), 0.0):
            assert min(ln.get_xdata()) < 0
    plt.close(fig)


def test_equal_aspect_keeps_circles_circular():
    fig, ax = _ax()
    G.draw_goal(ax, THEME)
    assert ax.get_aspect() == 1.0
    plt.close(fig)


def test_geometry_scales_with_size_but_stays_centred():
    """Bigger explicit dimensions keep the goal centred (symmetric x-limits)."""
    fig, ax = _ax()
    G.draw_goal(ax, THEME, width=200.0, height=80.0)
    x0, x1 = ax.get_xlim()
    mid = (x0 + x1) / 2
    assert abs(mid - 100.0) < 1e-6                          # centred on width/2
    rects = _rects(ax)
    assert any(r.get_x() >= 200.0 for r in rects)           # right post moved out to width
    plt.close(fig)


# ------------------------------------------------------------------ markers
def test_radius_responds_to_the_size_metric():
    r = G.scale_radii([0.1, 0.5, 0.9], rmin=2.0, rmax=5.0)
    assert r[0] == pytest.approx(2.0) and r[2] == pytest.approx(5.0)
    assert r[0] < r[1] < r[2]                               # monotonic in the metric


def test_no_size_metric_collapses_to_midpoint():
    r = G.scale_radii([None, None], rmin=2.0, rmax=6.0)
    assert list(r) == [4.0, 4.0]


def test_save_marker_is_hollow_and_goal_marker_is_filled():
    fig, ax = _ax()
    G.draw_shots(ax, THEME, xs=[20.0, 80.0], ys=[20.0, 20.0], is_goal=[False, True])
    circles = [p for p in ax.patches if isinstance(p, Circle)]
    assert len(circles) == 2
    save, goal = circles
    bg = to_rgba(THEME.colors["bg"])
    accent = to_rgba(THEME.colors["accent"])
    danger = to_rgba(THEME.colors["danger"])
    # save: hollow -> face is the editorial background, outline is the accent (purple)
    assert to_rgba(save.get_facecolor())[:3] == bg[:3]
    assert to_rgba(save.get_edgecolor())[:3] == accent[:3]
    assert save.get_linewidth() >= 2.0                      # relatively thick outline
    # goal: filled red
    assert to_rgba(goal.get_facecolor())[:3] == danger[:3]
    plt.close(fig)


def test_difficulty_legend_draws_growing_circles():
    fig, ax = _ax()
    G.draw_goal(ax, THEME)
    before = len([p for p in ax.patches if isinstance(p, Circle)])
    G.draw_difficulty_legend(ax, THEME, radii=(1.0, 2.0, 3.0, 4.0))
    circles = [p for p in ax.patches if isinstance(p, Circle)]
    assert len(circles) - before == 4
    radii = sorted(c.get_radius() for c in circles)
    assert radii == [1.0, 2.0, 3.0, 4.0]                    # progressively larger
    plt.close(fig)


# ------------------------------------------------------------------ integration
def _render(viz_id, df):
    viz = visual_registry.create(viz_id)
    fig = Renderer().render(viz, RenderContext(
        df=df, theme=THEME, controls={"title": viz_id}, meta={}))
    return fig


def _goal_rects(fig):
    ax = fig.axes[0]
    return [p for p in ax.patches if isinstance(p, Rectangle)]


GOAL_BASED = ["goal_mouth_map", "save_zones", "sp_pen_placement",
              "sp_pen_success_zones", "sp_gk_reach"]


@pytest.mark.parametrize("viz_id", GOAL_BASED)
def test_goal_based_maps_use_the_canonical_frame(viz_id):
    # a frame carrying both event-shot columns and penalty grid columns
    n = 40
    rng = np.random.default_rng(3)
    df = pd.DataFrame({
        "event_type": ["shot"] * n,
        "x": rng.uniform(80, 99, n), "y": rng.uniform(30, 70, n),
        "end_x": 100.0, "end_y": rng.uniform(44, 56, n),
        "shot_result": rng.choice(["Goal", "Saved", "Off Target"], n),
        "shot_xg": rng.uniform(0.03, 0.7, n),
        "gx": rng.integers(0, 3, n), "gy": rng.integers(0, 3, n),
        "saved": rng.choice([True, False], n),
        "attempts": rng.integers(1, 9, n), "conversion_pct": rng.uniform(0, 100, n),
    })
    fig = _render(viz_id, df)
    rects = _goal_rects(fig)
    # the 3 canonical frame rectangles (posts + crossbar) must be present
    posts = [r for r in rects if (r.get_x() < 0 or r.get_x() >= G.GOAL_WIDTH)
             and r.get_height() > G.GOAL_HEIGHT]
    crossbar = [r for r in rects if r.get_y() >= G.GOAL_HEIGHT - 0.01
                and r.get_width() > G.GOAL_WIDTH]
    assert len(posts) == 2 and crossbar, f"{viz_id} missing canonical goal frame"
    plt.close(fig)


def test_pitch_based_shot_map_is_not_goal_based():
    """A pitch map must NOT be converted to the goal frame — it draws a pitch."""
    viz = visual_registry.create("shot_map")
    assert getattr(viz, "pitch_based", False) is True
    fig = _render("shot_map", pd.DataFrame({
        "event_type": ["shot"] * 5, "x": [90] * 5, "y": [50] * 5,
        "end_x": [99] * 5, "end_y": [50] * 5,
        "shot_result": ["Goal", "Saved", "Off Target", "Blocked", "Goal"],
        "shot_xg": [0.2, 0.1, 0.05, 0.3, 0.5]}))
    # a pitch map has NO canonical goal posts (posts extend above GOAL_HEIGHT)
    posts = [r for r in _goal_rects(fig)
             if (r.get_x() < 0 or r.get_x() >= G.GOAL_WIDTH) and r.get_height() > G.GOAL_HEIGHT]
    assert not posts
    plt.close(fig)
