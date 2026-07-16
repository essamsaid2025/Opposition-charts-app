"""Spacing, sizing, radius, shadow and responsive breakpoint tokens.

A single unified sizing system so every surface uses consistent padding,
margins, corner radius and elevation. Layout constants (sidebar width, header
height) are configurable so a deployment can tune density.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class Spacing:
    # spacing scale (rem), 4px base
    space_1: str = "0.25rem"
    space_2: str = "0.5rem"
    space_3: str = "0.75rem"
    space_4: str = "1rem"
    space_5: str = "1.5rem"
    space_6: str = "2rem"
    space_8: str = "3rem"
    # radii
    radius_sm: str = "6px"
    radius_md: str = "10px"
    radius_lg: str = "14px"
    radius_xl: str = "20px"
    radius_full: str = "999px"
    # layout
    sidebar_width: str = "300px"
    sidebar_collapsed_width: str = "72px"
    header_height: str = "60px"
    footer_height: str = "34px"
    content_max_width: str = "1600px"
    # elevation (light-mode shadows; dark mode softens them in CSS)
    shadow_sm: str = "0 1px 2px rgba(16,22,30,0.06)"
    shadow_md: str = "0 4px 14px rgba(16,22,30,0.08)"
    shadow_lg: str = "0 12px 32px rgba(16,22,30,0.12)"
    # responsive breakpoints
    breakpoint_tablet: str = "768px"
    breakpoint_laptop: str = "1024px"
    breakpoint_desktop: str = "1440px"
    # motion (subtle, professional only)
    transition_fast: str = "120ms ease"
    transition_base: str = "180ms ease"

    def with_overrides(self, data: Mapping[str, Any]) -> "Spacing":
        def pick(cfg_key: str, current: str) -> str:
            value = data.get(cfg_key)
            if value is None:
                return current
            return f"{value}px" if isinstance(value, (int, float)) else str(value)
        return replace(
            self,
            sidebar_width=pick("sidebar_width", self.sidebar_width),
            header_height=pick("header_height", self.header_height),
            radius_md=pick("border_radius", self.radius_md),
            radius_lg=pick("border_radius", self.radius_lg) if "border_radius" in data else self.radius_lg,
        )


DEFAULT_SPACING = Spacing()
