"""Report exporters - render a ReportDocument to a target format.

Exporters RENDER ONLY: they never calculate, analyze or build a report. Each is
a plugin declaring the format it produces, so adding PDF/DOCX/PPTX later is one
module with no change to builders. HTML and Markdown ship now; the office
formats register as declared-but-unavailable stubs so the architecture already
supports them.
"""
from __future__ import annotations

import html as _html
from abc import abstractmethod
from dataclasses import dataclass
from typing import Any

from fap.core.exceptions import FAPError
from fap.core.plugin import Plugin, PluginInfo, PluginRegistry
from fap.reports.models import Cover, ReportDocument, Section


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
    def render(self, document: ReportDocument, branding: Any = None) -> RenderedReport: ...


exporter_registry: PluginRegistry[ReportExporter] = PluginRegistry("report_exporter")


class ReportFormatUnavailable(FAPError):
    """Raised when an exporter is registered (architecture ready) but not yet implemented."""


# ---------------------------------------------------------------- Markdown
@exporter_registry.register
class MarkdownReportExporter(ReportExporter):
    info = PluginInfo(id="report_markdown", name="Markdown", category="report_export")
    fmt = "markdown"

    def render(self, document: ReportDocument, branding: Any = None) -> RenderedReport:
        c = document.cover
        lines = [f"# {c.title}", ""]
        if c.subtitle:
            lines += [f"_{c.subtitle}_", ""]
        meta = [("Club", c.club), ("Opponent", c.opponent), ("Competition", c.competition),
                ("Season", c.season), ("Date", c.match_date), ("Analyst", c.analyst),
                ("Generated", c.generated_at), ("Version", c.version)]
        lines += [f"- **{k}:** {v}" for k, v in meta if v] + [""]
        for s in document.sections:
            lines += [f"## {s.title}"]
            if s.subtitle:
                lines += [f"_{s.subtitle}_", ""]
            if s.kpis:
                lines += ["| Metric | Value |", "| --- | --- |"]
                lines += [f"| {k.label} | {k.value} |" for k in s.kpis] + [""]
            for t in s.tables:
                if t.title:
                    lines += [f"**{t.title}**", ""]
                if t.columns:
                    lines += ["| " + " | ".join(map(str, t.columns)) + " |",
                              "| " + " | ".join(["---"] * len(t.columns)) + " |"]
                    lines += ["| " + " | ".join(map(str, r)) + " |" for r in t.rows]
                    lines += [""]
            for ins in s.insights:
                lines += [f"> {ins.text}"]
            if s.insights:
                lines += [""]
            if s.markdown:
                lines += [s.markdown, ""]
            if s.notes:
                lines += [f"**Notes:** {s.notes}", ""]
        for b in document.blocks:
            if b.hidden:
                continue
            if b.title:
                lines += [f"## {b.title}", ""]
            if b.kind == "text":
                lines += [b.payload.get("text", ""), ""]
            elif b.kind == "chart":
                lines += [f"_[chart: {b.payload.get('viz_id', '')}]_", ""]
            elif b.kind == "image":
                lines += [f"_[image: {b.payload.get('caption') or b.payload.get('image_id', '')}]_", ""]
        if document.notes:
            lines += ["## Notes", "", document.notes, ""]
        text = "\n".join(lines)
        return RenderedReport(content=text.encode("utf-8"), mime="text/markdown",
                              filename=f"{_slug(document.title)}.md", text=text)


