"""Pre-rendered PNGs for the professional Player Evaluation report.

Kept separate from the pure document builder (:mod:`fap.teams.player_report`) so the
builder stays renderer-independent — exactly like the scouting premium report feeds
its builder pre-rendered chart bytes. Everything here is best-effort: a chart that
cannot be drawn from the available data returns ``None`` (the section is then omitted),
never a fabricated figure and never a raised error that would block the report.

Two figures:
* ``render_development_png`` — small-multiples of the player's per-match metrics
  across the team's linked matches (the trend that sits under the Development tab).
* ``render_touch_heatmap_png`` — a touch/heat map from the player's event positions
  aggregated across matches (mplsoccer, canonical 0-100 "opta" pitch).
"""
from __future__ import annotations

import io
from typing import Any

_ACCENT = "#1b2a4a"       # professional navy (report-only; never touches app/chart themes)
_GRID = "#e6e8ee"
_MUTED = "#8a93a6"


def _png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="white")
    buf.seek(0)
    import matplotlib.pyplot as plt
    plt.close(fig)
    return buf.getvalue()


def render_development_png(progression: list[dict[str, Any]],
                          metrics: list[tuple[str, str]], *, accent: str = _ACCENT) -> bytes | None:
    """Small-multiples line charts of the player's metrics across matches (oldest→newest).

    ``progression`` is the per-match list from ``TeamService.player_progression``;
    ``metrics`` is an ordered list of ``(key, label)``. Only metrics with at least one
    real (non-null) value and some variation/movement are drawn, capped at six panels.
    Returns None when nothing plottable exists.
    """
    if not progression:
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return None

    # keep metrics that actually carry data
    usable: list[tuple[str, str, list]] = []
    for key, label in metrics:
        vals = [m.get(key) for m in progression]
        if any(v is not None for v in vals):
            usable.append((key, label, vals))
    if not usable:
        return None
    usable = usable[:6]

    xs = list(range(1, len(progression) + 1))
    xlabels = []
    for i, m in enumerate(progression, 1):
        opp = m.get("opponent") or f"M{i}"
        xlabels.append(f"vs {opp}"[:14])

    n = len(usable)
    cols = 2 if n > 1 else 1
    rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(9, 2.6 * rows), squeeze=False)
    flat = [ax for r in axes for ax in r]
    for ax, (key, label, vals) in zip(flat, usable):
        ys = [(float(v) if v is not None else None) for v in vals]
        # plot the line, skipping gaps
        xs_p = [x for x, y in zip(xs, ys) if y is not None]
        ys_p = [y for y in ys if y is not None]
        ax.plot(xs_p, ys_p, "-o", color=accent, linewidth=2, markersize=5, zorder=3)
        # rolling average (window 3) for context
        if len(ys_p) >= 2:
            roll = []
            hist: list[float] = []
            for y in ys_p:
                hist.append(y)
                roll.append(sum(hist[-3:]) / len(hist[-3:]))
            ax.plot(xs_p, roll, "--", color=_MUTED, linewidth=1.3, zorder=2)
        ax.set_title(label, fontsize=11, color="#20242c", fontweight="bold", loc="left")
        ax.set_xticks(xs)
        ax.set_xticklabels(xlabels, rotation=35, ha="right", fontsize=7, color=_MUTED)
        ax.grid(True, color=_GRID, linewidth=0.8)
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
        ax.tick_params(axis="y", labelsize=8, colors=_MUTED)
    for ax in flat[n:]:
        ax.axis("off")
    fig.suptitle("Development across matches", fontsize=13, fontweight="bold",
                 color="#20242c", x=0.02, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    try:
        return _png(fig)
    except Exception:
        return None


def render_touch_heatmap_png(frame, *, accent: str = _ACCENT) -> bytes | None:
    """A touch/heat map of the player's event positions on a canonical 0-100 pitch.

    ``frame`` is the player's aggregated event rows (x, y). Returns None when there are
    too few positioned events or mplsoccer/matplotlib are unavailable.
    """
    if frame is None or getattr(frame, "empty", True):
        return None
    if "x" not in frame.columns or "y" not in frame.columns:
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import pandas as pd
        from mplsoccer import Pitch
    except Exception:
        return None

    x = pd.to_numeric(frame["x"], errors="coerce")
    y = pd.to_numeric(frame["y"], errors="coerce")
    mask = x.notna() & y.notna()
    x, y = x[mask], y[mask]
    if len(x) < 8:                                   # too few points to be meaningful
        return None
    try:
        pitch = Pitch(pitch_type="opta", line_color="#c7ccd8", pitch_color="white",
                      linewidth=1.1)
        fig, ax = pitch.draw(figsize=(8, 5))
        try:
            pitch.kdeplot(x, y, ax=ax, fill=True, levels=60, thresh=0.05,
                          cmap="Blues", alpha=0.85, zorder=1)
        except Exception:
            pass
        pitch.scatter(x, y, ax=ax, s=16, color=accent, alpha=0.35, zorder=2,
                      edgecolors="none")
        # attacking-direction arrow (each team attacks +x on the canonical pitch)
        ax.annotate("", xy=(66, -4), xytext=(34, -4),
                    arrowprops=dict(arrowstyle="-|>", color=_MUTED, lw=1.4),
                    annotation_clip=False)
        ax.text(50, -7.5, "Attacking direction", ha="center", va="top", fontsize=8,
                color=_MUTED)
        fig.suptitle("Touch & activity map", fontsize=13, fontweight="bold",
                     color="#20242c", x=0.5)
        return _png(fig)
    except Exception:
        return None


def _rounded_portrait(photo_bytes: bytes, *, ratio: float = 0.78, radius_frac: float = 0.07,
                      border: str = "#c8a24a", border_px: int = 10):
    """Center-crop a portrait to ``ratio`` (w/h), round its corners and stroke a border.
    Returns a PIL RGBA image, or None."""
    try:
        import io as _io
        from PIL import Image, ImageDraw
    except Exception:
        return None
    try:
        im = Image.open(_io.BytesIO(photo_bytes)).convert("RGBA")
    except Exception:
        return None
    w, h = im.size
    if w == 0 or h == 0:
        return None
    # crop to target aspect (keep the upper body: bias the crop toward the top)
    target = ratio
    if w / h > target:                       # too wide → crop sides
        nw = int(h * target); im = im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    else:                                    # too tall → crop bottom, keep the head
        nh = int(w / target); im = im.crop((0, 0, w, min(nh, h)))
    w, h = im.size
    rad = int(min(w, h) * radius_frac)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=rad, fill=255)
    im.putalpha(mask)
    if border_px > 0:
        draw = ImageDraw.Draw(im)
        for k in range(border_px):
            draw.rounded_rectangle((k, k, w - 1 - k, h - 1 - k), radius=max(rad - k, 1),
                                   outline=border)
    return im


