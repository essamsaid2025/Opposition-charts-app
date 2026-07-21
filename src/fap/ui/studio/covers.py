"""Cover design presets and club-branding suggestions (pure data).

A cover template defines ONLY the design (colours, alignment, accent, logo
position) - never report content. These map onto ``CoverDesign`` (Phase 6C) which
the LayoutEngine renders. Club-branding suggestions derive designs from the
platform palette so a club instantly gets covers in its own colours.
"""
from __future__ import annotations

from typing import Any

# name -> CoverDesign field overrides (design only, no sections)
COVER_TEMPLATES: dict[str, dict[str, Any]] = {
    "Start from Blank": dict(template="blank", background_color="#ffffff", overlay_opacity=0.0,
                             alignment="left", accent_color="#E07B2B", text_color="#16181d",
                             divider=False, show_logos=True, logo_position="top"),
    "Minimal White": dict(template="minimal_white", background_color="#ffffff", overlay_opacity=0.0,
                          alignment="left", accent_color="#E07B2B", text_color="#16181d",
                          divider=True, logo_position="top"),
    "Modern Dark": dict(template="modern_dark", background_color="#0e1116", overlay_opacity=0.0,
                        alignment="left", accent_color="#E0A93B", text_color="#ffffff",
                        divider=True, logo_position="top"),
    "Opta Style": dict(template="opta", background_color="#0b1220", overlay_opacity=0.0,
                       alignment="left", accent_color="#ff2d55", text_color="#ffffff",
                       divider=True, logo_position="corner"),
    "The Athletic": dict(template="athletic", background_color="#111417", overlay_opacity=0.0,
                         alignment="left", accent_color="#e33b2e", text_color="#ffffff",
                         divider=True, logo_position="top"),
    "UEFA Technical": dict(template="uefa", background_color="#00234b", overlay_opacity=0.0,
                           alignment="center", accent_color="#c8a24a", text_color="#ffffff",
                           divider=True, logo_position="center"),
    "FIFA Report": dict(template="fifa", background_color="#0a3d2b", overlay_opacity=0.0,
                        alignment="center", accent_color="#d4af37", text_color="#ffffff",
                        divider=True, logo_position="center"),
    "Club Branding": dict(template="club", background_color="#0b1f3a", overlay_opacity=0.0,
                          alignment="left", accent_color="#d4af37", text_color="#ffffff",
                          divider=True, logo_position="top"),
    "Match Report": dict(template="match", background_color="#141414", overlay_opacity=0.25,
                         alignment="left", accent_color="#E07B2B", text_color="#ffffff",
                         divider=True, logo_position="top"),
    "Opposition Report": dict(template="opposition", background_color="#1a1030", overlay_opacity=0.2,
                              alignment="left", accent_color="#9b59b6", text_color="#ffffff",
                              divider=True, logo_position="top"),
    "Recruitment Report": dict(template="recruitment", background_color="#0d1b2a", overlay_opacity=0.0,
                               alignment="left", accent_color="#2a9d8f", text_color="#ffffff",
                               divider=True, logo_position="top"),
    "Academy Report": dict(template="academy", background_color="#132a13", overlay_opacity=0.0,
                           alignment="left", accent_color="#8ac926", text_color="#ffffff",
                           divider=True, logo_position="top"),
}

# report-type quick presets -> a cover template (design only; never content)
COVER_PRESETS: dict[str, str] = {
    "Player Report": "Minimal White",
    "Opponent Report": "Opposition Report",
    "Match Report": "Match Report",
    "Scouting Report": "Recruitment Report",
    "Tournament Report": "UEFA Technical",
    "Academy Report": "Academy Report",
    "Weekly Report": "Modern Dark",
    "Monthly Report": "Club Branding",
}


def template_design(name: str) -> dict[str, Any]:
    return dict(COVER_TEMPLATES.get(name, COVER_TEMPLATES["Minimal White"]))


def palette_from_image(data: bytes, k: int = 5) -> list[str]:
    """Extract the dominant colours from a club logo/image (hex), most common
    first, skipping near-white/near-black backgrounds. Pure (PIL); returns [] if
    the image can't be read."""
    try:
        import io
        from PIL import Image
        img = Image.open(io.BytesIO(data)).convert("RGB")
        img.thumbnail((80, 80))
        quant = img.quantize(colors=max(2, k * 3))
        pal = quant.getpalette() or []
        counts = sorted(quant.getcolors() or [], reverse=True)  # (count, index)
        out: list[str] = []
        for _count, idx in counts:
            r, g, b = pal[idx * 3:idx * 3 + 3]
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            if lum > 240 or lum < 12:          # skip white/black backgrounds
                continue
            hexc = f"#{r:02x}{g:02x}{b:02x}"
            if hexc not in out:
                out.append(hexc)
            if len(out) >= k:
                break
        return out
    except Exception:
        return []


def suggest_from_logo(data: bytes) -> dict[str, dict[str, Any]]:
    """Cover designs generated from the colours found in the club logo."""
    cols = palette_from_image(data, k=3)
    if not cols:
        return {}
    primary = cols[0]
    accent = cols[1] if len(cols) > 1 else primary
    return suggest_from_palette(primary, accent, accent)


def suggest_from_palette(primary: str, secondary: str = "", accent: str = "",
                         on_primary: str = "#ffffff") -> dict[str, dict[str, Any]]:
    """Two or three cover designs generated from the club identity, so the club
    gets covers in its own colours automatically. The user can still customise."""
    primary = primary or "#0b1f3a"
    accent = accent or secondary or "#d4af37"
    return {
        "Club Dark": dict(template="club_dark", background_color=primary, overlay_opacity=0.0,
                          alignment="left", accent_color=accent, text_color=on_primary,
                          divider=True, logo_position="top"),
        "Club Light": dict(template="club_light", background_color="#ffffff", overlay_opacity=0.0,
                           alignment="left", accent_color=primary, text_color="#16181d",
                           divider=True, logo_position="top"),
        "Club Bold": dict(template="club_bold", background_color=accent, overlay_opacity=0.0,
                          alignment="center", accent_color=primary, text_color=primary,
                          divider=True, logo_position="center"),
    }
