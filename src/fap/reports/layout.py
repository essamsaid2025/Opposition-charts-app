"""The Layout Engine - the single renderer shared by every exporter.

    ReportDocument -> ReportStudio -> Pages -> Blocks -> Layout -> RenderedPages

``LayoutEngine.build`` turns a report (its studio overlay + publish settings) into a
``RenderedDocument``: an ordered list of ``RenderedPage`` objects with resolution-
INDEPENDENT geometry (every element's box is a fraction 0..1 of its page). HTML uses
percentages, PDF multiplies by points, PPTX by EMUs, DOCX by page width - one model,
five media, zero duplicated layout logic.

Pure domain code: no Streamlit, no matplotlib, no I/O. Raster content (charts,
images) arrives already inlined on the blocks (``payload["image_b64"]``, produced by
``ReportsManager._materialize``); publish-level rasters (cover/watermark/master
backgrounds, logo ids) are resolved through an optional ``image_resolver`` so the
engine never imports storage.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any, Callable

from fap.reports.models import Cover, ReportDocument, Section
from fap.reports.publishing import MasterPage, PublishSettings, Watermark, Zone
from fap.reports.studio import ReportStudio, page_size

_MM_PER_IN = 25.4
_PT_PER_IN = 72.0


def _mm_to_pt(mm: float) -> float:
    return mm / _MM_PER_IN * _PT_PER_IN


# ================================================================ rendered model
@dataclass(slots=True)
class RenderedElement:
    """One positioned piece of content on a page. Geometry is fractional (0..1)."""
    kind: str                          # text | image | chart | divider | spacer |
                                       # heading | kpis | table | insight | logo
    fx: float = 0.0
    fy: float = 0.0
    fw: float = 1.0
    fh: float = 0.1
    z: int = 0
    rotation: float = 0.0
    opacity: float = 1.0
    radius: float = 0.0
    align: str = "left"
    role: str = "body"                 # title | subtitle | h1 | h2 | body | caption | meta
    content: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ResolvedZone:
    left: str = ""
    center: str = ""
    right: str = ""

    def is_empty(self) -> bool:
        return not (self.left or self.center or self.right)


@dataclass(slots=True)
class ResolvedWatermark:
    text: str = ""
    image_bytes: bytes | None = None
    opacity: float = 0.12
    rotation: float = 30.0
    position: str = "center"
    font_size: int = 64
    color: str = ""


@dataclass(slots=True)
class RenderedPage:
    index: int
    role: str                          # cover | inside | last | flow
    width_pt: float
    height_pt: float
    width_px: float
    height_px: float
    orientation: str = "portrait"
    size_name: str = "A4"
    margins_pt: tuple[float, float, float, float] = (54, 48, 54, 48)   # T R B L
    bleed_pt: float = 0.0
    safe_pt: float = 14.0
    crop_marks: bool = False
    background_color: str = ""
    background_bytes: bytes | None = None
    number: str | None = None          # display string, or None (no number)
    confidential: str = ""
    header: ResolvedZone | None = None
    footer: ResolvedZone | None = None
    watermark: ResolvedWatermark | None = None
    elements: list[RenderedElement] = field(default_factory=list)


@dataclass(slots=True)
class RenderedDocument:
    title: str
    pages: list[RenderedPage]
    settings: PublishSettings
    meta: dict[str, Any] = field(default_factory=dict)


# ================================================================ engine
ImageResolver = Callable[[str], "bytes | None"]


class LayoutEngine:
    """Builds a ``RenderedDocument`` from a ``ReportDocument``. Stateless."""

    def build(self, document: ReportDocument, branding: Any = None,
              image_resolver: ImageResolver | None = None) -> RenderedDocument:
        settings = PublishSettings.from_document(document)
        studio = ReportStudio.from_document(document)
        resolve = image_resolver or (lambda _id: None)

        pages: list[RenderedPage] = []

        # 1) generated cover (from Cover + cover design) --------------------
        if settings.cover.enabled and _has_cover(document.cover):
            pages.append(self._cover_page(document.cover, settings, branding, resolve))

        # 2) legacy/template sections -> auto-paginated flow pages ----------
        if document.sections:
            pages.extend(self._flow_pages(document.sections, settings, resolve))

        # 3) studio pages (positioned blocks) -------------------------------
        studio_pages = studio.pages
        skip_empty = bool(document.sections)      # template report: don't emit a blank canvas
        for page in studio_pages:
            blocks = [b for b in studio.blocks_on(page.id) if not b.hidden]
            if not blocks and skip_empty:
                continue
            pages.append(self._studio_page(page, studio, blocks, settings, resolve))

        if not pages:                              # never emit an empty document
            pages.append(self._blank_page(settings, resolve))

        # 4) roles, numbering, furniture ------------------------------------
        self._assign_roles(pages, settings)
        self._assign_numbers(pages, settings)
        for p in pages:
            self._apply_furniture(p, document.cover, settings, resolve)

        return RenderedDocument(title=document.title, pages=pages, settings=settings,
                                meta={"page_count": len(pages)})

    # -------------------------------------------------------------- geometry
    def _page_geometry(self, size_name: str, orientation: str,
                       settings: PublishSettings) -> dict[str, Any]:
        size_name = settings.print.size or size_name
        orientation = settings.print.orientation or orientation
        ps = page_size(size_name)
        w_px, h_px = ps.pixels(orientation)                     # 96 dpi
        wmm, hmm = (ps.width_mm, ps.height_mm) if orientation != "landscape" else (ps.height_mm, ps.width_mm)
        m = settings.print.margins
        return {
            "size_name": size_name, "orientation": orientation,
            "width_px": float(w_px), "height_px": float(h_px),
            "width_pt": _mm_to_pt(wmm), "height_pt": _mm_to_pt(hmm),
            "margins_pt": (_mm_to_pt(m.top), _mm_to_pt(m.right),
                           _mm_to_pt(m.bottom), _mm_to_pt(m.left)),
            "bleed_pt": _mm_to_pt(settings.print.bleed_mm),
            "safe_pt": _mm_to_pt(settings.print.safe_area_mm),
            "crop_marks": settings.print.crop_marks,
        }

    def _new_page(self, index: int, role: str, geo: dict[str, Any]) -> RenderedPage:
        return RenderedPage(
            index=index, role=role, width_pt=geo["width_pt"], height_pt=geo["height_pt"],
            width_px=geo["width_px"], height_px=geo["height_px"],
            orientation=geo["orientation"], size_name=geo["size_name"],
            margins_pt=geo["margins_pt"], bleed_pt=geo["bleed_pt"], safe_pt=geo["safe_pt"],
            crop_marks=geo["crop_marks"])

    # -------------------------------------------------------------- cover
    def _cover_page(self, cover: Cover, settings: PublishSettings, branding: Any,
                    resolve: ImageResolver) -> RenderedPage:
        geo = self._page_geometry("A4", "portrait", settings)
        page = self._new_page(0, "cover", geo)
        cd = settings.cover
        page.background_color = cd.overlay_color
        bg_id = cd.background_image or cover.cover_image
        if bg_id:
            page.background_bytes = resolve(bg_id)
        page.elements.append(RenderedElement(kind="cover_overlay", fx=0, fy=0, fw=1, fh=1,
                             content={"color": cd.overlay_color, "opacity": cd.overlay_opacity}))
        if cd.show_logos:
            for i, logo in enumerate((cover.club_logo, cover.organization_logo)):
                data = _logo_bytes(logo, resolve, branding)
                if data:
                    page.elements.append(RenderedElement(kind="logo", fx=0.08 + i * 0.14,
                                         fy=0.10, fw=0.12, fh=0.07,
                                         content={"image_bytes": data}))
        page.elements.append(RenderedElement(kind="text", fx=0.08, fy=0.62, fw=0.84, fh=0.12,
                             align=cd.alignment, role="title", content={"text": cover.title}))
        if cover.subtitle:
            page.elements.append(RenderedElement(kind="text", fx=0.08, fy=0.75, fw=0.84, fh=0.06,
                                 align=cd.alignment, role="subtitle", content={"text": cover.subtitle}))
        meta_lines = [v for v in (
            _join(" · ", cover.competition, cover.season),
            _join(" · ", ("vs " + cover.opponent) if cover.opponent else "", cover.match_date),
            _join(" · ", cover.analyst, cover.generated_at, ("v" + cover.version) if cover.version else "")
        ) if v]
        if meta_lines:
            page.elements.append(RenderedElement(kind="text", fx=0.08, fy=0.84, fw=0.84, fh=0.10,
                                 align=cd.alignment, role="meta", content={"text": "\n".join(meta_lines)}))
        return page

    # -------------------------------------------------------------- studio page
    def _studio_page(self, page: Any, studio: ReportStudio, blocks: list[Any],
                     settings: PublishSettings, resolve: ImageResolver) -> RenderedPage:
        geo = self._page_geometry(page.size, page.orientation, settings)
        rp = self._new_page(0, "inside", geo)
        rp.background_color = page.background_color
        if page.background:
            rp.background_bytes = resolve(page.background)
        pw, ph = page.dimensions()
        for b in blocks:
            lay = studio.layouts[b.id]
            rp.elements.append(self._element_from_block(b, lay, pw, ph, resolve))
        return rp

    def _element_from_block(self, block: Any, lay: Any, pw: float, ph: float,
                            resolve: ImageResolver) -> RenderedElement:
        p = block.payload or {}
        geom = dict(fx=lay.x / pw, fy=lay.y / ph, fw=lay.width / pw, fh=lay.height / ph,
                    z=lay.z, rotation=lay.rotation, align=lay.align)
        if block.kind == "text":
            variant = p.get("variant", "")
            role = {"section_header": "h1", "notes": "body"}.get(variant, "body")
            return RenderedElement(kind=("divider" if variant == "divider" else
                                         "spacer" if variant == "spacer" else "text"),
                                   role=role, content={"text": p.get("text", ""), "variant": variant},
                                   **geom)
        if block.kind == "image":
            return RenderedElement(kind="image", opacity=float(p.get("opacity", 1) or 1),
                                   radius=float(p.get("radius", 0) or 0),
                                   content={"image_bytes": _inlined(p) or resolve(p.get("image_id", "")),
                                            "mime": p.get("mime", "image/png"),
                                            "caption": p.get("caption", ""), "fit": p.get("fit", "cover")},
                                   **geom)
        if block.kind == "chart":
            return RenderedElement(kind="chart",
                                   content={"image_bytes": _inlined(p), "mime": "image/png",
                                            "caption": p.get("caption", ""), "viz_id": p.get("viz_id", "")},
                                   **geom)
        return RenderedElement(kind="text", content={"text": p.get("text", "")}, **geom)

    # -------------------------------------------------------------- legacy flow
    def _flow_pages(self, sections: list[Section], settings: PublishSettings,
                    resolve: ImageResolver) -> list[RenderedPage]:
        geo = self._page_geometry("A4", "portrait", settings)
        content_h = geo["height_px"] - 140                       # rough content band (px)
        top, gap = 70.0, 16.0
        pages: list[RenderedPage] = []
        cur = self._new_page(0, "flow", geo)
        y = top

        def place(kind, height, content, role="body"):
            nonlocal y, cur
            if y + height > content_h and cur.elements:
                pages.append(cur)
                cur = self._new_page(0, "flow", geo)
                y = top
            cur.elements.append(RenderedElement(
                kind=kind, role=role, fx=0.08, fy=y / geo["height_px"], fw=0.84,
                fh=height / geo["height_px"], content=content))
            y += height + gap

        for s in sections:
            place("text", 40, {"text": "# " + s.title, "variant": "section_header"}, role="h1")
            if s.subtitle:
                place("text", 26, {"text": s.subtitle}, role="subtitle")
            if s.kpis:
                place("kpis", 90, {"kpis": [(k.label, k.value) for k in s.kpis]})
            for t in s.tables:
                place("table", 34 + max(1, len(t.rows)) * 26,
                      {"title": t.title, "columns": list(t.columns),
                       "rows": [list(r) for r in t.rows]})
            for ins in s.insights:
                place("insight", 40, {"text": ins.text, "kind": ins.kind})
            for ch in s.charts:
                png = base64.b64decode(ch.image_b64) if ch.image_b64 else None
                place("chart", 240, {"image_bytes": png, "viz_id": ch.viz_id,
                                     "caption": ch.title})
            if s.markdown:
                place("text", max(40, s.markdown.count("\n") * 20 + 30), {"text": s.markdown})
            if s.notes:
                place("text", 40, {"text": s.notes}, role="caption")
        pages.append(cur)
        return pages

    def _blank_page(self, settings: PublishSettings, resolve: ImageResolver) -> RenderedPage:
        return self._new_page(0, "inside", self._page_geometry("A4", "portrait", settings))

    # -------------------------------------------------------------- roles/numbers
    def _assign_roles(self, pages: list[RenderedPage], settings: PublishSettings) -> None:
        for i, p in enumerate(pages):
            p.index = i
        if settings.last_master is not None:
            for p in reversed(pages):
                if p.role != "cover":
                    p.role = "last"
                    break

    def _assign_numbers(self, pages: list[RenderedPage], settings: PublishSettings) -> None:
        pn = settings.page_numbering
        if not pn.enabled:
            return
        numbered = [p for p in pages if not (pn.hide_on_cover and p.role == "cover")]
        total = len(numbered)
        n = pn.start
        for p in numbered:
            disp = _roman(n, pn.style == "ROMAN") if pn.style in ("roman", "ROMAN") else str(n)
            p.number = (pn.prefix + pn.template.replace("{n}", disp)
                        .replace("{total}", str(total)))
            n += 1

    # -------------------------------------------------------------- furniture
    def _apply_furniture(self, page: RenderedPage, cover: Cover, settings: PublishSettings,
                         resolve: ImageResolver) -> None:
        if page.role == "cover":
            return                                    # cover carries its own design
        master = self._master_for(page.role, settings)
        page.confidential = settings.confidential_label or (
            "CONFIDENTIAL" if master.confidential else "")
        ctx = _token_ctx(cover, page, settings)
        if master.show_header and not master.header.is_empty():
            page.header = _resolve_zone(master.header, ctx)
        if master.show_footer and not master.footer.is_empty():
            page.footer = _resolve_zone(master.footer, ctx)
        wm = settings.watermark
        if wm.text or wm.image_id:
            page.watermark = ResolvedWatermark(
                text=_resolve_tokens(wm.text, ctx), image_bytes=resolve(wm.image_id) if wm.image_id else None,
                opacity=wm.opacity, rotation=wm.rotation, position=wm.position,
                font_size=wm.font_size, color=wm.color)
        if master.background_color and not page.background_color:
            page.background_color = master.background_color
        if master.background_image and page.background_bytes is None:
            page.background_bytes = resolve(master.background_image)

    def _master_for(self, role: str, settings: PublishSettings) -> MasterPage:
        if role == "last" and settings.last_master is not None:
            return settings.last_master
        return settings.inside_master


# ================================================================ helpers
def _inlined(payload: dict[str, Any]) -> bytes | None:
    b64 = payload.get("image_b64")
    if b64:
        try:
            return base64.b64decode(b64)
        except Exception:
            return None
    return None


def _has_cover(cover: Cover) -> bool:
    return bool(cover.title or cover.subtitle or cover.competition or cover.opponent
                or cover.club_logo or cover.cover_image)


def _logo_bytes(logo: str, resolve: ImageResolver, branding: Any) -> bytes | None:
    if not logo:
        return None
    data = resolve(logo)
    if data:
        return data
    try:                                              # asset-path logo (theme)
        from fap.theme import asset_path
        p = asset_path(logo)
        if p:
            with open(p, "rb") as fh:
                return fh.read()
    except Exception:
        pass
    return None


def _join(sep: str, *parts: str) -> str:
    return sep.join(p for p in parts if p)


def _roman(n: int, upper: bool = True) -> str:
    if n <= 0:
        return str(n)
    vals = [(1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"),
            (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]
    out = []
    for v, s in vals:
        while n >= v:
            out.append(s); n -= v
    r = "".join(out)
    return r.upper() if upper else r


def _token_ctx(cover: Cover, page: RenderedPage, settings: PublishSettings) -> dict[str, str]:
    return {
        "club": cover.club, "organization": cover.organization,
        "competition": cover.competition, "season": cover.season,
        "opponent": cover.opponent, "match": (("vs " + cover.opponent) if cover.opponent else ""),
        "analyst": cover.analyst, "author": cover.analyst,
        "date": cover.match_date or cover.generated_at, "version": cover.version,
        "title": cover.title, "subtitle": cover.subtitle,
        "n": page.number or "", "confidential": settings.confidential_label,
    }


def _resolve_tokens(template: str, ctx: dict[str, str]) -> str:
    out = template or ""
    for key, val in ctx.items():
        out = out.replace("{" + key + "}", str(val))
    return out.strip()


def _resolve_zone(zone: Zone, ctx: dict[str, str]) -> ResolvedZone:
    return ResolvedZone(left=_resolve_tokens(zone.left, ctx),
                        center=_resolve_tokens(zone.center, ctx),
                        right=_resolve_tokens(zone.right, ctx))
