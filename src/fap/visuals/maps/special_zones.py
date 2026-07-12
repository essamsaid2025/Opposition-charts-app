"""Special zone plugins."""
from __future__ import annotations

from typing import Sequence

import numpy as np

from fap.core.plugin import PluginInfo
from fap.core.types import Control
from fap.visuals import analysis as A
from fap.visuals.base import PitchVisualization, visual_registry
from fap.visuals.context import LayerContext
from fap.visuals.layers.base import Layer, layer_registry
from fap.visuals.maps._builders import zone_map

_C = "Zones"

zone_map("zone14_map", "Zone 14", (A.ZONE_14,), category=_C,
         description="Activity share in Zone 14.")
zone_map("half_spaces_map", "Half Spaces", A.HALF_SPACES, category=_C)
zone_map("penalty_area_map", "Penalty Area", (A.PENALTY_AREA,), category=_C)
zone_map("final_third_map", "Final Third", (A.FINAL_THIRD,), category=_C)
zone_map("wide_areas_map", "Wide Areas", A.WIDE_AREAS, category=_C)
zone_map("crossing_zones_map", "Crossing Zones", A.CROSSING_ZONES, category=_C)
zone_map("golden_zone_map", "Golden Zone", (A.GOLDEN_ZONE,), category=_C)


@visual_registry.register
class CustomZones(PitchVisualization):
    info = PluginInfo(id="custom_zones", name="Custom Zones", category=_C,
                      description="Configurable grid with activity percentages.")
    control_groups = ("titles", "pitch", "colors", "grid", "legend",
                      "text", "images", "export", "layout")
    controls = (Control("zone_cols", "Zone columns", "int_slider",
                        default=6, min_value=2, max_value=12),
                Control("zone_rows", "Zone rows", "int_slider",
                        default=3, min_value=2, max_value=8),)

    def layers(self, ctx: LayerContext) -> Sequence[Layer]:
        d = ctx.df.dropna(subset=["x", "y"])
        cols = int(ctx.controls.get("zone_cols", 6))
        rows = int(ctx.controls.get("zone_rows", 3))
        total = max(len(d), 1)
        spec = []
        for i in range(cols):
            for j in range(rows):
                zone = (100 / cols * i, 100 / rows * j,
                        100 / cols * (i + 1), 100 / rows * (j + 1))
                n = int(A.in_zone(d["x"], d["y"], zone).sum())
                if n:
                    spec.append((*zone, "", f"{n / total * 100:.0f}%"))
        return [layer_registry.create(
            "zones", zones=spec, zone_alpha=0.14,
            color=ctx.controls.get("primary_color") or ctx.theme.colors["accent"])]
