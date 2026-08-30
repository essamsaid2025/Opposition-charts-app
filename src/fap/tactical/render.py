"""Tactical Board renderer (Phase 14) - a PURE state->SVG function.

This is the current "rendering layer". It reads a ``Board`` frame and returns an SVG
string; it never mutates state and has no Streamlit. Phase 15's JavaScript drag-and-
drop canvas is a drop-in replacement for THIS function (same input contract) - the
model/commands/persistence stay identical. Colours come from theme tokens the caller
resolves (so the board matches Professional Dark/Light/Club/Opta/Hudl), with a
sensible default palette for headless use.
"""
from __future__ import annotations

import html as _html
from typing import Any, Callable

from fap.tactical import visual as _v
from fap.tactical.models import Board, Frame, TacticalObject, resolve_position

# a professional default palette (overridden by the page with live theme tokens).
# "gk" is an additive role colour (goalkeepers); older palettes without it fall back
# via _c()'s DEFAULT_COLORS lookup, so nothing breaks.
DEFAULT_COLORS: dict[str, str] = {
    "grass": "#1f7a3f", "grass_alt": "#1c7139", "line": "#eaf3ec", "bg": "#0c0e12",
    "home": "#e07b2b", "away": "#2f7bd6", "ball": "#f5f5f5", "ball_line": "#1a1a1a",
    "cone": "#f0a020", "goal": "#e8e8e8", "text": "#ffffff", "accent": "#2f7bd6",
    "zone": "#2f7bd6", "mannequin": "#c9ccd2", "gk": "#22b573",
}

# board is authored in a 1050 x 680 space (10 px per pitch unit); 0-100 -> 0-1050/680
_W, _H = 1050.0, 680.0


def _esc(t: Any) -> str:
    return _html.escape(str(t))


def _c(colors: dict[str, str], key: str) -> str:
    return colors.get(key) or DEFAULT_COLORS.get(key, "#888888")


def _px(x: float, y: float) -> tuple[float, float]:
    return x / 100.0 * _W, y / 100.0 * _H


# ---------------------------------------------------------------- pitch
def _pitch_svg(board: Board, colors: dict[str, str], grid: bool) -> str:
    kind = board.pitch.kind
    line = _c(colors, "line")
    grass, grass2 = _c(colors, "grass"), _c(colors, "grass_alt")
    out = [f'<rect x="0" y="0" width="{_W}" height="{_H}" fill="{_c(colors,"bg")}"/>']
    if kind == "image":
        # Telestration background: a raster photo/frame fills the whole 1050x680 plane, and
        # every annotation object (arrows, spotlights, text, ...) is drawn on top of it exactly
        # as on a pitch. The image src (a data URL or path) lives in board.meta["bg_image"] so
        # the pitch stays a pure geometry description with no image bytes of its own.
        src = str((getattr(board, "meta", None) or {}).get("bg_image") or "")
        if src:
            out.append(f'<image href="{_esc(src)}" x="0" y="0" width="{_W}" height="{_H}" '
                       f'preserveAspectRatio="xMidYMid slice"/>')
        if grid:
            out.append(_grid(line))
        return "".join(out)
    if kind == "blank":
        if grid:
            out.append(_grid(line))
        return "".join(out)

    # mowing stripes
    stripes = 6
    sw = _W / stripes
    for i in range(stripes):
        out.append(f'<rect x="{i*sw:.1f}" y="0" width="{sw:.1f}" height="{_H}" '
                   f'fill="{grass if i%2==0 else grass2}"/>')
    lw = 3.0
    pad = 24.0
    x0, y0, x1, y1 = pad, pad, _W - pad, _H - pad
    st = f'fill="none" stroke="{line}" stroke-width="{lw}"'
    # outer + halfway + centre
    out.append(f'<rect x="{x0}" y="{y0}" width="{x1-x0}" height="{y1-y0}" {st} rx="2"/>')
    if kind != "futsal":
        cx = (x0 + x1) / 2
        out.append(f'<line x1="{cx}" y1="{y0}" x2="{cx}" y2="{y1}" {st}/>')
        out.append(f'<circle cx="{cx}" cy="{_H/2}" r="{9.15/68*(y1-y0):.1f}" {st}/>')
        out.append(f'<circle cx="{cx}" cy="{_H/2}" r="4" fill="{line}"/>')
        # penalty boxes (both ends)
        bh = (y1 - y0) * (40.32 / 68); bw = (x1 - x0) * (16.5 / 105)
        sh = (y1 - y0) * (18.32 / 68); sw2 = (x1 - x0) * (5.5 / 105)
        for left in (True, False):
            bx = x0 if left else x1 - bw
            sx = x0 if left else x1 - sw2
            out.append(f'<rect x="{bx}" y="{_H/2-bh/2}" width="{bw}" height="{bh}" {st}/>')
            out.append(f'<rect x="{sx}" y="{_H/2-sh/2}" width="{sw2}" height="{sh}" {st}/>')
            spot = x0 + bw * 0.65 if left else x1 - bw * 0.65
            out.append(f'<circle cx="{spot}" cy="{_H/2}" r="3" fill="{line}"/>')
    else:  # futsal: box + centre circle + small goals, no penalty boxes
        out.append(f'<circle cx="{(x0+x1)/2}" cy="{_H/2}" r="{(y1-y0)*0.12:.1f}" {st}/>')
    if kind == "thirds":
        for fx in (1 / 3, 2 / 3):
            xx = x0 + (x1 - x0) * fx
            out.append(f'<line x1="{xx}" y1="{y0}" x2="{xx}" y2="{y1}" stroke="{line}" '
                       f'stroke-width="1.5" stroke-dasharray="8 8" opacity="0.7"/>')
    if grid:
        out.append(_grid(line))
    return "".join(out)


