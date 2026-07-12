"""Plugin builders - how ~115 visualizations exist without duplicated code.

Each builder manufactures and registers an independent Visualization plugin
class from a declarative spec (id, name, selector, styling). Every plugin
still owns its own metadata, controls and layers; rendering, theming,
filtering, legends, layouts and export all come from the framework.

Colors resolve controls first (primary/secondary/fail color pickers), then
theme roles - nothing hardcoded."""
from __future__ import annotations

from typing import Any, Callable, Sequence

import numpy as np
import pandas as pd

from fap.core.plugin import PluginInfo
from fap.core.types import Control
from fap.visuals import analysis
from fap.visuals.base import ChartVisualization, PitchVisualization, visual_registry
from fap.visuals.context import LayerContext
from fap.visuals.layers.base import Layer, layer_registry

Selector = Callable[[pd.DataFrame, LayerContext], pd.DataFrame]

MAX_EVENTS_CONTROL = Control("max_events", "Max events drawn", "int_slider",
                             default=1500, min_value=100, max_value=5000,
                             help="Arrow maps sample beyond this for legibility.")


def _sample(d: pd.DataFrame, ctx: LayerContext) -> pd.DataFrame:
    cap = int(ctx.controls.get("max_events", 1500))
    return d.sample(cap, random_state=7) if len(d) > cap else d


def _primary(ctx: LayerContext) -> str:
    return ctx.controls.get("primary_color") or ctx.theme.colors["accent"]


def _secondary(ctx: LayerContext) -> str:
    return ctx.controls.get("secondary_color") or ctx.theme.colors["accent_2"]


def _fail(ctx: LayerContext) -> str:
    return ctx.controls.get("fail_color") or ctx.theme.colors["danger"]


def _register(cls: type) -> type:
    return visual_registry.register(cls)


