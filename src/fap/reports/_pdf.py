"""PDF rendering for the report exporter, using matplotlib - the platform's own
rendering engine (no new dependency). One figure per ``RenderedPage`` at the true
page size; text is drawn as real vector text (``pdf.fonttype=42`` -> embedded
TrueType, searchable/selectable, not rasterized); charts and images embed as the
raster they already are. Isolated in its own module so importing the exporter
package never pulls in matplotlib until a PDF is actually requested.
"""
from __future__ import annotations

import io
import logging
from typing import Any

from fap.reports.block_style import font_for
from fap.reports.layout import RenderedDocument, RenderedElement, RenderedPage

logger = logging.getLogger(__name__)

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

    TH = _theme(branding)

    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        for page in rendered.pages:
            fig = plt.figure(figsize=(page.width_pt / 72.0, page.height_pt / 72.0), dpi=150)
            fig.patch.set_facecolor(page.background_color or "#ffffff")
            _draw_background(fig, page)
            for el in sorted(page.elements, key=lambda e: e.z):
                try:
                    _draw_element(fig, el, TH)
                except Exception:
                    # one bad element never fails the page - but a silently vanished
                    # chart/table/KPI must leave a trace to be debuggable.
                    logger.exception("PDF export: dropping element kind=%r on page %r",
                                     getattr(el, "kind", "?"), getattr(page, "index", "?"))
            _draw_furniture(fig, page, TH)
            pdf.savefig(fig, facecolor=fig.get_facecolor())
            plt.close(fig)
    return buf.getvalue()


def _theme(branding: Any) -> dict[str, Any]:
    """The inside-page palette. Reads an optional rich palette off ``branding.palette``
    (primary/ink/muted/panel/line) so a report can carry its own theme; everything falls back
    to today's default look, and ``premium`` (opt-in) turns on the upgraded section/KPI/table
    styling so ONLY reports that ask for it change — every other report is byte-identical."""
    p = getattr(branding, "palette", None)
    def g(k, d):
        v = getattr(p, k, None) if p is not None else None
        return v if isinstance(v, str) and v else d
    return {"primary": g("primary", "#E07B2B"), "ink": g("ink", "#16181d"),
            "muted": g("muted", "#5b6472"), "panel": g("panel", "#f4f6fa"),
            "line": g("line", "#e6ebf2"), "premium": bool(getattr(branding, "premium", False))}


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


def _draw_element(fig, el: RenderedElement, TH: dict[str, Any]) -> None:
    ink, muted, primary, prem = TH["ink"], TH["muted"], TH["primary"], TH["premium"]
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
                              color=(TH["line"] if prem else "#d5dbe6"), linewidth=1.2))
        return
    if el.kind in ("image", "chart", "logo", "qr"):
        _draw_image(fig, el)
        return
    if el.kind == "table":
        _draw_table(fig, el, TH)
        return
    if el.kind == "kpis":
        if prem:
            _kpi_tiles(fig, el, TH)
        else:
            _text(fig, el, "   ".join(f"{k}: {v}" for k, v in c.get("kpis", [])), _ROLE_PT["body"], ink)
        return
    if el.kind == "insight":
        if prem:
            _insight_box(fig, el, TH)
        else:
            _text(fig, el, "‣ " + c.get("text", ""), _ROLE_PT["body"], ink)
        return
    # text-like — the premium theme gives section headers an accent rule
    if prem and el.role == "h1" and (c.get("variant") == "section_header"):
        _section_header(fig, el, TH)
        return
    size, color, weight, family = _text_style(el, ink, muted)
    _text(fig, el, _plain(c.get("text", "")), size, color, weight, family)


def _text_style(el: RenderedElement, ink: str, muted: str) -> tuple[float, str, str, str | None]:
    """Resolve (size, color, weight, family) for a text element: the role-based theme default,
    with the per-block override (font_size / color / font_family) applied on top when present.
    Returns ``family=None`` when no family override is set (matplotlib keeps its default).
    With no override this is byte-identical to the original role-only styling."""
    style = el.content.get("style") or {}
    color = {"title": ink, "subtitle": muted, "meta": muted, "caption": muted}.get(el.role, ink)
    if style.get("color"):
        color = style["color"]
    size = style.get("font_size") or _ROLE_PT.get(el.role, 11)
    weight = "bold" if el.role in ("title", "h1", "h2") else "normal"
    return size, color, weight, font_for(style, "mpl")


# ---------------------------------------------------------------- premium (theme-driven) blocks
def _section_header(fig, el: RenderedElement, TH: dict[str, Any]) -> None:
    """A section title (ink, bold) with a short gold accent + a hairline rule beneath — the
    same visual language as the cover."""
    from matplotlib.lines import Line2D
    _text(fig, el, _plain(el.content.get("text", "")), _ROLE_PT["h1"], TH["ink"], "bold")
    y = 1.0 - el.fy - 0.030
    fig.add_artist(Line2D([el.fx, el.fx + 0.055], [y, y], transform=fig.transFigure,
                          color=TH["primary"], linewidth=2.6, solid_capstyle="butt"))
    fig.add_artist(Line2D([el.fx + 0.062, el.fx + el.fw], [y, y], transform=fig.transFigure,
                          color=TH["line"], linewidth=1.0))