def _grid(line: str) -> str:
    parts = []
    for i in range(1, 10):
        parts.append(f'<line x1="{i/10*_W}" y1="0" x2="{i/10*_W}" y2="{_H}" '
                     f'stroke="{line}" stroke-width="0.6" opacity="0.14"/>')
        parts.append(f'<line x1="0" y1="{i/10*_H}" x2="{_W}" y2="{i/10*_H}" '
                     f'stroke="{line}" stroke-width="0.6" opacity="0.14"/>')
    return "".join(parts)


# ---------------------------------------------------------------- objects
def _player(o: TacticalObject, colors: dict[str, str]) -> str:
    """Professional football marker (Phase 5C): grounded (soft shadow), a strong
    dark separation ring so it reads on any grass, the team/GK disc, a subtle jersey
    sheen, a contrast-aware centred number and an outlined name — one coherent piece.
    Sizing/colour roles come from ``fap.tactical.visual`` (single source of truth)."""
    x, y = _px(o.x, o.y); r = _v.PLAYER_R * o.scale
    p = o.props
    fill = _v.player_fill(colors, p)
    ink = _v.ink_for(fill)
    edge = _c(colors, "line")
    parts: list[str] = []
    # soft ground shadow (depth)
    parts.append(f'<ellipse cx="{x}" cy="{y+r*0.86}" rx="{r*0.82}" ry="{r*0.30}" '
                 f'fill="#000000" fill-opacity="0.22"/>')
    # goalkeeper: a dashed outer ring — clearly of the same marker family, but distinct
    if p.get("goalkeeper"):
        parts.append(f'<circle cx="{x}" cy="{y}" r="{r+3.5}" fill="none" stroke="{edge}" '
                     f'stroke-width="2" stroke-dasharray="3 3"/>')
    # facing-direction nub: drawn BEFORE the disc so the disc overdraws its base, leaving a
    # clean nub poking out the top (0deg = up). Lives inside the rotated <g>, so it swings with
    # o.rotation and agrees with the rotate handle. Keeps rotation visible on a plain player.
    wr = r * 0.32
    parts.append(f'<polygon points="{x},{y-r-r*0.5} {x-wr},{y-r*0.6} {x+wr},{y-r*0.6}" '
                 f'fill="{edge}"/>')
    # dark separation ring under the disc (contrast on light grass) + the team disc
    parts.append(f'<circle cx="{x}" cy="{y}" r="{r+1.2}" fill="#0d0f13" fill-opacity="0.55"/>')
    parts.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}" stroke="{edge}" '
                 f'stroke-width="2.4"/>')
    # subtle top sheen (jersey highlight)
    parts.append(f'<ellipse cx="{x}" cy="{y-r*0.42}" rx="{r*0.62}" ry="{r*0.34}" '
                 f'fill="#ffffff" fill-opacity="0.16"/>')
    num = p.get("number", "")
    if num not in ("", None):
        parts.append(f'<text x="{x}" y="{y+r*0.34}" text-anchor="middle" '
                     f'font-size="{r*_v.NUMBER_SCALE:.0f}" font-weight="800" fill="{ink}" '
                     f'font-family="Inter,Arial">{_esc(num)}</text>')
    if p.get("captain"):
        parts.append(f'<text x="{x+r*0.95}" y="{y-r*0.7}" font-size="{r*0.8:.0f}" '
                     f'font-weight="800" fill="{_c(colors,"accent")}" '
                     f'font-family="Inter,Arial">C</text>')
    name = p.get("name", "")
    if name:
        # outlined label (paint-order stroke) so the name stays legible over players/lines
        parts.append(f'<text x="{x}" y="{y+r+14}" text-anchor="middle" '
                     f'font-size="{_v.NAME_SIZE:.0f}" font-weight="600" fill="{_c(colors,"text")}" '
                     f'font-family="Inter,Arial" paint-order="stroke" stroke="#0c0e12" '
                     f'stroke-width="3" stroke-linejoin="round">{_esc(name)}</text>')
    return "".join(parts)


