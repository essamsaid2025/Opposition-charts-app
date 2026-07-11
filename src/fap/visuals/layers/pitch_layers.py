from __future__ import annotations

import numpy as np
from matplotlib.patches import Rectangle

from fap.core.plugin import PluginInfo
from fap.visuals.context import LayerContext
from fap.visuals.layers.base import Layer, layer_registry
from fap.visuals.pitch import DISPLAY_LENGTH, DISPLAY_WIDTH, PitchFactory


@layer_registry.register
class PitchLayer(Layer):
    """Draws the themed pitch itself. Params: pitch_stripes, pitch_line_width."""
    info = PluginInfo(id="pitch", name="Pitch", category="base")
    zorder = 0

    def draw(self, ctx: LayerContext) -> None:
        PitchFactory().draw_pitch(
            ctx.ax, ctx.theme, ctx.pitch_spec, vertical=ctx.vertical,
            stripes=self.p("pitch_stripes", ctx),
            line_width=self.p("pitch_line_width", ctx),
        )


@layer_registry.register
class GridLayer(Layer):
    """Regular reference grid. Params: nx, ny, color, grid_alpha."""
    info = PluginInfo(id="grid", name="Grid", category="base")
    zorder = 1

    def draw(self, ctx: LayerContext) -> None:
        nx, ny = int(self.p("nx", ctx, 6)), int(self.p("ny", ctx, 4))
        color = self.params.get("color") or ctx.theme.colors["grid"]
        alpha = float(self.p("grid_alpha", ctx, 0.4))
        for gx in np.linspace(0, DISPLAY_LENGTH, nx + 1):
            ctx.ax.plot(*ctx.to_display([gx, gx], [0, 100]),
                        color=color, lw=0.8, ls=":", alpha=alpha, zorder=self.zorder)
        for gy in np.linspace(0, 100, ny + 1):
            ctx.ax.plot(*ctx.to_display([0, 100], [gy, gy]),
                        color=color, lw=0.8, ls=":", alpha=alpha, zorder=self.zorder)


@layer_registry.register
class ZoneLayer(Layer):
    """Shaded rectangular zones with optional labels/values.
    Params: zones = [(x0, y0, x1, y1, label?, value?), ...] canonical coords."""
    info = PluginInfo(id="zones", name="Zones", category="base")
    zorder = 2

    def draw(self, ctx: LayerContext) -> None:
        color = self.params.get("color") or ctx.theme.colors["warning"]
        for zone in self.params.get("zones", []):
            x0, y0, x1, y1 = zone[:4]
            label = zone[4] if len(zone) > 4 else ""
            value = zone[5] if len(zone) > 5 else None
            px0, py0 = ctx.to_display([x0], [y0])
            px1, py1 = ctx.to_display([x1], [y1])
            ctx.ax.add_patch(Rectangle(
                (min(px0[0], px1[0]), min(py0[0], py1[0])),
                abs(px1[0] - px0[0]), abs(py1[0] - py0[0]),
                color=color, alpha=float(self.p("zone_alpha", ctx, 0.22)),
                zorder=self.zorder))
            if label or value is not None:
                cx, cy = ctx.to_display([(x0 + x1) / 2], [(y0 + y1) / 2])
                text = f"{value}" if value is not None else label
                ctx.ax.text(cx[0], cy[0], text, ha="center", va="center",
                            fontsize=ctx.style("label_size"), fontweight="bold",
                            color=ctx.theme.colors["text"], zorder=self.zorder + 1,
                            bbox=dict(boxstyle="round,pad=0.3",
                                      fc=ctx.theme.colors["panel"], ec="none", alpha=0.9))


@layer_registry.register
class GoalLayer(Layer):
    """Emphasized goal mouth. Params: side ('left'|'right'), color."""
    info = PluginInfo(id="goal", name="Goal", category="base")
    zorder = 3

    def draw(self, ctx: LayerContext) -> None:
        side = self.params.get("side", "right")
        color = self.params.get("color") or ctx.theme.colors["accent"]
        goal_w = ctx.pitch_spec.uy(7.32)
        y0 = (DISPLAY_WIDTH - goal_w) / 2
        x = DISPLAY_LENGTH if side == "right" else 0.0
        pts_y = [y0, y0 + goal_w]
        if ctx.vertical:
            ctx.ax.plot(pts_y, [x, x], color=color, lw=4.0, alpha=0.9,
                        solid_capstyle="butt", zorder=self.zorder)
        else:
            ctx.ax.plot([x, x], pts_y, color=color, lw=4.0, alpha=0.9,
                        solid_capstyle="butt", zorder=self.zorder)
