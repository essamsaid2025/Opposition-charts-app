"""Layout Engine: professional multi-panel figure layouts via GridSpec.
Every layout returns (fig, {panel_name: Axes}) so the Renderer can place a
visualization (or several) per panel. 'scale' makes layouts responsive."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure


@dataclass(frozen=True, slots=True)
class LayoutSpec:
    id: str
    name: str
    figsize: tuple[float, float]
    panels: tuple[str, ...]
    build: Any = field(repr=False, default=None)     # (fig) -> dict[str, Axes]


class LayoutEngine:
    def __init__(self) -> None:
        self._layouts: dict[str, LayoutSpec] = {}
        self._register_builtin()

    def register(self, spec: LayoutSpec) -> None:
        self._layouts[spec.id] = spec

    def ids(self) -> list[str]:
        return sorted(self._layouts)

    def build(self, layout_id: str, theme: Any, *, scale: float = 1.0
              ) -> tuple[Figure, dict[str, Axes]]:
        spec = self._layouts.get(layout_id, self._layouts["single"])
        w, h = spec.figsize
        fig = plt.figure(figsize=(w * scale, h * scale))
        fig.patch.set_facecolor(theme.colors["bg"])
        axes = spec.build(fig)
        for ax in axes.values():
            ax.set_facecolor(theme.colors["bg"])
        return fig, axes

    # ------------------------------------------------------------ builtin
    def _register_builtin(self) -> None:
        def single(fig: Figure) -> dict[str, Axes]:
            return {"main": fig.add_subplot(111)}

        def two_panel(fig: Figure) -> dict[str, Axes]:
            gs = fig.add_gridspec(1, 2, wspace=0.08)
            return {"a": fig.add_subplot(gs[0]), "b": fig.add_subplot(gs[1])}

        def four_panel(fig: Figure) -> dict[str, Axes]:
            gs = fig.add_gridspec(2, 2, wspace=0.08, hspace=0.14)
            return {"a": fig.add_subplot(gs[0, 0]), "b": fig.add_subplot(gs[0, 1]),
                    "c": fig.add_subplot(gs[1, 0]), "d": fig.add_subplot(gs[1, 1])}

        def dashboard(fig: Figure) -> dict[str, Axes]:
            gs = fig.add_gridspec(2, 3, wspace=0.1, hspace=0.16,
                                  height_ratios=[1.4, 1.0])
            return {"main": fig.add_subplot(gs[0, :2]),
                    "side": fig.add_subplot(gs[0, 2]),
                    "a": fig.add_subplot(gs[1, 0]),
                    "b": fig.add_subplot(gs[1, 1]),
                    "c": fig.add_subplot(gs[1, 2])}

        def split_view(fig: Figure) -> dict[str, Axes]:
            gs = fig.add_gridspec(1, 2, width_ratios=[2.2, 1.0], wspace=0.1)
            return {"main": fig.add_subplot(gs[0]), "side": fig.add_subplot(gs[1])}

        def comparison(fig: Figure) -> dict[str, Axes]:
            gs = fig.add_gridspec(1, 2, wspace=0.05)
            return {"left": fig.add_subplot(gs[0]), "right": fig.add_subplot(gs[1])}

        def report(fig: Figure) -> dict[str, Axes]:
            gs = fig.add_gridspec(3, 2, height_ratios=[0.16, 1.0, 1.0],
                                  wspace=0.09, hspace=0.18)
            header = fig.add_subplot(gs[0, :]); header.axis("off")
            return {"header": header,
                    "a": fig.add_subplot(gs[1, 0]), "b": fig.add_subplot(gs[1, 1]),
                    "c": fig.add_subplot(gs[2, 0]), "d": fig.add_subplot(gs[2, 1])}

        def presentation(fig: Figure) -> dict[str, Axes]:
            ax = fig.add_axes([0.06, 0.08, 0.88, 0.8])
            return {"main": ax}

        for spec in (
            LayoutSpec("single", "Single visualization", (11.8, 8.0), ("main",), single),
            LayoutSpec("two_panel", "Two panels", (16.0, 7.2), ("a", "b"), two_panel),
            LayoutSpec("four_panel", "Four panels", (15.0, 11.0), ("a", "b", "c", "d"), four_panel),
            LayoutSpec("dashboard", "Dashboard", (17.0, 10.5),
                       ("main", "side", "a", "b", "c"), dashboard),
            LayoutSpec("split_view", "Split view", (15.5, 7.5), ("main", "side"), split_view),
            LayoutSpec("comparison", "Comparison view", (16.0, 7.2), ("left", "right"), comparison),
            LayoutSpec("report", "Report view", (14.0, 13.5),
                       ("header", "a", "b", "c", "d"), report),
            LayoutSpec("presentation", "Presentation (16:9)", (16.0, 9.0), ("main",), presentation),
        ):
            self.register(spec)