def render_cover_png(*, player_name: str, position: str = "", club: str = "", shirt: str = "",
                     department: str = "Data Analysis Department", title_line: str = "",
                     date: str = "", photo_bytes: bytes | None = None,
                     crest_bytes: bytes | None = None, accent: str = "#c8a24a",
                     show_title: bool = True, show_shirt: bool = True) -> bytes | None:
    """A bespoke, light-corporate A4 cover: crest, a small report title, the player's
    photo in a rounded gold-framed panel, the name, shirt/position/club, a gold rule, the
    department and the date. Fully self-designed so it does not depend on the report
    engine's cover text layout. Returns None if matplotlib is unavailable."""
    try:
        import io as _io
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return None

    INK, MUTED, BG, PANEL = "#14181f", "#6b7280", "#ffffff", "#eef0f4"
    figw, figh = 8.27, 11.69                              # A4 portrait inches
    fig = plt.figure(figsize=(figw, figh), dpi=150)
    fig.patch.set_facecolor(BG)

    # frame rules (thin gold top + bottom)
    for yy in (0.955, 0.045):
        fig.add_artist(plt.Line2D([0.12, 0.88], [yy, yy], color=accent, lw=1.4,
                                  transform=fig.transFigure))

    def _sp(s: str) -> str:                               # faux letter-spacing for small caps
        return "  ".join(list(s.upper()))

    # crest (top center)
    if crest_bytes:
        try:
            im = plt.imread(_io.BytesIO(crest_bytes))
            ih, iw = im.shape[0], im.shape[1]
            cw = 0.135
            ch = cw * (figw / figh) * (ih / max(iw, 1))
            ax = fig.add_axes([0.5 - cw / 2, 0.885 - ch / 2, cw, ch]); ax.imshow(im); ax.axis("off")
        except Exception:
            pass

    if show_title and title_line:
        fig.text(0.5, 0.808, _sp(title_line), ha="center", va="center", fontsize=11.5,
                 color=accent, fontweight="bold")

    # player photo (rounded, gold border), centered on white — clean, no hard shadow
    placed = False
    if photo_bytes:
        pil = _rounded_portrait(photo_bytes, border=accent, border_px=12)
        if pil is not None:
            import numpy as np
            arr = np.asarray(pil)
            ih, iw = arr.shape[0], arr.shape[1]
            pw = 0.38
            ph = pw * (figw / figh) * (ih / max(iw, 1))
            cy = 0.60
            ax = fig.add_axes([0.5 - pw / 2, cy - ph / 2, pw, ph]); ax.imshow(arr); ax.axis("off")
            placed = True
    if not placed:
        # initials medallion fallback
        initials = "".join(w[0] for w in player_name.split()[:2]).upper() or "P"
        ax = fig.add_axes([0.37, 0.50, 0.26, 0.185]); ax.axis("off")
        ax.add_patch(plt.Circle((0.5, 0.5), 0.5, facecolor=PANEL, edgecolor=accent, lw=3))
        ax.text(0.5, 0.5, initials, ha="center", va="center", fontsize=42, color=INK,
                fontweight="bold")

    # name (auto-size to fit)
    name = player_name or "Player"
    nsize = 31 if len(name) <= 16 else 26 if len(name) <= 24 else 20
    fig.text(0.5, 0.355, name, ha="center", va="center", fontsize=nsize, color=INK,
             fontweight="bold")

    # shirt · position · club
    bits = []
    if show_shirt and shirt:
        bits.append(f"#{shirt}")
    if position:
        bits.append(position)
    if club:
        bits.append(club)
    if bits:
        fig.text(0.5, 0.313, "   ·   ".join(bits), ha="center", va="center", fontsize=13.5,
                 color=MUTED)

    # gold rule
    fig.add_artist(plt.Line2D([0.435, 0.565], [0.279, 0.279], color=accent, lw=2.4,
                              transform=fig.transFigure))

    # department + date
    fig.text(0.5, 0.232, _sp(department), ha="center", va="center", fontsize=12,
             color=INK, fontweight="bold")
    if date:
        fig.text(0.5, 0.11, date, ha="center", va="center", fontsize=10.5, color=MUTED)

    try:
        buf = _io.BytesIO()
        fig.savefig(buf, format="png", facecolor=BG, bbox_inches=None)
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()
    except Exception:
        try:
            plt.close(fig)
        except Exception:
            pass
        return None


__all__ = ["render_development_png", "render_touch_heatmap_png", "render_cover_png"]