def _ball(o: TacticalObject, colors: dict[str, str], px: float | None = None,
          py: float | None = None) -> str:
    # px/py override the ball's own coords when it is "sticky" on a player (resolved by the
    # caller via resolve_position); default = the ball's stored position.
    # Phase 5C: a recognizable football — white sphere with a soft shadow, a central dark
    # pentagon and short seam spokes — instead of a plain dot. Same BALL_R token as the mpl export.
    import math
    x, y = (px, py) if px is not None else _px(o.x, o.y); r = _v.BALL_R * o.scale
    dark = _c(colors, "ball_line"); white = _c(colors, "ball")
    pr = r * 0.5
    pent = [(x + pr * math.cos(-math.pi / 2 + i * 2 * math.pi / 5),
             y + pr * math.sin(-math.pi / 2 + i * 2 * math.pi / 5)) for i in range(5)]
    parts = [f'<ellipse cx="{x}" cy="{y+r*0.9}" rx="{r*0.85}" ry="{r*0.32}" '
             f'fill="#000000" fill-opacity="0.22"/>',
             f'<circle cx="{x}" cy="{y}" r="{r}" fill="{white}" stroke="{dark}" stroke-width="1.4"/>']
    for a, b in pent:                                    # seam spokes to the rim
        ex, ey = x + (a - x) / pr * r * 0.98, y + (b - y) / pr * r * 0.98
        parts.append(f'<line x1="{a:.1f}" y1="{b:.1f}" x2="{ex:.1f}" y2="{ey:.1f}" '
                     f'stroke="{dark}" stroke-width="1"/>')
    parts.append(f'<polygon points="{" ".join(f"{a:.1f},{b:.1f}" for a, b in pent)}" fill="{dark}"/>')
    return "".join(parts)


def _cone(o: TacticalObject, colors: dict[str, str]) -> str:
    x, y = _px(o.x, o.y); s = 12 * o.scale
    return (f'<polygon points="{x},{y-s} {x-s*0.8},{y+s} {x+s*0.8},{y+s}" '
            f'fill="{_c(colors,"cone")}" stroke="{_c(colors,"ball_line")}" stroke-width="1"/>')


