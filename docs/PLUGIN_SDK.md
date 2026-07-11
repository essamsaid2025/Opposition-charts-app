# Visualization Plugin SDK

A complete visualization is **one file** dropped into `src/fap/visuals/maps/`
(pitch maps) or `src/fap/visuals/charts/` (statistical charts). It is
auto-discovered at startup, appears in the UI selector, gets its control
panel generated automatically, and renders/exports through the shared
framework. You never touch framework files and never create Streamlit widgets.

## What a plugin provides - and nothing else

| Concern            | How you declare it                                        |
|--------------------|-----------------------------------------------------------|
| Metadata           | `info = PluginInfo(id=..., name=..., category=...)`       |
| Required data      | `requires = ("event_type", "x", "y", "end_x", "end_y")`   |
| Controls           | `control_groups` (shared groups) + `controls` (extras)    |
| Rendering layers   | `layers(ctx) -> [Layer, ...]`                             |

The framework handles: filtering (`FilterSet` from meta), theme + style
tokens, pitch (spec/view/orientation), layout, titles/typography,
annotations, watermark, legend, layer/figure caching and export.

## Minimal complete example

```python
# src/fap/visuals/maps/progressive_pass_map.py
from fap.core.plugin import PluginInfo
from fap.core.types import Control
from fap.visuals.base import PitchVisualization, visual_registry
from fap.visuals.layers.base import layer_registry


@visual_registry.register
class ProgressivePassMap(PitchVisualization):
    info = PluginInfo(id="progressive_pass_map", name="Progressive Pass Map",
                      category="maps", description="Passes that gain ground.")
    requires = ("event_type", "x", "y", "end_x", "end_y", "outcome")
    control_groups = ("titles", "pitch", "arrows", "markers", "legend", "layout")
    controls = (Control("min_gain", "Min. forward gain", "int_slider",
                        default=10, min_value=0, max_value=40),)

    def layers(self, ctx):
        d = ctx.df[ctx.df["event_type"].eq("pass")]
        d = d[(d["end_x"] - d["x"]) >= float(ctx.controls.get("min_gain", 10))]
        ok = d[d["outcome"].eq("successful")]
        ko = d[~d["outcome"].eq("successful")]
        return [
            layer_registry.create("arrows", df=ok, label="Completed",
                                  color=ctx.theme.colors["accent"]),
            layer_registry.create("arrows", df=ko, label="Incomplete",
                                  color=ctx.theme.colors["danger"], linestyle="--"),
            layer_registry.create("scatter", df=ok, label="Origin"),
        ]
```

That is the entire plugin. Rendering it:

```python
from fap.core.types import RenderContext
fig = ProgressivePassMap().render(RenderContext(df=canonical_df, theme=theme,
                                                controls=control_values))
```

## Layer catalogue (31 built-in)

`pitch, grid, zones, goal` · `heatmap, hexbin, color_scale` ·
`scatter, player_markers, ball, highlight, glow, shadow` ·
`arrows, curved_arrows, lines, path, trajectory` ·
`polygon, convex_hull, voronoi` · `text, labels, annotations, watermark` ·
`image, logo, svg` · `legend, timeline, custom_artist`

Every layer accepts `df=` to draw a subset, `color=`/`colors=`, `label=`
(auto-legend), `zorder=`, plus its documented params. Styling always resolves
**layer param > control value > theme token > framework default**, so a plugin
that sets nothing still looks correct in every theme.

## Control groups

`titles, pitch, markers, arrows, heatmap, legend, text, images, layout` -
compose with `control_groups`; add plugin-specific `Control`s via `controls`.
The generic UI renderer (`fap.ui.components.controls.render_controls`) builds
the widget panel; plugins contain zero UI code.

## Annotations, layouts, export

* Coach annotations arrive via `RenderContext.meta["annotations"]`
  (an `AnnotationSet` or its `to_dict()` form) - drawn automatically.
* Multi-panel output: set `layout = "comparison"` (or two_panel, four_panel,
  dashboard, split_view, report, presentation) or pass `controls["layout"]`.
* Export: `ctx_app.export_engine.export(fig, title, fmt="png|svg|pdf",
  dpi="screen|standard|print|ultra"|int, transparent=True)`;
  `batch([...])` returns a zip; `Renderer(cache).render_png(...)` serves the
  figure-byte cache on unchanged inputs.

## Custom layers

New layer types are plugins too - drop a module in `fap/visuals/layers/`:

```python
@layer_registry.register
class PressureRingLayer(Layer):
    info = PluginInfo(id="pressure_rings", name="Pressure rings", category="points")
    zorder = 7
    def draw(self, ctx):
        x, y = ctx.to_display(ctx.df["x"], ctx.df["y"])
        ...
```

## Rules of the road

1. Consume only the canonical event model (never provider formats/coords).
2. Never filter inside a plugin beyond its own semantics - global filtering
   is the FilterSet's job.
3. Never instantiate Streamlit widgets, themes or pitches yourself.
4. Keep `layers()` pure: same ctx in, same layers out (enables caching).
