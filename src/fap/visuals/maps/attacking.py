"""Attacking analysis plugins."""
from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd

from fap.core.plugin import PluginInfo
from fap.core.types import Control
from fap.visuals import analysis as A
from fap.visuals.base import PitchVisualization, visual_registry
from fap.visuals.context import LayerContext
from fap.visuals.display import VisualizationCapabilities
from fap.visuals.layers.base import Layer, layer_registry
from fap.visuals.maps._builders import (_fail, _labels_on, _primary, _secondary,
                                        arrow_map, density_map, scatter_map)

_C = "Attacking"

_ON_TARGET = ("goal", "saved", "on target", "on_target", "saved to post")
_OFF_TARGET = ("off target", "off_target", "wayward", "wide", "post", "off t")


def _xg_col(df: pd.DataFrame) -> pd.Series:
    """post_shot_xg column when the provider ships it, else shot_xg."""
    if "post_shot_xg" in df.columns and pd.to_numeric(
            df["post_shot_xg"], errors="coerce").notna().any():
        return pd.to_numeric(df["post_shot_xg"], errors="coerce")
    return pd.to_numeric(df["shot_xg"], errors="coerce")


class _ShotMapBase(PitchVisualization):
    """Shots sized by xG, colored by result - the base for shot variants."""
    selector = staticmethod(lambda df: A.shots(df))
    control_groups = ("titles", "pitch", "markers", "colors", "legend",
                      "text", "images", "export", "layout")
    # xG is genuinely rendered here (marker size), so both the encoding (show_xg)
    # and the numeric value (show_xg_values) are honoured, independently.
    capabilities = VisualizationCapabilities(
        legend=True, player_names=True, xg=True, xg_values=True, annotations=True)

    def layers(self, ctx: LayerContext) -> Sequence[Layer]:
        d = self.selector(ctx.df).dropna(subset=["x", "y"])
        if d.empty:
            return []
        base = float(ctx.style("marker_size"))
        xg = _xg_col(d).fillna(0.06)
        # show_xg (default on) gates ONLY the size encoding; the xG data is untouched.
        sizes = None
        if ctx.controls.get("show_xg", True):
            sizes = base * 0.5 + xg / max(xg.max(), 0.05) * base * 2.4
        result = d["shot_result"].str.lower()
        goals = d[result.eq("goal")]
        others = d[~result.eq("goal")]
        out: list[Layer] = []
        if len(others):
            out.append(layer_registry.create(
                "scatter", df=others,
                sizes=sizes.loc[others.index].values if sizes is not None else None,
                color=ctx.controls.get("primary_color") or ctx.theme.colors["panel"],
                label="Shot"))
        if len(goals):
            out.append(layer_registry.create("glow", df=goals, color=_fail(ctx)))
            out.append(layer_registry.create(
                "scatter", df=goals,
                sizes=sizes.loc[goals.index].values if sizes is not None else None,
                color=_fail(ctx), label="Goal"))
        if _labels_on(ctx):
            out.append(layer_registry.create("labels", df=d, column="player"))
        # show_xg_values (default off): print the numeric xG next to each shot.
        if ctx.controls.get("show_xg_values", False):
            out.append(layer_registry.create(
                "value_labels", df=d.assign(_xg_val=xg.to_numpy()), column="_xg_val"))
        return out


def _shot_variant(id: str, name: str, selector, description: str = "") -> type:
    cls = type(f"Viz_{id}", (_ShotMapBase,), {
        "info": PluginInfo(id=id, name=name, category=_C, description=description),
        "selector": staticmethod(selector),
    })
    return visual_registry.register(cls)


_shot_variant("shot_map", "Shot Map", lambda df: A.shots(df),
              "All shots, sized by xG, goals highlighted.")
_shot_variant("goals_map", "Goals",
              lambda df: A.shots(df)[A.shots(df)["shot_result"].str.lower().eq("goal")])
_shot_variant("shots_on_target", "Shots On Target",
              lambda df: A.shots(df)[A.shots(df)["shot_result"].str.lower().isin(_ON_TARGET)])
_shot_variant("shots_off_target", "Shots Off Target",
              lambda df: A.shots(df)[A.shots(df)["shot_result"].str.lower().isin(_OFF_TARGET)])
_shot_variant("blocked_shots", "Blocked Shots",
              lambda df: A.shots(df)[A.shots(df)["shot_result"].str.lower().eq("blocked")])
_shot_variant("big_chances", "Big Chances",
              lambda df: A.shots(df)[_xg_col(A.shots(df)).fillna(0) >= 0.3],
              "Shots with xG ≥ 0.30.")
_shot_variant("expected_goals_map", "Expected Goals",
              lambda df: A.shots(df), "Shot map emphasizing xG size encoding.")
_shot_variant("post_shot_xg", "Post Shot xG",
              lambda df: A.shots(df)[A.shots(df)["shot_result"].str.lower().isin(_ON_TARGET)],
              "On-target shots sized by post-shot xG when the provider supplies it.")