def _goal(o: TacticalObject, colors: dict[str, str]) -> str:
    x, y = _px(o.x, o.y); w = 34 * o.scale; h = 20 * o.scale
    g = _c(colors, "goal")
    return (f'<g stroke="{g}" stroke-width="3" fill="none">'
            f'<line x1="{x-w/2}" y1="{y-h}" x2="{x-w/2}" y2="{y}"/>'
            f'<line x1="{x+w/2}" y1="{y-h}" x2="{x+w/2}" y2="{y}"/>'
            f'<line x1="{x-w/2}" y1="{y-h}" x2="{x+w/2}" y2="{y-h}"/></g>')


def _mannequin(o: TacticalObject, colors: dict[str, str]) -> str:
    x, y = _px(o.x, o.y); s = 13 * o.scale
    m = _c(colors, "mannequin")
    return (f'<circle cx="{x}" cy="{y-s}" r="{s*0.5}" fill="{m}"/>'
            f'<rect x="{x-s*0.4}" y="{y-s*0.5}" width="{s*0.8}" height="{s*1.6}" rx="3" fill="{m}"/>')


def curve_control_point(x1: float, y1: float, x2: float, y2: float,
                        curvature: float) -> tuple[float, float]:
    """Quadratic-bezier control point for a curved arrow: a perpendicular offset from the
    straight line's midpoint, scaled by ``curvature``. This is the SINGLE source of truth
    for the curve shape - the renderer draws through this point and the JS canvas places the
    draggable curve handle at exactly this point (kept in sync via
    ``curvature_from_control_point``, its exact inverse). Coordinate-space agnostic: callers
    pass whatever space they draw in (the renderer uses the 1050x680 pixel plane)."""
    k = float(curvature)
    cx = (x1 + x2) / 2 + (y2 - y1) * k
    cy = (y1 + y2) / 2 - (x2 - x1) * k
    return cx, cy


def curvature_from_control_point(x1: float, y1: float, x2: float, y2: float,
                                 cx: float, cy: float) -> float:
    """Inverse of ``curve_control_point``: given a dragged control point ``(cx, cy)`` return
    the ``curvature`` scalar. Projects the drag offset (from the line midpoint) onto the
    line's perpendicular, so a purely-perpendicular drag round-trips EXACTLY and any other
    drag maps to the nearest representable curve. Degenerate zero-length lines yield 0."""
    dx = x2 - x1
    dy = y2 - y1
    denom = dx * dx + dy * dy
    if denom == 0:
        return 0.0
    mx = (x1 + x2) / 2
    my = (y1 + y2) / 2
    return ((cx - mx) * dy - (cy - my) * dx) / denom


def _head_svg(geom: dict, color: str, sw: float) -> str:
    """SVG for a renderer-neutral arrowhead spec from geometry.arrowhead_geometry()."""
    def _pts(poly):
        return " ".join(f"{a:.1f},{b:.1f}" for a, b in poly)
    out = []
    for poly in geom["fill_polys"]:
        out.append(f'<polygon points="{_pts(poly)}" fill="{color}"/>')
    for poly in geom["stroke_closed"]:
        out.append(f'<polygon points="{_pts(poly)}" fill="none" stroke="{color}" '
                   f'stroke-width="{sw}" stroke-linejoin="round"/>')
    for poly in geom["stroke_open"]:
        out.append(f'<polyline points="{_pts(poly)}" fill="none" stroke="{color}" '
                   f'stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round"/>')
    for cx, cy, r in geom["fill_circles"]:
        out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{color}"/>')
    for cx, cy, r in geom["stroke_circles"]:
        out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="none" '
                   f'stroke="{color}" stroke-width="{sw}"/>')
    return "".join(out)


