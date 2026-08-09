"""Per-block typography / colour overrides (free-form canvas Phase 2).

An OPTIONAL override layered on top of the report's role-based theme styling. It lives on
``Block.payload["style"]`` and is ABSENT by default, so every existing block/report renders
exactly as before. One curated font list is mapped to each export backend's own font syntax
so the on-screen canvas, the HTML preview, the PDF and the Office output all agree — the
"the preview is what the export will be" guarantee extends to the override.

Shape (all keys optional; a cleaned dict only carries the keys that are actually set)::

    {"font_size": int, "font_family": "Sans"|"Serif"|"Mono", "color": "#rrggbb"}

``clean_style`` is the single normalisation point; the three exporters and the canvas all
read the cleaned dict, so there is one source of truth and no per-backend drift.
"""
from __future__ import annotations

from typing import Any

from fap.theme.typography import DEFAULT_TYPOGRAPHY

# Curated font choices. The HTML column REUSES the app's own theme font stacks (so "Sans"
# and "Mono" match the rest of the product); the PDF column uses matplotlib generic families
# (always resolvable, needs no installed font); the Office column uses ubiquitous faces.
_SERIF_HTML = 'Georgia, "Times New Roman", "Noto Serif", serif'
FONT_FAMILIES: dict[str, dict[str, str]] = {
    "Sans":  {"html": DEFAULT_TYPOGRAPHY.font_sans, "mpl": "sans-serif", "office": "Arial"},
    "Serif": {"html": _SERIF_HTML,                  "mpl": "serif",      "office": "Georgia"},
    "Mono":  {"html": DEFAULT_TYPOGRAPHY.font_mono, "mpl": "monospace",  "office": "Consolas"},
}
#: dropdown order for the UI (labels only; "" / None means "keep the theme default")
FONT_CHOICES: tuple[str, ...] = ("Sans", "Serif", "Mono")

MIN_FONT_SIZE, MAX_FONT_SIZE = 8, 96


def clean_style(raw: Any) -> dict[str, Any]:
    """Normalise a raw style mapping into a dict of ONLY the present, valid keys (or ``{}``
    when nothing is set). Invalid/blank fields are dropped, never guessed. Never raises."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    fs = raw.get("font_size")
    if isinstance(fs, (int, float)) and not isinstance(fs, bool) and fs > 0:
        out["font_size"] = max(MIN_FONT_SIZE, min(MAX_FONT_SIZE, int(fs)))
    ff = raw.get("font_family")
    if isinstance(ff, str) and ff in FONT_FAMILIES:
        out["font_family"] = ff
    col = raw.get("color")
    if isinstance(col, str) and col.strip():
        out["color"] = col.strip()
    return out


def font_for(style: dict[str, Any] | None, backend: str) -> str | None:
    """The backend-specific font string ("html"|"mpl"|"office") for a cleaned style, or
    ``None`` when no family override is set (caller keeps its own default)."""
    fam = (style or {}).get("font_family")
    spec = FONT_FAMILIES.get(fam or "")
    return spec.get(backend) if spec else None


def html_style_css(style: dict[str, Any] | None) -> str:
    """Inline CSS for the font overrides (empty string when nothing is set). Placed on the
    element wrapper, which already carries the ``role-*`` class, so an inline rule wins over
    the role stylesheet on the SAME element and cascades to its text children."""
    if not style:
        return ""
    css = ""
    if style.get("font_size"):
        css += f"font-size:{int(style['font_size'])}px;"
    fam = font_for(style, "html")
    if fam:
        css += f"font-family:{fam};"
    if style.get("color"):
        css += f"color:{style['color']};"
    return css


def hex_to_rgb(color: str | None) -> tuple[int, int, int] | None:
    """Parse ``#rrggbb`` (or ``#rgb``) into an (r, g, b) int tuple, or ``None`` if invalid.
    Backend-agnostic so DOCX/PPTX can build their own RGBColor from it."""
    if not isinstance(color, str):
        return None
    s = color.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6:
        return None
    try:
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except ValueError:
        return None
