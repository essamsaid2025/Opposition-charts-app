"""Possession / sequence plugins."""
from __future__ import annotations

from typing import Sequence

import pandas as pd

from fap.core.plugin import PluginInfo
from fap.core.types import Control
from fap.visuals import analysis as A
from fap.visuals.base import PitchVisualization, visual_registry
from fap.visuals.context import LayerContext
from fap.visuals.layers.base import Layer, layer_registry
from fap.visuals.maps._builders import _fail, _primary, _secondary

_C = "Possession"


class _SequenceMapBase(PitchVisualization):
    """Possession-chain map: numbered path + player markers + end highlight."""
    mode = "longest"           # longest | shot | specific
    control_groups = ("titles", "pitch", "markers", "arrows", "colors",
                      "legend", "text", "images", "export", "layout")
    controls = (Control("sequence_id", "Sequence ID", "text", default=""),
                Control("max_sequences", "Max sequences", "int_slider",
                        default=1, min_value=1, max_value=8),)

    def _pick(self, ctx: LayerContext) -> list[pd.DataFrame]:
        groups = dict(list(A.sequences(ctx.df)))
        if not groups:
            return []
        wanted = str(ctx.controls.get("sequence_id", "")).strip()
        if self.mode == "specific" and wanted and wanted in groups:
            return [groups[wanted].sort_values("time_min")]
        if self.mode == "shot":
            with_shot = [g for g in groups.values()
                         if g["event_type"].str.lower().eq("shot").any()]
            chosen = with_shot or list(groups.values())
        else:
            chosen = sorted(groups.values(), key=len, reverse=True)
        n = int(ctx.controls.get("max_sequences", 1))
        return [g.sort_values("time_min") for g in chosen[:n]]

    def layers(self, ctx: LayerContext) -> Sequence[Layer]:
        out: list[Layer] = []
        palette = [ctx.theme.colors[k] for k in ("accent", "accent_2", "success",
                                                 "warning", "grey")]
        for i, seq in enumerate(self._pick(ctx)):
            color = ctx.controls.get("primary_color") or palette[i % len(palette)]
            out.append(layer_registry.create("path", df=seq, color=color,
                                             number_points=len(self._pick(ctx)) == 1))
            end = seq.iloc[-1:]
            out.append(layer_registry.create("highlight", df=end, color=_fail(ctx)))
        if out:
            out.append(layer_registry.create("player_markers",
                                             df=self._pick(ctx)[0], color=_secondary(ctx)))
        return out


for vid, vname, mode, desc in (
    ("possession_chains", "Possession Chains", "longest",
     "Longest possession chains, step by step."),
    ("attacking_sequences", "Attacking Sequences", "shot",
     "Sequences ending in a shot."),
    ("passing_sequences", "Passing Sequences", "longest",
     "Chained passing moves."),
    ("sequence_builder", "Sequence Builder", "specific",
     "Inspect one chosen sequence id."),
):
    cls = type(f"Viz_{vid}", (_SequenceMapBase,), {
        "info": PluginInfo(id=vid, name=vname, category=_C, description=desc),
        "mode": mode})
    visual_registry.register(cls)
