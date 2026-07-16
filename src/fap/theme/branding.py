"""Branding - the single, configuration-driven source of the application's
identity. Everything visual is editable from here (or from config that feeds
here); nothing is hard-coded in pages.

No real club or organization is baked in. The defaults are neutral placeholders
("FAP Analytics" / "Your Organization" / placeholder logos in assets/logos)
that a deployment replaces by editing configuration or swapping the asset files.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from fap.theme.colors import DEFAULT_PALETTE, Palette
from fap.theme.spacing import DEFAULT_SPACING, Spacing
from fap.theme.typography import DEFAULT_TYPOGRAPHY, Typography

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
LOGOS_DIR = ASSETS_DIR / "logos"

# neutral placeholder assets, replaceable without touching code
PLACEHOLDER_PLATFORM_LOGO = str(LOGOS_DIR / "platform_logo.svg")
PLACEHOLDER_CLUB_LOGO = str(LOGOS_DIR / "club_logo.svg")
PLACEHOLDER_ORG_LOGO = str(LOGOS_DIR / "organization_logo.svg")


@dataclass(frozen=True, slots=True)
class Branding:
    platform_name: str = "FAP Analytics"
    organization_name: str = "Your Organization"
    club_name: str = "Your Club"
    tagline: str = "Football Analysis Platform"
    platform_logo: str = PLACEHOLDER_PLATFORM_LOGO
    club_logo: str = PLACEHOLDER_CLUB_LOGO
    organization_logo: str = PLACEHOLDER_ORG_LOGO
    favicon: str = ""                     # asset path or empty (host default)
    palette: Palette = field(default_factory=lambda: DEFAULT_PALETTE)
    typography: Typography = field(default_factory=lambda: DEFAULT_TYPOGRAPHY)
    spacing: Spacing = field(default_factory=lambda: DEFAULT_SPACING)
    default_mode: str = "auto"            # light | dark | auto


DEFAULT_BRANDING = Branding()


def load_branding(config: Mapping[str, Any] | None = None) -> Branding:
    """Build the Branding from a config mapping (Streamlit ``[branding]`` secrets
    or a plain dict), falling back to the neutral professional default. Every
    field is optional; unknown keys are ignored."""
    data = dict(config or {})
    if not data:
        return DEFAULT_BRANDING

    def text(key: str, default: str) -> str:
        value = data.get(key)
        return str(value) if value not in (None, "") else default

    return Branding(
        platform_name=text("platform_name", DEFAULT_BRANDING.platform_name),
        organization_name=text("organization_name", DEFAULT_BRANDING.organization_name),
        club_name=text("club_name", DEFAULT_BRANDING.club_name),
        tagline=text("tagline", DEFAULT_BRANDING.tagline),
        platform_logo=text("platform_logo", DEFAULT_BRANDING.platform_logo),
        club_logo=text("club_logo", DEFAULT_BRANDING.club_logo),
        organization_logo=text("organization_logo", DEFAULT_BRANDING.organization_logo),
        favicon=text("favicon", DEFAULT_BRANDING.favicon),
        palette=DEFAULT_PALETTE.with_overrides(data),
        typography=DEFAULT_TYPOGRAPHY.with_overrides(data),
        spacing=DEFAULT_SPACING.with_overrides(data),
        default_mode=text("default_mode", DEFAULT_BRANDING.default_mode),
    )
