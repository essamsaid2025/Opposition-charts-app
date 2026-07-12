"""Team analysis plugins."""
from __future__ import annotations

from typing import Sequence

import pandas as pd

from fap.core.plugin import PluginInfo
from fap.visuals import analysis as A
from fap.visuals.base import PitchVisualization, visual_registry
from fap.visuals.context import LayerContext
from fap.visuals.layers.base import Layer, layer_registry
from fap.visuals.maps._builders import _primary, _secondary, density_map

_C = "Team"

IN_POSSESSION = ("pass", "carry", "dribble", "cross", "shot")
OUT_POSSESSION = ("duel", "recovery", "interception", "clearance",
                  "tackle", "block", "pressure")


def _avg_positions(df: pd.DataFrame, kinds: tuple[str, ...] = ()) -> pd.DataFrame:
    d = df if not kinds else df[df["event_type"].str.lower().isin(kinds)]
    d = d[d["player"].str.strip().ne("")]
    return d.groupby("player").agg(
        x=("x", "mean"), y=("y", "mean"), count=("x", "size"),
        jersey_number=("jersey_number", "first")).reset_index()


class _ShapeBase(PitchVisualization):
    kinds: tuple[str, ...] = ()
    with_hull = False
    control_groups = ("titles", "pitch", "markers", "colors", "legend",
                      "text", "images", "export", "layout")

    def layers(self, ctx: LayerContext) -> Sequence[Layer]:
        nodes = _avg_positions(ctx.df, self.kinds)
        if nodes.empty:
            return []
        out: list[Layer] = []
        if self.with_hull and len(nodes) >= 3:
            out.append(layer_registry.create("convex_hull", df=nodes,
                                             color=_primary(ctx)))
        out.append(layer_registry.create("player_markers", df=nodes,
                                         color=_secondary(ctx), show_names=True))
        return out


for vid, vname, kinds, hull, desc in (
    ("average_positions", "Average Positions", (), False,
     "Mean event location per player."),
    ("average_shape", "Average Shape", (), True,
     "Average positions with team convex hull."),
    ("in_possession_shape", "In Possession Shape", IN_POSSESSION, True,
     "Shape from on-ball events."),
    ("out_possession_shape", "Out of Possession Shape", OUT_POSSESSION, True,
     "Shape from defensive events."),
    ("team_convex_hull", "Convex Hull", (), True, "Team occupation hull."),
):
    cls = type(f"Viz_{vid}", (_ShapeBase,), {
        "info": PluginInfo(id=vid, name=vname, category=_C, description=desc),
        "kinds": kinds, "with_hull": hull})
    visual_registry.register(cls)


@visual_registry.register
class TeamVoronoi(PitchVisualization):
    info = PluginInfo(id="team_voronoi", name="Voronoi / Space Control", category=_C,
                      description="Space controlled from average positions.")
    control_groups = ("titles", "pitch", "markers", "colors", "legend",
                      "text", "images", "export", "layout")

    def layers(self, ctx: LayerContext) -> Sequence[Layer]:
        nodes = _avg_positions(ctx.df)
        if len(nodes) < 4:
            return []
        return [
            layer_registry.create("voronoi", df=nodes, color=_primary(ctx)),
            layer_registry.create("player_markers", df=nodes,
                                  color=_secondary(ctx), show_names=True),
        ]


@visual_registry.register
class SpaceOccupation(TeamVoronoi):
    info = PluginInfo(id="space_occupation", name="Space Occupation", category=_C,
                      description="Voronoi space control with occupation density.")

    def layers(self, ctx: LayerContext) -> Sequence[Layer]:
        return [layer_registry.create("heatmap", heat_alpha=0.35)] + \
            list(super().layers(ctx))


density_map("occupation_map", "Occupation Map", lambda df, ctx: df, category=_C)
density_map("territory_map", "Territory Map", lambda df, ctx: A.movement(df),
            category=_C, kind="hexbin")