def _vector_custom(o: TacticalObject, colors: dict[str, str], head_kind: str) -> str:
    """Arrow with an EXPLICIT ``props["arrowhead"]`` — the body keeps its variant/legacy
    semantics but the endpoint is drawn from geometry.arrowhead_geometry(). Reached only
    when the prop is present, so arrows without it stay on the classic byte-identical path."""
    from fap.tactical import geometry as _geo
    x1, y1 = _px(o.x, o.y); x2, y2 = _px(o.props.get("x2", o.x + 12), o.props.get("y2", o.y))
    spec = _geo.variant_spec(o.props.get("variant"))
    if spec is not None:
        col = o.props.get("color") or spec["color"] or _c(colors, "line")
        width = float(o.props.get("stroke_width", spec.get("width", 4)))
        dash = f'stroke-dasharray="{spec["dash"]}"' if spec.get("dash") else ""
        wave = str(spec.get("wave", ""))
    else:
        col = o.props.get("color") or _c(colors, "line")
        width = float(o.props.get("stroke_width", 4))
        dash = 'stroke-dasharray="10 8"' if o.type == "dashed_arrow" else ""
        wave = ""
    size = float(o.props.get("arrowhead_size", 1.0))
    hsw = float(o.props.get("arrowhead_stroke_width", 1.5))
    geom = _geo.arrowhead_geometry(head_kind, x1, y1, x2, y2, size=size, stroke_width=hsw)
    ux, uy, _, _ = _geo._dir(x1, y1, x2, y2)
    trim = 0.0 if o.type == "line" else float(geom["trim"])
    ex, ey = x2 - ux * trim, y2 - uy * trim
    if o.type == "curved_arrow":
        cx, cy = curve_control_point(x1, y1, x2, y2, float(o.props.get("curvature", 0.3)))
        body = (f'<path d="M {x1} {y1} Q {cx} {cy} {ex} {ey}" fill="none" stroke="{col}" '
                f'stroke-width="{width}" {dash} stroke-linecap="round"/>')
    elif wave:
        pts = _geo.wave_points(x1, y1, ex, ey, wave)
        d = "M " + " L ".join(f"{px:.1f} {py:.1f}" for px, py in pts)
        body = f'<path d="{d}" fill="none" stroke="{col}" stroke-width="{width}" {dash} stroke-linecap="round"/>'
    else:
        body = (f'<line x1="{x1}" y1="{y1}" x2="{ex}" y2="{ey}" stroke="{col}" '
                f'stroke-width="{width}" {dash} stroke-linecap="round"/>')
    head = "" if o.type == "line" and head_kind == "none" else _head_svg(geom, col, hsw)
    label = o.props.get("label")
    if label:
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        head += (f'<text x="{mx:.1f}" y="{my - 7:.1f}" text-anchor="middle" font-size="13" '
                 f'font-weight="700" fill="{col}" font-family="Inter,Arial">{_esc(str(label))}</text>')
    return body + head


def _vector(o: TacticalObject, colors: dict[str, str], marker: str) -> str:
    from fap.tactical import geometry as _geo
    if o.props.get("arrowhead") is not None:                # explicit head -> new custom path
        return _vector_custom(o, colors, str(o.props.get("arrowhead")))
    x1, y1 = _px(o.x, o.y); x2, y2 = _px(o.props.get("x2", o.x + 12), o.props.get("y2", o.y))
    spec = _geo.variant_spec(o.props.get("variant"))
    if spec is None:                                        # legacy arrow — byte-identical to before
        col = o.props.get("color") or _c(colors, "line")
        dash = 'stroke-dasharray="10 8"' if o.type == "dashed_arrow" else ""
        head = f'marker-end="url(#{marker})"' if o.type != "line" else ""
        if o.type == "curved_arrow":
            cx, cy = curve_control_point(x1, y1, x2, y2, float(o.props.get("curvature", 0.3)))
            return (f'<path d="M {x1} {y1} Q {cx} {cy} {x2} {y2}" fill="none" stroke="{col}" '
                    f'stroke-width="4" {dash} {head}/>')
        return (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{col}" '
                f'stroke-width="4" {dash} {head}/>')
    # semantic variant: coloured centreline (wavy/zigzag for run/dribble/pressing) +
    # an explicit coloured arrowhead (the shared marker only carries the theme colour).
    col = o.props.get("color") or spec["color"] or _c(colors, "line")
    width = spec.get("width", 4)
    dash = f'stroke-dasharray="{spec["dash"]}"' if spec.get("dash") else ""
    if o.type == "curved_arrow":
        cx, cy = curve_control_point(x1, y1, x2, y2, float(o.props.get("curvature", 0.3)))
        body = (f'<path d="M {x1} {y1} Q {cx} {cy} {x2} {y2}" fill="none" stroke="{col}" '
                f'stroke-width="{width}" {dash}/>')
    else:
        pts = _geo.wave_points(x1, y1, x2, y2, str(spec.get("wave", "")))
        d = "M " + " L ".join(f"{px:.1f} {py:.1f}" for px, py in pts)
        body = f'<path d="{d}" fill="none" stroke="{col}" stroke-width="{width}" {dash}/>'
    if spec.get("head") and o.type != "line":
        hpts = _geo.arrowhead_points(x1, y1, x2, y2)
        body += f'<polygon points="{" ".join(f"{px:.1f},{py:.1f}" for px, py in hpts)}" fill="{col}"/>'
    label = o.props.get("label")
    if label:
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        body += (f'<text x="{mx:.1f}" y="{my - 7:.1f}" text-anchor="middle" font-size="13" '
                 f'font-weight="700" fill="{col}" font-family="Inter,Arial">{_esc(str(label))}</text>')
    return body


