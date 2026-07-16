"""Application branding & theme system (Phase 5).

The theme package is the app *skin* - distinct from fap.themes (visualization).
Everything here is pure/config-driven and testable without Streamlit; the CSS
can never affect a chart, so these tests also guard that separation.
"""
import os
os.environ["FAP_TEST"] = "1"
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import fap.theme as theme
from fap.theme import (
    Branding, DEFAULT_BRANDING, DEFAULT_PALETTE, build_css, has_icon, icon,
    icon_names, load_branding, logo_data_uri, require_asset, resolve_mode,
)
from fap.theme.components import badge_html, breadcrumb_html, footer_html, kpi_card_html, logo_html

SRC = pathlib.Path(__file__).resolve().parent.parent / "src" / "fap" / "theme"


# ---------------------------------------------------------------- branding / config
def test_default_branding_is_fc_masar_right_to_dream():
    assert DEFAULT_BRANDING.platform_name == "Football Analysis Platform"
    assert DEFAULT_BRANDING.club_name == "FC Masar"
    assert DEFAULT_BRANDING.organization_name == "Right To Dream"
    assert DEFAULT_BRANDING.tagline == "powered by Right To Dream"


def test_default_logos_point_to_real_uploaded_assets():
    club = pathlib.Path(DEFAULT_BRANDING.primary_logo)
    org = pathlib.Path(DEFAULT_BRANDING.secondary_logo)
    assert club.name == "fc_masar.png" and club.is_file() and club.stat().st_size > 1000
    assert org.name == "right_to_dream.png" and org.is_file() and org.stat().st_size > 1000
    # backward-compatible aliases resolve to the same real files
    assert DEFAULT_BRANDING.club_logo == DEFAULT_BRANDING.primary_logo
    assert DEFAULT_BRANDING.organization_logo == DEFAULT_BRANDING.secondary_logo


def test_missing_asset_fails_loudly_no_silent_fallback():
    with pytest.raises(FileNotFoundError):
        require_asset("logos/does_not_exist.png")
    with pytest.raises(FileNotFoundError):
        logo_data_uri("logos/nope.png")
    with pytest.raises(FileNotFoundError):
        logo_html("logos/missing.png")


def test_logo_data_uri_embeds_real_bytes():
    uri = logo_data_uri(DEFAULT_BRANDING.primary_logo)
    assert uri.startswith("data:image/png;base64,") and len(uri) > 1000
    assert 'src="data:image/png;base64,' in logo_html(DEFAULT_BRANDING.secondary_logo, height=40)


def test_brand_colors_reflect_identity_and_stay_overridable():
    # default primary is the club amber-orange...
    assert DEFAULT_BRANDING.palette.primary.upper() == "#E07B2B"
    # ...but everything remains configurable
    assert load_branding({"primary_color": "#123456"}).palette.primary == "#123456"


def test_branding_is_configuration_driven():
    brand = load_branding({
        "platform_name": "Acme IQ", "organization_name": "Acme Group",
        "primary_color": "#FF0000", "accent_color": "#00FF00",
        "sidebar_width": 320, "border_radius": "16px", "font": "Inter, sans-serif",
        "default_mode": "dark"})
    assert brand.platform_name == "Acme IQ"
    assert brand.palette.primary == "#FF0000" and brand.palette.accent == "#00FF00"
    assert brand.spacing.sidebar_width == "320px"
    assert brand.typography.font_sans == "Inter, sans-serif"
    assert brand.default_mode == "dark"


def test_empty_config_returns_default():
    assert load_branding({}) is DEFAULT_BRANDING
    assert load_branding(None) is DEFAULT_BRANDING


def test_brand_logo_assets_exist_and_are_real_images():
    for path in (DEFAULT_BRANDING.primary_logo, DEFAULT_BRANDING.secondary_logo):
        p = pathlib.Path(path)
        assert p.exists() and p.suffix == ".png" and p.stat().st_size > 1000


