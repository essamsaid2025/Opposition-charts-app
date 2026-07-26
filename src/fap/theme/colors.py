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
    """Neutral colours for one mode (light or dark).

    ``raised`` is the elevation layer above ``surface`` (popovers, active cards,
    header/sidebar chrome); ``hover`` is the interactive wash for rows/items;
    ``border_strong`` is a higher-contrast divider for tables and inputs. All
    optional with sensible defaults so older constructions stay valid.
    """
    bg: str
    surface: str
    surface_alt: str
    border: str
    text: str
    text_muted: str
    text_subtle: str
    overlay: str
    raised: str = ""
    hover: str = ""
    border_strong: str = ""

    def __post_init__(self) -> None:
        # frozen dataclass: fill derived defaults without mutating the contract.
        object.__setattr__(self, "raised", self.raised or self.surface_alt)
        object.__setattr__(self, "hover", self.hover or self.surface_alt)
        object.__setattr__(self, "border_strong", self.border_strong or self.border)


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
        bg="#F4F6FA", surface="#FFFFFF", surface_alt="#EDF0F6",
        border="#E1E6EF", text="#141A22", text_muted="#576070",
        text_subtle="#8A93A2", overlay="rgba(16,22,30,0.45)",
        raised="#FFFFFF", hover="#F0F3F9", border_strong="#D2D9E4"),
    dark=Surface(
        # premium neutral-slate dark (StatsBomb IQ / Hudl console): a calm,
        # low-saturation charcoal base with clearly separated elevation layers
        # and calibrated text contrast - not a naive inversion, not blue-black.
        bg="#0C0E12", surface="#16181D", surface_alt="#1E2128",
        border="#2A2E37", text="#E6E9EF", text_muted="#979DA8",
        text_subtle="#6A6F79", overlay="rgba(2,4,8,0.66)",
        raised="#1E2128", hover="#24272F", border_strong="#363B45"),
)
