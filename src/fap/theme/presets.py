"""Named application theme presets.

The brief asks for several selectable "themes" — Professional Dark, Professional
Light, Club, Opta Style, Hudl Style — that all share ONE design system. A preset
is therefore not a new stylesheet: it is a small set of palette/mode overrides
layered on top of the active :class:`Branding`. The stylesheet (``css.build_css``)
and every component read the same tokens, so a preset only re-tints the system.

Pure module: no Streamlit, no matplotlib, no ``fap.themes`` (visualization) import
— it stays testable and can never touch a chart.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

from fap.theme.branding import Branding
from fap.theme.colors import Palette, Surface


@dataclass(frozen=True, slots=True)
class ThemePreset:
    """One selectable look. ``mode`` is the light/dark default; ``palette`` /
    ``surface`` hold optional overrides applied over the deployment branding."""
    id: str
    label: str
    mode: str
    description: str
    palette: Mapping[str, str]
    surface_dark: Mapping[str, str]
    surface_light: Mapping[str, str]

    def apply_to(self, base: Branding) -> Branding:
        """Return a Branding that keeps the deployment's logos/names/spacing but
        swaps in this preset's colours and default mode. The base brand's own
        configured primary colour still wins for the 'club' preset (empty
        overrides), so a club that set its colour in config keeps it."""
        p = base.palette
        if self.palette:
            p = replace(p, **{k: v for k, v in self.palette.items() if hasattr(p, k)})
        if self.surface_light:
            p = replace(p, light=_merge_surface(p.light, self.surface_light))
        if self.surface_dark:
            p = replace(p, dark=_merge_surface(p.dark, self.surface_dark))
        return replace(base, palette=p, default_mode=self.mode)


def _merge_surface(s: Surface, overrides: Mapping[str, str]) -> Surface:
    return replace(s, **{k: v for k, v in overrides.items() if hasattr(s, k)})


# Professional dark / light reuse the shipped neutral surfaces; only the mode
# changes. Club is the shipped brand (amber) with no colour override. Opta and
# Hudl re-tint the accent + chrome into their recognizable house styles.
PRESETS: dict[str, ThemePreset] = {
    "pro_dark": ThemePreset(
        "pro_dark", "Professional Dark", "dark",
        "Executive deep blue-black. The default analyst workspace.",
        palette={}, surface_dark={}, surface_light={}),
    "pro_light": ThemePreset(
        "pro_light", "Professional Light", "light",
        "Clean, bright, print-friendly. Ideal for reports and meetings.",
        palette={}, surface_dark={}, surface_light={}),
    "club": ThemePreset(
        "club", "Club Theme", "auto",
        "The club identity — brand amber on neutral surfaces, follows the OS.",
        palette={}, surface_dark={}, surface_light={}),
    "opta": ThemePreset(
        "opta", "Opta Style", "light",
        "Crisp analytical light theme with a confident data-blue accent.",
        palette={"primary": "#1F6FEB", "primary_hover": "#195BC4",
                 "accent": "#12B5A5", "info": "#1F6FEB"},
        surface_light={"bg": "#F2F5F9", "surface": "#FFFFFF",
                       "surface_alt": "#EAEFF6", "border": "#DCE3EE",
                       "border_strong": "#C7D1E0"},
        surface_dark={}),
    "hudl": ThemePreset(
        "hudl", "Hudl Style", "dark",
        "Bold broadcast dark — vivid orange on a deep navy pitch-side console.",
        palette={"primary": "#FF6300", "primary_hover": "#E85800",
                 "accent": "#FF8A3D", "info": "#37A2FF"},
        surface_dark={"bg": "#0B111C", "surface": "#131C2B",
                      "surface_alt": "#1B2740", "raised": "#1B2740",
                      "hover": "#22314F", "border": "#26344F",
                      "border_strong": "#33445F"},
        surface_light={}),
}

DEFAULT_PRESET_ID = "club"


def preset_ids() -> list[str]:
    return list(PRESETS)


def get_preset(preset_id: str | None) -> ThemePreset:
    return PRESETS.get(preset_id or "", PRESETS[DEFAULT_PRESET_ID])


def branding_for(preset_id: str | None, base: Branding) -> Branding:
    """The Branding to render for ``preset_id`` layered on the deployment brand."""
    return get_preset(preset_id).apply_to(base)


def preset_choices() -> list[tuple[str, str]]:
    """(id, label) pairs for a selector, in declaration order."""
    return [(p.id, p.label) for p in PRESETS.values()]
