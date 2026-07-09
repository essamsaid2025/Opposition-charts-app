"""Visualization plugins.

A visualization declares (a) metadata, (b) the controls it needs, and
(c) a pure ``render(ctx) -> Figure``. The UI renders controls generically
from the declaration and never contains per-chart code, so adding a chart
touches exactly one new file.

Pitch-based visuals inherit PitchVisualization and receive a themed,
pre-drawn pitch axes via fap.visuals.pitch.PitchFactory.
"""
from __future__ import annotations

from abc import abstractmethod

from matplotlib.figure import Figure

from fap.core.plugin import Plugin, PluginRegistry
from fap.core.types import Control, RenderContext

# Controls shared by every visual; concrete plugins extend with their own.
COMMON_CONTROLS: tuple[Control, ...] = (
    Control("title", "Chart title", "text", default=""),
    Control("show_title", "Show title", "checkbox", default=True),
    Control("title_size", "Title size", "int_slider", default=20, min_value=12, max_value=32),
    Control("label_size", "Label size", "int_slider", default=11, min_value=7, max_value=18),
    Control("legend", "Show legend", "checkbox", default=True),
)


class Visualization(Plugin):
    controls: tuple[Control, ...] = ()

    @property
    def all_controls(self) -> tuple[Control, ...]:
        return COMMON_CONTROLS + self.controls

    @abstractmethod
    def render(self, ctx: RenderContext) -> Figure: ...


class PitchVisualization(Visualization):
    """Base for maps drawn on a pitch; adds orientation/overlay controls."""
    controls = (
        Control("vertical", "Vertical pitch", "checkbox", default=False),
        Control("show_thirds", "Show thirds", "checkbox", default=True),
        Control("show_lanes", "Show lane lines", "checkbox", default=False),
    )


visual_registry: PluginRegistry[Visualization] = PluginRegistry("visualization")


def load_builtin_visuals() -> None:
    from fap.core.discovery import discover_plugins
    import fap.visuals.charts as charts
    import fap.visuals.maps as maps
    discover_plugins(charts)
    discover_plugins(maps)
