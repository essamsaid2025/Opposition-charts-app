"""Passing analysis - xT, direction, networks, density, zones, entries."""
from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd
import matplotlib
from matplotlib.colors import Normalize, to_hex

from fap.core.plugin import PluginInfo
from fap.core.types import Control
from fap.visuals import analysis as A
from fap.visuals.base import PitchVisualization, visual_registry
from fap.visuals.context import LayerContext
from fap.visuals.layers.base import Layer, layer_registry
from fap.visuals.maps._builders import (MAX_EVENTS_CONTROL, _fail, _primary,
                                        _sample, _secondary, arrow_map,
                                        density_map, zone_map)

_C = "Passing"


def _xt_colored_arrows(id: str, name: str, selector, description: str) -> type:
    class _XtMap(PitchVisualization):
        info = PluginInfo(id=id, name=name, category=_C, description=description)
        control_groups = ("titles", "pitch", "arrows", "heatmap", "legend",
                          "text", "images", "export", "layout")
        controls = (MAX_EVENTS_CONTROL,)

        def layers(self, ctx: LayerContext) -> Sequence[Layer]:
            d = _sample(selector(ctx.df).dropna(
                subset=["x", "y", "end_x", "end_y"]), ctx)
            if d.empty:
                return []
            gains = A.xt_gain(d)
            d = d.loc[gains.index]
            vmax = max(float(gains.abs().max()), 1e-4)
            cmap = matplotlib.colormaps.get_cmap(ctx.controls.get("cmap") or "RdYlGn")
            colors = [to_hex(cmap(Normalize(-vmax, vmax)(g))) for g in gains]
            return [
                layer_registry.create("arrows", df=d, colors=colors),
                layer_registry.create("color_scale", cmap=cmap.name,
                                      vmin=-vmax, vmax=vmax, label="xT gained"),
            ]

    _XtMap.__name__ = f"Viz_{id}"
    return visual_registry.register(_XtMap)


_xt_colored_arrows("xt_pass_map", "Expected Threat from Passes",
                   lambda df: A.passes(df), "Passes colored by xT gained.")
_xt_colored_arrows("expected_assists", "Expected Assists",
                   lambda df: A.key_passes(A.passes(df)),
                   "Key passes colored by threat created (xA proxy).")


@visual_registry.register
class PassDirectionMap(PitchVisualization):
    info = PluginInfo(id="pass_direction_map", name="Pass Direction Map",
                      category=_C, description="Passes colored by direction.")
    control_groups = ("titles", "pitch", "arrows", "legend", "text",
                      "images", "export", "layout")
    controls = (MAX_EVENTS_CONTROL,)

    def layers(self, ctx: LayerContext) -> Sequence[Layer]:
        d = _sample(A.passes(ctx.df).dropna(subset=["x", "y", "end_x", "end_y"]), ctx)
        out: list[Layer] = []
        for sel, label, color in ((A.forward, "Forward", ctx.theme.colors["success"]),
                                  (A.sideways, "Sideways", ctx.theme.colors["grey"]),
                                  (A.backward, "Backward", _fail(ctx))):
            sub = sel(d)
            if len(sub):
                out.append(layer_registry.create("arrows", df=sub, label=label, color=color))
        return out


