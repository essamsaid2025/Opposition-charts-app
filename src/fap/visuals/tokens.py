"""Style tokens - the single source of styling truth.

Every layer resolves styling through StyleTokens; nothing is hardcoded in
layer code. Tokens come from three tiers (later wins):

    1. framework defaults (below)
    2. the active theme's ``tokens:`` YAML section
    3. per-visualization control values (resolved by LayerContext.style)
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from fap.themes.theme import Theme

_DEFAULTS: dict[str, Any] = {
    # typography
    "font_family": "DejaVu Sans",
    "title_size": 20, "subtitle_size": 12, "label_size": 11, "legend_size": 10,
    "title_weight": "bold", "letter_spacing": 0.0, "uppercase_titles": False,
    # spacing / layout
    "margin": 0.04, "padding": 0.02, "panel_gap": 0.06,
    "border_radius": 12, "shadow_alpha": 0.25, "shadow_offset": 1.2,
    # pitch
    "pitch_line_width": 1.6, "pitch_stripes": True, "stripe_alpha": 0.55,
    "thirds_line_style": "--", "thirds_alpha": 0.7, "lane_line_style": ":",
    # markers
    "marker_size": 80, "marker_shape": "o", "marker_edge_width": 1.1,
    "marker_alpha": 0.85, "marker_edge_color": None,      # None -> theme lines
    # arrows
    "arrow_width": 1.6, "arrow_alpha": 0.72, "arrow_head": 8.0, "arrow_curve": 0.18,
    # density
    "heat_bins": 13, "heat_alpha": 0.65, "heat_blur": 0.0, "hex_gridsize": 18,
    # legend
    "legend_loc": "lower center", "legend_ncol": 3, "legend_frame_alpha": 0.95,
    # annotations / media
    "annotation_size": 10, "watermark_alpha": 0.18, "logo_zoom": 0.12,
    "image_alpha": 1.0,
}


@dataclass(frozen=True, slots=True)
class StyleTokens:
    values: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        if key in self.values:
            return self.values[key]
        if key in _DEFAULTS:
            return _DEFAULTS[key]
        return default

    def with_overrides(self, overrides: dict[str, Any]) -> "StyleTokens":
        merged = dict(self.values)
        merged.update({k: v for k, v in overrides.items() if v is not None})
        return replace(self, values=merged)

    @classmethod
    def from_theme(cls, theme: Theme) -> "StyleTokens":
        values = dict(_DEFAULTS)
        values.update(theme.fonts or {})
        values.update(getattr(theme, "tokens", {}) or {})
        return cls(values=values)


def default_tokens() -> StyleTokens:
    return StyleTokens(values=dict(_DEFAULTS))
