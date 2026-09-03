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


# ---------------------------------------------------------------- arrowheads (Phase 5B)
# The arrowhead is an INDEPENDENT visual property of an arrow (props["arrowhead"]); the
# variant controls the body, the head controls the endpoint. This table is the single
# vocabulary; the geometry function below is the single source of truth both renderers use.
ARROWHEAD_KINDS: tuple[str, ...] = (
    "filled_triangle", "outline_triangle", "circle", "dot", "chevron", "bar", "none")
ARROWHEAD_LABELS: dict[str, str] = {
    "filled_triangle": "Filled triangle", "outline_triangle": "Outline triangle",
    "circle": "Hollow circle", "dot": "Dot", "chevron": "Chevron", "bar": "Bar",
    "none": "None"}
# When props has NO "arrowhead", arrows keep their EXISTING look (filled head via the
# classic path) — this constant is only the fallback for an explicit but unknown value.
ARROWHEAD_DEFAULT = "filled_triangle"


def _dir(x1: float, y1: float, x2: float, y2: float) -> tuple[float, float, float, float]:
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length == 0:
        return 1.0, 0.0, 0.0, 1.0
    ux, uy = dx / length, dy / length
    return ux, uy, -uy, ux                            # unit direction + unit perpendicular


def arrowhead_geometry(kind: str, x1: float, y1: float, x2: float, y2: float, *,
                       size: float = 1.0, stroke_width: float = 1.5) -> dict[str, Any]:
    """Renderer-neutral arrowhead primitives at the ``(x2,y2)`` tip, oriented along the
    line from ``(x1,y1)``. The SVG renderer and the matplotlib exporter both consume THIS
    (no duplicated head maths). Returns a dict of primitive lists in the caller's pixel
    plane plus ``trim`` (how far to pull the body endpoint back so open/closed endpoints
    don't poke through). An unknown ``kind`` falls back to the classic filled triangle;
    ``"none"`` yields no primitives.

    Keys: ``fill_polys`` (filled polygons), ``stroke_closed`` (outlined closed polygons),
    ``stroke_open`` (open polylines), ``fill_circles``/``stroke_circles`` (cx,cy,r)."""
    out: dict[str, Any] = {"fill_polys": [], "stroke_closed": [], "stroke_open": [],
                           "fill_circles": [], "stroke_circles": [], "trim": 0.0}
    k = str(kind or "").strip().lower()
    if k == "none":
        return out
    if k not in ARROWHEAD_KINDS:
        k = ARROWHEAD_DEFAULT
    ux, uy, px, py = _dir(x1, y1, x2, y2)
    s = max(0.2, float(size))
    tri_len = 11.0 * s                                # matches arrowhead_points default at size 1
    radius = 5.5 * s
    tip = (x2, y2)
    if k in ("filled_triangle", "outline_triangle"):
        bx, by = x2 - ux * tri_len, y2 - uy * tri_len
        tri = [tip, (bx + px * tri_len * 0.5, by + py * tri_len * 0.5),
               (bx - px * tri_len * 0.5, by - py * tri_len * 0.5)]
        if k == "filled_triangle":
            out["fill_polys"].append(tri)
        else:
            out["stroke_closed"].append(tri)
            out["trim"] = tri_len * 0.9
    elif k in ("circle", "dot"):
        cx, cy = x2 - ux * radius, y2 - uy * radius
        (out["fill_circles"] if k == "dot" else out["stroke_circles"]).append((cx, cy, radius))
        out["trim"] = 2.0 * radius
    elif k == "chevron":
        bx, by = x2 - ux * tri_len, y2 - uy * tri_len
        out["stroke_open"].append([(bx + px * tri_len * 0.55, by + py * tri_len * 0.55),
                                   tip, (bx - px * tri_len * 0.55, by - py * tri_len * 0.55)])
    elif k == "bar":
        h = tri_len * 0.6
        out["stroke_open"].append([(x2 + px * h, y2 + py * h), (x2 - px * h, y2 - py * h)])
    return out


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


def pitch_markings(x0: float, y0: float, x1: float, y1: float) -> dict[str, Any]:
    """Extra pitch markings a real football pitch needs but the base draw omitted: the two GOALS
    (small frames just outside each goal line), the two penalty ARCS (the "D" outside each box) and
    the four CORNER arcs. Pure geometry in the caller's pixel plane (``x0,y0``-``x1,y1`` = the pitch
    rectangle), shared by both renderers so screen + export match. These are barely visible on the
    full pitch but essential once the view is cropped to the box (att_third), where their absence
    reads as an unfinished pitch. Ellipse-sampled (rx from the pitch's x-scale, ry from its y-scale)
    so the arcs sit correctly on the non-square plane. Returns ``goals`` (x, y, w, h rects) and
    ``arcs`` (each a list of (x, y) points → a polyline)."""
    W, H = x1 - x0, y1 - y0
    cy = (y0 + y1) / 2
    # goals: 7.32 m wide, ~2 m deep, centred on each goal line, sticking just outside the pitch
    gh, gd = H * (7.32 / 68), W * (2.0 / 105)
    goals = [(x0 - gd, cy - gh / 2, gd, gh), (x1, cy - gh / 2, gd, gh)]
    arcs: list[list[tuple[float, float]]] = []
    # penalty "D": 9.15 m radius from the penalty spot, only the part OUTSIDE the 16.5 m box
    bw = W * (16.5 / 105)
    rx, ry = W * (9.15 / 105), H * (9.15 / 68)
    for left in (True, False):
        spot_x = x0 + bw * 0.65 if left else x1 - bw * 0.65
        a = max(-1.0, min(1.0, (bw * 0.35) / rx))        # cos of the box-edge angle
        th = math.acos(a)
        t0, t1 = (-th, th) if left else (math.pi - th, math.pi + th)
        arcs.append([(spot_x + rx * math.cos(t0 + (t1 - t0) * i / 20),
                      cy + ry * math.sin(t0 + (t1 - t0) * i / 20)) for i in range(21)])
    # corner quarter-circles: 1 m radius, bulging into the pitch
    rcx, rcy = W * (1.0 / 105), H * (1.0 / 68)
    for cx, cyc, t0, t1 in ((x0, y0, 0.0, math.pi / 2), (x1, y0, math.pi / 2, math.pi),
                            (x0, y1, -math.pi / 2, 0.0), (x1, y1, math.pi, 1.5 * math.pi)):
        arcs.append([(cx + rcx * math.cos(t0 + (t1 - t0) * i / 8),
                      cyc + rcy * math.sin(t0 + (t1 - t0) * i / 8)) for i in range(9)])
    return {"goals": goals, "arcs": arcs}


__all__ = ["ARROW_VARIANTS", "ARROW_VARIANT_KEYS", "variant_spec", "wave_points",
           "arrowhead_points", "freehand_points", "ARROWHEAD_KINDS", "ARROWHEAD_LABELS",
           "ARROWHEAD_DEFAULT", "arrowhead_geometry", "pitch_markings"]