@visual_registry.register
class PassingLanes(PitchVisualization):
    info = PluginInfo(id="passing_lanes", name="Passing Lanes", category=_C,
                      description="Pass volume by lane with aggregated direction.")
    control_groups = ("titles", "pitch", "arrows", "colors", "grid", "legend",
                      "text", "images", "export", "layout")

    def layers(self, ctx: LayerContext) -> Sequence[Layer]:
        d = A.passes(ctx.df).dropna(subset=["x", "y", "end_x", "end_y"])
        lanes = ((0.0, 0.0, 100.0, 33.33, "Left"), (0.0, 33.33, 100.0, 66.67, "Central"),
                 (0.0, 66.67, 100.0, 100.0, "Right"))
        total = max(len(d), 1)
        spec, agg_rows = [], []
        for x0, y0, x1, y1, label in lanes:
            sub = d[A.in_zone(d["y"], d["y"], (y0, y0, y1, y1))] if False else \
                d[d["y"].between(y0, y1)]
            spec.append((x0, y0, x1, y1, label, f"{len(sub)/total*100:.0f}%"))
            if len(sub):
                agg_rows.append({"x": sub["x"].mean(), "y": (y0 + y1) / 2,
                                 "end_x": sub["end_x"].mean(), "end_y": (y0 + y1) / 2})
        out: list[Layer] = [layer_registry.create(
            "zones", zones=spec,
            color=ctx.controls.get("primary_color") or ctx.theme.colors["warning"])]
        if agg_rows:
            out.append(layer_registry.create("arrows", df=pd.DataFrame(agg_rows),
                                             color=_primary(ctx), arrow_width=3.2))
        return out


@visual_registry.register
class PassingOptions(PitchVisualization):
    info = PluginInfo(id="passing_options", name="Passing Options", category=_C,
                      description="Where a player's passes go: receivers and volume.")
    controls = (Control("focus_player", "Focus player", "text", default=""),)
    control_groups = ("titles", "pitch", "arrows", "markers", "colors",
                      "legend", "text", "images", "export", "layout")

    def layers(self, ctx: LayerContext) -> Sequence[Layer]:
        d = A.successful(A.passes(ctx.df))
        focus = str(ctx.controls.get("focus_player", "")).strip()
        if focus:
            d = d[d["player"].str.lower() == focus.lower()]
        if d.empty:
            return []
        targets = d.groupby("receiver").agg(
            x=("end_x", "mean"), y=("end_y", "mean"), count=("x", "size")).reset_index()
        targets = targets[targets["receiver"].str.strip().ne("")]
        origin = pd.DataFrame({"x": [d["x"].mean()], "y": [d["y"].mean()]})
        edges = pd.DataFrame({
            "x": d["x"].mean(), "y": d["y"].mean(),
            "end_x": targets["x"], "end_y": targets["y"]})
        base = float(ctx.style("marker_size"))
        return [
            layer_registry.create("arrows", df=edges, color=_primary(ctx)),
            layer_registry.create("scatter", df=targets.rename(columns={"receiver": "player"}),
                                  sizes=(base * 0.6 + targets["count"] /
                                         targets["count"].max() * base * 2).values,
                                  color=_secondary(ctx), label="Receivers"),
            layer_registry.create("labels",
                                  df=targets.rename(columns={"receiver": "player"}),
                                  column="player"),
            layer_registry.create("scatter", df=origin, color=_primary(ctx),
                                  marker_size=base * 1.6, label="Origin"),
        ]


class _NetworkBase(PitchVisualization):
    weighted = False
    edge_source = "pass"
    control_groups = ("titles", "pitch", "markers", "colors", "legend",
                      "text", "images", "export", "layout")
    controls = (Control("min_links", "Min. connections", "int_slider",
                        default=2, min_value=1, max_value=15),)

    def layers(self, ctx: LayerContext) -> Sequence[Layer]:
        source = A.carries(ctx.df) if self.edge_source == "carry" else ctx.df
        nodes, edges = A.pass_network(source if self.edge_source == "pass" else ctx.df,
                                      min_links=int(ctx.controls.get("min_links", 2)))
        if self.edge_source == "carry":
            d = A.carries(ctx.df)
            nodes = d.groupby("player").agg(x=("x", "mean"), y=("y", "mean"),
                                            count=("x", "size"),
                                            jersey_number=("jersey_number", "first")
                                            ).reset_index()
            edges = pd.DataFrame(columns=["p1", "p2", "count"])
        if nodes.empty:
            return []
        pos = nodes.set_index("player")
        rows = []
        for _, e in edges.iterrows():
            if e["p1"] in pos.index and e["p2"] in pos.index:
                rows.append({"x": pos.loc[e["p1"], "x"], "y": pos.loc[e["p1"], "y"],
                             "end_x": pos.loc[e["p2"], "x"], "end_y": pos.loc[e["p2"], "y"],
                             "count": e["count"]})
        out: list[Layer] = []
        if rows:
            edf = pd.DataFrame(rows)
            if self.weighted:
                for _, r in edf.iterrows():
                    out.append(layer_registry.create(
                        "lines", df=pd.DataFrame([r]), color=_primary(ctx),
                        line_width=0.8 + 4.5 * r["count"] / edf["count"].max()))
            else:
                out.append(layer_registry.create("lines", df=edf, color=_primary(ctx),
                                                 line_width=1.6))
        base = float(ctx.style("marker_size"))
        out.append(layer_registry.create(
            "player_markers",
            df=nodes.assign(sizes=base + nodes["count"] / max(nodes["count"].max(), 1) * base),
            color=_secondary(ctx), show_names=bool(ctx.controls.get("show_labels"))))
        return out


