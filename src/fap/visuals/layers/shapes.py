from __future__ import annotations

import numpy as np

from fap.core.plugin import PluginInfo
from fap.visuals.context import LayerContext
from fap.visuals.layers.base import Layer, layer_registry
from fap.visuals.pitch import DISPLAY_LENGTH, DISPLAY_WIDTH


@layer_registry.register
class PolygonLayer(Layer):
    """Filled polygon. Params: points=[(x, y), ...] canonical, color,
    fill_alpha, edge_width, label."""
    info = PluginInfo(id="polygon", name="Polygon", category="shapes")
    zorder = 3

    def draw(self, ctx: LayerContext) -> None:
        pts = self.params.get("points", [])
        if len(pts) < 3:
            return
        xs, ys = ctx.to_display([p[0] for p in pts], [p[1] for p in pts])
        color = self.params.get("color") or ctx.theme.colors["accent"]
        ctx.ax.fill(xs, ys, color=color,
                    alpha=float(self.params.get("fill_alpha", 0.25)),
                    zorder=self.zorder)
        ctx.ax.plot(np.append(xs, xs[0]), np.append(ys, ys[0]), color=color,
                    lw=float(self.params.get("edge_width", 1.5)), zorder=self.zorder)
        if self.params.get("label"):
            ctx.legend.add(self.params["label"], kind="patch", color=color)


@layer_registry.register
class ConvexHullLayer(Layer):
    """Convex hull around the layer's points (team shape / action areas).
    Params: color, fill_alpha, df."""
    info = PluginInfo(id="convex_hull", name="Convex hull", category="shapes")
    zorder = 3

    def draw(self, ctx: LayerContext) -> None:
        df = self.params.get("df")
        df = ctx.df if df is None else df
        d = df.dropna(subset=["x", "y"])
        if len(d) < 3:
            return
        x, y = ctx.to_display(d["x"], d["y"])
        pts = np.column_stack([x, y])
        key = f"hull::{self.signature()}::{len(pts)}"

        def compute() -> np.ndarray:
            from scipy.spatial import ConvexHull
            hull = ConvexHull(pts)
            return pts[hull.vertices]

        vertices = ctx.memo(key, compute)
        color = self.params.get("color") or ctx.theme.colors["accent"]
        ctx.ax.fill(vertices[:, 0], vertices[:, 1], color=color,
                    alpha=float(self.params.get("fill_alpha", 0.2)), zorder=self.zorder)
        closed = np.vstack([vertices, vertices[:1]])
        ctx.ax.plot(closed[:, 0], closed[:, 1], color=color, lw=1.6, zorder=self.zorder)


@layer_registry.register
class VoronoiLayer(Layer):
    """Voronoi tessellation of points, clipped to the pitch (space control).
    Params: colors (per point) or color, fill_alpha, df."""
    info = PluginInfo(id="voronoi", name="Voronoi", category="shapes")
    zorder = 2

    def draw(self, ctx: LayerContext) -> None:
        df = self.params.get("df")
        df = ctx.df if df is None else df
        d = df.dropna(subset=["x", "y"])
        if len(d) < 4:
            return
        x, y = ctx.to_display(d["x"], d["y"])
        pts = np.column_stack([x, y])
        # mirror points across boundaries so every real cell is finite
        bx = (DISPLAY_WIDTH, DISPLAY_LENGTH) if ctx.vertical else (DISPLAY_LENGTH, DISPLAY_WIDTH)
        mirrored = np.vstack([
            pts,
            pts * [-1, 1], pts * [1, -1],
            [2 * bx[0], 0] + pts * [-1, 1],
            [0, 2 * bx[1]] + pts * [1, -1],
        ])
        key = f"voronoi::{self.signature()}::{len(pts)}"

        def compute():
            from scipy.spatial import Voronoi
            return Voronoi(mirrored)

        vor = ctx.memo(key, compute)
        colors = self.params.get("colors")
        base = self.params.get("color") or ctx.theme.colors["accent"]
        alpha = float(self.params.get("fill_alpha", 0.18))
        for i in range(len(pts)):
            region = vor.regions[vor.point_region[i]]
            if not region or -1 in region:
                continue
            poly = vor.vertices[region]
            c = colors[i] if colors is not None else base
            ctx.ax.fill(poly[:, 0], poly[:, 1], color=c, alpha=alpha,
                        edgecolor=ctx.theme.colors["lines"], lw=0.7, zorder=self.zorder)
