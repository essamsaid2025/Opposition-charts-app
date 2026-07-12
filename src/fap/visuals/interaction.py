"""Interactivity architecture (linked visualizations, cross-highlighting,
selection; brushing/animation hooks for later phases).

A SelectionModel is a serializable description of what is selected. The app
stores ONE selection in session state; every rendered visualization receives
it via RenderContext.meta["selection"], and the Renderer automatically adds
highlight layers - that is cross-highlighting across linked visuals with no
per-plugin code. Brushing will write SelectionModels from UI gestures;
animation will iterate FilterSet minute windows - both slot into the same
meta contract without framework changes."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

from fap.visuals.layers.base import Layer, layer_registry


@dataclass(slots=True)
class SelectionModel:
    players: tuple[str, ...] = ()
    event_types: tuple[str, ...] = ()
    sequence_ids: tuple[str, ...] = ()
    minute_range: tuple[float, float] | None = None
    source_viz: str = ""                        # which visual created it

    def is_empty(self) -> bool:
        return not (self.players or self.event_types or self.sequence_ids
                    or self.minute_range)

    def mask(self, df: pd.DataFrame) -> pd.Series:
        mask = pd.Series(False, index=df.index)
        if self.players:
            mask |= df["player"].isin(self.players)
        if self.event_types:
            mask |= df["event_type"].str.lower().isin([e.lower() for e in self.event_types])
        if self.sequence_ids:
            mask |= df["sequence_id"].astype(str).isin([str(s) for s in self.sequence_ids])
        if self.minute_range:
            lo, hi = self.minute_range
            mask |= df["time_min"].between(lo, hi)
        return mask

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SelectionModel":
        data = dict(data)
        for key in ("players", "event_types", "sequence_ids"):
            if isinstance(data.get(key), list):
                data[key] = tuple(data[key])
        if isinstance(data.get("minute_range"), list):
            data["minute_range"] = tuple(data["minute_range"])
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


def selection_layers(selection: Any, df: pd.DataFrame, theme: Any) -> list[Layer]:
    """Layers the Renderer appends automatically when a selection is active."""
    model = selection if isinstance(selection, SelectionModel) \
        else SelectionModel.from_dict(selection)
    if model.is_empty():
        return []
    selected = df[model.mask(df)]
    if selected.empty:
        return []
    return [
        layer_registry.create("glow", df=selected, color=theme.colors["warning"]),
        layer_registry.create("highlight", df=selected, color=theme.colors["warning"]),
    ]
