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
    """Shots plotted across the goal mouth on the canonical Opta goal renderer.

    Rendering only: the shot/goal selection, xG columns and result classification
    are the existing data semantics — this class merely maps ``end_y`` across the
    goal and hands the points to :mod:`fap.visuals.goal`."""
    selector = staticmethod(lambda df: A.shots(df))
    control_groups = ("titles", "markers", "colors", "legend", "text",
                      "export", "layout")
    show_difficulty_legend = True         # markers are sized by the existing xG metric

    def layers(self, ctx: LayerContext) -> Sequence[Layer]:
        def draw(lctx: LayerContext) -> None:
            from fap.visuals import goal as G
            ax = lctx.ax
            G.draw_goal(ax, lctx.theme)
            d = self.selector(lctx.df)
            if "end_y" not in d.columns:
                return
            end_y = pd.to_numeric(d["end_y"], errors="coerce")
            d = d[end_y.between(38, 62)]
            if d.empty:
                return
            end_y = pd.to_numeric(d["end_y"], errors="coerce")
            # posts sit at canonical y 44/56 -> map arrival across the goal width;
            # clamp wide (off-target) shots to just outside the posts, as in the reference
            lo, hi = -14.0, G.GOAL_WIDTH + 14.0
            xs = [min(hi, max(lo, G.map_across_goal(v, 44.0, 56.0))) for v in end_y]
            ys = [G.GOAL_HEIGHT * 0.5] * len(d)      # arrival is a horizontal distribution
            is_goal = list(d["shot_result"].astype(str).str.lower().eq("goal"))
            sizes = None                              # size by the existing xG column when present
            for col in ("post_shot_xg", "shot_xg", "xg"):
                if col in d.columns and pd.to_numeric(d[col], errors="coerce").notna().any():
                    sizes = pd.to_numeric(d[col], errors="coerce").fillna(0.0).tolist()
                    break
            G.draw_shots(ax, lctx.theme, xs=xs, ys=ys, is_goal=is_goal, sizes=sizes,
                         save_color=lctx.controls.get("primary_color"),
                         goal_color=lctx.controls.get("fail_color"),
                         legend=(lctx.legend if lctx.controls.get("legend", True) else None))
            if sizes is not None and self.show_difficulty_legend:
                lx = G.GOAL_WIDTH + G.POST + G.GROUND_EXTEND + 10.0
                G.draw_difficulty_legend(ax, lctx.theme, x=lx, y=G.GOAL_HEIGHT * 0.62)
                x0, x1 = ax.get_xlim()
                ax.set_xlim(x0, max(x1, lx + 48.0))   # give the legend room on the right
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
