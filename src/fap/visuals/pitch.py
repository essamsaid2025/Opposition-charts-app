"""Professional Pitch Engine.

Data is ALWAYS in canonical space (x 0-100, y plotted 0-68 display units);
the pitch spec controls only real-world marking geometry (box depths, circle
radius, goal width) so a StatsBomb-proportioned pitch and a UEFA pitch draw
correct markings over the same data. Views crop the axes; orientation swaps
axes; 'auto' orientation picks vertical for attacking/defensive views.

The legacy ``PitchFactory.create(theme, vertical=..., show_thirds=...)`` API
is preserved for existing callers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Tuple

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import Arc, Circle, Rectangle

from fap.core.types import PitchDims

DISPLAY_LENGTH = 100.0     # canonical plotting units (matches pipeline y_plot)
DISPLAY_WIDTH = 68.0


@dataclass(frozen=True, slots=True)
class PitchSpec:
    """Real pitch geometry in meters; drawn scaled into display units."""
    id: str
    name: str
    length_m: float = 105.0
    width_m: float = 68.0

    def ux(self, meters: float) -> float:
        return meters / self.length_m * DISPLAY_LENGTH

    def uy(self, meters: float) -> float:
        return meters / self.width_m * DISPLAY_WIDTH


PITCH_SPECS: dict[str, PitchSpec] = {
    "uefa": PitchSpec("uefa", "UEFA (105 x 68)", 105, 68),
    "fifa": PitchSpec("fifa", "FIFA (105 x 68)", 105, 68),
    "statsbomb": PitchSpec("statsbomb", "StatsBomb (120 x 80)", 120, 80),
    "opta": PitchSpec("opta", "Opta (105 x 68)", 105, 68),
    "wyscout": PitchSpec("wyscout", "Wyscout (105 x 68)", 105, 68),
    "tracab": PitchSpec("tracab", "Tracab (105 x 68)", 105, 68),
    "skillcorner": PitchSpec("skillcorner", "SkillCorner (105 x 68)", 105, 68),
    "metrica": PitchSpec("metrica", "Metrica (105 x 68)", 105, 68),
}

VIEWS: dict[str, tuple[float, float]] = {          # x-range in display units
    "full": (0.0, 100.0),
    "half": (50.0, 100.0),
    "attacking_half": (50.0, 100.0),
    "defensive_half": (0.0, 50.0),
    "final_third": (66.67, 100.0),
    "middle_third": (33.33, 66.67),
    "penalty_area": (78.0, 100.0),
}
_VERTICAL_VIEWS = {"half", "attacking_half", "defensive_half", "final_third", "penalty_area"}


def get_spec(spec: str | PitchSpec | None, *, custom_length: float | None = None,
             custom_width: float | None = None) -> PitchSpec:
    if isinstance(spec, PitchSpec):
        return spec
    if spec == "custom" or (spec is None and custom_length):
        return PitchSpec("custom", "Custom", custom_length or 105.0, custom_width or 68.0)
    return PITCH_SPECS.get(spec or "uefa", PITCH_SPECS["uefa"])


def resolve_orientation(view: str, orientation: str = "auto") -> bool:
    """Returns vertical? - 'auto' chooses vertical for goal-facing views."""
    if orientation in ("horizontal", "vertical"):
        return orientation == "vertical"
    return view in _VERTICAL_VIEWS


class PitchFactory:
    def __init__(self, dims: PitchDims | None = None) -> None:
        self._dims = dims or PitchDims()

    # ---------------------------------------------------------------- new API
    def build(self, theme: Any, *, spec: str | PitchSpec = "uefa", view: str = "full",
              orientation: str = "auto", crop: tuple[float, float, float, float] | None = None,
              show_thirds: bool = False, show_lanes: bool = False,
              stripes: bool | None = None, line_width: float | None = None,
              fig_scale: float = 1.0, ax: Axes | None = None) -> Tuple[Figure, Axes]:
        """Draw a themed pitch. ``crop=(x0, x1, y0, y1)`` in display units
        overrides the named view."""
        pitch_spec = get_spec(spec)
        vertical = resolve_orientation(view, orientation)

        if ax is None:
            x0, x1, y0, y1 = self._window(view, crop)
            span_x, span_y = (y1 - y0, x1 - x0) if vertical else (x1 - x0, y1 - y0)
            base = 11.8 * fig_scale
            fig, ax = plt.subplots(figsize=(base, max(2.5, base * span_y / max(span_x, 1))))
        else:
            fig = ax.figure
        fig.patch.set_facecolor(theme.colors["bg"])

        self.draw_pitch(ax, theme, pitch_spec, vertical=vertical,
                        stripes=stripes, line_width=line_width)
        self.draw_overlays(ax, theme, vertical=vertical,
                           show_thirds=show_thirds, show_lanes=show_lanes)
        self.apply_view(ax, view=view, crop=crop, vertical=vertical)
        return fig, ax

    # ---------------------------------------------------------------- legacy API
    def create(self, theme: Any, *, vertical: bool = False, show_thirds: bool = True,
               show_lanes: bool = False, fig_scale: float = 1.0) -> Tuple[Figure, Axes]:
        return self.build(theme, spec="uefa", view="full",
                          orientation="vertical" if vertical else "horizontal",
                          show_thirds=show_thirds, show_lanes=show_lanes,
                          fig_scale=fig_scale)

    @staticmethod
    def coords(df: pd.DataFrame, vertical: bool, end: bool = False) -> Tuple[pd.Series, pd.Series]:
        x = df["x2_plot"] if end else df["x_plot"]
        y = df["y2_plot"] if end else df["y_plot"]
        return (y, x) if vertical else (x, y)

    # ---------------------------------------------------------------- drawing
    def draw_pitch(self, ax: Axes, theme: Any, spec: PitchSpec, *, vertical: bool,
                   stripes: bool | None = None, line_width: float | None = None) -> None:
        c = theme.colors
        lw = line_width or 1.6
        L, W = DISPLAY_LENGTH, DISPLAY_WIDTH
        ax.set_facecolor(c["pitch"])

        def T(x: float, y: float) -> tuple[float, float]:
            return (y, x) if vertical else (x, y)

        def rect(x: float, y: float, w: float, h: float, **kw: Any) -> None:
            (px, py), (pw, ph) = T(x, y), ((h, w) if vertical else (w, h))
            ax.add_patch(Rectangle((px, py), pw, ph, **kw))

        do_stripes = stripes if stripes is not None else \
            (c.get("stripe") and c["stripe"] != c["pitch"])
        if do_stripes:
            for i in range(0, 100, 20):
                if (i // 20) % 2 == 0:
                    rect(i, 0, 20, W, color=c["stripe"], alpha=0.55, zorder=0)

        # geometry from real meters -> display units
        box_d, box_w = spec.ux(16.5), spec.uy(40.32)
        six_d, six_w = spec.ux(5.5), spec.uy(18.32)
        spot, radius = spec.ux(11.0), spec.ux(9.15)
        goal_w, goal_d = spec.uy(7.32), spec.ux(2.0)

        rect(0, 0, L, W, fill=False, edgecolor=c["lines"], linewidth=lw, zorder=1)
        ax.plot(*zip(T(50, 0), T(50, W)), color=c["lines"], lw=lw, zorder=1)
        ax.add_patch(Circle(T(50, W / 2), radius, fill=False, edgecolor=c["lines"], lw=lw, zorder=1))
        ax.add_patch(Circle(T(50, W / 2), 0.45, color=c["lines"], zorder=1))
        for side in (0, 1):                       # 0 = left goal, 1 = right goal
            gx = 0 if side == 0 else L
            sgn = 1 if side == 0 else -1
            rect(gx if side == 0 else L - box_d, (W - box_w) / 2, box_d, box_w,
                 fill=False, edgecolor=c["lines"], linewidth=lw, zorder=1)
            rect(gx if side == 0 else L - six_d, (W - six_w) / 2, six_d, six_w,
                 fill=False, edgecolor=c["lines"], linewidth=lw, zorder=1)
            ax.add_patch(Circle(T(gx + sgn * spot, W / 2), 0.45, color=c["lines"], zorder=1))
            theta = (310, 50) if side == 0 else (130, 230)
            if vertical:
                theta = (theta[0] + 90, theta[1] + 90)
            ax.add_patch(Arc(T(gx + sgn * spot, W / 2), 2 * radius, 2 * radius,
                             theta1=theta[0], theta2=theta[1], color=c["lines"], lw=lw, zorder=1))
            rect(gx - goal_d if side == 0 else L, (W - goal_w) / 2, goal_d, goal_w,
                 fill=False, edgecolor=c["lines"], linewidth=lw, zorder=1)
        ax.set_aspect("equal")
        ax.axis("off")

    def draw_overlays(self, ax: Axes, theme: Any, *, vertical: bool,
                      show_thirds: bool, show_lanes: bool) -> None:
        c = theme.colors
        if show_thirds:
            for x in (33.33, 66.67):
                pts = ((0, x), (DISPLAY_WIDTH, x)) if vertical else ((x, 0), (x, DISPLAY_WIDTH))
                ax.plot(*zip(*pts), color=c["warning"], lw=1.3, ls="--", alpha=0.7, zorder=2)
        if show_lanes:
            for y in (DISPLAY_WIDTH / 3, 2 * DISPLAY_WIDTH / 3):
                pts = ((y, 0), (y, DISPLAY_LENGTH)) if vertical else ((0, y), (DISPLAY_LENGTH, y))
                ax.plot(*zip(*pts), color=c["grid"], lw=1.0, ls=":", alpha=0.75, zorder=2)

    def apply_view(self, ax: Axes, *, view: str = "full",
                   crop: tuple[float, float, float, float] | None = None,
                   vertical: bool = False, pad: float = 3.0) -> None:
        x0, x1, y0, y1 = self._window(view, crop)
        if vertical:
            ax.set_xlim(y0 - pad, y1 + pad)
            ax.set_ylim(x0 - pad, x1 + pad)
        else:
            ax.set_xlim(x0 - pad, x1 + pad)
            ax.set_ylim(y0 - pad, y1 + pad)

    @staticmethod
    def _window(view: str, crop: tuple[float, float, float, float] | None
                ) -> tuple[float, float, float, float]:
        if crop:
            return crop
        x0, x1 = VIEWS.get(view, VIEWS["full"])
        if view == "penalty_area":
            box_half = 40.32 / 68 * DISPLAY_WIDTH / 2
            return x0, x1, DISPLAY_WIDTH / 2 - box_half - 4, DISPLAY_WIDTH / 2 + box_half + 4
        return x0, x1, 0.0, DISPLAY_WIDTH
