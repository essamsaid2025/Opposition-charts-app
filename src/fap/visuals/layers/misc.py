from __future__ import annotations

import numpy as np
import pandas as pd

from fap.core.plugin import PluginInfo
from fap.visuals.context import LayerContext
from fap.visuals.layers.base import Layer, layer_registry


@layer_registry.register
class LegendLayer(Layer):
    """Finalizes the legend collected by other layers, plus manual entries.
    Params: entries (manual), position, ncol, title, hide (labels), order."""
    info = PluginInfo(id="legend", name="Legend", category="framework")
    zorder = 50

    def draw(self, ctx: LayerContext) -> None:
        if not ctx.controls.get("legend", True):
            return
        if self.params.get("entries"):
            ctx.legend.add_manual(self.params["entries"])
        if self.params.get("hide"):
            ctx.legend.hide(*self.params["hide"])
        if self.params.get("order"):
            ctx.legend.reorder(self.params["order"])
        ctx.legend.build(ctx.ax, ctx.theme, ctx.tokens,
                         position=self.params.get("position",
                                                  ctx.controls.get("legend_position", "bottom")),
                         ncol=self.params.get("ncol"),
                         title=self.params.get("title"))


@layer_registry.register
class TimelineLayer(Layer):
    """Compact event timeline strip under the pitch (inset axes).
    Params: column (time), color, height."""
    info = PluginInfo(id="timeline", name="Timeline", category="framework")
    zorder = 26

    def draw(self, ctx: LayerContext) -> None:
        column = self.params.get("column", "time_min")
        if column not in ctx.df.columns:
            return
        times = pd.to_numeric(ctx.df[column], errors="coerce").dropna()
        if times.empty:
            return
        inset = ctx.ax.inset_axes([0.0, -0.16, 1.0, float(self.params.get("height", 0.07))])
        color = self.params.get("color") or ctx.theme.colors["accent"]
        inset.eventplot(times.values, colors=color, lineoffsets=0.5, linelengths=0.8)
        inset.set_xlim(0, max(95, float(times.max()) + 2))
        inset.set_ylim(0, 1)
        inset.set_yticks([])
        inset.tick_params(colors=ctx.theme.colors["muted"],
                          labelsize=max(6, ctx.style("label_size") - 3))
        inset.set_facecolor(ctx.theme.colors["panel"])
        for spine in inset.spines.values():
            spine.set_color(ctx.theme.colors["grid"])


@layer_registry.register
class CustomArtistLayer(Layer):
    """Escape hatch: run any callable(ctx) to draw custom matplotlib artists
    without leaving the framework. Params: artist (callable)."""
    info = PluginInfo(id="custom_artist", name="Custom artist", category="framework")
    zorder = 15

    def draw(self, ctx: LayerContext) -> None:
        fn = self.params.get("artist")
        if callable(fn):
            fn(ctx)
