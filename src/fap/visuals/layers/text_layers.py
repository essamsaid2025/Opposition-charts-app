from __future__ import annotations

from fap.core.plugin import PluginInfo
from fap.visuals.annotations import AnnotationSet
from fap.visuals.context import LayerContext
from fap.visuals.layers.base import Layer, layer_registry
from fap.visuals.typography import TextStyle


@layer_registry.register
class TextLayer(Layer):
    """Free text at a canonical position. Params: x, y, text, style kwargs."""
    info = PluginInfo(id="text", name="Text", category="text")
    zorder = 20

    def draw(self, ctx: LayerContext) -> None:
        text = self.params.get("text", "")
        if not text:
            return
        style = TextStyle(
            family=ctx.style("font_family"),
            size=float(self.params.get("size", ctx.style("annotation_size"))),
            weight=self.params.get("weight", "normal"),
            italic=bool(self.params.get("italic", False)),
            uppercase=bool(self.params.get("uppercase", False)),
            letter_spacing=float(self.params.get("letter_spacing", 0)),
            align=self.params.get("align", "center"),
            color=self.params.get("color") or ctx.theme.colors["text"],
            wrap_width=self.params.get("wrap_width"),
        )
        px, py = ctx.to_display([self.params.get("x", 50)], [self.params.get("y", 50)])
        ctx.ax.text(px[0], py[0], style.format(text), va="center",
                    zorder=self.zorder, **style.kwargs())


@layer_registry.register
class LabelLayer(Layer):
    """Per-row labels from a dataframe column. Params: column, color, dy."""
    info = PluginInfo(id="labels", name="Labels", category="text")
    zorder = 21

    def draw(self, ctx: LayerContext) -> None:
        df = self.params.get("df")
        df = ctx.df if df is None else df
        column = self.params.get("column", "player")
        d = df.dropna(subset=["x", "y"])
        if column not in d.columns or d.empty:
            return
        x, y = ctx.to_display(d["x"], d["y"])
        dy = float(self.params.get("dy", -2.4))
        color = self.params.get("color") or ctx.theme.colors["text"]
        for px, py, value in zip(x, y, d[column]):
            text = str(value).strip()
            if text and text.lower() != "nan":
                ctx.ax.text(px, py + dy, text, ha="center", va="top",
                            fontsize=max(6, ctx.style("label_size") - 2),
                            color=color, zorder=self.zorder)


@layer_registry.register
class AnnotationLayer(Layer):
    """Renders an AnnotationSet (coach notes, callouts, boxes, circles,
    numbers, highlighted players/areas). Params: annotations (AnnotationSet
    or list of dicts)."""
    info = PluginInfo(id="annotations", name="Annotations", category="text")
    zorder = 22

    def draw(self, ctx: LayerContext) -> None:
        raw = self.params.get("annotations")
        if raw is None:
            return
        ann_set = raw if isinstance(raw, AnnotationSet) else AnnotationSet.from_dict(raw)
        for a in ann_set.items:
            self._draw_one(ctx, a)

    def _draw_one(self, ctx: LayerContext, a) -> None:
        from matplotlib.patches import Circle, Rectangle
        color = a.color or ctx.theme.colors["danger"]
        size = a.size or ctx.style("annotation_size")
        px, py = ctx.to_display([a.x], [a.y])
        px, py = px[0], py[0]
        text_kw = dict(fontsize=size, color=ctx.theme.colors["text"],
                       family=ctx.style("font_family"), zorder=self.zorder)

        if a.kind in ("text", "coach_note"):
            box = dict(boxstyle="round,pad=0.4", fc=ctx.theme.colors["panel"],
                       ec=color if a.kind == "coach_note" else "none", alpha=0.92)
            ctx.ax.text(px, py, a.text, ha="center", va="center", bbox=box, **text_kw)
        elif a.kind == "callout":
            tx, ty = ctx.to_display([a.x2 if a.x2 is not None else a.x + 12],
                                    [a.y2 if a.y2 is not None else a.y + 12])
            ctx.ax.annotate(a.text, xy=(px, py), xytext=(tx[0], ty[0]),
                            arrowprops=dict(arrowstyle="->", color=color, lw=1.6),
                            bbox=dict(boxstyle="round,pad=0.35",
                                      fc=ctx.theme.colors["panel"], ec=color, alpha=0.92),
                            ha="center", **text_kw)
        elif a.kind == "arrow":
            tx, ty = ctx.to_display([a.x2 or a.x], [a.y2 or a.y])
            ctx.ax.annotate("", xy=(tx[0], ty[0]), xytext=(px, py),
                            arrowprops=dict(arrowstyle="-|>", color=color, lw=2.0),
                            zorder=self.zorder)
        elif a.kind == "box":
            tx, ty = ctx.to_display([a.x2 or a.x + 10], [a.y2 or a.y + 10])
            ctx.ax.add_patch(Rectangle((min(px, tx[0]), min(py, ty[0])),
                                       abs(tx[0] - px), abs(ty[0] - py),
                                       fill=False, edgecolor=color, lw=2.0,
                                       zorder=self.zorder))
        elif a.kind in ("circle", "player_highlight"):
            radius = (a.size or 4.0)
            ctx.ax.add_patch(Circle((px, py), radius, fill=False, edgecolor=color,
                                    lw=2.2, zorder=self.zorder))
        elif a.kind == "area_highlight":
            radius = (a.size or 8.0)
            ctx.ax.add_patch(Circle((px, py), radius, color=color, alpha=0.2,
                                    zorder=self.zorder - 18))
        elif a.kind == "number":
            ctx.ax.text(px, py, a.text or "1", ha="center", va="center",
                        fontsize=size, fontweight="bold", color=ctx.theme.colors["bg"],
                        bbox=dict(boxstyle="circle,pad=0.32", fc=color, ec="none"),
                        zorder=self.zorder)


@layer_registry.register
class WatermarkLayer(Layer):
    """Diagonal text watermark. Params: text, watermark_alpha, size."""
    info = PluginInfo(id="watermark", name="Watermark", category="text")
    zorder = 40

    def draw(self, ctx: LayerContext) -> None:
        text = self.params.get("text", "")
        if not text:
            return
        ctx.ax.text(0.5, 0.5, text, transform=ctx.ax.transAxes, ha="center", va="center",
                    fontsize=float(self.params.get("size", 42)), rotation=28,
                    color=ctx.theme.colors["muted"],
                    alpha=float(self.p("watermark_alpha", ctx)),
                    family=ctx.style("font_family"), zorder=self.zorder)
