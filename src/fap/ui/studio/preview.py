"""WYSIWYG A4 document preview for the Report Studio (UI only).

The professional reporting systems (Hudl, StatsBomb IQ, Wyscout) show the actual
paginated document while you edit. We get that for free and with perfect
fidelity by rendering the platform's **existing HTML exporter** — the very same
``RenderedDocument`` the PDF exporter consumes — and displaying it inside the
app. Nothing here computes a layout or renders a chart: it calls
``ReportsManager.render(..., "html")`` (unchanged engine) and only *decorates*
the returned HTML string for on-screen display (a neutral "desk", page shadows,
zoom). Charts are the same base64 PNGs that land in the PDF, so the preview is
what the export will be.

Performance: ``render()`` re-materializes charts and writes an audit row per
call, so the preview is rendered **once per content change** and cached in
``st.session_state`` keyed by a signature of the document. Plain reruns (typing
in a widget, opening an expander) reuse the cache; only a real edit — which
changes the document and therefore the signature — triggers a re-render.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import streamlit as st

_CACHE = "_studio_preview_cache"        # {report_id: {"sig":..., "html":..., "pages":int}}
A4_RATIO = 297 / 210


# ---------------------------------------------------------------- signature
def document_signature(reports: Any, report_id: str) -> str:
    """A stable hash of the report's current document (content + publish/studio
    overlays). Changes iff something that affects the rendered output changed."""
    try:
        doc = reports.document(report_id)
        payload = json.dumps(doc.to_dict(), sort_keys=True, default=str) if doc else report_id
    except Exception:
        payload = report_id
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def invalidate(report_id: str) -> None:
    """Drop the cached preview (called after an edit so it re-renders once)."""
    cache = st.session_state.get(_CACHE) or {}
    cache.pop(report_id, None)
    st.session_state[_CACHE] = cache


# ---------------------------------------------------------------- render + cache
def get_preview_html(shell: Any, reports: Any, report_id: str) -> tuple[str, int]:
    """Return (raw_export_html, page_count), rendering at most once per content
    change. Falls back to an empty string on failure so the caller can show a
    friendly state rather than crashing."""
    sig = document_signature(reports, report_id)
    cache = st.session_state.get(_CACHE) or {}
    hit = cache.get(report_id)
    if hit and hit.get("sig") == sig:
        return hit["html"], hit.get("pages", 0)
    try:
        html = reports.render(shell.user, report_id, "html").text
    except Exception as exc:                        # keep the workspace alive
        return f"__ERROR__{exc}", 0
    pages = html.count("class='page'") + html.count('class="page"')
    cache[report_id] = {"sig": sig, "html": html, "pages": pages}
    st.session_state[_CACHE] = cache
    return html, pages


# ---------------------------------------------------------------- decoration
def decorate(html: str, *, zoom: float = 1.0) -> str:
    """Wrap the export HTML for on-screen display: a neutral studio desk, drop
    shadows and rounded corners on each A4 page, and a zoom level. We never touch
    the report's own typography/colours — the paper must look exactly like the
    exported document, so only the *surround* is styled here."""
    overlay = f"""
<style>
  html, body {{ margin: 0; background: #E7EBF2; }}
  .report {{ padding: 26px 12px 40px !important; gap: 22px !important;
    display: flex !important; flex-direction: column !important; align-items: center !important;
    zoom: {zoom:.3f}; }}
  .report .page {{ box-shadow: 0 6px 24px rgba(16,22,30,0.20), 0 1px 3px rgba(16,22,30,0.12);
    border-radius: 4px; overflow: hidden; outline: 1px solid rgba(16,22,30,0.06); }}
  ::-webkit-scrollbar {{ width: 12px; height: 12px; }}
  ::-webkit-scrollbar-thumb {{ background: #b7c0cf; border-radius: 999px;
    border: 3px solid #E7EBF2; background-clip: padding-box; }}
</style>"""
    # number the pages so the outline can reference them, and inject our overlay
    n = {"i": 0}

    def _tag(m: re.Match) -> str:
        n["i"] += 1
        return m.group(0)[:-1] + f" id='sp-page-{n['i']}'>"

    html = re.sub(r"<section class=['\"]page['\"][^>]*>", _tag, html, count=0)
    if "</head>" in html:
        return html.replace("</head>", overlay + "</head>", 1)
    return overlay + html


# ---------------------------------------------------------------- outline (TOC)
_HEADING_RE = re.compile(r"^\s{0,3}#{1,3}\s+(.+?)\s*#*\s*$", re.MULTILINE)


def outline(studio: Any) -> list[dict[str, Any]]:
    """A navigable table of contents built from the document's sections: one
    entry per visible block, using its title (or first markdown heading)."""
    items: list[dict[str, Any]] = []
    for i, b in enumerate(getattr(studio.document, "blocks", []) or []):
        variant = (b.payload or {}).get("variant", "")
        title = (b.title or "").strip()
        if not title and b.kind == "text":
            m = _HEADING_RE.search((b.payload or {}).get("text", ""))
            title = m.group(1).strip() if m else "Untitled"
        items.append({
            "id": b.id, "index": i, "kind": b.kind, "variant": variant,
            "title": title or b.kind.title(), "hidden": bool(b.hidden),
        })
    return items