# ------------------------------------------------------------------ arrow maps
def arrow_map(id: str, name: str, selector: Selector, *, category: str,
              description: str = "", split_outcome: bool = True,
              curved: bool = False, ok_label: str = "Successful",
              ko_label: str = "Unsuccessful", extra_controls: tuple = (),
              extra_layers: Callable[[LayerContext, pd.DataFrame], Sequence[Layer]] | None = None
              ) -> type:
    layer_id = "curved_arrows" if curved else "arrows"

    class _ArrowMap(PitchVisualization):
        info = PluginInfo(id=id, name=name, category=category, description=description)
        requires = ("event_type", "x", "y", "end_x", "end_y")
        control_groups = ("titles", "pitch", "arrows", "markers", "colors",
                          "legend", "text", "images", "export", "layout")
        controls = (MAX_EVENTS_CONTROL,) + tuple(extra_controls)

        def layers(self, ctx: LayerContext) -> Sequence[Layer]:
            d = _sample(selector(ctx.df, ctx).dropna(subset=["x", "y", "end_x", "end_y"]), ctx)
            out: list[Layer] = []
            if split_outcome:
                ok, ko = analysis.successful(d), analysis.unsuccessful(d)
                rest = d.drop(ok.index.union(ko.index))
                if len(ok):
                    out.append(layer_registry.create(layer_id, df=ok, label=ok_label,
                                                     color=_primary(ctx)))
                if len(ko):
                    out.append(layer_registry.create(layer_id, df=ko, label=ko_label,
                                                     color=_fail(ctx), linestyle="--"))
                if len(rest):
                    out.append(layer_registry.create(layer_id, df=rest,
                                                     color=_primary(ctx)))
            else:
                out.append(layer_registry.create(layer_id, df=d, label=name,
                                                 color=_primary(ctx)))
            out.append(layer_registry.create("scatter", df=d, color=_primary(ctx),
                                             marker_size=int(ctx.style("marker_size")) // 2))
            if ctx.controls.get("show_labels"):
                out.append(layer_registry.create("labels", df=d, column="player"))
            if extra_layers:
                out.extend(extra_layers(ctx, d))
            return out

    _ArrowMap.__name__ = f"Viz_{id}"
    return _register(_ArrowMap)


# ------------------------------------------------------------------ scatter maps
def scatter_map(id: str, name: str, selector: Selector, *, category: str,
                description: str = "", color_role: str = "accent",
                by_type: bool = False, sized_by: str | None = None,
                extra_controls: tuple = ()) -> type:
    class _ScatterMap(PitchVisualization):
        info = PluginInfo(id=id, name=name, category=category, description=description)
        control_groups = ("titles", "pitch", "markers", "colors", "legend",
                          "text", "images", "export", "layout")
        controls = tuple(extra_controls)

        def layers(self, ctx: LayerContext) -> Sequence[Layer]:
            d = selector(ctx.df, ctx).dropna(subset=["x", "y"])
            out: list[Layer] = []
            if by_type and len(d):
                palette = [ctx.theme.colors[k] for k in
                           ("accent", "accent_2", "success", "warning", "danger", "grey")]
                for i, (ev, sub) in enumerate(d.groupby(d["event_type"].str.lower())):
                    out.append(layer_registry.create(
                        "scatter", df=sub, label=str(ev).title(),
                        color=palette[i % len(palette)]))
            else:
                sizes = None
                if sized_by and sized_by in d.columns and len(d):
                    values = pd.to_numeric(d[sized_by], errors="coerce").fillna(0)
                    base = float(ctx.style("marker_size"))
                    sizes = (base * 0.4 + values / max(values.max(), 1e-6) * base * 2.2).values
                out.append(layer_registry.create(
                    "scatter", df=d, label=name, sizes=sizes,
                    color=ctx.controls.get("primary_color") or ctx.theme.colors[color_role]))
            if ctx.controls.get("show_labels"):
                out.append(layer_registry.create("labels", df=d, column="player"))
            return out

    _ScatterMap.__name__ = f"Viz_{id}"
    return _register(_ScatterMap)


# ------------------------------------------------------------------ density maps
def density_map(id: str, name: str, selector: Selector, *, category: str,
                description: str = "", kind: str = "heatmap",
                use_end: bool = False, weight_xt: bool = False) -> type:
    class _DensityMap(PitchVisualization):
        info = PluginInfo(id=id, name=name, category=category, description=description)
        control_groups = ("titles", "pitch", "heatmap", "legend", "text",
                          "images", "export", "layout")

        def layers(self, ctx: LayerContext) -> Sequence[Layer]:
            d = selector(ctx.df, ctx)
            if use_end:
                d = d.dropna(subset=["end_x", "end_y"]).rename(
                    columns={"x": "_x0", "y": "_y0"}).rename(
                    columns={"end_x": "x", "end_y": "y"})
            if weight_xt and len(d):
                gains = analysis.xt_gain(d).clip(lower=0)
                d = d.loc[gains.index]
                reps = np.clip((gains * 400).round().astype(int), 1, 40)
                d = d.loc[d.index.repeat(reps)]
            return [layer_registry.create(kind, df=d,
                                          cmap=ctx.controls.get("cmap"))]

    _DensityMap.__name__ = f"Viz_{id}"
    return _register(_DensityMap)


# ------------------------------------------------------------------ zone maps
def zone_map(id: str, name: str, zones: tuple, *, category: str,
             description: str = "", selector: Selector | None = None) -> type:
    sel = selector or (lambda df, ctx: df)

    class _ZoneMap(PitchVisualization):
        info = PluginInfo(id=id, name=name, category=category, description=description)
        control_groups = ("titles", "pitch", "markers", "colors", "grid",
                          "legend", "text", "images", "export", "layout")

        def layers(self, ctx: LayerContext) -> Sequence[Layer]:
            d = sel(ctx.df, ctx).dropna(subset=["x", "y"])
            total = max(len(d), 1)
            spec = []
            for z in zones:
                inside = int(analysis.in_zone(d["x"], d["y"], z).sum())
                spec.append((*z, name, f"{inside / total * 100:.0f}%"))
            out: list[Layer] = []
            if ctx.controls.get("show_zone_overlay", True):
                out.append(layer_registry.create(
                    "zones", zones=spec,
                    color=ctx.controls.get("primary_color") or ctx.theme.colors["warning"]))
            out.append(layer_registry.create(
                "scatter", df=d[analysis.in_zone(d["x"], d["y"], zones[0]) if len(zones) == 1
                                else np.logical_or.reduce([analysis.in_zone(d["x"], d["y"], z)
                                                           for z in zones])],
                color=_primary(ctx), label="Inside zone"))
            return out

    _ZoneMap.__name__ = f"Viz_{id}"
    return _register(_ZoneMap)


# ------------------------------------------------------------------ charts
def chart(id: str, name: str, artist: Callable[[LayerContext, Any], None], *,
          category: str, description: str = "", extra_controls: tuple = ()) -> type:
    class _Chart(ChartVisualization):
        info = PluginInfo(id=id, name=name, category=category, description=description)
        controls = tuple(extra_controls)

        def layers(self, ctx: LayerContext) -> Sequence[Layer]:
            def draw(lctx: LayerContext) -> None:
                _frame_axes(lctx)
                artist(lctx, lctx.ax)
            return [layer_registry.create("custom_artist", artist=draw)]

    _Chart.__name__ = f"Viz_{id}"
    return _register(_Chart)


def _frame_axes(ctx: LayerContext) -> None:
    """Themed chart frame shared by every non-pitch chart."""
    ax, c = ctx.ax, ctx.theme.colors
    ax.set_facecolor(c["panel"])
    ax.tick_params(colors=c["text"], labelsize=ctx.style("label_size"))
    for spine in ax.spines.values():
        spine.set_color(c["grid"])
    ax.grid(axis="y", color=c["grid"], alpha=0.35, linestyle="--")
    ax.xaxis.label.set_color(c["muted"])
    ax.yaxis.label.set_color(c["muted"])
