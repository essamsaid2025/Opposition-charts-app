"""Tactical Board arrow/line geometry — pure, renderer-agnostic (Phase 3).

The SINGLE source of truth for how the semantic arrow *variants* (pass / run /
movement / pressing / defensive / dribble / shot) and freehand paths are shaped, so
the live SVG renderer (``render.py``) and the raster exporter (``export_render.py``)
draw byte-for-byte the same thing. Everything here works in a generic 2-D plane
(the caller passes already-projected pixel coordinates); no Streamlit, no matplotlib,
no SVG. Variants live as DATA (``ARROW_VARIANTS``) so a new arrow style needs no code
branch, only a table row.

Back-compat rule: an arrow with NO ``variant`` prop is legacy and must render exactly
as before — callers only reach this module's variant styling when ``variant`` is set.
"""
from __future__ import annotations

import math
from typing import Any

# variant -> style. ``color`` "" means "use the renderer's theme line colour" (so an
# arrow drawn with the default/movement variant matches the classic look). ``wave`` is
# the centreline decoration; ``dash`` is an SVG-style dash array (also honoured by the
# exporter); ``width`` overrides the 4px default; ``head`` toggles the arrowhead.
ARROW_VARIANTS: dict[str, dict[str, Any]] = {
    "pass":      {"label": "Pass",              "color": "#2f6fdb", "dash": "",      "wave": "",       "width": 4, "head": True},
    "run":       {"label": "Run",               "color": "#2e9e5b", "dash": "",      "wave": "wavy",   "width": 4, "head": True},
    "movement":  {"label": "Movement (dashed)", "color": "",        "dash": "10 8",  "wave": "",       "width": 4, "head": True},
    "pressing":  {"label": "Pressing",          "color": "#e0532b", "dash": "",      "wave": "zigzag", "width": 4, "head": True},
    "defensive": {"label": "Defensive",         "color": "#c0392b", "dash": "10 8",  "wave": "",       "width": 4, "head": True},
    "dribble":   {"label": "Dribble",           "color": "#8e44ad", "dash": "",      "wave": "wavy",   "width": 4, "head": True},
    "shot":      {"label": "Shot",              "color": "#111318", "dash": "",      "wave": "",       "width": 6, "head": True},
}

ARROW_VARIANT_KEYS: tuple[str, ...] = tuple(ARROW_VARIANTS)


def variant_spec(variant: str | None) -> dict[str, Any] | None:
    """The style row for a variant, or ``None`` for legacy/unknown (caller keeps the
    classic rendering path)."""
    v = str(variant or "").strip().lower()
    return ARROW_VARIANTS.get(v)


def _unit_perp(x1: float, y1: float, x2: float, y2: float) -> tuple[float, float, float]:
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length == 0:
        return 0.0, 0.0, 0.0
    return -dy / length, dx / length, length      # perpendicular unit vector + length


def wave_points(x1: float, y1: float, x2: float, y2: float, style: str, *,
                amplitude: float = 9.0, wavelength: float = 26.0) -> list[tuple[float, float]]:
    """Points along the line from (x1,y1) to (x2,y2), decorated per ``style``:
    ``""`` → the two endpoints (straight); ``"wavy"`` → a sine ripple; ``"zigzag"`` →
    a triangle wave. Amplitude/wavelength are in the caller's pixel units. The last
    point is exactly (x2,y2) so an arrowhead sits at the true end. Pure/deterministic."""
    if style not in ("wavy", "zigzag"):
        return [(x1, y1), (x2, y2)]
    px, py, length = _unit_perp(x1, y1, x2, y2)
    if length == 0:
        return [(x1, y1), (x2, y2)]
    ux, uy = (x2 - x1) / length, (y2 - y1) / length
    n = max(2, int(length / max(6.0, wavelength / 2)))
    pts: list[tuple[float, float]] = []
    for i in range(n + 1):
        t = i / n
        base_x, base_y = x1 + ux * length * t, y1 + uy * length * t
        # taper the wave to zero at both ends so it starts/ends cleanly on the line
        taper = math.sin(math.pi * t)
        if style == "wavy":
            off = amplitude * taper * math.sin(2 * math.pi * (length / wavelength) * t)
        else:  # zigzag: triangle wave
            frac = (length / wavelength * t) % 1.0
            tri = (4 * frac - 1) if frac < 0.5 else (3 - 4 * frac)
            off = amplitude * taper * tri
        pts.append((base_x + px * off, base_y + py * off))
    pts[-1] = (x2, y2)
    return pts


def arrowhead_points(x1: float, y1: float, x2: float, y2: float,
                     size: float = 11.0) -> list[tuple[float, float]]:
    """A filled triangular arrowhead polygon at the (x2,y2) end, oriented along the
    line. Returns [tip, barb1, barb2]. Used when the head colour must match a coloured
    variant arrow (the shared SVG ``marker`` is only the theme line colour)."""
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length == 0:
        return [(x2, y2), (x2 - size, y2 - size / 2), (x2 - size, y2 + size / 2)]
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    base_x, base_y = x2 - ux * size, y2 - uy * size
    return [(x2, y2),
            (base_x + px * size * 0.5, base_y + py * size * 0.5),
            (base_x - px * size * 0.5, base_y - py * size * 0.5)]


def freehand_points(props: dict[str, Any]) -> list[tuple[float, float]]:
    """Normalized freehand path points (0-100 pitch space) from ``props['points']``
    (a list of [x, y] or {'x','y'}). Invalid entries are skipped; never raises."""
    out: list[tuple[float, float]] = []
    for p in (props.get("points") or []):
        try:
            if isinstance(p, dict):
                out.append((float(p["x"]), float(p["y"])))
            else:
                out.append((float(p[0]), float(p[1])))
        except (KeyError, IndexError, TypeError, ValueError):
            continue
    return out


__all__ = ["ARROW_VARIANTS", "ARROW_VARIANT_KEYS", "variant_spec", "wave_points",
           "arrowhead_points", "freehand_points"]