arrow_map("shot_ending_map", "Shot Ending Map",
          lambda df, ctx: A.shots(df), category=_C, split_outcome=False,
          description="Shot locations with trajectories to their end points.")
arrow_map("shot_assist_map", "Shot Assists",
          lambda df, ctx: A.key_passes(A.passes(df)), category=_C,
          split_outcome=False, description="Passes leading directly to shots.")
density_map("shot_density", "Shot Density", lambda df, ctx: A.shots(df),
            category=_C, kind="hexbin")
density_map("shot_heatmap", "Shot Heatmap", lambda df, ctx: A.shots(df), category=_C)
density_map("expected_threat_map", "Expected Threat",
            lambda df, ctx: A.movement(df), category=_C, weight_xt=True,
            description="Where the team generates threat (xT-weighted).")
scatter_map("shot_body_part", "Shot Body Part",
            lambda df, ctx: A.shots(df), category=_C, by_type=False,
            description="Shots labeled by body part.")


@visual_registry.register
class ChanceCreatingZones(PitchVisualization):
    """Where chances come from: a grid over the origins of chance-creating passes
    (key passes, falling back to assists), each cell labelled with its count, with
    the key-pass arrows overlaid."""
    info = PluginInfo(id="chance_creating_zones", name="Chance Creating Zone",
                      category=_C,
                      description="Grid of key-pass / assist origins - where chances are created from.")
    control_groups = ("titles", "pitch", "colors", "grid", "legend",
                      "text", "images", "export", "layout")
    controls = (Control("zone_cols", "Zone columns", "int_slider",
                        default=6, min_value=3, max_value=12),
                Control("zone_rows", "Zone rows", "int_slider",
                        default=3, min_value=2, max_value=8),)

    def layers(self, ctx: LayerContext) -> Sequence[Layer]:
        passes = A.passes(ctx.df)
        chances = A.key_passes(passes)
        if chances.empty:                                 # provider didn't flag key passes
            chances = A.assists(passes)
        d = chances.dropna(subset=["x", "y"])
        if d.empty:
            return []
        cols = int(ctx.controls.get("zone_cols", 6))
        rows = int(ctx.controls.get("zone_rows", 3))
        spec = []
        for i in range(cols):
            for j in range(rows):
                zone = (100 / cols * i, 100 / rows * j,
                        100 / cols * (i + 1), 100 / rows * (j + 1))
                n = int(A.in_zone(d["x"], d["y"], zone).sum())
                if n:
                    spec.append((*zone, "", str(n)))
        out: list[Layer] = [layer_registry.create(
            "zones", zones=spec, zone_alpha=0.16,
            color=ctx.controls.get("primary_color") or ctx.theme.colors["accent"])]
        if d[["end_x", "end_y"]].notna().any().any():
            out.append(layer_registry.create("arrows", df=d.dropna(subset=["end_x", "end_y"]),
                                             color=_secondary(ctx), label="Chance created"))
        return out


@visual_registry.register
class GoalProbabilityMap(PitchVisualization):
    info = PluginInfo(id="goal_probability", name="Goal Probability", category=_C,
                      description="Shots colored on an xG color scale.")
    control_groups = ("titles", "pitch", "markers", "heatmap", "legend",
                      "text", "images", "export", "layout")
    # xG is the colour encoding here; show_xg toggles it, the colour scale is the
    # legend, and show_xg_values prints the numeric xG.
    capabilities = VisualizationCapabilities(
        legend=True, xg=True, xg_values=True, player_names=True, annotations=True)

    def layers(self, ctx: LayerContext) -> Sequence[Layer]:
        import matplotlib
        from matplotlib.colors import Normalize, to_hex
        d = A.shots(ctx.df).dropna(subset=["x", "y"])
        if d.empty:
            return []
        xg = _xg_col(d).fillna(0.05).clip(0, 1)
        show_xg = ctx.controls.get("show_xg", True)
        out: list[Layer] = []
        if show_xg:
            cmap = matplotlib.colormaps.get_cmap(ctx.controls.get("cmap") or "YlOrRd")
            colors = [to_hex(cmap(Normalize(0, max(xg.max(), 0.3))(v))) for v in xg]
            out.append(layer_registry.create("scatter", df=d, colors=colors))
            if ctx.controls.get("legend", True):        # the colour scale IS the legend
                out.append(layer_registry.create("color_scale", cmap=cmap.name, vmin=0,
                                                 vmax=float(max(xg.max(), 0.3)), label="xG"))
        else:                                            # encoding off -> plain markers
            out.append(layer_registry.create(
                "scatter", df=d,
                color=ctx.controls.get("primary_color") or ctx.theme.colors["accent"]))
        if _labels_on(ctx):
            out.append(layer_registry.create("labels", df=d, column="player"))
        if ctx.controls.get("show_xg_values", False):
            out.append(layer_registry.create(
                "value_labels", df=d.assign(_xg_val=xg.to_numpy()), column="_xg_val"))
        return out
