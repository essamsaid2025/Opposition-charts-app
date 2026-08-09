"""Tactical Board raster/vector export (PNG + PDF) via matplotlib.

The interactive board and its share preview are SVG (``render.board_svg``). For file
downloads a coach expects PNG/PDF, and the usual SVG→raster path (cairosvg) needs native
cairo libraries that are awkward on Windows. Since the platform already ships matplotlib
(it renders report PDFs), this module draws the SAME board model straight to a matplotlib
figure and saves PNG or PDF — no extra system dependency.

It is a pure state→bytes function that reads the model only (no Streamlit, no mutation),
mirroring the SVG renderer's geometry (a 1050×680 plane, 0–100 pitch coords) and colours so
the exported board matches what is on screen. It is import-guarded by the caller: if
matplotlib is missing, export degrades to SVG exactly as before.
"""
from __future__ import annotations

import io
import math
from typing import Any

from fap.tactical.models import Board, Frame, TacticalObject
from fap.tactical.render import DEFAULT_COLORS

# same authoring plane as render.py (10 px per pitch unit)
_W, _H = 1050.0, 680.0
_VECTOR = {"arrow", "curved_arrow", "dashed_arrow", "line"}


def _c(colors: dict[str, str], key: str) -> str:
    return colors.get(key) or DEFAULT_COLORS.get(key, "#888888")


def _px(x: float, y: float) -> tuple[float, float]:
    return x / 100.0 * _W, y / 100.0 * _H


# ---------------------------------------------------------------- pitch
def _draw_pitch(ax, board: Board, colors: dict[str, str]) -> None:
    import matplotlib.patches as mp

    kind = board.pitch.kind
    line = _c(colors, "line")
    ax.add_patch(mp.Rectangle((0, 0), _W, _H, facecolor=_c(colors, "bg"), edgecolor="none", zorder=0))
    if kind == "blank":
        return

    grass, grass2 = _c(colors, "grass"), _c(colors, "grass_alt")
    stripes = 6
    sw = _W / stripes
    for i in range(stripes):
        ax.add_patch(mp.Rectangle((i * sw, 0), sw, _H, facecolor=grass if i % 2 == 0 else grass2,
                                  edgecolor="none", zorder=0.1))

    lw, pad = 3.0, 24.0
    x0, y0, x1, y1 = pad, pad, _W - pad, _H - pad

    def rect(x, y, w, h):
        ax.add_patch(mp.Rectangle((x, y), w, h, fill=False, edgecolor=line, linewidth=lw, zorder=1))

    rect(x0, y0, x1 - x0, y1 - y0)
    if kind != "futsal":
        cx = (x0 + x1) / 2
        ax.plot([cx, cx], [y0, y1], color=line, linewidth=lw, zorder=1)
        r = 9.15 / 68 * (y1 - y0)
        ax.add_patch(mp.Circle((cx, _H / 2), r, fill=False, edgecolor=line, linewidth=lw, zorder=1))
        ax.add_patch(mp.Circle((cx, _H / 2), 4, facecolor=line, edgecolor="none", zorder=1))
        bh, bw = (y1 - y0) * (40.32 / 68), (x1 - x0) * (16.5 / 105)
        sh, sw2 = (y1 - y0) * (18.32 / 68), (x1 - x0) * (5.5 / 105)
        for left in (True, False):
            bx = x0 if left else x1 - bw
            sx = x0 if left else x1 - sw2
            rect(bx, _H / 2 - bh / 2, bw, bh)
            rect(sx, _H / 2 - sh / 2, sw2, sh)
            spot = x0 + bw * 0.65 if left else x1 - bw * 0.65
            ax.add_patch(mp.Circle((spot, _H / 2), 3, facecolor=line, edgecolor="none", zorder=1))
    else:
        ax.add_patch(mp.Circle(((x0 + x1) / 2, _H / 2), (y1 - y0) * 0.12, fill=False,
                               edgecolor=line, linewidth=lw, zorder=1))
    if kind == "thirds":
        for fx in (1 / 3, 2 / 3):
            xx = x0 + (x1 - x0) * fx
            ax.plot([xx, xx], [y0, y1], color=line, linewidth=1.5, linestyle=(0, (8, 8)),
                    alpha=0.7, zorder=1)


