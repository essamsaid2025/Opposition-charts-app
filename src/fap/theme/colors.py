"""Colour tokens for the application skin.

This is the APPLICATION palette (sidebar, header, cards, buttons) - not the
visualization figure themes, which live in ``fap.themes`` and are never touched
here. Application colours never reach a chart: matplotlib figures are rendered
to images, immune to CSS.

Brand colours are constant across light/dark; only the neutral surfaces flip.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class Surface:
    """Neutral colours for one mode (light or dark)."""
    bg: str
    surface: str
    surface_alt: str
    border: str
    text: str
    text_muted: str
    text_subtle: str
    overlay: str


@dataclass(frozen=True, slots=True)
class Palette:
    """Brand colours + the light/dark neutral surfaces."""
    primary: str
    primary_hover: str
    on_primary: str
    secondary: str
    accent: str
    success: str
    warning: str
    danger: str
    info: str
    light: Surface
    dark: Surface

    def surface_for(self, mode: str) -> Surface:
        return self.dark if mode == "dark" else self.light

    def with_overrides(self, data: Mapping[str, Any]) -> "Palette":
        """Return a copy with brand colours overridden from a config mapping.
        Recognized keys: primary/secondary/accent/success/warning/danger/info."""
        def pick(key: str, default: str) -> str:
            value = data.get(key)
            return str(value) if value else default
        return replace(
            self,
            primary=pick("primary_color", self.primary),
            secondary=pick("secondary_color", self.secondary),
            accent=pick("accent_color", self.accent),
            success=pick("success", self.success),
            warning=pick("warning", self.warning),
            danger=pick("danger", self.danger),
            info=pick("info", self.info),
        )


# FC Masar / Right To Dream identity: executive, minimal - deep charcoal
# neutrals with the club's amber-orange as the single brand accent. These are
# the configurable DEFAULTS (overridable via [branding] config), not hard-coded
# in any page or stylesheet.
DEFAULT_PALETTE = Palette(
    primary="#E07B2B",          # FC Masar / RTD amber-orange
    primary_hover="#C76A22",
    on_primary="#FFFFFF",
    secondary="#16181D",        # FC Masar shield black
    accent="#F2A24E",           # Right To Dream lighter orange
    success="#2F9E44",
    warning="#E8590C",
    danger="#E03131",
    info="#1C7ED6",
    light=Surface(
        bg="#F5F7FA", surface="#FFFFFF", surface_alt="#EEF1F6",
        border="#DDE3EC", text="#161C24", text_muted="#5B6472",
        text_subtle="#8A93A2", overlay="rgba(16,22,30,0.45)"),
    dark=Surface(
        # intentionally designed dark: deep blue-black base, elevated surfaces,
        # a visible-but-quiet border, and calibrated text contrast (not a naive
        # inversion of the light theme).
        bg="#0B0E14", surface="#141922", surface_alt="#1C2330",
        border="#262E3B", text="#E7EBF3", text_muted="#98A2B3",
        text_subtle="#69727F", overlay="rgba(3,6,12,0.60)"),
)
