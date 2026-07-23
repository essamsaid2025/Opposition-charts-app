"""Set-piece visualization builders (Phase 9.2).

Each factory manufactures and registers an independent ``Visualization`` plugin
in the EXISTING ``visual_registry``, reusing the EXISTING base classes, pitch
engine, layers, themes, tokens, legend, layout and export. No rendering code and
no pitch geometry is duplicated here - a builder only declares which set-piece
dataset it needs (``sp_dataset``) and composes existing layers over it.

The plugin reads its data from ``ctx.df`` exactly like every other visualization;
the set-piece service is responsible for building the right frame for a given
``sp_dataset`` and passing it in as the RenderContext df. That is the whole
integration surface - identical to how canonical-event maps consume ctx.df.
"""
from __future__ import annotations

from typing import Any, Callable, Sequence

import numpy as np
import pandas as pd

from fap.core.plugin import PluginInfo
from fap.visuals.base import ChartVisualization, PitchVisualization, visual_registry
from fap.visuals.context import LayerContext
from fap.visuals.layers.base import Layer, layer_registry

# category labels (Opta-style grouping in the picker)
CAT_OCCUPANCY = "Set Piece · Occupancy"
CAT_DELIVERY = "Set Piece · Delivery"
CAT_CONTACTS = "Set Piece · Contacts"
CAT_DEFENSIVE = "Set Piece · Defensive"
CAT_MOVEMENT = "Set Piece · Movement"
CAT_OUTCOMES = "Set Piece · Outcomes"
CAT_PENALTIES = "Set Piece · Penalties"


def _register(cls: type) -> type:
    return visual_registry.register(cls)


def _primary(ctx: LayerContext) -> str:
    return ctx.controls.get("primary_color") or ctx.theme.colors["accent"]


def _secondary(ctx: LayerContext) -> str:
    return ctx.controls.get("secondary_color") or ctx.theme.colors["accent_2"]


def _danger(ctx: LayerContext) -> str:
    return ctx.controls.get("fail_color") or ctx.theme.colors["danger"]


_PITCH_GROUPS = ("titles", "pitch", "markers", "colors", "legend", "text",
                 "images", "export", "layout")


def sp_heatmap(id: str, name: str, category: str, dataset: str, *,
               description: str = "", overlay_points: bool = False) -> type:
    """Density heatmap over the dataset's (x, y). Reuses the heatmap layer."""
    class _V(PitchVisualization):
        info = PluginInfo(id=id, name=name, category=category, description=description)
        requires = ("x", "y")
        sp_dataset = dataset
        sp_category = category
        control_groups = ("titles", "pitch", "heatmap", "legend", "text",
                          "images", "export", "layout")

        def layers(self, ctx: LayerContext) -> Sequence[Layer]:
            out: list[Layer] = [layer_registry.create("heatmap", cmap=ctx.controls.get("cmap"))]
            if overlay_points and len(ctx.df.dropna(subset=["x", "y"])):
                out.append(layer_registry.create("scatter", df=ctx.df, color=_primary(ctx),
                                                 marker_size=int(ctx.style("marker_size")) // 2,
                                                 marker_alpha=0.5))
            return out

    _V.__name__ = f"SPViz_{id}"
    return _register(_V)


