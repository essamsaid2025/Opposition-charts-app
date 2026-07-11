from __future__ import annotations

import numpy as np
import pandas as pd

from fap.core.plugin import PluginInfo
from fap.visuals.context import LayerContext
from fap.visuals.layers.base import Layer, layer_registry


def _segments(ctx: LayerContext, layer: Layer) -> pd.DataFrame:
    df = layer.params.get("df")
    df = ctx.df if df is None else df
    return df.dropna(subset=["x", "y", "end_x", "end_y"])


class _ArrowBase(Layer):
    curve: float = 0.0

    def draw(self, ctx: LayerContext) -> None:
        d = _segments(ctx, self)
        if d.empty:
            return
        color = self.params.get("color") or ctx.theme.colors["accent"]
        colors = self.params.get("colors")
        width = float(self.p("arrow_width", ctx))
        alpha = float(self.p("arrow_alpha", ctx))
        head = float(self.p("arrow_head", ctx))
        curve = float(self.params.get("arrow_curve", self.curve))
        style = self.params.get("linestyle", "-")
        x, y = ctx.to_display(d["x"], d["y"])
        x2, y2 = ctx.to_display(d["end_x"], d["end_y"])
        for i in range(len(d)):
            c = colors[i] if colors is not None else color
            ctx.ax.annotate(
                "", xy=(x2[i], y2[i]), xytext=(x[i], y[i]),
                arrowprops=dict(
                    arrowstyle=f"-|>,head_width={head/20:.2f},head_length={head/12:.2f}",
                    color=c, lw=width, alpha=alpha, linestyle=style,
                    connectionstyle=f"arc3,rad={curve}" if curve else "arc3",
                    shrinkA=0, shrinkB=0),
                zorder=self.zorder)
        if self.params.get("label"):
            ctx.legend.add(self.params["label"], kind="line",
                           color=color, linestyle=style)


@layer_registry.register
class ArrowLayer(_ArrowBase):
    """Straight start->end arrows for pass/carry style events.
    Params: color/colors, arrow_width, arrow_head, arrow_alpha, linestyle, label."""
    info = PluginInfo(id="arrows", name="Arrows", category="vectors")
    zorder = 5
    curve = 0.0


@layer_registry.register
class CurvedArrowLayer(_ArrowBase):
    """Curved arrows (crosses, switches). Extra param: arrow_curve."""
    info = PluginInfo(id="curved_arrows", name="Curved arrows", category="vectors")
    zorder = 5

    def draw(self, ctx: LayerContext) -> None:
        self.curve = float(self.p("arrow_curve", ctx))   # control/token default
        super().draw(ctx)


@layer_registry.register
class LineLayer(Layer):
    """Plain segments (no heads). Params: color, line_width, linestyle, label."""
    info = PluginInfo(id="lines", name="Lines", category="vectors")
    zorder = 4

    def draw(self, ctx: LayerContext) -> None:
        d = _segments(ctx, self)
        if d.empty:
            return
        color = self.params.get("color") or ctx.theme.colors["accent"]
        x, y = ctx.to_display(d["x"], d["y"])
        x2, y2 = ctx.to_display(d["end_x"], d["end_y"])
        for i in range(len(d)):
            ctx.ax.plot([x[i], x2[i]], [y[i], y2[i]], color=color,
                        lw=float(self.params.get("line_width", self.p("arrow_width", ctx))),
                        ls=self.params.get("linestyle", "-"),
                        alpha=float(self.p("arrow_alpha", ctx)), zorder=self.zorder)
        if self.params.get("label"):
            ctx.legend.add(self.params["label"], kind="line", color=color,
                           linestyle=self.params.get("linestyle", "-"))


@layer_registry.register
class PathLayer(Layer):
    """Connected path through ordered points (possession chains).
    Params: color, line_width, show_points, number_points."""
    info = PluginInfo(id="path", name="Path", category="vectors")
    zorder = 6

    def draw(self, ctx: LayerContext) -> None:
        df = self.params.get("df")
        df = ctx.df if df is None else df
        d = df.dropna(subset=["x", "y"])
        if len(d) < 2:
            return
        color = self.params.get("color") or ctx.theme.colors["accent"]
        x, y = ctx.to_display(d["x"], d["y"])
        ctx.ax.plot(x, y, color=color, lw=float(self.params.get("line_width", 2.0)),
                    alpha=float(self.p("arrow_alpha", ctx)), zorder=self.zorder,
                    solid_capstyle="round")
        if self.params.get("show_points", True):
            ctx.ax.scatter(x, y, s=float(self.p("marker_size", ctx)) * 0.5, c=color,
                           edgecolors=ctx.theme.colors["lines"], zorder=self.zorder + 1)
        if self.params.get("number_points"):
            for i, (px, py) in enumerate(zip(x, y), start=1):
                ctx.ax.text(px, py, str(i), ha="center", va="center",
                            fontsize=max(6, ctx.style("label_size") - 3),
                            color=ctx.theme.colors["bg"], fontweight="bold",
                            bbox=dict(boxstyle="circle,pad=0.22",
                                      fc=ctx.theme.colors["text"], ec="none", alpha=0.9),
                            zorder=self.zorder + 2)


@layer_registry.register
class TrajectoryLayer(Layer):
    """Smooth fading trajectory (tracking-style movement). Params: color,
    line_width, fade (bool)."""
    info = PluginInfo(id="trajectory", name="Trajectory", category="vectors")
    zorder = 6

    def draw(self, ctx: LayerContext) -> None:
        df = self.params.get("df")
        df = ctx.df if df is None else df
        d = df.dropna(subset=["x", "y"])
        if len(d) < 2:
            return
        color = self.params.get("color") or ctx.theme.colors["accent_2"]
        lw = float(self.params.get("line_width", 2.2))
        x, y = ctx.to_display(d["x"], d["y"])
        n = len(x) - 1
        for i in range(n):
            alpha = 0.15 + 0.85 * (i + 1) / n if self.params.get("fade", True) else 0.9
            ctx.ax.plot(x[i:i + 2], y[i:i + 2], color=color, lw=lw, alpha=alpha,
                        zorder=self.zorder, solid_capstyle="round")
        ctx.ax.scatter(x[-1:], y[-1:], s=float(self.p("marker_size", ctx)) * 0.8,
                       c=color, edgecolors=ctx.theme.colors["lines"],
                       zorder=self.zorder + 1)