def _freehand(o: TacticalObject, colors: dict[str, str]) -> str:
    from fap.tactical import geometry as _geo
    pts = _geo.freehand_points(o.props)
    if len(pts) < 2:
        return ""
    px = [_px(x, y) for x, y in pts]
    col = o.props.get("color") or _c(colors, "line")
    w = float(o.props.get("width", 3))
    d = "M " + " L ".join(f"{a:.1f} {b:.1f}" for a, b in px) + (" Z" if o.props.get("closed") else "")
    return (f'<path d="{d}" fill="none" stroke="{col}" stroke-width="{w}" '
            f'stroke-linecap="round" stroke-linejoin="round"/>')


def _spotlight_svg(x: float, y: float, w: float, h: float, col: str, op: float) -> str:
    """A broadcast-style player spotlight: a soft coloured halo, a bright crisp ring and a
    thin white inner accent — the "glow under the player" from live-analysis overlays. Built
    from plain ellipses (no SVG filters) so the matplotlib PNG/PDF export reproduces it exactly
    (see export_render._spotlight). ``op`` scales the halo intensity."""
    rx, ry = w / 2, h / 2
    halo = max(0.10, min(0.45, op))
    return (f'<ellipse cx="{x}" cy="{y}" rx="{rx*1.18:.1f}" ry="{ry*1.18:.1f}" fill="{col}" '
            f'fill-opacity="{halo*0.55:.3f}"/>'
            f'<ellipse cx="{x}" cy="{y}" rx="{rx:.1f}" ry="{ry:.1f}" fill="{col}" '
            f'fill-opacity="{halo:.3f}" stroke="{col}" stroke-width="5" stroke-opacity="0.95"/>'
            f'<ellipse cx="{x}" cy="{y}" rx="{rx*0.86:.1f}" ry="{ry*0.86:.1f}" fill="none" '
            f'stroke="#ffffff" stroke-width="1.6" stroke-opacity="0.75"/>')