# ---------------------------------------------------------------- HTML
@exporter_registry.register
class HtmlReportExporter(ReportExporter):
    info = PluginInfo(id="report_html", name="HTML", category="report_export")
    fmt = "html"

    def render(self, document: ReportDocument, branding: Any = None) -> RenderedReport:
        css = _report_css(branding)
        body = (_cover_html(document.cover, branding)
                + "".join(_section_html(s) for s in document.sections)
                + "".join(_block_html(b) for b in document.blocks if not b.hidden))
        if document.notes:
            body += (f"<section class='section'><h2>Notes</h2>"
                     f"<div class='notes'>{_esc(document.notes)}</div></section>")
        page = (f"<!doctype html><html><head><meta charset='utf-8'>"
                f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
                f"<title>{_esc(document.title)}</title><style>{css}</style></head>"
                f"<body><main class='report'>{body}</main></body></html>")
        return RenderedReport(content=page.encode("utf-8"), mime="text/html",
                              filename=f"{_slug(document.title)}.html", text=page)


# ---------------------------------------------------------------- office stubs (architecture-ready)
class _UnavailableExporter(ReportExporter):
    available = False

    def render(self, document: ReportDocument, branding: Any = None) -> RenderedReport:
        raise ReportFormatUnavailable(
            f"The {self.fmt.upper()} report exporter is registered but not yet implemented. "
            f"Export to HTML or Markdown, or add a renderer in fap.reports.exporters.")


@exporter_registry.register
class PdfReportExporter(_UnavailableExporter):
    info = PluginInfo(id="report_pdf", name="PDF", category="report_export")
    fmt = "pdf"


@exporter_registry.register
class DocxReportExporter(_UnavailableExporter):
    info = PluginInfo(id="report_docx", name="Word (DOCX)", category="report_export")
    fmt = "docx"


@exporter_registry.register
class PptxReportExporter(_UnavailableExporter):
    info = PluginInfo(id="report_pptx", name="PowerPoint (PPTX)", category="report_export")
    fmt = "pptx"


def load_builtin_exporters() -> None:
    """Registration happens on import; kept for symmetry with other families."""
    return None


# ---------------------------------------------------------------- html helpers
def _esc(s: Any) -> str:
    return _html.escape(str(s), quote=True)


def _slug(s: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in s.strip().lower()).strip("_") or "report"


def _report_css(branding: Any) -> str:
    p = getattr(branding, "palette", None)
    primary = getattr(p, "primary", "#E07B2B")
    ink = "#16181d"
    return (
        f"body{{margin:0;background:#eef1f6;color:{ink};"
        f"font-family:-apple-system,Segoe UI,Roboto,sans-serif;}}"
        ".report{max-width:900px;margin:0 auto;background:#fff;}"
        ".cover{padding:56px 48px;border-bottom:4px solid " + primary + ";}"
        ".cover h1{font-size:34px;margin:8px 0;}"
        ".cover .sub{color:#5b6472;font-size:16px;}"
        ".cover .meta{margin-top:24px;display:grid;grid-template-columns:1fr 1fr;gap:6px 24px;font-size:14px;}"
        ".cover .meta b{color:#5b6472;font-weight:600;}"
        ".cover .logos{display:flex;gap:16px;align-items:center;margin-bottom:12px;}"
        ".cover .logos img{height:56px;}"
        ".section{padding:28px 48px;border-bottom:1px solid #e6ebf2;}"
        ".section h2{font-size:20px;margin:0 0 2px;}"
        ".section .subtitle{color:#5b6472;font-size:13px;margin-bottom:14px;}"
        ".kpis{display:flex;flex-wrap:wrap;gap:12px;margin:8px 0 14px;}"
        ".kpi{border:1px solid #e2e8f0;border-radius:10px;padding:10px 14px;min-width:120px;}"
        ".kpi .label{color:#5b6472;font-size:12px;}.kpi .value{font-size:20px;font-weight:750;}"
        "table{border-collapse:collapse;width:100%;margin:8px 0 14px;font-size:13px;}"
        "th,td{border:1px solid #e6ebf2;padding:6px 10px;text-align:left;}"
        "th{background:#f4f6fa;}"
        ".insight{border-left:3px solid " + primary + ";padding:6px 12px;margin:6px 0;"
        "background:#faf6f0;font-size:14px;}"
        ".notes{color:#5b6472;font-size:13px;font-style:italic;margin-top:8px;}"
        "@media print{body{background:#fff;}.report{max-width:none;}}"
    )


