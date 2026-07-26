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
    radius_xs: str = "4px"
    radius_sm: str = "6px"
    radius_md: str = "10px"
    radius_lg: str = "14px"
    radius_xl: str = "20px"
    radius_2xl: str = "28px"
    radius_full: str = "999px"
    # layout
    sidebar_width: str = "288px"
    sidebar_collapsed_width: str = "72px"
    header_height: str = "62px"
    footer_height: str = "34px"
    content_max_width: str = "1680px"
    # elevation (light-mode shadows; dark mode softens them in CSS). Layered,
    # low-spread shadows read as "premium SaaS" rather than a single hard drop.
    shadow_xs: str = "0 1px 1px rgba(16,22,30,0.03)"
    shadow_sm: str = "0 1px 2px rgba(16,22,30,0.04), 0 1px 2px rgba(16,22,30,0.03)"
    shadow_md: str = "0 2px 4px rgba(16,22,30,0.04), 0 6px 14px rgba(16,22,30,0.06)"
    shadow_lg: str = "0 4px 8px rgba(16,22,30,0.05), 0 14px 34px rgba(16,22,30,0.10)"
    shadow_xl: str = "0 8px 16px rgba(16,22,30,0.06), 0 24px 56px rgba(16,22,30,0.16)"
    # responsive breakpoints
    breakpoint_tablet: str = "768px"
    breakpoint_laptop: str = "1024px"
    breakpoint_desktop: str = "1440px"
    # motion (subtle, professional only)
    transition_fast: str = "120ms cubic-bezier(0.4, 0, 0.2, 1)"
    transition_base: str = "200ms cubic-bezier(0.4, 0, 0.2, 1)"
    transition_slow: str = "320ms cubic-bezier(0.4, 0, 0.2, 1)"

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