# ---------------------------------------------------------------- objects
def _draw_object(ax, o: TacticalObject, colors: dict[str, str]) -> None:
    import matplotlib.patches as mp

    z = 2 + o.z * 0.001
    x, y = _px(o.x, o.y)
    p = o.props
    t = o.type

    if t == "player":
        r = 17 * o.scale
        fill = p.get("color") or _c(colors, "away" if p.get("team") == "away" else "home")
        if p.get("goalkeeper"):
            ax.add_patch(mp.Circle((x, y), r + 3, fill=False, edgecolor=_c(colors, "line"),
                                   linewidth=2, zorder=z))
        ax.add_patch(mp.Circle((x, y), r, facecolor=fill, edgecolor=_c(colors, "line"),
                               linewidth=2, zorder=z))
        num = p.get("number", "")
        if num not in ("", None):
            ax.text(x, y, str(num), ha="center", va="center", color=_c(colors, "text"),
                    fontsize=r * 0.8, fontweight="bold", zorder=z + 0.01)
        if p.get("captain"):
            ax.text(x + r * 0.9, y - r * 0.7, "C", ha="left", va="center", color=_c(colors, "accent"),
                    fontsize=r * 0.6, fontweight="bold", zorder=z + 0.01)
        if p.get("name"):
            ax.text(x, y + r + 12, str(p["name"]), ha="center", va="top", color=_c(colors, "text"),
                    fontsize=9, zorder=z + 0.01)
    elif t == "ball":
        r = 9 * o.scale
        ax.add_patch(mp.Circle((x, y), r, facecolor=_c(colors, "ball"),
                               edgecolor=_c(colors, "ball_line"), linewidth=1.5, zorder=z))
        ax.add_patch(mp.Circle((x, y), r * 0.32, facecolor=_c(colors, "ball_line"),
                               edgecolor="none", zorder=z + 0.01))
    elif t == "cone":
        s = 12 * o.scale
        ax.add_patch(mp.Polygon([(x, y - s), (x - s * 0.8, y + s), (x + s * 0.8, y + s)],
                                closed=True, facecolor=_c(colors, "cone"),
                                edgecolor=_c(colors, "ball_line"), linewidth=1, zorder=z))
    elif t == "goal":
        w, h = 34 * o.scale, 20 * o.scale
        g = _c(colors, "goal")
        for seg in ([(x - w / 2, y - h), (x - w / 2, y)], [(x + w / 2, y - h), (x + w / 2, y)],
                    [(x - w / 2, y - h), (x + w / 2, y - h)]):
            ax.plot([seg[0][0], seg[1][0]], [seg[0][1], seg[1][1]], color=g, linewidth=3, zorder=z)
    elif t == "mannequin":
        s = 13 * o.scale
        m = _c(colors, "mannequin")
        ax.add_patch(mp.Circle((x, y - s), s * 0.5, facecolor=m, edgecolor="none", zorder=z))
        ax.add_patch(mp.Rectangle((x - s * 0.4, y - s * 0.5), s * 0.8, s * 1.6, facecolor=m,
                                  edgecolor="none", zorder=z))
    elif t in _VECTOR:
        x2, y2 = _px(p.get("x2", o.x + 12), p.get("y2", o.y))
        col = p.get("color") or _c(colors, "line")
        style = "--" if t == "dashed_arrow" else "-"
        if t == "line":
            ax.plot([x, x2], [y, y2], color=col, linewidth=4, linestyle=style, zorder=z)
        else:
            conn = "arc3,rad=0"
            if t == "curved_arrow":
                conn = f"arc3,rad={float(p.get('curvature', 0.3))}"
            ax.annotate("", xy=(x2, y2), xytext=(x, y), zorder=z,
                        arrowprops=dict(arrowstyle="-|>", color=col, linewidth=4,
                                        linestyle=style, connectionstyle=conn,
                                        shrinkA=0, shrinkB=0, mutation_scale=22))
    elif t in ("zone", "highlight", "shape"):
        # kept in lockstep with render.py _zone(): identical stroke/fill/shape props, and the
        # default (no new props) reproduces today's exact patch call -> pixel-identical export.
        w = p.get("w", 20) / 100 * _W
        h = p.get("h", 16) / 100 * _H
        col = p.get("color") or _c(colors, "zone")
        op = float(p.get("opacity", 0.28))
        filled = p.get("filled", True)
        face = col if filled else "none"
        edge = p.get("stroke_color") or col
        # filled: keep today's exact behaviour (alpha dims fill+border together). Unfilled:
        # full-opacity border so the outline matches the SVG's full-opacity stroke.
        kw = dict(facecolor=face, alpha=(op if filled else 1.0), edgecolor=edge,
                  linewidth=float(p.get("stroke_width", 2)), zorder=z)
        if p.get("stroke_style") == "dashed":              # match dashed_arrow's linestyle
            kw["linestyle"] = "--"
        shape = p.get("shape")
        if shape == "triangle" and t != "highlight":       # isoceles, pointing up (cone-glyph style)
            ax.add_patch(mp.Polygon([(x, y - h / 2), (x - w / 2, y + h / 2), (x + w / 2, y + h / 2)],
                                    closed=True, **kw))
        elif shape == "ellipse" or t == "highlight":
            ax.add_patch(mp.Ellipse((x, y), w, h, **kw))
        else:
            ax.add_patch(mp.Rectangle((x - w / 2, y - h / 2), w, h, **kw))
    elif t in ("text", "number"):
        size = float(p.get("size", 14)) * o.scale
        ax.text(x, y, str(p.get("text", "")), ha="center", va="center",
                color=p.get("color") or _c(colors, "text"), fontsize=size, fontweight="bold", zorder=z)
    elif t == "image":
        w = p.get("w", 12) / 100 * _W
        h = p.get("h", 12) / 100 * _H
        ax.add_patch(mp.Rectangle((x - w / 2, y - h / 2), w, h, fill=False,
                                  edgecolor=_c(colors, "line"), linestyle=(0, (4, 4)), zorder=z))