def _zone(o: TacticalObject, colors: dict[str, str]) -> str:
    x, y = _px(o.x, o.y); w = o.props.get("w", 20) / 100 * _W; h = o.props.get("h", 16) / 100 * _H
    col = o.props.get("color") or _c(colors, "zone"); op = float(o.props.get("opacity", 0.28))
    # optional stroke/fill overrides - all default to today's exact look (filled, same-colour
    # 2px solid stroke) so an object with none of these renders byte-identically to before.
    fill = col if o.props.get("filled", True) else "none"
    stroke = o.props.get("stroke_color") or col
    sw = float(o.props.get("stroke_width", 2))
    sw_s = str(int(sw)) if sw == int(sw) else str(sw)       # 2.0 -> "2" (keep old byte output)
    # reuse the dashed_arrow dash-array so a dashed border matches dashed arrows visually
    dash = ' stroke-dasharray="10 8"' if o.props.get("stroke_style") == "dashed" else ""
    style = f'fill="{fill}" fill-opacity="{op}" stroke="{stroke}" stroke-width="{sw_s}"{dash}'
    if o.props.get("spotlight"):                             # glowing player-spotlight ellipse
        return _spotlight_svg(x, y, w, h, col, op)
    shape = o.props.get("shape")
    if shape == "triangle" and o.type != "highlight":       # isoceles, pointing up (cone-glyph style)
        pts = f"{x},{y-h/2} {x-w/2},{y+h/2} {x+w/2},{y+h/2}"
        return f'<polygon points="{pts}" {style}/>'
    if shape == "ellipse" or o.type in ("highlight", "circle"):
        return f'<ellipse cx="{x}" cy="{y}" rx="{w/2}" ry="{h/2}" {style}/>'
    return f'<rect x="{x-w/2}" y="{y-h/2}" width="{w}" height="{h}" rx="6" {style}/>'


def _text(o: TacticalObject, colors: dict[str, str]) -> str:
    x, y = _px(o.x, o.y); size = float(o.props.get("size", 14)) * o.scale
    col = o.props.get("color") or _c(colors, "text")
    # optional readability outline (telestration captions over a photo). Absent / width 0 =>
    # byte-identical to before. paint-order="stroke" draws the halo behind the glyph fill.
    ow = float(o.props.get("outline_width", 0) or 0)
    outline = ""
    if ow > 0:
        oc = o.props.get("outline") or "#0c0e12"
        outline = (f' paint-order="stroke" stroke="{oc}" stroke-width="{ow:.1f}" '
                   f'stroke-linejoin="round"')
    return (f'<text x="{x}" y="{y}" text-anchor="middle" font-size="{size:.0f}" '
            f'font-weight="700" fill="{col}" font-family="Inter,Arial"{outline}>'
            f'{_esc(o.props.get("text", ""))}</text>')


def _shape(o: TacticalObject, colors: dict[str, str]) -> str:
    return _zone(o, colors)


def _image(o: TacticalObject, colors: dict[str, str]) -> str:
    x, y = _px(o.x, o.y); w = o.props.get("w", 12) / 100 * _W; h = o.props.get("h", 12) / 100 * _H
    src = o.props.get("src", "")
    if src:
        return f'<image href="{_esc(src)}" x="{x-w/2}" y="{y-h/2}" width="{w}" height="{h}"/>'
    return (f'<rect x="{x-w/2}" y="{y-h/2}" width="{w}" height="{h}" fill="none" '
            f'stroke="{_c(colors,"line")}" stroke-dasharray="4 4"/>')


_OBJ: dict[str, Callable[[TacticalObject, dict], str]] = {
    "player": _player, "ball": _ball, "cone": _cone, "goal": _goal, "mannequin": _mannequin,
    "arrow": lambda o, c: _vector(o, c, "arrowhead"),
    "curved_arrow": lambda o, c: _vector(o, c, "arrowhead"),
    "dashed_arrow": lambda o, c: _vector(o, c, "arrowhead"),
    "line": lambda o, c: _vector(o, c, "arrowhead"),
    "freehand": _freehand,
    "zone": _zone, "highlight": _zone, "circle": _zone, "text": _text, "number": _text,
    "shape": _shape, "image": _image,
}


