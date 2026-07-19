"""PDF rendering for the report exporter, using matplotlib - the platform's own
rendering engine (no new dependency). One figure per ``RenderedPage`` at the true
page size; text is drawn as real vector text (``pdf.fonttype=42`` -> embedded
TrueType, searchable/selectable, not rasterized); charts and images embed as the
raster they already are. Isolated in its own module so importing the exporter
package never pulls in matplotlib until a PDF is actually requested.
"""
from __future__ import annotations

import io
from typing import Any

from fap.reports.layout import RenderedDocument, RenderedElement, RenderedPage

# role -> font size in points (independent of medium; scaled by the figure DPI)
_ROLE_PT = {"title": 30, "subtitle": 16, "h1": 17, "h2": 14,
            "meta": 10, "body": 11, "caption": 9}


def render_pdf(rendered: RenderedDocument, branding: Any = None) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    matplotlib.rcParams["pdf.fonttype"] = 42          # embed TrueType (real text)
    matplotlib.rcParams["ps.fonttype"] = 42

    primary = getattr(getattr(branding, "palette", None), "primary", "#E07B2B")
    ink, muted = "#16181d", "#5b6472"

    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        for page in rendered.pages:
            fig = plt.figure(figsize=(page.width_pt / 72.0, page.height_pt / 72.0), dpi=150)
            fig.patch.set_facecolor(page.background_color or "#ffffff")
            _draw_background(fig, page)
            for el in sorted(page.elements, key=lambda e: e.z):
                try:
                    _draw_element(fig, el, ink, muted, primary)
                except Exception:
                    pass                                  # one bad element never fails the page
            _draw_furniture(fig, page, muted, primary)
            pdf.savefig(fig, facecolor=fig.get_facecolor())
            plt.close(fig)
    return buf.getvalue()


# ---------------------------------------------------------------- geometry
def _rect(el_or_box) -> tuple[float, float, float, float]:
    """(fx,fy,fw,fh) top-based -> matplotlib figure rect (left,bottom,w,h)."""
    fx, fy, fw, fh = el_or_box
    return (fx, 1.0 - fy - fh, fw, fh)


def _draw_background(fig, page: RenderedPage) -> None:
    if page.background_bytes is not None:
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(page.background_bytes)).convert("RGB")
            ax = fig.add_axes([0, 0, 1, 1]); ax.set_axis_off(); ax.imshow(img, aspect="auto",
                                                                          extent=(0, 1, 0, 1))
        except Exception:
            pass


def _draw_element(fig, el: RenderedElement, ink: str, muted: str, primary: str) -> None:
    c = el.content
    if el.kind == "cover_overlay":
        from matplotlib.patches import Rectangle
        ax = fig.add_axes([0, 0, 1, 1]); ax.set_axis_off()
        ax.add_patch(Rectangle((0, 0), 1, 1, transform=ax.transAxes,
                               facecolor=c.get("color", "#000000"),
                               alpha=float(c.get("opacity", 0.3)), edgecolor="none"))
        return
    if el.kind == "spacer":
        return
    if el.kind == "divider":
        from matplotlib.lines import Line2D
        y = 1.0 - el.fy
        fig.add_artist(Line2D([el.fx, el.fx + el.fw], [y, y], transform=fig.transFigure,
                              color="#d5dbe6", linewidth=1.2))
        return
    if el.kind in ("image", "chart", "logo"):
        _draw_image(fig, el)
        return
    if el.kind == "table":
        _draw_table(fig, el, ink, muted)
        return
    if el.kind == "kpis":
        text = "   ".join(f"{k}: {v}" for k, v in c.get("kpis", []))
        _text(fig, el, text, _ROLE_PT["body"], ink)
        return
    if el.kind == "insight":
        _text(fig, el, "‣ " + c.get("text", ""), _ROLE_PT["body"], ink)
        return
    # text-like
    color = {"title": ink, "subtitle": muted, "meta": muted, "caption": muted}.get(el.role, ink)
    weight = "bold" if el.role in ("title", "h1", "h2") else "normal"
    _text(fig, el, _plain(c.get("text", "")), _ROLE_PT.get(el.role, 11), color, weight)


def _text(fig, el: RenderedElement, s: str, size: float, color: str,
          weight: str = "normal") -> None:
    if not s:
        return
    ha = {"left": "left", "center": "center", "right": "right"}.get(el.align, "left")
    x = el.fx if ha == "left" else (el.fx + el.fw / 2 if ha == "center" else el.fx + el.fw)
    y = 1.0 - el.fy
    fig.text(x, y, s, ha=ha, va="top", fontsize=size, color=color, weight=weight,
             wrap=True, alpha=el.opacity)


def _draw_image(fig, el: RenderedElement) -> None:
    data = el.content.get("image_bytes")
    if not data:
        return
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        return
    left, bottom, w, h = _rect((el.fx, el.fy, el.fw, el.fh))
    ax = fig.add_axes([left, bottom, w, h]); ax.set_axis_off()
    ax.imshow(img, aspect="auto" if el.kind != "chart" else None, alpha=el.opacity)


def _draw_table(fig, el: RenderedElement, ink: str, muted: str) -> None:
    c = el.content
    cols, rows = c.get("columns", []), c.get("rows", [])
    if not cols:
        return
    left, bottom, w, h = _rect((el.fx, el.fy, el.fw, el.fh))
    ax = fig.add_axes([left, bottom, w, h]); ax.set_axis_off()
    tbl = ax.table(cellText=[[str(x) for x in r] for r in rows] or [[""] * len(cols)],
                   colLabels=[str(x) for x in cols], loc="upper center", cellLoc="left")
    tbl.auto_set_font_size(False); tbl.set_fontsize(8)


def _draw_furniture(fig, page: RenderedPage, muted: str, primary: str) -> None:
    if page.watermark:
        wm = page.watermark
        if wm.text:
            fig.text(0.5, 0.5, wm.text, ha="center", va="center", fontsize=wm.font_size,
                     color=wm.color or muted, alpha=wm.opacity, rotation=wm.rotation, zorder=5)
    if page.header and not page.header.is_empty():
        _zone(fig, page.header, 0.965, muted)
    if page.footer and not page.footer.is_empty():
        _zone(fig, page.footer, 0.03, muted)
    if page.number:
        fig.text(0.94, 0.03, page.number, ha="right", va="bottom", fontsize=8, color=muted)
    if page.confidential:
        fig.text(0.06, 0.965, page.confidential, ha="left", va="top", fontsize=8,
                 color=primary, weight="bold")


def _zone(fig, zone, y: float, color: str) -> None:
    if zone.left:
        fig.text(0.06, y, zone.left, ha="left", va="center", fontsize=8, color=color)
    if zone.center:
        fig.text(0.5, y, zone.center, ha="center", va="center", fontsize=8, color=color)
    if zone.right:
        fig.text(0.94, y, zone.right, ha="right", va="center", fontsize=8, color=color)


# ---------------------------------------------------------------- primitives
def _plain(text: str) -> str:
    """Markdown -> plain text for vector rendering: strip heading/bullet markers."""
    out = []
    for line in (text or "").splitlines():
        s = line.rstrip()
        if s.startswith("### "):
            out.append(s[4:])
        elif s.startswith("## "):
            out.append(s[3:])
        elif s.startswith("# "):
            out.append(s[2:])
        elif s.startswith("- "):
            out.append("• " + s[2:])
        else:
            out.append(s)
    return "\n".join(out)
