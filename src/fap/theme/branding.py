"""Branding - the single, configuration-driven source of the application's
identity. Everything visual is editable from here (or from ``[branding]``
config that feeds here); nothing is hard-coded in pages.

The shipped default is the FC Masar / Right To Dream identity, pointing at the
real uploaded logo files in ``assets/logos``. A different deployment overrides
every field via configuration.

Asset loading FAILS LOUDLY: ``require_asset``/``logo_data_uri`` raise when a
logo file is missing, so a broken path surfaces as a visible error rather than
a silent fall back to generic branding.
"""
from __future__ import annotations

import base64
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from fap.theme.colors import DEFAULT_PALETTE, Palette
from fap.theme.spacing import DEFAULT_SPACING, Spacing
from fap.theme.typography import DEFAULT_TYPOGRAPHY, Typography

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
LOGOS_DIR = ASSETS_DIR / "logos"

# real uploaded brand assets (committed under assets/logos)
FC_MASAR_LOGO = str(LOGOS_DIR / "fc_masar.png")
RIGHT_TO_DREAM_LOGO = str(LOGOS_DIR / "right_to_dream.png")


# ---------------------------------------------------------------- asset loading
def asset_path(path: str) -> Path:
    """Resolve a branding asset. Absolute paths pass through; a bare name or a
    relative path resolves inside the theme ``assets`` folder."""
    p = Path(path)
    return p if p.is_absolute() else (ASSETS_DIR / path)


def require_asset(path: str) -> Path:
    """Resolve an asset, raising loudly if it is missing (no silent fallback)."""
    resolved = asset_path(path)
    if not resolved.is_file():
        raise FileNotFoundError(
            f"Branding asset not found: {path!r} (resolved to {resolved}). "
            f"Provide the real file or fix the configured path - the app will not "
            f"silently fall back to generic branding.")
    return resolved


def logo_data_uri(path: str) -> str:
    """A ``data:`` URI for a logo, for inline <img> in the shell. Fails loudly
    if the file is missing."""
    resolved = require_asset(path)
    mime = mimetypes.guess_type(resolved.name)[0] or "image/png"
    encoded = base64.b64encode(resolved.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


@dataclass(frozen=True, slots=True)
class Branding:
    platform_name: str = "Football Analysis Platform"
    organization_name: str = "Right To Dream"
    club_name: str = "FC Masar"
    tagline: str = "powered by Right To Dream"
    # primary = club badge (FC Masar); secondary = organization (Right To Dream)
    primary_logo: str = FC_MASAR_LOGO
    secondary_logo: str = RIGHT_TO_DREAM_LOGO
    favicon: str = FC_MASAR_LOGO
    palette: Palette = field(default_factory=lambda: DEFAULT_PALETTE)
    typography: Typography = field(default_factory=lambda: DEFAULT_TYPOGRAPHY)
    spacing: Spacing = field(default_factory=lambda: DEFAULT_SPACING)
    default_mode: str = "auto"            # light | dark | auto

    # -- backward-compatible aliases (older code/tests) ---------------
    @property
    def club_logo(self) -> str:
        return self.primary_logo

    @property
    def organization_logo(self) -> str:
        return self.secondary_logo

    @property
    def platform_logo(self) -> str:
        return self.primary_logo

    def validate_assets(self) -> None:
        """Raise loudly if either brand logo is missing."""
        require_asset(self.primary_logo)
        require_asset(self.secondary_logo)


DEFAULT_BRANDING = Branding()
# committed assets must exist at import time; if they don't, fail loudly now.
DEFAULT_BRANDING.validate_assets()


def load_branding(config: Mapping[str, Any] | None = None) -> Branding:
    """Build the Branding from a config mapping (Streamlit ``[branding]`` secrets
    or a plain dict), over the FC Masar / RTD default. Every field is optional;
    unknown keys are ignored. Colours/logos/names are all configurable."""
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
        primary_logo=text("primary_logo", DEFAULT_BRANDING.primary_logo),
        secondary_logo=text("secondary_logo", DEFAULT_BRANDING.secondary_logo),
        favicon=text("favicon", DEFAULT_BRANDING.favicon),
        palette=DEFAULT_PALETTE.with_overrides(data),
        typography=DEFAULT_TYPOGRAPHY.with_overrides(data),
        spacing=DEFAULT_SPACING.with_overrides(data),
        default_mode=text("default_mode", DEFAULT_BRANDING.default_mode),
    )
