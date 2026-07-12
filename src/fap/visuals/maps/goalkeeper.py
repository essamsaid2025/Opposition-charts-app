"""Goalkeeper analysis plugins (pass/launch maps live in passing_maps)."""
from __future__ import annotations

from typing import Sequence

import pandas as pd

from fap.core.plugin import PluginInfo
from fap.visuals import analysis as A
from fap.visuals.base import ChartVisualization, visual_registry
from fap.visuals.context import LayerContext
from fap.visuals.layers.base import Layer, layer_registry
from fap.visuals.maps._builders import _frame_axes, density_map, scatter_map

_C = "Goalkeeper"

scatter_map("save_map", "Save Map",
            lambda df, ctx: df[df["event_type"].str.lower().eq("save")],
            category=_C, color_role="success")
scatter_map("gk_claims", "Claims",
            lambda df, ctx: df[df["event_type"].str.lower().eq("claim")], category=_C)
scatter_map("gk_punches", "Punches",
            lambda df, ctx: df[df["event_type"].str.lower().eq("punch")], category=_C)
scatter_map("sweeper_actions", "Sweeper Actions",
            lambda df, ctx: A.goalkeeper(df)[A.goalkeeper(df)["x"] > 16.5],
            category=_C, description="Goalkeeper actions outside the box.")
density_map("gk_positioning", "GK Positioning",
            lambda df, ctx: A.goalkeeper(df), category=_C)


class _GoalMouthBase(ChartVisualization):
    """Shots plotted across the goal mouth (end_y across the frame)."""
    selector = staticmethod(lambda df: A.shots(df))
    control_groups = ("titles", "markers", "colors", "legend", "text",
                      "export", "layout")

    def layers(self, ctx: LayerContext) -> Sequence[Layer]:
        def draw(lctx: LayerContext) -> None:
            ax, c = lctx.ax, lctx.theme.colors
            ax.set_facecolor(c["pitch"])
            # goal frame: canonical goal spans y 46.2 - 53.8 -> widen for display
            ax.plot([44, 44, 56, 56], [0, 4, 4, 0], color=c["lines"], lw=3)
            d = self.selector(lctx.df).dropna(subset=["end_y"])
            d = d[d["end_y"].between(38, 62)]
            if d.empty:
                ax.set_xlim(35, 65); ax.set_ylim(-0.5, 6); ax.axis("off")
                return
            goals = d[d["shot_result"].str.lower().eq("goal")]
            others = d.drop(goals.index)
            heights_o = pd.Series(1.2, index=others.index)
            heights_g = pd.Series(2.2, index=goals.index)
            size = float(lctx.style("marker_size"))
            if len(others):
                ax.scatter(others["end_y"], heights_o, s=size,
                           c=lctx.controls.get("primary_color") or c["grey"],
                           edgecolors=c["lines"], alpha=0.85, label="Saved / missed")
            if len(goals):
                ax.scatter(goals["end_y"], heights_g, s=size * 1.4,
                           c=lctx.controls.get("fail_color") or c["danger"],
                           edgecolors=c["lines"], label="Goal")
            ax.set_xlim(35, 65); ax.set_ylim(-0.5, 6); ax.axis("off")
            if lctx.controls.get("legend", True):
                ax.legend(loc="upper right", facecolor=c["panel"],
                          edgecolor=c["grid"], labelcolor=c["text"],
                          fontsize=lctx.style("legend_size"))
        return [layer_registry.create("custom_artist", artist=draw)]


@visual_registry.register
class GoalMouthMap(_GoalMouthBase):
    info = PluginInfo(id="goal_mouth_map", name="Goal Mouth Map", category="Attacking",
                      description="Where shots arrive across the goal frame.")


@visual_registry.register
class SaveZones(_GoalMouthBase):
    info = PluginInfo(id="save_zones", name="Save Zones", category=_C,
                      description="Goal-mouth zones where the keeper made saves.")
    selector = staticmethod(
        lambda df: A.shots(df)[A.shots(df)["shot_result"].str.lower().isin(
            ["saved", "on target", "on_target"])])
