"""PitchFactory: the ONLY place pitch drawing lives. Every map plugin asks it
for a themed (fig, ax) and plots on top - single source of truth for pitch
geometry, stripes, thirds and lane overlays. Falls back to a manual matplotlib
pitch when mplsoccer is unavailable."""
from __future__ import annotations

from typing import Any, Tuple

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from fap.core.types import PitchDims

try:
    from mplsoccer import Pitch, VerticalPitch
    HAS_MPLSOCCER = True
except Exception:  # pragma: no cover
    HAS_MPLSOCCER = False


class PitchFactory:
    def __init__(self, dims: PitchDims | None = None) -> None:
        self._dims = dims or PitchDims()

    def create(self, theme: Any, *, vertical: bool = False, show_thirds: bool = True,
               show_lanes: bool = False, fig_scale: float = 1.0) -> Tuple[Figure, Axes]:
        d = self._dims
        figsize = (7.2 * fig_scale, 10.4 * fig_scale) if vertical else (11.8 * fig_scale, 8.0 * fig_scale)
        fig, ax = plt.subplots(figsize=figsize)
        fig.patch.set_facecolor(theme.colors["bg"])
        if HAS_MPLSOCCER:
            cls = VerticalPitch if vertical else Pitch
            cls(pitch_type="custom", pitch_length=d.length, pitch_width=d.width,
                pitch_color=theme.colors["pitch"], line_color=theme.colors["lines"],
                linewidth=1.6, pad_top=3, pad_bottom=3, pad_left=3, pad_right=3).draw(ax=ax)
        else:
            self._draw_manual(ax, theme, d)
        self._overlays(ax, theme, d, vertical, show_thirds, show_lanes)
        return fig, ax

    @staticmethod
    def coords(df: pd.DataFrame, vertical: bool, end: bool = False) -> Tuple[pd.Series, pd.Series]:
        x = df["x2_plot"] if end else df["x_plot"]
        y = df["y2_plot"] if end else df["y_plot"]
        return (y, x) if vertical else (x, y)

    # -- internals ------------------------------------------------------
    def _overlays(self, ax: Axes, theme: Any, d: PitchDims,
                  vertical: bool, thirds: bool, lanes: bool) -> None:
        if thirds:
            for x in (33.33, 66.67):
                if vertical:
                    ax.plot([0, d.width], [x, x], color=theme.colors["warning"], lw=1.3, ls="--", alpha=0.7)
                else:
                    ax.plot([x, x], [0, d.width], color=theme.colors["warning"], lw=1.3, ls="--", alpha=0.7)
        if lanes:
            for y in (d.width / 3, 2 * d.width / 3):
                if vertical:
                    ax.plot([y, y], [0, d.length], color=theme.colors["grid"], lw=1.0, ls=":", alpha=0.75)
                else:
                    ax.plot([0, d.length], [y, y], color=theme.colors["grid"], lw=1.0, ls=":", alpha=0.75)

    def _draw_manual(self, ax: Axes, theme: Any, d: PitchDims) -> None:
        from matplotlib.patches import Arc, Circle, Rectangle
        lc, lw = theme.colors["lines"], 1.6
        ax.set_facecolor(theme.colors["pitch"])
        ax.add_patch(Rectangle((0, 0), d.length, d.width, fill=False, edgecolor=lc, linewidth=lw))
        ax.plot([50, 50], [0, d.width], color=lc, lw=lw)
        ax.add_patch(Circle((50, d.width / 2), 9.15, fill=False, edgecolor=lc, lw=lw))
        ax.add_patch(Rectangle((0, 13.84), 16.5, 40.32, fill=False, edgecolor=lc, linewidth=lw))
        ax.add_patch(Rectangle((83.5, 13.84), 16.5, 40.32, fill=False, edgecolor=lc, linewidth=lw))
        ax.add_patch(Arc((11, d.width / 2), 18.3, 18.3, theta1=310, theta2=50, color=lc, lw=lw))
        ax.add_patch(Arc((89, d.width / 2), 18.3, 18.3, theta1=130, theta2=230, color=lc, lw=lw))
        ax.set_xlim(-3, d.length + 3)
        ax.set_ylim(-3, d.width + 3)
        ax.set_aspect("equal")
        ax.axis("off")
