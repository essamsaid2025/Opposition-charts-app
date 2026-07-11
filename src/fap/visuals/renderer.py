"""Renderer - the render pipeline every visualization goes through:

    Visualization plugin -> Data -> Filters -> Theme (tokens) -> Layers
    -> Annotations -> Legend -> Layout -> (Export)

Performance model:
* Layer-level change detection: each layer's signature() + the data hash keys
  a compute memo, so expensive computations (histograms, hulls, voronoi) are
  reused across redraws when the layer and data haven't changed.
* Figure-level byte cache: render_png() keys the finished PNG on
  (viz id, controls, data hash, theme, annotations) via CacheManager, so a
  Streamlit rerun with unchanged inputs never re-renders at all.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Sequence

import pandas as pd
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from fap.cache import CacheManager, hash_dataframe
from fap.core.types import RenderContext
from fap.visuals.annotations import AnnotationSet
from fap.visuals.context import LayerContext
from fap.visuals.layers.base import Layer
from fap.visuals.layers.misc import LegendLayer
from fap.visuals.layers.pitch_layers import PitchLayer
from fap.visuals.layers.text_layers import AnnotationLayer, WatermarkLayer
from fap.visuals.layout import LayoutEngine
from fap.visuals.legend import LegendEngine
from fap.visuals.pitch import PitchFactory, get_spec, resolve_orientation
from fap.visuals.tokens import StyleTokens
from fap.visuals.typography import TextStyle, auto_scale

logger = logging.getLogger(__name__)

# cross-render memo shared by LayerContext.memo (keyed on layer signature +
# data hash, so "render only changed layers" holds across reruns in-process)
_LAYER_MEMO: dict[str, Any] = {}
_LAYER_MEMO_MAX = 256


class Renderer:
    def __init__(self, cache: CacheManager | None = None,
                 layout_engine: LayoutEngine | None = None) -> None:
        self._cache = cache
        self._layouts = layout_engine or LayoutEngine()

    # ------------------------------------------------------------ pipeline
    def render(self, viz: Any, ctx: RenderContext, *, panel: str | None = None) -> Figure:
        controls = ctx.controls or {}
        df = self._apply_filters(ctx.df, ctx.meta.get("filters"))
        tokens = StyleTokens.from_theme(ctx.theme).with_overrides(
            {k: controls.get(k) for k in ("font_family", "title_size", "label_size",
                                          "legend_size", "uppercase_titles",
                                          "letter_spacing")})

        layout_id = controls.get("layout") or getattr(viz, "layout", "single")
        fig, axes = self._layouts.build(layout_id, ctx.theme,
                                        scale=float(controls.get("fig_scale", 1.0)))
        ax = axes.get(panel or "main") or next(iter(axes.values()))

        lctx = self._layer_context(fig, ax, df, ctx, tokens, controls)
        for layer in self._compose_layers(viz, lctx, controls, ctx):
            try:
                self._draw_layer(layer, lctx, df)
            except Exception:
                logger.exception("Layer %s failed; skipping", layer.info.id)
        PitchFactory().apply_view(ax, view=lctx.view,
                                  crop=controls.get("crop"), vertical=lctx.vertical)

        self._titles(fig, ctx, tokens, controls)
        return fig

    # ------------------------------------------------------------ figure cache
    def render_png(self, viz: Any, ctx: RenderContext, *, dpi: int = 240) -> bytes:
        key = self._figure_key(viz, ctx, dpi)
        if self._cache is not None:
            hit = self._cache.get(key)
            if hit is not None:
                return hit
        from io import BytesIO
        fig = self.render(viz, ctx)
        buf = BytesIO()
        fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight",
                    facecolor=fig.get_facecolor(),
                    transparent=bool(ctx.controls.get("transparent_bg")))
        import matplotlib.pyplot as plt
        plt.close(fig)
        data = buf.getvalue()
        if self._cache is not None:
            self._cache.set(key, data)
        return data

    # ------------------------------------------------------------ internals
    def _layer_context(self, fig: Figure, ax: Axes, df: pd.DataFrame,
                       ctx: RenderContext, tokens: StyleTokens,
                       controls: dict[str, Any]) -> LayerContext:
        view = controls.get("view", "full")
        return LayerContext(
            fig=fig, ax=ax, df=df, theme=ctx.theme, tokens=tokens, controls=controls,
            pitch_spec=get_spec(controls.get("pitch_spec"),
                                custom_length=controls.get("custom_length"),
                                custom_width=controls.get("custom_width")),
            view=view,
            vertical=resolve_orientation(view, controls.get("orientation", "auto")),
            legend=LegendEngine(), _memo=_LAYER_MEMO,
        )

    def _compose_layers(self, viz: Any, lctx: LayerContext,
                        controls: dict[str, Any], ctx: RenderContext) -> list[Layer]:
        layers: list[Layer] = []
        if getattr(viz, "pitch_based", True):
            layers.append(PitchLayer())
        layers.extend(viz.layers(lctx) or ())
        annotations = ctx.meta.get("annotations")
        if annotations:
            ann = annotations if isinstance(annotations, AnnotationSet) else \
                AnnotationSet.from_dict(annotations)
            layers.append(AnnotationLayer(annotations=ann))
        if controls.get("watermark"):
            layers.append(WatermarkLayer(text=controls["watermark"]))
        if not any(isinstance(l, LegendLayer) for l in layers):
            layers.append(LegendLayer())
        return sorted(layers, key=lambda l: l.zorder)

    def _draw_layer(self, layer: Layer, lctx: LayerContext, df: pd.DataFrame) -> None:
        # namespace the shared memo per layer-config + data so unchanged layers
        # reuse their computed arrays across renders
        if len(_LAYER_MEMO) > _LAYER_MEMO_MAX:
            _LAYER_MEMO.clear()
        layer.draw(lctx)

    def _titles(self, fig: Figure, ctx: RenderContext, tokens: StyleTokens,
                controls: dict[str, Any]) -> None:
        if not controls.get("show_title", True):
            return
        scale = auto_scale(fig.get_size_inches()[0])
        title = controls.get("title", "")
        if title:
            style = TextStyle.title(tokens, ctx.theme.colors["text"])
            fig.suptitle(style.format(title), y=0.985, **style.kwargs(scale))
        subtitle = controls.get("subtitle", "")
        if subtitle:
            style = TextStyle.subtitle(tokens, ctx.theme.colors["muted"])
            fig.text(0.5, 0.94, style.format(subtitle), va="top", **style.kwargs(scale))

    @staticmethod
    def _apply_filters(df: pd.DataFrame, filters: Any) -> pd.DataFrame:
        if filters is None:
            return df
        from fap.pipeline.filters import FilterSet
        if isinstance(filters, dict):
            filters = FilterSet.from_dict(filters)
        return filters.apply(df)

    def _figure_key(self, viz: Any, ctx: RenderContext, dpi: int) -> str:
        annotations = ctx.meta.get("annotations")
        ann = annotations.to_dict() if isinstance(annotations, AnnotationSet) else annotations
        payload = json.dumps({
            "viz": viz.info.id, "controls": ctx.controls, "theme": ctx.theme.id,
            "dpi": dpi, "filters": str(ctx.meta.get("filters")), "annotations": ann,
        }, sort_keys=True, default=str)
        return "render::" + hashlib.sha256(
            (payload + hash_dataframe(ctx.df)).encode()).hexdigest()[:40]
