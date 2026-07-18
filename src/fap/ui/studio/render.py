"""Editor-preview rendering: turn one block into the HTML the canvas shows.

This is the *live editor preview* only. The export path is unchanged and remains
the single source of truth (``fap.reports.exporters``); for text we even reuse the
exporter's own markdown converter so the preview matches the export. Charts reuse
``ReportsManager.preview_chart`` (the platform Renderer + byte cache); images reuse
``ReportsManager.image_bytes`` (ImageStorage). Nothing here draws a chart or stores
an image itself.
"""
from __future__ import annotations

import base64
import html as _html
from typing import Any

from fap.reports.exporters import _markdown_to_html  # reuse: preview == export text

# extra block variants layered on the existing "text" kind (payload["variant"])
SECTION_HEADER = "section_header"
NOTES = "notes"
DIVIDER = "divider"
SPACER = "spacer"


def _esc(s: Any) -> str:
    return _html.escape(str(s), quote=True)


def block_content_html(block: Any, *, reports: Any, dataset_id: str | None,
                       theme_id: str | None, colors: dict[str, str],
                       chart_cache: dict[str, str] | None = None) -> str:
    """HTML for a block's interior (no positioning - the canvas positions it)."""
    text_col = colors.get("text", "#16181d")
    muted = colors.get("muted", "#5b6472")
    accent = colors.get("accent", "#2563EB")
    border = colors.get("border", "#e2e8f0")
    kind = block.kind
    p = block.payload or {}

    if kind == "text":
        variant = p.get("variant", "")
        if variant == DIVIDER:
            return f"<hr style='border:none;border-top:2px solid {border};margin:0'/>"
        if variant == SPACER:
            return "<div></div>"
        body = _markdown_to_html(p.get("text", ""))
        if variant == SECTION_HEADER:
            return (f"<div style='color:{text_col};font-weight:800;font-size:20px;"
                    f"border-bottom:2px solid {accent};padding-bottom:4px'>{body}</div>")
        if variant == NOTES:
            return (f"<div style='color:{text_col};background:{colors.get('surface_alt', '#f4f6fa')};"
                    f"border-left:3px solid {accent};padding:8px 12px;font-size:14px'>{body}</div>")
        return f"<div style='color:{text_col};font-size:15px;line-height:1.45'>{body}</div>"

    if kind == "image":
        image_id = p.get("image_id", "")
        data = reports.image_bytes(image_id) if image_id else None
        radius = int(p.get("radius", 0) or 0)
        opacity = float(p.get("opacity", 1) or 1)
        fit = p.get("fit", "cover")
        if data:
            mime = reports.image_mime(image_id) or "image/png"
            b64 = base64.b64encode(data).decode("ascii")
            img = (f"<img src='data:{mime};base64,{b64}' "
                   f"style='width:100%;height:100%;object-fit:{fit};"
                   f"border-radius:{radius}px;opacity:{opacity};display:block'/>")
        else:
            img = (f"<div style='width:100%;height:100%;display:flex;align-items:center;"
                   f"justify-content:center;color:{muted};border:1px dashed {border}'>image</div>")
        cap = p.get("caption", "")
        if cap:
            img += f"<div style='color:{muted};font-size:12px;margin-top:4px'>{_esc(cap)}</div>"
        return img

    if kind == "chart":
        viz_id = p.get("viz_id", "")
        controls = p.get("controls", {})
        key = f"{viz_id}|{hash(repr(sorted(controls.items())))}|{theme_id}"
        b64 = None
        if chart_cache is not None and key in chart_cache:
            b64 = chart_cache[key]
        else:
            frame = reports.dataset_frame(dataset_id)
            if frame is not None and viz_id:
                png = reports.preview_chart(viz_id, frame, controls)
                if png:
                    b64 = base64.b64encode(png).decode("ascii")
            if chart_cache is not None and b64:
                chart_cache[key] = b64
        if b64:
            return (f"<img src='data:image/png;base64,{b64}' "
                    f"style='width:100%;height:100%;object-fit:contain;display:block'/>")
        return (f"<div style='width:100%;height:100%;display:flex;align-items:center;"
                f"justify-content:center;color:{muted};border:1px dashed {border};"
                f"text-align:center;font-size:13px'>chart “{_esc(viz_id)}”<br/>needs a dataset</div>")

    return f"<div style='color:{muted}'>{_esc(kind)}</div>"