# ---------------------------------------------------------------- public
def board_image(board: Board, frame_index: int = 0, *, fmt: str = "png",
                colors: dict[str, str] | None = None, dpi: int = 150) -> bytes:
    """Render one frame of ``board`` to PNG or PDF bytes via matplotlib. Vertical boards
    are rotated to portrait to match the on-screen orientation. Raises if matplotlib is
    unavailable — the caller import-guards and degrades to SVG."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors = {**DEFAULT_COLORS, **(colors or {})}
    fr: Frame = board.frame(frame_index)
    vertical = board.pitch.orientation == "vertical"

    fig, ax = plt.subplots(figsize=(_W / 100.0, _H / 100.0))
    try:
        ax.set_xlim(0, _W)
        ax.set_ylim(_H, 0)                       # SVG y grows downward
        ax.set_aspect("equal")
        ax.axis("off")
        fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
        _draw_pitch(ax, board, colors)
        for o in sorted(fr.objects, key=lambda o: o.z):
            _draw_object(ax, o, colors)

        buf = io.BytesIO()
        fig.savefig(buf, format="pdf" if fmt == "pdf" else "png", dpi=dpi,
                    facecolor=_c(colors, "bg"), bbox_inches=None, pad_inches=0)
        data = buf.getvalue()
    finally:
        plt.close(fig)

    if vertical:
        data = _rotate(data, fmt)
    return data


def board_gif(board: Board, *, colors: dict[str, str] | None = None,
              duration_ms: int = 800, dpi: int = 100) -> bytes:
    """Render EVERY frame of ``board`` (in order) into one animated GIF.

    Reuses ``board_image(..., fmt="png")`` per frame - no drawing logic is
    duplicated - then stitches the frames with Pillow. Each frame is held for its
    own ``Frame.duration_ms`` when present, else ``duration_ms``. A single-frame
    board yields a valid (static) GIF. The default dpi is lower than the still
    export (100 vs 150) because file size scales with frame_count × resolution, so
    a many-frame animation stays reasonable; raise ``dpi`` for a crisper clip.

    Raises if matplotlib/Pillow are unavailable - the caller import-guards on
    ``available()`` and degrades exactly like ``board_image``."""
    from PIL import Image                            # Pillow is already a project dependency

    images: list[Any] = []
    durations: list[int] = []
    for i, fr in enumerate(board.frames):
        png = board_image(board, i, fmt="png", colors=colors, dpi=dpi)
        images.append(Image.open(io.BytesIO(png)).convert("RGB"))
        d = getattr(fr, "duration_ms", None)
        durations.append(int(d) if isinstance(d, (int, float)) and d > 0 else int(duration_ms))
    if not images:                                   # Board guarantees >=1 frame; defensive anyway
        raise ValueError("board has no frames to animate")

    out = io.BytesIO()
    images[0].save(out, format="GIF", save_all=True, append_images=images[1:],
                   duration=durations, loop=0, disposal=2)
    return out.getvalue()


def _rotate(data: bytes, fmt: str) -> bytes:
    """Rotate a landscape export to portrait for vertical boards. PNG via Pillow; PDF is
    left landscape if Pillow can't help (content is still correct)."""
    if fmt == "pdf":
        return data
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data)).rotate(90, expand=True)
        out = io.BytesIO()
        img.save(out, format="PNG")
        return out.getvalue()
    except Exception:
        return data


def available() -> bool:
    """True when the matplotlib export path can run (import-guard for the service)."""
    try:
        import matplotlib  # noqa: F401
        return True
    except Exception:
        return False