@visual_registry.register
class PassNetwork(_NetworkBase):
    info = PluginInfo(id="pass_network", name="Pass Network", category=_C,
                      description="Average positions linked by pass volume.")


@visual_registry.register
class WeightedPassNetwork(_NetworkBase):
    info = PluginInfo(id="weighted_passing_network", name="Weighted Passing Network",
                      category=_C, description="Edge width scaled by pass count.")
    weighted = True


@visual_registry.register
class PassingConnections(_NetworkBase):
    info = PluginInfo(id="passing_connections", name="Passing Connections",
                      category=_C, description="Strongest passing pairs on the pitch.")
    weighted = True
    controls = (Control("min_links", "Min. connections", "int_slider",
                        default=4, min_value=2, max_value=20),)


@visual_registry.register
class CarryNetwork(_NetworkBase):
    info = PluginInfo(id="carry_network", name="Carry Network", category="Progression",
                      description="Average carry positions per player.")
    edge_source = "carry"


# density + zone plugins
density_map("pass_density", "Pass Density", lambda df, ctx: A.passes(df),
            category=_C, kind="hexbin")
density_map("pass_heatmap", "Pass Heatmap", lambda df, ctx: A.passes(df),
            category=_C)
density_map("pass_origin_zones", "Pass Origin Zones",
            lambda df, ctx: A.passes(df), category=_C)
density_map("pass_destination_zones", "Pass Destination Zones",
            lambda df, ctx: A.passes(df), category=_C, use_end=True)

arrow_map("final_third_entries", "Final Third Entries",
          lambda df, ctx: A.entries_into(df, A.FINAL_THIRD), category=_C)
arrow_map("penalty_area_entries", "Penalty Area Entries",
          lambda df, ctx: A.entries_into(df, A.PENALTY_AREA), category=_C)
arrow_map("zone14_entries", "Zone 14 Entries",
          lambda df, ctx: A.entries_into(df, A.ZONE_14), category=_C)


@visual_registry.register
class HalfSpaceEntries(PitchVisualization):
    info = PluginInfo(id="half_space_entries", name="Half Space Entries",
                      category=_C, description="Entries into either half-space.")
    control_groups = ("titles", "pitch", "arrows", "colors", "legend",
                      "text", "images", "export", "layout")
    controls = (MAX_EVENTS_CONTROL,)

    def layers(self, ctx: LayerContext) -> Sequence[Layer]:
        left = A.entries_into(ctx.df, A.HALF_SPACES[0])
        right = A.entries_into(ctx.df, A.HALF_SPACES[1])
        d = _sample(pd.concat([left, right]), ctx)
        zones = [(*A.HALF_SPACES[0], "Left HS", len(left)),
                 (*A.HALF_SPACES[1], "Right HS", len(right))]
        return [
            layer_registry.create("zones", zones=zones,
                                  color=ctx.theme.colors["warning"]),
            layer_registry.create("arrows", df=d, color=_primary(ctx),
                                  label="Entries"),
        ]