# ---------------------------------------------------------------- css generation
def test_css_carries_branding_tokens():
    brand = load_branding({"primary_color": "#123456"})
    css = build_css(brand, "light")
    assert "#123456" in css and "--fap-primary" in css and css.startswith("<style")


def test_light_and_dark_differ():
    light = build_css(DEFAULT_BRANDING, "light")
    dark = build_css(DEFAULT_BRANDING, "dark")
    assert light != dark
    assert DEFAULT_PALETTE.light.bg in light and DEFAULT_PALETTE.dark.bg in dark


def test_auto_mode_supports_os_and_explicit_toggle():
    css = build_css(DEFAULT_BRANDING, "auto")
    assert "prefers-color-scheme: dark" in css
    assert "data-theme=dark" in css and "data-theme=light" in css


def test_css_includes_shell_components():
    css = build_css(DEFAULT_BRANDING, "light")
    for selector in ("[data-testid=\"stSidebar\"]", ".fap-header", ".fap-card",
                     ".fap-kpi", ".fap-badge", ".fap-footer", ".fap-nav-item"):
        assert selector in css


def test_css_includes_accessibility_and_responsive_and_motion():
    css = build_css(DEFAULT_BRANDING, "light")
    assert "focus-visible" in css                       # focus indicators
    assert "prefers-reduced-motion" in css              # subtle/no flashy motion
    assert "@media (max-width:" in css                  # responsive
    # tablet + laptop breakpoints present
    assert DEFAULT_BRANDING.spacing.breakpoint_tablet in css
    assert DEFAULT_BRANDING.spacing.breakpoint_laptop in css


def test_active_page_indicator_and_hover_states():
    css = build_css(DEFAULT_BRANDING, "light")
    assert ".fap-nav-item.active" in css and ".fap-nav-item:hover" in css


def test_resolve_mode():
    assert resolve_mode("dark") == "dark"
    assert resolve_mode("nonsense") == "auto"
    assert resolve_mode(None, load_branding({"default_mode": "light"})) == "light"


# ---------------------------------------------------------------- icons
def test_icons_are_svg_no_emoji_no_duplicates():
    names = icon_names()
    assert len(names) == len(set(names)) and len(names) >= 20
    for name in names:
        svg = icon(name)
        assert svg.startswith("<svg") and "viewBox" in svg
        assert all(ord(ch) < 0x2190 for ch in svg)      # no emoji / pictographs
    assert icon("nonexistent") == ""                     # missing icon is safe
    assert has_icon("dashboard") and not has_icon("zzz")


def test_icon_inherits_current_color():
    assert 'stroke="currentColor"' in icon("search")


# ---------------------------------------------------------------- components (pure html)
def test_component_html_builders():
    assert "fap-kpi" in kpi_card_html("Passes", "842", delta="+3%", direction="up")
    assert 'class="fap-badge success"' in badge_html("OK", "success")
    assert badge_html("x", "bogus").count("neutral") == 1     # unknown kind -> neutral
    assert "<b>Rival</b>" in breadcrumb_html(["Club", "Season", "Rival"])
    assert "fap-footer" in footer_html([("User", "Ana"), ("Version", "1.0")])


# ---------------------------------------------------------------- separation from charts
def test_pure_modules_do_not_import_streamlit():
    for module in ("branding", "colors", "typography", "spacing", "icons", "css"):
        text = (SRC / f"{module}.py").read_text(encoding="utf-8")
        # css.py imports streamlit only lazily inside apply()
        assert "\nimport streamlit" not in text


def test_theme_package_is_separate_from_visualization_themes():
    # the app theme package must not IMPORT the visualization figure-theme
    # system (docstrings may mention it to draw the distinction).
    for module in ("branding", "colors", "css", "components", "__init__"):
        text = (SRC / f"{module}.py").read_text(encoding="utf-8")
        assert "import fap.themes" not in text and "from fap.themes" not in text
        assert "import matplotlib" not in text