def sp_scatter(id: str, name: str, category: str, dataset: str, *,
               description: str = "", split: str | None = None,
               size_by: str | None = None, color_role: str = "accent",
               labels: bool = False) -> type:
    """Point map. ``split`` in {team, success, won, outcome_goal}; ``size_by`` a
    column (e.g. xg) scales markers. Reuses the scatter layer."""
    class _V(PitchVisualization):
        info = PluginInfo(id=id, name=name, category=category, description=description)
        requires = ("x", "y")
        sp_dataset = dataset
        sp_category = category
        control_groups = _PITCH_GROUPS

        def layers(self, ctx: LayerContext) -> Sequence[Layer]:
            d = ctx.df.dropna(subset=["x", "y"])
            out: list[Layer] = []
            base = float(ctx.style("marker_size"))
            sizes = None
            if size_by and size_by in d.columns and len(d):
                vals = pd.to_numeric(d[size_by], errors="coerce").fillna(0.0)
                m = float(vals.max()) or 1.0
                sizes = (base * 0.5 + vals / m * base * 3.0).values
            if split == "team" and "team" in d.columns:
                palette = {"attack": _primary(ctx), "defence": _secondary(ctx)}
                for tm, sub in d.groupby("team"):
                    out.append(layer_registry.create(
                        "scatter", df=sub, label=str(tm).title(),
                        color=palette.get(str(tm), ctx.theme.colors["grey"])))
            elif split in ("success", "won") and split in d.columns:
                good = d[d[split].astype(bool)]
                bad = d[~d[split].astype(bool)]
                if len(good):
                    out.append(layer_registry.create("scatter", df=good, label="Successful",
                                                     color=ctx.theme.colors["success"]))
                if len(bad):
                    out.append(layer_registry.create("scatter", df=bad, label="Unsuccessful",
                                                     color=_danger(ctx)))
            else:
                out.append(layer_registry.create(
                    "scatter", df=d, label=name, sizes=sizes,
                    color=ctx.controls.get("primary_color") or ctx.theme.colors[color_role]))
            if labels and "player" in d.columns:
                out.append(layer_registry.create("labels", df=d, column="player"))
            return out

    _V.__name__ = f"SPViz_{id}"
    return _register(_V)


