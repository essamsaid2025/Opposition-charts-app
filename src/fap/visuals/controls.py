"""Generic control groups. Visualizations declare group names + their own
extras; the existing generic renderer (fap.ui.components.controls) turns the
declarations into widgets. No visualization ever creates Streamlit widgets."""
from __future__ import annotations

from fap.core.types import Control
from fap.visuals.legend import POSITIONS
from fap.visuals.pitch import PITCH_SPECS, VIEWS

MARKER_SHAPES = ("o", "s", "^", "v", "D", "h", "*", "P", "X")
FONT_FAMILIES = ("DejaVu Sans", "DejaVu Serif", "monospace")

CONTROL_GROUPS: dict[str, tuple[Control, ...]] = {
    "titles": (
        Control("title", "Title", "text", default=""),
        Control("subtitle", "Subtitle", "text", default=""),
        Control("show_title", "Show title", "checkbox", default=True),
        Control("title_size", "Title size", "int_slider", default=20, min_value=12, max_value=34),
        Control("label_size", "Label size", "int_slider", default=11, min_value=7, max_value=18),
    ),
    "pitch": (
        Control("pitch_spec", "Pitch standard", "select", default="uefa",
                options=tuple(PITCH_SPECS)),
        Control("view", "Pitch view", "select", default="full", options=tuple(VIEWS)),
        Control("orientation", "Orientation", "select", default="auto",
                options=("auto", "horizontal", "vertical")),
        Control("pitch_stripes", "Pitch stripes", "checkbox", default=True),
        Control("show_thirds", "Show thirds", "checkbox", default=False),
        Control("show_lanes", "Show lanes", "checkbox", default=False),
    ),
    "markers": (
        Control("marker_size", "Marker size", "int_slider", default=80, min_value=20, max_value=260),
        Control("marker_shape", "Marker shape", "select", default="o", options=MARKER_SHAPES),
        Control("marker_edge_width", "Marker border", "slider", default=1.1,
                min_value=0.0, max_value=4.0, step=0.1),
        Control("marker_alpha", "Marker opacity", "slider", default=0.85,
                min_value=0.2, max_value=1.0, step=0.05),
    ),
    "arrows": (
        Control("arrow_width", "Arrow width", "slider", default=1.6,
                min_value=0.5, max_value=5.0, step=0.1),
        Control("arrow_head", "Arrow head size", "slider", default=8.0,
                min_value=2.0, max_value=20.0, step=0.5),
        Control("arrow_curve", "Arrow curve", "slider", default=0.18,
                min_value=0.0, max_value=0.6, step=0.02),
        Control("arrow_alpha", "Arrow opacity", "slider", default=0.72,
                min_value=0.2, max_value=1.0, step=0.05),
    ),
    "heatmap": (
        Control("heat_bins", "Heatmap resolution", "int_slider", default=13,
                min_value=5, max_value=40),
        Control("heat_blur", "Heatmap blur", "slider", default=0.0,
                min_value=0.0, max_value=3.0, step=0.1),
        Control("heat_alpha", "Heatmap opacity", "slider", default=0.65,
                min_value=0.15, max_value=0.95, step=0.05),
    ),
    "legend": (
        Control("legend", "Show legend", "checkbox", default=True),
        Control("legend_position", "Legend position", "select", default="bottom",
                options=tuple(POSITIONS)),
    ),
    "text": (
        Control("font_family", "Font", "select", default="DejaVu Sans", options=FONT_FAMILIES),
        Control("uppercase_titles", "Uppercase titles", "checkbox", default=False),
        Control("letter_spacing", "Letter spacing", "slider", default=0.0,
                min_value=0.0, max_value=3.0, step=0.5),
        Control("show_labels", "Show labels", "checkbox", default=False),
    ),
    "images": (
        Control("watermark", "Watermark text", "text", default=""),
        Control("logo_anchor", "Logo position", "select", default="top_right",
                options=("top_left", "top_center", "top_right",
                         "bottom_left", "bottom_center", "bottom_right")),
        Control("logo_zoom", "Logo size", "slider", default=0.12,
                min_value=0.04, max_value=0.4, step=0.01),
    ),
    "colors": (
        Control("primary_color", "Primary color", "color", default=None),
        Control("secondary_color", "Secondary color", "color", default=None),
        Control("fail_color", "Unsuccessful color", "color", default=None),
    ),
    "grid": (
        Control("show_grid", "Show grid", "checkbox", default=False),
        Control("show_zone_overlay", "Show zone overlay", "checkbox", default=True),
    ),
    "export": (
        Control("export_dpi", "Export DPI", "select", default="standard",
                options=("screen", "standard", "print", "ultra")),
        Control("transparent_bg", "Transparent background", "checkbox", default=False),
    ),
    "layout": (
        Control("fig_scale", "Figure scale", "slider", default=1.0,
                min_value=0.6, max_value=1.6, step=0.05),
        Control("transparent_bg", "Transparent background", "checkbox", default=False),
    ),
}


def controls_for(*groups: str, extra: tuple[Control, ...] = ()) -> tuple[Control, ...]:
    """Compose control groups + plugin-specific controls, de-duplicated by key."""
    seen: dict[str, Control] = {}
    for group in groups:
        for control in CONTROL_GROUPS.get(group, ()):
            seen.setdefault(control.key, control)
    for control in extra:
        seen[control.key] = control
    return tuple(seen.values())
