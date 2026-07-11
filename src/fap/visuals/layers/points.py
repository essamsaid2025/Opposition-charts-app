from __future__ import annotations

import numpy as np
import pandas as pd

from fap.core.plugin import PluginInfo
from fap.visuals.context import LayerContext
from fap.visuals.layers.base import Layer, layer_registry


def _points(ctx: LayerContext, layer: Layer) -> tuple[np.ndarray, np.ndarray, pd.DataFrame]:
    df = layer.params.get("df")
    df = ctx.df if df is None else df
    df = df.dropna(subset=["x", "y"])
    x, y = ctx.to_display(df["x"], df["y"])
    return x, y, df


@layer_registry.register
class ScatterLayer(Layer):
    """Event scatter. Params: color, marker_shape, marker_size, marker_alpha,
    marker_edge_width, sizes (array), colors (array), label (legend)."""
    info = PluginInfo(id="scatter", name="Scatter", category="points")
    zorder = 6

    def draw(self, ctx: LayerContext) -> None:
        x, y, _ = _points(ctx, self)
        if not len(x):
            return
        color = self.params.get("colors")
        if color is None:
            color = self.params.get("color") or ctx.theme.colors["accent"]
        edge = self.p("marker_edge_color", ctx) or ctx.theme.colors["lines"]
        ctx.ax.scatter(
            x, y,
            s=self.params.get("sizes", float(self.p("marker_size", ctx))),
            c=color, marker=self.p("marker_shape", ctx),
            edgecolors=edge, linewidths=float(self.p("marker_edge_width", ctx)),
            alpha=float(self.p("marker_alpha", ctx)), zorder=self.zorder)
        if self.params.get("label"):
            ctx.legend.add(self.params["label"], kind="marker",
                           color=color if isinstance(color, str) else ctx.theme.colors["accent"],
                           marker=self.p("marker_shape", ctx))


@layer_registry.register
class PlayerMarkerLayer(Layer):
    """Player dots with jersey numbers (and optional name labels).
    Params: color, number_column, name_column, show_names."""
    info = PluginInfo(id="player_markers", name="Player markers", category="points")
    zorder = 8

    def draw(self, ctx: LayerContext) -> None:
        x, y, df = _points(ctx, self)
        if not len(x):
            return
        color = self.params.get("color") or ctx.theme.colors["accent"]
        size = float(self.p("marker_size", ctx)) * 1.4
        ctx.ax.scatter(x, y, s=size, c=color, edgecolors=ctx.theme.colors["lines"],
                       linewidths=float(self.p("marker_edge_width", ctx)),
                       alpha=float(self.p("marker_alpha", ctx)), zorder=self.zorder)
        numbers = df.get(self.params.get("number_column", "jersey_number"))
        if numbers is not None:
            for px, py, num in zip(x, y, numbers):
                text = str(num).replace(".0", "")
                if text and text.lower() != "nan":
                    ctx.ax.text(px, py, text, ha="center", va="center",
                                fontsize=max(6, ctx.style("label_size") - 2),
                                fontweight="bold", color=ctx.theme.colors["bg"],
                                zorder=self.zorder + 1)
        if self.params.get("show_names"):
            names = df.get(self.params.get("name_column", "player"), pd.Series(dtype=str))
            for px, py, name in zip(x, y, names):
                if str(name).strip():
                    ctx.ax.text(px, py - 2.6, str(name), ha="center", va="top",
                                fontsize=max(6, ctx.style("label_size") - 3),
                                color=ctx.theme.colors["text"], zorder=self.zorder + 1)


@layer_registry.register
class BallLayer(Layer):
    """Ball position marker. Params: x, y (canonical), color."""
    info = PluginInfo(id="ball", name="Ball", category="points")
    zorder = 12

    def draw(self, ctx: LayerContext) -> None:
        bx, by = ctx.to_display([self.params.get("x", 50)], [self.params.get("y", 50)])
        ctx.ax.scatter(bx, by, s=float(self.p("marker_size", ctx)) * 0.7,
                       c=self.params.get("color", "#FFFFFF"),
                       edgecolors="#111111", linewidths=1.4, marker="o",
                       zorder=self.zorder)


@layer_registry.register
class HighlightLayer(Layer):
    """Ring highlight around points. Params: color, ring_scale."""
    info = PluginInfo(id="highlight", name="Highlight", category="points")
    zorder = 7

    def draw(self, ctx: LayerContext) -> None:
        x, y, _ = _points(ctx, self)
        if not len(x):
            return
        color = self.params.get("color") or ctx.theme.colors["danger"]
        scale = float(self.params.get("ring_scale", 3.0))
        ctx.ax.scatter(x, y, s=float(self.p("marker_size", ctx)) * scale,
                       facecolors="none", edgecolors=color, linewidths=2.0,
                       alpha=0.95, zorder=self.zorder)


@layer_registry.register
class GlowLayer(Layer):
    """Soft glow behind points (broadcast look): stacked translucent halos.
    Params: color, glow_layers, glow_scale."""
    info = PluginInfo(id="glow", name="Glow", category="effects")
    zorder = 5

    def draw(self, ctx: LayerContext) -> None:
        x, y, _ = _points(ctx, self)
        if not len(x):
            return
        color = self.params.get("color") or ctx.theme.colors["accent"]
        base = float(self.p("marker_size", ctx))
        n = int(self.params.get("glow_layers", 4))
        scale = float(self.params.get("glow_scale", 5.0))
        for i in range(n, 0, -1):
            ctx.ax.scatter(x, y, s=base * (1 + scale * i / n), c=color,
                           alpha=0.06, edgecolors="none", zorder=self.zorder)


@layer_registry.register
class ShadowLayer(Layer):
    """Drop shadow under points. Params: offset (display units), color."""
    info = PluginInfo(id="shadow", name="Shadow", category="effects")
    zorder = 4

    def draw(self, ctx: LayerContext) -> None:
        x, y, _ = _points(ctx, self)
        if not len(x):
            return
        off = float(self.params.get("offset", ctx.tokens.get("shadow_offset")))
        ctx.ax.scatter(x + off, y - off, s=float(self.p("marker_size", ctx)),
                       c=self.params.get("color", "#000000"),
                       alpha=float(ctx.tokens.get("shadow_alpha")),
                       edgecolors="none", zorder=self.zorder)
