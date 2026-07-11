from __future__ import annotations

import numpy as np

from fap.core.plugin import PluginInfo
from fap.visuals.context import LayerContext
from fap.visuals.layers.base import Layer, layer_registry
from fap.visuals.pitch import DISPLAY_LENGTH, DISPLAY_WIDTH


def _xy(ctx: LayerContext) -> tuple[np.ndarray, np.ndarray]:
    df = ctx.df.dropna(subset=["x", "y"])
    return ctx.to_display(df["x"], df["y"])


@layer_registry.register
class HeatmapLayer(Layer):
    """2D histogram heatmap. Params: heat_bins, cmap, heat_alpha,
    heat_blur (gaussian sigma in bins - the 'radius/blur' controls)."""
    info = PluginInfo(id="heatmap", name="Heatmap", category="density")
    zorder = 2

    def draw(self, ctx: LayerContext) -> None:
        x, y = _xy(ctx)
        if not len(x):
            return
        bins = int(self.p("heat_bins", ctx))
        blur = float(self.p("heat_blur", ctx))
        extent = ((0, DISPLAY_WIDTH, 0, DISPLAY_LENGTH) if ctx.vertical
                  else (0, DISPLAY_LENGTH, 0, DISPLAY_WIDTH))
        key = f"heat::{self.signature()}::{len(x)}"

        def compute() -> np.ndarray:
            h, _, _ = np.histogram2d(
                x, y, bins=bins,
                range=[[extent[0], extent[1]], [extent[2], extent[3]]])
            if blur > 0:
                from scipy.ndimage import gaussian_filter
                h = gaussian_filter(h, sigma=blur)
            return h

        h = ctx.memo(key, compute)
        ctx.ax.imshow(h.T, origin="lower", extent=extent, aspect="auto",
                      cmap=self.p("cmap", ctx, ctx.theme.heatmap_cmaps[0]),
                      alpha=float(self.p("heat_alpha", ctx)), zorder=self.zorder)


@layer_registry.register
class HexbinLayer(Layer):
    """Hexagonal binning. Params: hex_gridsize, cmap, heat_alpha, mincnt."""
    info = PluginInfo(id="hexbin", name="Hexbin", category="density")
    zorder = 2

    def draw(self, ctx: LayerContext) -> None:
        x, y = _xy(ctx)
        if not len(x):
            return
        ctx.ax.hexbin(x, y, gridsize=int(self.p("hex_gridsize", ctx)),
                      cmap=self.p("cmap", ctx, ctx.theme.heatmap_cmaps[0]),
                      alpha=float(self.p("heat_alpha", ctx)),
                      mincnt=int(self.params.get("mincnt", 1)),
                      linewidths=0.2, zorder=self.zorder)


@layer_registry.register
class ColorScaleLayer(Layer):
    """Horizontal colorbar explaining a density/metric scale.
    Params: cmap, label, vmin, vmax."""
    info = PluginInfo(id="color_scale", name="Color scale", category="density")
    zorder = 25

    def draw(self, ctx: LayerContext) -> None:
        import matplotlib.cm as cm
        from matplotlib.colors import Normalize
        norm = Normalize(vmin=float(self.params.get("vmin", 0)),
                         vmax=float(self.params.get("vmax", 1)))
        mappable = cm.ScalarMappable(norm=norm, cmap=self.p("cmap", ctx, "viridis"))
        cbar = ctx.fig.colorbar(mappable, ax=ctx.ax, orientation="horizontal",
                                fraction=0.035, pad=0.05, aspect=40)
        cbar.outline.set_edgecolor(ctx.theme.colors["grid"])
        cbar.ax.tick_params(colors=ctx.theme.colors["muted"],
                            labelsize=ctx.style("label_size") - 2)
        if self.params.get("label"):
            cbar.set_label(self.params["label"], color=ctx.theme.colors["muted"],
                           fontsize=ctx.style("label_size"))
