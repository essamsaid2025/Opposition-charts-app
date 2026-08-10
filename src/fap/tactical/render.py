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

from fap.tactical.models import Board, Frame, TacticalObject, resolve_position

# a professional default palette (overridden by the page with live theme tokens)
DEFAULT_COLORS: dict[str, str] = {
    "grass": "#1f7a3f", "grass_alt": "#1c7139", "line": "#eaf3ec", "bg": "#0c0e12",
    "home": "#e07b2b", "away": "#2f7bd6", "ball": "#f5f5f5", "ball_line": "#1a1a1a",
    "cone": "#f0a020", "goal": "#e8e8e8", "text": "#ffffff", "accent": "#2f7bd6",
    "zone": "#2f7bd6", "mannequin": "#c9ccd2",
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
    x, y = _px(o.x, o.y); r = 17 * o.scale
    p = o.props
    team = p.get("team", "home")
    fill = p.get("color") or _c(colors, "away" if team == "away" else "home")
    ring = (f'<circle cx="{x}" cy="{y}" r="{r+3}" fill="none" stroke="{_c(colors,"line")}" '
            f'stroke-width="2"/>' if p.get("goalkeeper") else "")
    num = p.get("number", "")
    num_t = (f'<text x="{x}" y="{y+r*0.35}" text-anchor="middle" font-size="{r*1.1:.0f}" '
             f'font-weight="700" fill="{_c(colors,"text")}" '
             f'font-family="Inter,Arial">{_esc(num)}</text>' if num not in ("", None) else "")
    cap = (f'<text x="{x+r*0.9}" y="{y-r*0.7}" font-size="{r*0.8:.0f}" font-weight="800" '
           f'fill="{_c(colors,"accent")}" font-family="Inter,Arial">C</text>'
           if p.get("captain") else "")
    name = p.get("name", "")
    name_t = (f'<text x="{x}" y="{y+r+15}" text-anchor="middle" font-size="13" '
              f'fill="{_c(colors,"text")}" font-family="Inter,Arial">{_esc(name)}</text>'
              if name else "")
    # facing-direction indicator: a small wedge on the top edge pointing "up" (0deg). It is
    # drawn FIRST so the circle overdraws its base, leaving a clean nub poking out the top; and
    # it lives inside the object's <g>, which _object_svg rotates by o.rotation — so it always
    # points where the player faces and agrees with the rotate handle (which also uses 0deg = up).
    # This makes rotation VISIBLE for a plain player (a symmetric circle + centred number alone
    # barely changes when rotated). Additive: a player at rotation 0 just gains this small nub.
    wr = r * 0.34
    wedge = (f'<polygon points="{x},{y-r-r*0.48} {x-wr},{y-r*0.62} {x+wr},{y-r*0.62}" '
             f'fill="{_c(colors,"line")}"/>')
    return (f'{wedge}{ring}<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}" '
            f'stroke="{_c(colors,"line")}" stroke-width="2"/>{num_t}{cap}{name_t}')


def _ball(o: TacticalObject, colors: dict[str, str], px: float | None = None,
          py: float | None = None) -> str:
    # px/py override the ball's own coords when it is "sticky" on a player (resolved by the
    # caller via resolve_position); default = the ball's stored position (byte-identical to before)
    x, y = (px, py) if px is not None else _px(o.x, o.y); r = 9 * o.scale
    return (f'<circle cx="{x}" cy="{y}" r="{r}" fill="{_c(colors,"ball")}" '
            f'stroke="{_c(colors,"ball_line")}" stroke-width="1.5"/>'
            f'<circle cx="{x}" cy="{y}" r="{r*0.32}" fill="{_c(colors,"ball_line")}"/>')


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


def _vector(o: TacticalObject, colors: dict[str, str], marker: str) -> str:
    x1, y1 = _px(o.x, o.y); x2, y2 = _px(o.props.get("x2", o.x + 12), o.props.get("y2", o.y))
    col = o.props.get("color") or _c(colors, "line")
    dash = 'stroke-dasharray="10 8"' if o.type == "dashed_arrow" else ""
    head = f'marker-end="url(#{marker})"' if o.type != "line" else ""
    if o.type == "curved_arrow":
        cx, cy = curve_control_point(x1, y1, x2, y2, float(o.props.get("curvature", 0.3)))
        return (f'<path d="M {x1} {y1} Q {cx} {cy} {x2} {y2}" fill="none" stroke="{col}" '
                f'stroke-width="4" {dash} {head}/>')
    return (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{col}" '
            f'stroke-width="4" {dash} {head}/>')


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
    shape = o.props.get("shape")
    if shape == "triangle" and o.type != "highlight":       # isoceles, pointing up (cone-glyph style)
        pts = f"{x},{y-h/2} {x-w/2},{y+h/2} {x+w/2},{y+h/2}"
        return f'<polygon points="{pts}" {style}/>'
    if shape == "ellipse" or o.type == "highlight":
        return f'<ellipse cx="{x}" cy="{y}" rx="{w/2}" ry="{h/2}" {style}/>'
    return f'<rect x="{x-w/2}" y="{y-h/2}" width="{w}" height="{h}" rx="6" {style}/>'


def _text(o: TacticalObject, colors: dict[str, str]) -> str:
    x, y = _px(o.x, o.y); size = float(o.props.get("size", 14)) * o.scale
    col = o.props.get("color") or _c(colors, "text")
    return (f'<text x="{x}" y="{y}" text-anchor="middle" font-size="{size:.0f}" '
            f'font-weight="700" fill="{col}" font-family="Inter,Arial">'
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
    "zone": _zone, "highlight": _zone, "text": _text, "number": _text,
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
        sel = (f'<circle cx="{cx}" cy="{cy}" r="26" fill="none" stroke="{_c(colors,"accent")}" '
               f'stroke-width="2" stroke-dasharray="4 4"/>')
    return f'<g data-oid="{_esc(o.id)}"{transform}>{body}{sel}</g>'


# ---------------------------------------------------------------- public
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
                   for o in sorted(fr.objects, key=lambda o: o.z))
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
