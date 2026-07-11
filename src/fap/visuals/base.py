"""Visualization plugin family - Phase 5 declarative contract.

A visualization plugin now provides ONLY:
  * metadata      (info)
  * required data (requires: canonical columns)
  * controls      (control_groups + extra controls)
  * layers        (layers(ctx) -> ordered rendering layers)

The framework handles everything else: filtering, theming, tokens, pitch,
layout, annotations, legend, typography, titles, caching and export
(fap.visuals.renderer.Renderer). ``render()`` has a framework default, so a
complete visualization is one small file - see docs/PLUGIN_SDK.md.
"""
from __future__ import annotations

from abc import abstractmethod
from typing import Sequence

from matplotlib.figure import Figure

from fap.core.plugin import Plugin, PluginRegistry
from fap.core.types import Control, RenderContext
from fap.visuals.context import LayerContext
from fap.visuals.controls import controls_for
from fap.visuals.layers.base import Layer

# kept for backward compatibility with earlier phases
COMMON_CONTROLS: tuple[Control, ...] = controls_for("titles", "legend")


class Visualization(Plugin):
    # -- declarative surface ------------------------------------------------
    requires: tuple[str, ...] = ("event_type", "x", "y")   # canonical columns
    control_groups: tuple[str, ...] = ("titles", "legend", "layout")
    controls: tuple[Control, ...] = ()                     # plugin extras
    layout: str = "single"
    pitch_based: bool = True

    @property
    def all_controls(self) -> tuple[Control, ...]:
        return controls_for(*self.control_groups, extra=self.controls)

    def layers(self, ctx: LayerContext) -> Sequence[Layer]:
        """Ordered layers composing this visualization. Framework adds the
        pitch (if pitch_based), annotations, watermark and legend around
        them automatically."""
        return ()

    # -- framework-provided rendering ----------------------------------------
    def render(self, ctx: RenderContext) -> Figure:
        from fap.visuals.renderer import Renderer
        return Renderer().render(self, ctx)


class PitchVisualization(Visualization):
    """Base for pitch maps: adds pitch/marker control groups by default."""
    control_groups = ("titles", "pitch", "markers", "legend", "text", "images", "layout")


class ChartVisualization(Visualization):
    """Base for non-pitch statistical charts."""
    pitch_based = False
    control_groups = ("titles", "legend", "text", "layout")


visual_registry: PluginRegistry[Visualization] = PluginRegistry("visualization")


def load_builtin_visuals() -> None:
    from fap.core.discovery import discover_plugins
    import fap.visuals.charts as charts
    import fap.visuals.maps as maps
    from fap.visuals.layers.base import load_builtin_layers
    load_builtin_layers()
    discover_plugins(charts)
    discover_plugins(maps)
