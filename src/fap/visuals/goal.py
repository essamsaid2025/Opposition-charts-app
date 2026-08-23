"""Canonical Opta-style goal renderer.

The single, reusable implementation of the goal geometry used by EVERY goal-based
visualization (goal-mouth maps, save maps, penalty placement/heatmaps, goalkeeper
reach…). It is the goal-frame sibling of :mod:`fap.visuals.pitch` (the pitch
renderer): a pure, theme-aware rendering primitive with no data semantics of its
own — callers map their own data into the normalized goal coordinate system and
hand it here for drawing.

Coordinate system (display units)::

    x = 0            left post          x = GOAL_WIDTH   right post
    y = 0            ground             y = GOAL_HEIGHT  crossbar (underside)

Data for any goal-based map is mapped into ``x in [0, GOAL_WIDTH]`` and
``y in [0, GOAL_HEIGHT]``; the geometry below is identical for every caller, so
the Penalty Map and the Goal-Mouth Map draw a visually identical goal.

Visual language matches the Opta Analyst reference: a large rectangular frame,
thick grey posts and crossbar of identical thickness, an open bottom, a grey
ground line extending beyond both posts, no net, no pitch markings, a clean
editorial background. Colours come from the active chart theme (grey ``lines``,
purple ``accent`` saves, red ``danger`` goals) — this module introduces no new
theme and hardcodes no palette.
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence

import numpy as np
from matplotlib.axes import Axes
from matplotlib.patches import Circle, Rectangle

# ---- canonical geometry (display units, tuned to the Opta reference) --------
GOAL_WIDTH = 100.0        # left post (0) -> right post (GOAL_WIDTH)
GOAL_HEIGHT = 40.0        # ground (0) -> crossbar underside (GOAL_HEIGHT); ~2.5:1
POST = 3.4                # post AND crossbar thickness (identical), display units
GROUND_EXTEND = 15.0      # ground line reaches this far beyond each post
_PAD_X = 6.0              # whitespace left/right of the ground line
_PAD_TOP = 12.0           # whitespace above the crossbar
_PAD_BOTTOM = 11.0        # whitespace below the ground line


def _face(theme: Any, override: Any) -> str:
    if override is not None:
        return override
    c = theme.colors
    return c.get("bg") or c.get("panel") or "#ECECEC"


def draw_goal(ax: Axes, theme: Any, *, width: float = GOAL_WIDTH,
              height: float = GOAL_HEIGHT, post: float = POST,
              ground_extend: float = GROUND_EXTEND, line_color: str | None = None,
              ground_color: str | None = None, ground_width: float = 4.5,
              face: str | None = None, set_limits: bool = True,
              zorder: float = 3) -> Axes:
    """Draw the canonical goal frame onto ``ax``.

    Posts and crossbar are drawn as filled rectangles of identical thickness
    (``post``); the bottom is left open; a grey ground line runs along ``y = 0``
    and extends ``ground_extend`` beyond each post. Sets an equal aspect (so shot
    circles stay circular at any figure size/DPI), hides ticks/spines and, when
    ``set_limits`` is true, frames the goal with consistent whitespace so it stays
    centred and scales proportionally. Returns ``ax``.
    """
    c = theme.colors
    frame = line_color or c["lines"]
    ground = ground_color or c.get("grey") or frame
    ax.set_facecolor(_face(theme, face))

    # posts run from the ground up to the top of the crossbar (solid corners)
    ax.add_patch(Rectangle((-post, 0.0), post, height + post,
                           facecolor=frame, edgecolor="none", zorder=zorder))
    ax.add_patch(Rectangle((width, 0.0), post, height + post,
                           facecolor=frame, edgecolor="none", zorder=zorder))
    # crossbar spans the outer edges of both posts
    ax.add_patch(Rectangle((-post, height), width + 2 * post, post,
                           facecolor=frame, edgecolor="none", zorder=zorder))
    # ground line (open bottom), extending beyond the posts
    gx0, gx1 = -post - ground_extend, width + post + ground_extend
    ax.plot([gx0, gx1], [0.0, 0.0], color=ground, lw=ground_width,
            solid_capstyle="butt", zorder=zorder - 1)

    if set_limits:
        ax.set_xlim(gx0 - _PAD_X, gx1 + _PAD_X)
        ax.set_ylim(-_PAD_BOTTOM, height + post + _PAD_TOP)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    return ax


def scale_radii(values: Iterable[Any], *, rmin: float, rmax: float) -> np.ndarray:
    """Map a size metric (xG, save difficulty, …) to marker radii in ``[rmin, rmax]``.

    Blank/degenerate inputs collapse to the midpoint so a map with no size metric
    still renders sensibly. This never invents a metric — callers pass whatever
    existing semantic column they already use for point size."""
    v = np.array([float(x) if x is not None and str(x) != "" else np.nan
                  for x in values], dtype=float)
    if v.size == 0:
        return np.array([])
    mid = (rmin + rmax) / 2.0
    if np.all(np.isnan(v)):
        return np.full(v.size, mid)
    lo, hi = np.nanmin(v), np.nanmax(v)
    if hi <= lo:
        return np.full(v.size, mid)
    t = np.nan_to_num((v - lo) / (hi - lo), nan=0.0)
    return rmin + t * (rmax - rmin)


def draw_shots(ax: Axes, theme: Any, *, xs: Sequence[float], ys: Sequence[float],
               is_goal: Sequence[bool] | None = None,
               sizes: Sequence[Any] | None = None,
               save_color: str | None = None, goal_color: str | None = None,
               hollow_face: str | None = None, base_radius: float = 2.6,
               max_radius: float = 5.4, edge_width: float = 2.2,
               alpha: float = 0.95, zorder: float = 6, legend: Any = None,
               save_label: str = "On target / saved", goal_label: str = "Goal"
               ) -> None:
    """Plot shot/save markers in goal coordinates, Opta-style.

    Saves / on-target shots render as hollow circles (theme ``accent`` outline,
    editorial interior, thick stroke); goals render as filled ``danger`` circles.
    Radii are data-driven from ``sizes`` (an existing metric — e.g. xG or save
    difficulty) via :func:`scale_radii`; when ``sizes`` is ``None`` a constant
    radius is used. ``is_goal`` classifies each marker (the caller derives it from
    its existing outcome column — this function never reclassifies events).
    """
    c = theme.colors
    save_c = save_color or c["accent"]
    goal_c = goal_color or c.get("danger") or c.get("accent_2") or save_c
    face = _face(theme, hollow_face)
    n = len(xs)
    goals = list(is_goal) if is_goal is not None else [False] * n
    radii = (scale_radii(sizes, rmin=base_radius, rmax=max_radius)
             if sizes is not None else np.full(n, base_radius))
    for i in range(n):
        x, y, r = float(xs[i]), float(ys[i]), float(radii[i])
        if goals[i]:
            ax.add_patch(Circle((x, y), r, facecolor=goal_c, edgecolor=goal_c,
                                lw=edge_width * 0.6, alpha=min(1.0, alpha),
                                zorder=zorder + 1))
        else:
            ax.add_patch(Circle((x, y), r, facecolor=face, edgecolor=save_c,
                                lw=edge_width, alpha=alpha, zorder=zorder))
    if legend is not None:
        if any(not g for g in goals):
            legend.add(save_label, kind="marker", color=save_c, marker="o")
        if any(goals):
            legend.add(goal_label, kind="marker", color=goal_c, marker="o")


def draw_difficulty_legend(ax: Axes, theme: Any, *, x: float | None = None,
                           y: float | None = None, radii: Sequence[float] = (1.7, 3.0, 4.3, 5.6),
                           gap: float = 14.0, color: str | None = None,
                           easier_label: str = "Easier save",
                           harder_label: str = "Harder save",
                           text_size: float = 10.0) -> None:
    """Reproduce the reference "Easier save … Harder save" key: a row of hollow
    circles growing left→right, captioned at each end. Positioned to the right of
    the goal by default (data coords). Opt-in — callers pass this only where marker
    size means save difficulty, so no misleading legend is ever shown."""
    c = theme.colors
    ec = color or c["accent"]
    face = c.get("bg") or c.get("panel") or "#ECECEC"
    if x is None:
        x = GOAL_WIDTH + POST + GROUND_EXTEND * 0.4
    if y is None:
        y = GOAL_HEIGHT * 0.55
    cx = x
    for r in radii:
        ax.add_patch(Circle((cx, y), float(r), facecolor=face, edgecolor=ec,
                            lw=1.8, zorder=8))
        cx += gap
    span = gap * (len(radii) - 1)
    ax.text(x, y + max(radii) + 3.2, easier_label, ha="center", va="bottom",
            color=c.get("muted", ec), fontsize=text_size, fontweight="bold")
    ax.text(x + span, y + max(radii) + 3.2, harder_label, ha="center", va="bottom",
            color=c.get("muted", ec), fontsize=text_size, fontweight="bold")


def goal_annotation(ax: Axes, theme: Any, text: str, *, x: float | None = None,
                    y: float | None = None, ha: str = "center",
                    color: str | None = None, size: float = 9.0) -> None:
    """Reusable muted annotation (e.g. "Penalties and own goals are removed").

    A rendering helper ONLY — it never filters events. Callers pass it exactly the
    text their existing visualization already implies, so event selection stays a
    data concern, separate from rendering."""
    c = theme.colors
    if x is None:
        x = -POST - GROUND_EXTEND
    if y is None:
        y = GOAL_HEIGHT * 0.45
    ax.text(x, y, text, ha=ha, va="center", color=color or c.get("muted", c["lines"]),
            fontsize=size, fontweight="bold", zorder=8)


def cell_rect(col: int, row: int, ncols: int, nrows: int, color: Any, *,
              width: float = GOAL_WIDTH, height: float = GOAL_HEIGHT,
              inset: float = 0.4) -> Rectangle:
    """A shaded grid cell mapped into goal coordinates — the placement-heatmap
    building block (penalty placement / zone grids), so those maps overlay their
    existing per-cell values on the CANONICAL goal geometry."""
    cw, ch = width / ncols, height / nrows
    return Rectangle((col * cw + inset, row * ch + inset), cw - 2 * inset,
                     ch - 2 * inset, color=color, ec="none")


def cell_center(col: int, row: int, ncols: int, nrows: int, *,
                width: float = GOAL_WIDTH, height: float = GOAL_HEIGHT
                ) -> tuple[float, float]:
    """Centre of grid cell ``(col, row)`` in goal coordinates."""
    return (col + 0.5) * width / ncols, (row + 0.5) * height / nrows


def map_across_goal(value: float, lo: float, hi: float, *,
                    width: float = GOAL_WIDTH) -> float:
    """Map a horizontal placement value in ``[lo, hi]`` (e.g. shot end_y between the
    posts) onto the goal's x-axis ``[0, width]``. Values outside land just outside
    the posts, exactly as off-target shots do in the reference."""
    if hi <= lo:
        return width / 2.0
    return (float(value) - lo) / (hi - lo) * width