def _kpi_tiles(fig, el: RenderedElement, TH: dict[str, Any]) -> None:
    """KPIs as clean stat tiles: panel card, a gold top accent, big value, small caps label."""
    from matplotlib.patches import Rectangle
    kpis = el.content.get("kpis", [])
    n = max(1, len(kpis)); gap = 0.012
    tw = (el.fw - gap * (n - 1)) / n
    top = 1.0 - el.fy; boxh = el.fh
    for i, (label, value) in enumerate(kpis):
        lx = el.fx + i * (tw + gap)
        ax = fig.add_axes([lx, top - boxh, tw, boxh]); ax.set_axis_off()
        ax.add_patch(Rectangle((0, 0), 1, 1, transform=ax.transAxes, facecolor=TH["panel"],
                               edgecolor=TH["line"], linewidth=1.0))
        ax.add_patch(Rectangle((0, 0.93), 1, 0.07, transform=ax.transAxes,
                               facecolor=TH["primary"], edgecolor="none"))
        ax.text(0.5, 0.60, str(value), ha="center", va="center", fontsize=16, fontweight="bold",
                color=TH["ink"], transform=ax.transAxes)
        ax.text(0.5, 0.22, str(label).upper(), ha="center", va="center", fontsize=7,
                color=TH["muted"], transform=ax.transAxes)


def _insight_box(fig, el: RenderedElement, TH: dict[str, Any]) -> None:
    """An insight/callout: soft panel with a gold left rule."""
    from matplotlib.patches import Rectangle
    left, bottom, w, h = _rect((el.fx, el.fy, el.fw, el.fh))
    ax = fig.add_axes([left, bottom, w, h]); ax.set_axis_off()
    ax.add_patch(Rectangle((0, 0), 1, 1, transform=ax.transAxes, facecolor=TH["panel"], edgecolor="none"))
    ax.add_patch(Rectangle((0, 0), 0.014, 1, transform=ax.transAxes, facecolor=TH["primary"], edgecolor="none"))
    ax.text(0.035, 0.5, el.content.get("text", ""), ha="left", va="center", fontsize=9,
            color=TH["ink"], transform=ax.transAxes, wrap=True)


def _text(fig, el: RenderedElement, s: str, size: float, color: str,
          weight: str = "normal", family: str | None = None) -> None:
    if not s:
        return
    ha = {"left": "left", "center": "center", "right": "right"}.get(el.align, "left")
    x = el.fx if ha == "left" else (el.fx + el.fw / 2 if ha == "center" else el.fx + el.fw)
    y = 1.0 - el.fy
    kw: dict[str, Any] = dict(ha=ha, va="top", fontsize=size, color=color, weight=weight,
                              wrap=True, alpha=el.opacity)
    if family:                                    # only override when set (else mpl default)
        kw["fontfamily"] = family
    fig.text(x, y, s, **kw)


def _draw_image(fig, el: RenderedElement) -> None:
    data = el.content.get("image_bytes")
    if not data:
        return
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        # a corrupt/undecodable image silently disappears from the PDF otherwise
        logger.exception("PDF export: could not decode image for element kind=%r",
                         getattr(el, "kind", "?"))
        return
    left, bottom, w, h = _rect((el.fx, el.fy, el.fw, el.fh))
    ax = fig.add_axes([left, bottom, w, h]); ax.set_axis_off()
    # charts and QR codes keep their true aspect (no stretch); photos fill the box
    ax.imshow(img, aspect="auto" if el.kind not in ("chart", "qr") else None, alpha=el.opacity)


def _draw_table(fig, el: RenderedElement, TH: dict[str, Any]) -> None:
    c = el.content
    cols, rows = c.get("columns", []), c.get("rows", [])
    if not cols:
        return
    left, bottom, w, h = _rect((el.fx, el.fy, el.fw, el.fh))
    ax = fig.add_axes([left, bottom, w, h]); ax.set_axis_off()
    tbl = ax.table(cellText=[[str(x) for x in r] for r in rows] or [[""] * len(cols)],
                   colLabels=[str(x) for x in cols], loc="upper center", cellLoc="left")
    tbl.auto_set_font_size(False); tbl.set_fontsize(8.5 if TH["premium"] else 8)
    if TH["premium"]:
        tbl.scale(1, 1.32)                            # taller, less cramped rows
        for (r, _ci), cell in tbl.get_celld().items():
            cell.set_edgecolor(TH["line"]); cell.set_linewidth(0.8)
            txt = cell.get_text()
            if r == 0:                                # header row: dark bg, white bold text
                cell.set_facecolor(TH["ink"]); txt.set_color("#ffffff"); txt.set_fontweight("bold")
            else:                                     # body rows: subtle zebra
                cell.set_facecolor("#ffffff" if (r % 2) else TH["panel"]); txt.set_color(TH["ink"])


def _draw_furniture(fig, page: RenderedPage, TH: dict[str, Any]) -> None:
    muted, primary = TH["muted"], TH["primary"]
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
    """Markdown -> plain text for vector rendering: strip heading/bullet + inline bold/italic
    markers (**bold**, __bold__, *em*) so no raw markdown shows in the PDF."""
    import re
    out = []
    for line in (text or "").splitlines():
        s = line.rstrip()
        if s.startswith("### "):
            s = s[4:]
        elif s.startswith("## "):
            s = s[3:]
        elif s.startswith("# "):
            s = s[2:]
        elif s.startswith("- "):
            s = "• " + s[2:]
        s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)        # **bold** -> bold
        s = re.sub(r"__(.+?)__", r"\1", s)            # __bold__ -> bold
        out.append(s)
    return "\n".join(out)
