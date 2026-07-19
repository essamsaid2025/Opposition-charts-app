"""Report exporters - every one renders the SAME ``RenderedDocument`` produced by
the Layout Engine (``fap.reports.layout``). An exporter only maps rendered pages
onto its medium; it never calculates a layout, so there is one layout engine and
zero duplicated positioning logic.

Ships and runs here: Markdown, HTML (print-CSS multi-page), PDF (matplotlib - the
platform's own rendering engine, so vector text + embedded images, no new
dependency). Implemented and import-guarded: DOCX (python-docx) and PPTX
(python-pptx) - real editable output when the library is installed, otherwise the
long-standing "declared but unavailable" degradation.

Back-compat: ``ReportExporter.render(document, branding)`` still works - the base
builds the layout and calls ``export(rendered, branding)``.
"""
from __future__ import annotations

import html as _html
import importlib.util
import io
from abc import abstractmethod
from dataclasses import dataclass
from typing import Any

from fap.core.exceptions import FAPError
from fap.core.plugin import Plugin, PluginInfo, PluginRegistry
from fap.reports.layout import (
    LayoutEngine, RenderedDocument, RenderedElement, RenderedPage, ResolvedZone,
)
from fap.reports.models import ReportDocument


def _has(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except Exception:
        return False


_HAS_MPL = _has("matplotlib")
_HAS_DOCX = _has("docx")
_HAS_PPTX = _has("pptx")
_HAS_PIL = _has("PIL")


@dataclass(slots=True)
class RenderedReport:
    content: bytes
    mime: str
    filename: str
    text: str = ""                 # convenience for text formats


class ReportExporter(Plugin):
    fmt: str = ""                  # html | markdown | pdf | docx | pptx
    available: bool = True

    @abstractmethod
    def export(self, rendered: RenderedDocument, branding: Any = None) -> RenderedReport: ...

    # back-compat entry: build the layout then export (single code path)
    def render(self, document: ReportDocument, branding: Any = None,
               image_resolver: Any = None) -> RenderedReport:
        rendered = LayoutEngine().build(document, branding, image_resolver)
        return self.export(rendered, branding)


exporter_registry: PluginRegistry[ReportExporter] = PluginRegistry("report_exporter")


class ReportFormatUnavailable(FAPError):
    """Raised when an exporter is registered (architecture ready) but its optional
    dependency is not installed."""


# ================================================================ Markdown
@exporter_registry.register
class MarkdownReportExporter(ReportExporter):
    info = PluginInfo(id="report_markdown", name="Markdown", category="report_export")
    fmt = "markdown"

    def export(self, rendered: RenderedDocument, branding: Any = None) -> RenderedReport:
        lines: list[str] = [f"# {rendered.title}", ""]
        for page in rendered.pages:
            if page.role == "cover":
                lines += [f"# {_el_text(page, 'title') or rendered.title}", ""]
                sub = _el_text(page, "subtitle")
                if sub:
                    lines += [f"_{sub}_", ""]
                meta = _el_text(page, "meta")
                if meta:
                    lines += [m for m in meta.splitlines()] + [""]
                lines += ["---", ""]
                continue
            if page.number:
                lines += [f"<!-- {page.number} -->"]
            for el in _ordered(page.elements):
                lines += _md_element(el)
            lines += ["", "---", ""]
        text = "\n".join(lines).rstrip() + "\n"
        return RenderedReport(content=text.encode("utf-8"), mime="text/markdown",
                              filename=f"{_slug(rendered.title)}.md", text=text)


def _md_element(el: RenderedElement) -> list[str]:
    c = el.content
    if el.kind == "divider":
        return ["", "---", ""]
    if el.kind == "spacer":
        return [""]
    if el.kind == "text":
        return [c.get("text", ""), ""]
    if el.kind == "chart":
        return [f"_[chart: {c.get('viz_id', '') or 'visualization'}]_", ""]
    if el.kind == "image":
        return [f"_[image: {c.get('caption') or 'image'}]_", ""]
    if el.kind == "kpis":
        rows = c.get("kpis", [])
        return ["| Metric | Value |", "| --- | --- |"] + [f"| {k} | {v} |" for k, v in rows] + [""]
    if el.kind == "table":
        cols = c.get("columns", [])
        out = []
        if c.get("title"):
            out += [f"**{c['title']}**", ""]
        if cols:
            out += ["| " + " | ".join(map(str, cols)) + " |",
                    "| " + " | ".join(["---"] * len(cols)) + " |"]
            out += ["| " + " | ".join(map(str, r)) + " |" for r in c.get("rows", [])]
        return out + [""]
    if el.kind == "insight":
        return [f"> {c.get('text', '')}", ""]
    return []


# ================================================================ HTML
@exporter_registry.register
class HtmlReportExporter(ReportExporter):
    info = PluginInfo(id="report_html", name="HTML", category="report_export")
    fmt = "html"

    def export(self, rendered: RenderedDocument, branding: Any = None) -> RenderedReport:
        css = _page_css(branding)
        body = "".join(_page_html(p, branding) for p in rendered.pages)
        page = (f"<!doctype html><html><head><meta charset='utf-8'>"
                f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
                f"<title>{_esc(rendered.title)}</title><style>{css}</style></head>"
                f"<body><div class='report'>{body}</div></body></html>")
        return RenderedReport(content=page.encode("utf-8"), mime="text/html",
                              filename=f"{_slug(rendered.title)}.html", text=page)


# ================================================================ PDF (matplotlib)
class PdfReportExporter(ReportExporter):
    info = PluginInfo(id="report_pdf", name="PDF", category="report_export")
    fmt = "pdf"
    available = _HAS_MPL

    def export(self, rendered: RenderedDocument, branding: Any = None) -> RenderedReport:
        if not _HAS_MPL:
            raise ReportFormatUnavailable(
                "PDF export needs matplotlib (the platform visualization engine). "
                "Install matplotlib or export to HTML/Markdown.")
        from fap.reports._pdf import render_pdf         # lazy: keeps matplotlib off import path
        data = render_pdf(rendered, branding)
        return RenderedReport(content=data, mime="application/pdf",
                              filename=f"{_slug(rendered.title)}.pdf")


exporter_registry.register(PdfReportExporter)


# ================================================================ DOCX / PPTX
class DocxReportExporter(ReportExporter):
    info = PluginInfo(id="report_docx", name="Word (DOCX)", category="report_export")
    fmt = "docx"
    available = _HAS_DOCX

    def export(self, rendered: RenderedDocument, branding: Any = None) -> RenderedReport:
        if not _HAS_DOCX:
            raise ReportFormatUnavailable(
                "DOCX export needs python-docx (`pip install python-docx`). "
                "Export to PDF/HTML/Markdown, or install the library.")
        from fap.reports._office import render_docx
        data = render_docx(rendered, branding)
        return RenderedReport(
            content=data,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=f"{_slug(rendered.title)}.docx")


class PptxReportExporter(ReportExporter):
    info = PluginInfo(id="report_pptx", name="PowerPoint (PPTX)", category="report_export")
    fmt = "pptx"
    available = _HAS_PPTX

    def export(self, rendered: RenderedDocument, branding: Any = None) -> RenderedReport:
        if not _HAS_PPTX:
            raise ReportFormatUnavailable(
                "PPTX export needs python-pptx (`pip install python-pptx`). "
                "Export to PDF/HTML/Markdown, or install the library.")
        from fap.reports._office import render_pptx
        data = render_pptx(rendered, branding)
        return RenderedReport(
            content=data,
            mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            filename=f"{_slug(rendered.title)}.pptx")


exporter_registry.register(DocxReportExporter)
exporter_registry.register(PptxReportExporter)


def load_builtin_exporters() -> None:
    """Registration happens on import; kept for symmetry with other families."""
    return None


# ================================================================ shared helpers
def _esc(s: Any) -> str:
    return _html.escape(str(s), quote=True)


def _slug(s: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in (s or "").strip().lower()).strip("_") or "report"


def _ordered(elements: list[RenderedElement]) -> list[RenderedElement]:
    """Top-to-bottom, then left-to-right - the reading order for linear media."""
    return sorted(elements, key=lambda e: (round(e.fy, 3), round(e.fx, 3), e.z))


def _el_text(page: RenderedPage, role: str) -> str:
    for el in page.elements:
        if el.kind == "text" and el.role == role:
            return el.content.get("text", "")
    return ""


def _markdown_to_html(text: str) -> str:
    """Minimal, safe rendering of editor text blocks: #/##/### headings, - bullets,
    blank-line paragraphs. Everything is escaped first."""
    html_lines, bullets = [], False
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if line.startswith("- "):
            if not bullets:
                html_lines.append("<ul>"); bullets = True
            html_lines.append(f"<li>{_esc(line[2:])}</li>")
            continue
        if bullets:
            html_lines.append("</ul>"); bullets = False
        if line.startswith("### "):
            html_lines.append(f"<h4>{_esc(line[4:])}</h4>")
        elif line.startswith("## "):
            html_lines.append(f"<h3>{_esc(line[3:])}</h3>")
        elif line.startswith("# "):
            html_lines.append(f"<h2>{_esc(line[2:])}</h2>")
        elif line.strip():
            html_lines.append(f"<p>{_esc(line)}</p>")
    if bullets:
        html_lines.append("</ul>")
    return "".join(html_lines)


# ---------------------------------------------------------------- html builders
def _palette(branding: Any) -> dict[str, str]:
    p = getattr(branding, "palette", None)
    return {
        "primary": getattr(p, "primary", "#E07B2B"),
        "ink": "#16181d", "muted": "#5b6472", "line": "#e6ebf2",
        "panel": "#f4f6fa", "cover_ink": "#ffffff",
    }


def _page_css(branding: Any) -> str:
    c = _palette(branding)
    return (
        "*{box-sizing:border-box;}"
        f"body{{margin:0;background:#5a606b;color:{c['ink']};"
        "font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;}"
        ".report{padding:20px;display:flex;flex-direction:column;align-items:center;gap:20px;}"
        ".page{position:relative;background:#fff;box-shadow:0 6px 24px rgba(0,0,0,.28);"
        "overflow:hidden;}"
        ".page .content{position:absolute;inset:0;}"
        ".el{position:absolute;overflow:hidden;}"
        ".el h2{font-size:1.6em;margin:0 0 .2em;}.el h3{font-size:1.25em;margin:0 0 .2em;}"
        ".el h4{font-size:1.05em;margin:0 0 .2em;}.el p{margin:0 0 .4em;line-height:1.4;}"
        ".el ul{margin:.2em 0 .4em 1.1em;padding:0;}"
        ".role-title{font-size:2.4em;font-weight:850;letter-spacing:-.02em;}"
        f".role-subtitle{{font-size:1.2em;color:{c['muted']};}}"
        ".role-h1{font-size:1.5em;font-weight:800;border-bottom:2px solid " + c['primary'] + ";}"
        f".role-meta{{font-size:.95em;color:{c['muted']};white-space:pre-line;}}"
        ".kpis{display:flex;flex-wrap:wrap;gap:10px;}"
        f".kpi{{border:1px solid {c['line']};border-radius:10px;padding:8px 12px;min-width:110px;}}"
        f".kpi .l{{color:{c['muted']};font-size:.8em;}}.kpi .v{{font-size:1.4em;font-weight:800;}}"
        "table{border-collapse:collapse;width:100%;font-size:.85em;}"
        f"th,td{{border:1px solid {c['line']};padding:4px 8px;text-align:left;}}th{{background:{c['panel']};}}"
        f".insight{{border-left:3px solid {c['primary']};padding:4px 10px;background:{c['panel']};}}"
        ".hf{position:absolute;left:0;right:0;display:flex;justify-content:space-between;"
        f"font-size:10px;color:{c['muted']};padding:0 6%;}}"
        ".hf .c{flex:1;text-align:center;}.hf .r{text-align:right;}"
        ".wm{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;"
        "pointer-events:none;font-weight:800;}"
        ".pnum{position:absolute;bottom:2.5%;right:6%;font-size:10px;color:" + c['muted'] + ";}"
        ".conf{position:absolute;top:2.5%;left:6%;font-size:10px;font-weight:700;color:" + c['primary'] + ";"
        "letter-spacing:.08em;}"
        "@media print{body{background:#fff;}.report{padding:0;gap:0;}"
        ".page{box-shadow:none;page-break-after:always;}}"
    )


def _mm(pt: float) -> str:
    return f"{pt / 72 * 25.4:.2f}mm"


def _page_html(page: RenderedPage, branding: Any) -> str:
    style = (f"width:{_mm(page.width_pt)};height:{_mm(page.height_pt)};"
             f"background:{page.background_color or '#ffffff'};")
    parts = [f"<section class='page' style='{style}'>"]
    if page.background_bytes:
        b64 = _b64(page.background_bytes)
        parts.append(f"<img class='content' style='object-fit:cover' src='data:image/png;base64,{b64}'/>")
    parts.append("<div class='content'>")
    for el in sorted(page.elements, key=lambda e: e.z):
        parts.append(_element_html(el))
    parts.append("</div>")
    if page.watermark:
        parts.append(_watermark_html(page.watermark))
    m = page.margins_pt
    if page.header and not page.header.is_empty():
        top = m[0] / page.height_pt * 100 * 0.5
        parts.append(_hf_html(page.header, f"top:{top:.1f}%;"))
    if page.footer and not page.footer.is_empty():
        parts.append(_hf_html(page.footer, "bottom:3%;"))
    if page.number:
        parts.append(f"<div class='pnum'>{_esc(page.number)}</div>")
    if page.confidential:
        parts.append(f"<div class='conf'>{_esc(page.confidential)}</div>")
    if page.crop_marks:
        parts.append("<div class='crop'></div>")
    parts.append("</section>")
    return "".join(parts)


def _pct(v: float) -> str:
    return f"{v * 100:.3f}%"


def _element_html(el: RenderedElement) -> str:
    box = (f"left:{_pct(el.fx)};top:{_pct(el.fy)};width:{_pct(el.fw)};height:{_pct(el.fh)};"
           f"z-index:{el.z};opacity:{el.opacity};text-align:{el.align};")
    if el.rotation:
        box += f"transform:rotate({el.rotation}deg);"
    inner = _element_inner(el)
    return f"<div class='el role-{el.role}' style='{box}'>{inner}</div>"


def _element_inner(el: RenderedElement) -> str:
    c = el.content
    if el.kind == "divider":
        return "<hr style='border:none;border-top:2px solid #d5dbe6;margin:0'/>"
    if el.kind == "spacer":
        return ""
    if el.kind == "cover_overlay":
        return (f"<div style='position:absolute;inset:0;background:{c.get('color', '#000')};"
                f"opacity:{c.get('opacity', 0.3)}'></div>")
    if el.kind == "text":
        return _markdown_to_html(c.get("text", ""))
    if el.kind == "logo":
        data = c.get("image_bytes")
        return f"<img style='max-width:100%;max-height:100%' src='data:image/png;base64,{_b64(data)}'/>" if data else ""
    if el.kind in ("image", "chart"):
        data = c.get("image_bytes")
        fit = c.get("fit", "contain" if el.kind == "chart" else "cover")
        out = ""
        if data:
            out = (f"<img style='width:100%;height:100%;object-fit:{fit};"
                   f"border-radius:{el.radius}px' src='data:{c.get('mime', 'image/png')};base64,{_b64(data)}'/>")
        elif el.kind == "chart":
            out = f"<div style='color:#8a93a2'>chart “{_esc(c.get('viz_id', ''))}”</div>"
        if c.get("caption"):
            out += f"<div style='font-size:11px;color:#5b6472'>{_esc(c['caption'])}</div>"
        return out
    if el.kind == "kpis":
        return "<div class='kpis'>" + "".join(
            f"<div class='kpi'><div class='l'>{_esc(k)}</div><div class='v'>{_esc(v)}</div></div>"
            for k, v in c.get("kpis", [])) + "</div>"
    if el.kind == "table":
        head = "".join(f"<th>{_esc(x)}</th>" for x in c.get("columns", []))
        rows = "".join("<tr>" + "".join(f"<td>{_esc(x)}</td>" for x in r) + "</tr>"
                       for r in c.get("rows", []))
        title = f"<b>{_esc(c['title'])}</b>" if c.get("title") else ""
        return f"{title}<table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>"
    if el.kind == "insight":
        return f"<div class='insight'>{_esc(c.get('text', ''))}</div>"
    return ""


def _hf_html(zone: ResolvedZone, pos: str) -> str:
    return (f"<div class='hf' style='{pos}'><div class='l'>{_esc(zone.left)}</div>"
            f"<div class='c'>{_esc(zone.center)}</div><div class='r'>{_esc(zone.right)}</div></div>")


def _watermark_html(wm: Any) -> str:
    if wm.image_bytes:
        inner = (f"<img style='max-width:60%;opacity:{wm.opacity};"
                 f"transform:rotate({wm.rotation}deg)' src='data:image/png;base64,{_b64(wm.image_bytes)}'/>")
    else:
        color = wm.color or "#8a93a2"
        inner = (f"<span style='opacity:{wm.opacity};color:{color};font-size:{wm.font_size}px;"
                 f"transform:rotate({wm.rotation}deg)'>{_esc(wm.text)}</span>")
    return f"<div class='wm'>{inner}</div>"


def _b64(data: bytes | None) -> str:
    import base64
    return base64.b64encode(data).decode("ascii") if data else ""