def sp_arrows(id: str, name: str, category: str, dataset: str, *,
              description: str = "", curved: bool = False,
              split: str | None = None) -> type:
    """Vector map from (x, y) -> (end_x, end_y). Reuses the arrows layer."""
    layer_id = "curved_arrows" if curved else "arrows"

    class _V(PitchVisualization):
        info = PluginInfo(id=id, name=name, category=category, description=description)
        requires = ("x", "y", "end_x", "end_y")
        sp_dataset = dataset
        sp_category = category
        control_groups = ("titles", "pitch", "arrows", "markers", "colors",
                          "legend", "text", "images", "export", "layout")

        def layers(self, ctx: LayerContext) -> Sequence[Layer]:
            d = ctx.df.dropna(subset=["x", "y", "end_x", "end_y"])
            out: list[Layer] = []
            if split == "team" and "team" in d.columns and len(d):
                palette = {"attack": _primary(ctx), "defence": _secondary(ctx)}
                for tm, sub in d.groupby("team"):
                    out.append(layer_registry.create(layer_id, df=sub, label=str(tm).title(),
                                                     color=palette.get(str(tm), _primary(ctx))))
            else:
                out.append(layer_registry.create(layer_id, df=d, label=name, color=_primary(ctx)))
            out.append(layer_registry.create("scatter", df=d, color=_primary(ctx),
                                             marker_size=int(ctx.style("marker_size")) // 2))
            return out

    _V.__name__ = f"SPViz_{id}"
    return _register(_V)


def sp_positions(id: str, name: str, category: str, dataset: str, *,
                 description: str = "", hull: bool = False, line: bool = False) -> type:
    """Average / marker positions with player labels; optional convex hull (team
    shape) or a defensive-line marker. Reuses scatter + labels + convex_hull."""
    class _V(PitchVisualization):
        info = PluginInfo(id=id, name=name, category=category, description=description)
        requires = ("x", "y")
        sp_dataset = dataset
        sp_category = category
        control_groups = _PITCH_GROUPS

        def layers(self, ctx: LayerContext) -> Sequence[Layer]:
            d = ctx.df.dropna(subset=["x", "y"])
            out: list[Layer] = []
            if hull and len(d) >= 3:
                out.append(layer_registry.create("convex_hull", df=d, color=_primary(ctx)))
            if line and len(d):
                depth = float(pd.to_numeric(d["x"], errors="coerce").min())
                out.append(layer_registry.create("custom_artist",
                                                 artist=_line_at(depth, _secondary(ctx))))
            color = None
            if "marking" in d.columns:
                cmap = {"man": _danger(ctx), "zonal": _primary(ctx), "": ctx.theme.colors["grey"]}
                color = [cmap.get(str(m), ctx.theme.colors["grey"]) for m in d["marking"]]
            out.append(layer_registry.create("scatter", df=d,
                                             colors=color, color=_primary(ctx), label=name))
            if "player" in d.columns:
                out.append(layer_registry.create("labels", df=d, column="player"))
            return out

    _V.__name__ = f"SPViz_{id}"
    return _register(_V)


def sp_zonegrid(id: str, name: str, category: str, dataset: str, *,
                description: str = "", weight: str | None = None,
                cols: int = 5, rows: int = 5,
                region: tuple[float, float, float, float] = (50.0, 100.0, 0.0, 100.0)) -> type:
    """Zone grid coloured/labelled by count or a weighted sum (e.g. xg for
    Dangerous Zones). Reuses the zones layer - no new geometry."""
    class _V(PitchVisualization):
        info = PluginInfo(id=id, name=name, category=category, description=description)
        requires = ("x", "y")
        sp_dataset = dataset
        sp_category = category
        control_groups = ("titles", "pitch", "colors", "grid", "legend",
                          "text", "images", "export", "layout")

        def layers(self, ctx: LayerContext) -> Sequence[Layer]:
            d = ctx.df.dropna(subset=["x", "y"])
            x0, x1, y0, y1 = region
            xs = pd.to_numeric(d["x"], errors="coerce")
            ys = pd.to_numeric(d["y"], errors="coerce")
            w = (pd.to_numeric(d[weight], errors="coerce").fillna(0.0)
                 if weight and weight in d.columns else pd.Series(1.0, index=d.index))
            spec = []
            total = float(w.sum()) or 1.0
            for i in range(cols):
                for j in range(rows):
                    cx0, cx1 = x0 + (x1 - x0) * i / cols, x0 + (x1 - x0) * (i + 1) / cols
                    cy0, cy1 = y0 + (y1 - y0) * j / rows, y0 + (y1 - y0) * (j + 1) / rows
                    mask = (xs >= cx0) & (xs < cx1) & (ys >= cy0) & (ys < cy1)
                    val = float(w[mask].sum())
                    if val > 0:
                        label = f"{val:.2f}" if weight else f"{int(val)}"
                        spec.append((cx0, cy0, cx1, cy1, "", label))
            if not spec:
                return []
            return [layer_registry.create("zones", zones=spec, zone_alpha=0.16,
                                          color=ctx.controls.get("primary_color")
                                          or ctx.theme.colors["accent"])]

    _V.__name__ = f"SPViz_{id}"
    return _register(_V)


def sp_chart(id: str, name: str, category: str, dataset: str,
             artist: Callable[[LayerContext], None], *, description: str = "") -> type:
    """Non-pitch chart (penalty goal grids, preference bars, timelines). Reuses
    the custom_artist layer inside the same ChartVisualization framework."""
    class _V(ChartVisualization):
        info = PluginInfo(id=id, name=name, category=category, description=description)
        requires = ()
        sp_dataset = dataset
        sp_category = category

        def layers(self, ctx: LayerContext) -> Sequence[Layer]:
            return [layer_registry.create("custom_artist", artist=artist)]

    _V.__name__ = f"SPViz_{id}"
    return _register(_V)


# ------------------------------------------------------------------ helpers
def _line_at(x_depth: float, color: str) -> Callable[[LayerContext], None]:
    def draw(ctx: LayerContext) -> None:
        xs, ys = ctx.to_display([x_depth, x_depth], [0, 100])
        ctx.ax.plot(xs, ys, color=color, lw=2.0, ls="--", alpha=0.9, zorder=9)
    return draw
