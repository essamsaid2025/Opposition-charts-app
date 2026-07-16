"""Application branding & theme system (the platform *skin*).

Centralized, configuration-driven look-and-feel for the app shell: colours,
typography, spacing, icons, components and the stylesheet. Everything visual is
editable from here or from ``[branding]`` configuration - nothing is hard-coded
in pages, and no real club is baked in (neutral placeholders only).

NOTE: this is the APPLICATION theme. It is distinct from ``fap.themes`` (plural),
which holds the *visualization* figure themes. Application theming never touches
a chart - matplotlib figures are images, immune to CSS - so switching light/dark
here can never alter a visualization.

Typical use in the shell:

    from fap.theme import load_branding, apply
    brand = load_branding(config)          # config-driven, professional default
    apply(brand, mode="auto")              # inject the stylesheet
"""
from fap.theme.branding import (
    DEFAULT_BRANDING, Branding, load_branding,
    PLACEHOLDER_CLUB_LOGO, PLACEHOLDER_ORG_LOGO, PLACEHOLDER_PLATFORM_LOGO,
)
from fap.theme.colors import DEFAULT_PALETTE, Palette, Surface
from fap.theme.typography import DEFAULT_TYPOGRAPHY, Typography
from fap.theme.spacing import DEFAULT_SPACING, Spacing
from fap.theme.icons import icon, icon_names, has_icon
from fap.theme.css import apply, build_css
from fap.theme import components

VALID_MODES = ("light", "dark", "auto")


def resolve_mode(requested: str | None, brand: Branding | None = None) -> str:
    """Normalize a requested theme mode to a valid one, falling back to the
    brand default then 'auto'."""
    for candidate in (requested, (brand or DEFAULT_BRANDING).default_mode, "auto"):
        if candidate in VALID_MODES:
            return candidate
    return "auto"


__all__ = [
    "Branding", "DEFAULT_BRANDING", "load_branding",
    "PLACEHOLDER_PLATFORM_LOGO", "PLACEHOLDER_CLUB_LOGO", "PLACEHOLDER_ORG_LOGO",
    "Palette", "Surface", "DEFAULT_PALETTE",
    "Typography", "DEFAULT_TYPOGRAPHY", "Spacing", "DEFAULT_SPACING",
    "icon", "icon_names", "has_icon",
    "apply", "build_css", "components", "resolve_mode", "VALID_MODES",
]