def _cover_html(c: Cover, branding: Any) -> str:
    logos = ""
    for path in (c.club_logo, c.organization_logo):
        if path:
            try:
                from fap.theme import logo_data_uri
                logos += f"<img src='{logo_data_uri(path)}' alt='logo'/>"
            except Exception:
                pass
    rows = [("Club", c.club), ("Opponent", c.opponent), ("Competition", c.competition),
            ("Season", c.season), ("Match date", c.match_date), ("Analyst", c.analyst),
            ("Generated", c.generated_at), ("Version", c.version)]
    meta = "".join(f"<div><b>{_esc(k)}</b><br>{_esc(v)}</div>" for k, v in rows if v)
    return (f"<section class='cover'><div class='logos'>{logos}</div>"
            f"<h1>{_esc(c.title)}</h1><div class='sub'>{_esc(c.subtitle)}</div>"
            f"<div class='meta'>{meta}</div></section>")


def _markdown_to_html(text: str) -> str:
    """Minimal, safe rendering of the editor's text blocks: #/##/### headings,
    - bullets, blank-line paragraphs. Everything is escaped first."""
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


def _block_html(b: Any) -> str:
    """Render one editor block. Charts/images arrive pre-materialized as base64
    - the exporter only embeds, it never renders a chart itself."""
    parts = ["<section class='section fap-block'>"]
    if b.title:
        parts.append(f"<h2>{_esc(b.title)}</h2>")
    if b.kind == "text":
        parts.append(_markdown_to_html(b.payload.get("text", "")))
    elif b.kind in ("image", "chart"):
        data = b.payload.get("image_b64", "")
        mime = b.payload.get("mime", "image/png")
        width = int(b.payload.get("width_pct", 100) or 100)
        if data:
            parts.append(f"<img style='width:{width}%;max-width:100%' "
                         f"alt='{_esc(b.title or b.kind)}' src='data:{mime};base64,{data}'/>")
        elif b.kind == "chart":
            parts.append(f"<div class='notes'>Chart “{_esc(b.payload.get('viz_id',''))}” "
                         f"could not be regenerated (no dataset available).</div>")
        caption = b.payload.get("caption", "")
        if caption:
            parts.append(f"<div class='notes'>{_esc(caption)}</div>")
    parts.append("</section>")
    return "".join(parts)


def _section_html(s: Section) -> str:
    parts = [f"<section class='section'><h2>{_esc(s.title)}</h2>"]
    if s.subtitle:
        parts.append(f"<div class='subtitle'>{_esc(s.subtitle)}</div>")
    if s.kpis:
        cards = "".join(f"<div class='kpi'><div class='label'>{_esc(k.label)}</div>"
                        f"<div class='value'>{_esc(k.value)}</div></div>" for k in s.kpis)
        parts.append(f"<div class='kpis'>{cards}</div>")
    for t in s.tables:
        if t.title:
            parts.append(f"<b>{_esc(t.title)}</b>")
        head = "".join(f"<th>{_esc(c)}</th>" for c in t.columns)
        body = "".join("<tr>" + "".join(f"<td>{_esc(v)}</td>" for v in r) + "</tr>" for r in t.rows)
        parts.append(f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>")
    for c in s.charts:
        if c.image_b64:
            parts.append(f"<img style='max-width:100%' alt='{_esc(c.title)}' "
                         f"src='data:image/png;base64,{c.image_b64}'/>")
    for ins in s.insights:
        parts.append(f"<div class='insight'>{_esc(ins.text)}</div>")
    if s.markdown:
        parts.append(f"<p>{_esc(s.markdown)}</p>")
    if s.notes:
        parts.append(f"<div class='notes'>{_esc(s.notes)}</div>")
    parts.append("</section>")
    return "".join(parts)