def _object_svg(o: TacticalObject, colors: dict[str, str], fr: Frame, *, selected: bool) -> str:
    # resolve_position is a no-op (returns o.x/o.y) for every object EXCEPT a sticky ball, so
    # cx/cy — and the rotation centre + selection ring below — follow the ball to its player.
    rx, ry = resolve_position(fr, o)
    cx, cy = _px(rx, ry)
    body = _ball(o, colors, cx, cy) if o.type == "ball" else _OBJ.get(o.type, lambda *_: "")(o, colors)
    transform = f' transform="rotate({o.rotation} {cx} {cy})"' if o.rotation else ""
    sel = ""
    if selected:
        acc = _c(colors, "accent")
        # a clean solid ring + a soft accent halo (replaces the old thin dashed ring). The JS
        # canvas draws the SAME shape for EXTRA multi-selected objects (index.html), so single
        # and multi selection look identical.
        sel = (f'<circle cx="{cx}" cy="{cy}" r="{_v.SELECT_HALO_R}" fill="none" stroke="{acc}" '
               f'stroke-width="{_v.SELECT_HALO_WIDTH}" stroke-opacity="{_v.SELECT_HALO_OPACITY}"/>'
               f'<circle cx="{cx}" cy="{cy}" r="{_v.SELECT_RING_R}" fill="none" stroke="{acc}" '
               f'stroke-width="{_v.SELECT_RING_WIDTH}"/>')
    return f'<g data-oid="{_esc(o.id)}"{transform}>{body}{sel}</g>'


# ---------------------------------------------------------------- public
def board_pitch_svg(board: Board, *, colors: dict[str, str] | None = None,
                    grid: bool = False) -> str:
    """Pitch-ONLY SVG (no pieces) for the client-rendered live board. Carries a ``#tb-plane``
    group that IS the 1050x680 pitch-coordinate space (rotated for a vertical pitch) and an
    empty ``#tb-pieces`` group the JS component renders every piece into — so pieces are drawn
    and manipulated entirely in the browser (instant), Python only owns the pitch + persistence.
    ``board_svg`` (full, with pieces) stays unchanged for export and the no-component fallback."""
    colors = {**DEFAULT_COLORS, **(colors or {})}
    vertical = board.pitch.orientation == "vertical"
    defs = (f'<defs><marker id="arrowhead" markerWidth="10" markerHeight="10" refX="8" refY="3" '
            f'orient="auto"><path d="M0,0 L8,3 L0,6 Z" fill="{_c(colors,"line")}"/></marker></defs>')
    pitch = _pitch_svg(board, colors, grid)
    inner = f'{defs}{pitch}<g id="tb-pieces"></g>'
    if vertical:
        view = f'0 0 {_H} {_W}'
        content = f'<g id="tb-plane" transform="translate({_H} 0) rotate(90)">{inner}</g>'
    else:
        view = f'0 0 {_W} {_H}'
        content = f'<g id="tb-plane">{inner}</g>'
    return (f'<svg class="tb-board-svg" viewBox="{view}" width="100%" '
            f'xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid meet" '
            f'style="display:block;border-radius:12px">{content}</svg>')


def board_svg(board: Board, frame_index: int = 0, *, colors: dict[str, str] | None = None,
              grid: bool = False, selected_id: str | None = None,
              overlays: list[str] | None = None) -> str:
    """Render one frame of ``board`` to an SVG string. ``overlays`` is an extension
    point (future Open Play viz / heatmaps injected as extra SVG) - unused for now."""
    colors = {**DEFAULT_COLORS, **(colors or {})}
    fr: Frame = board.frame(frame_index)
    vertical = board.pitch.orientation == "vertical"
    defs = (f'<defs><marker id="arrowhead" markerWidth="10" markerHeight="10" refX="8" refY="3" '
            f'orient="auto"><path d="M0,0 L8,3 L0,6 Z" fill="{_c(colors,"line")}"/></marker></defs>')
    pitch = _pitch_svg(board, colors, grid)
    objs = "".join(_object_svg(o, colors, fr, selected=(o.id == selected_id))
                   for o in sorted(fr.objects, key=lambda o: o.z)
                   if not (o.props or {}).get("hidden"))
    extra = "".join(overlays or [])
    inner = f'{defs}{pitch}{extra}{objs}'
    if vertical:
        # rotate the whole board 90deg for a vertical pitch
        view = f'0 0 {_H} {_W}'
        content = f'<g transform="translate({_H} 0) rotate(90)">{inner}</g>'
    else:
        view = f'0 0 {_W} {_H}'
        content = inner
    return (f'<svg class="tb-board-svg" viewBox="{view}" width="100%" '
            f'xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid meet" '
            f'style="display:block;border-radius:12px">{content}</svg>')
