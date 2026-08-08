"""The Report Studio editor (Phase 6D - Performance First).

A structured, section-based report editor - NOT a free canvas. It feels like
editing a professional scouting report (Opta / Wyscout / club scouting dept.),
not designing a magazine. The template owns typography/spacing/margins/cover/
branding; the user only edits CONTENT.

Performance is the priority:

* no custom-component iframe (that was the blank-canvas / "keeps loading" cause);
* charts are NEVER rendered live while editing - they render once on "Refresh"
  or at Export, and the result is cached on the block (``image_b64``) and reused;
* every edit is one ``update_studio`` autosave + one cheap rerun of native
  widgets; there is no heavy per-run HTML;
* blocks are an ordered, auto-flowed list - no positioning math.

It REUSES everything: the studio/block models, ``update_studio`` autosave, the
6C LayoutEngine + exporters (blocks are re-stacked so the editor order == the
exported order), ImageStorage and the visualization registry. Models, manager,
exporters and storage are unchanged.
"""
from __future__ import annotations

import hashlib
from typing import Any, Callable

import streamlit as st

from fap.reports import chart_block, image_block, qr_block, text_block
from fap.reports.editor_ops import create_page, delete_page
from fap.theme import DEFAULT_PALETTE
from fap.theme import components as C
from fap.theme import icon
from fap.ui.builtin.report_canvas import report_canvas
from fap.ui.studio import history, preview
from fap.ui.studio.covers import (
    COVER_PRESETS, COVER_TEMPLATES, palette_from_image, suggest_from_logo,
    suggest_from_palette, template_design,
)
from fap.ui.studio.sortable import sortable

# block "variants" layered on the text block kind (kept identical to 6C so the
# exporters/layout engine render them unchanged)
SECTION_HEADER, NOTES, DIVIDER, SPACER = "section_header", "notes", "divider", "spacer"

# professional report templates -> existing 6C publishing presets (no exporter change)
REPORT_TEMPLATES: dict[str, str] = {
    "Scouting Department": "scout",
    "Professional White": "professional",
    "Presentation": "presentation",
    "Executive Summary": "executive",
    "Coach": "coach",
    "Print": "print",
}
_HEIGHT = {SECTION_HEADER: 54, NOTES: 150, DIVIDER: 24, SPACER: 40}
_MARGIN = 48.0
_GAP = 18.0
_QR_SIDE = 200.0                        # default square side (px) for a QR-code block
_CASCADE = 28.0                         # px offset between successive free-page drops
# default drop size (px) per kind when a block is added onto a FREE page
_FREE_SIZE = {"chart": (360.0, 260.0), "image": (300.0, 220.0), "qr": (_QR_SIDE, _QR_SIDE),
              "text": (320.0, 120.0)}
_PREVIEW = "_studio_preview_html"       # cached export-preview HTML (session, per report)


# ================================================================ entry point
def render_studio(shell: Any, reports: Any, report_id: str) -> None:
    """The professional Report Studio: a document-first WYSIWYG workspace. The
    left rail holds the editing controls (sections, cover, design, export); the
    right stage shows the live, multi-page A4 document exactly as it will export.
    Everything routes through the existing engine — this is presentation only."""
    record = reports.get(report_id)
    if record is None:
        st.warning("That report no longer exists.")
        return
    studio = reports.studio(report_id)
    if studio is None:
        st.info("Report could not be opened.")
        return

    _toolbar(shell, reports, report_id, record)
    rail, stage = st.columns([37, 63], gap="medium")
    with rail:
        tabs = st.tabs(["Sections", "Cover", "Design", "Export"])
        with tabs[0]:
            _sections_panel(shell, reports, report_id, studio)
        with tabs[1]:
            _cover_editor(shell, reports, report_id, studio)
        with tabs[2]:
            _template_editor(shell, reports, report_id, studio)
        with tabs[3]:
            _export(shell, reports, report_id)
    with stage:
        _stage(shell, reports, report_id, studio)


# ================================================================ toolbar
def _toolbar(shell, reports, report_id, record) -> None:
    st.markdown(
        f'<div class="fap-studio-toolbar">'
        f'<span class="fap-title-chip" style="width:36px;height:36px">{icon("reports", 18)}</span>'
        f'<div><div class="rt-title">{_esc(record.title)}</div>'
        f'<div class="rt-meta">{_esc(record.template_id or "report")} · updated '
        f'{_esc(record.updated_at)} · v{record.version}</div></div>'
        f'<span class="spacer"></span></div>', unsafe_allow_html=True)
    c = st.columns([1, 1, 1, 5])
    if c[0].button("Undo", key="rt_undo", disabled=not history.can_undo(report_id),
                   use_container_width=True):
        _undo(shell, reports, report_id)
    if c[1].button("Redo", key="rt_redo", disabled=not history.can_redo(report_id),
                   use_container_width=True):
        _redo(shell, reports, report_id)
    if c[2].button("Save version", key="rt_savever", use_container_width=True):
        reports.save_version(shell.user, report_id, note="editor snapshot")
        st.toast("Version saved")


# ================================================================ sections panel (rail)
def _kind_label(block) -> str:
    variant = (block.payload or {}).get("variant", "")
    if not variant and block.kind == "qr":
        return "QR Code"
    return {"section_header": "Section", "notes": "Notes", "divider": "Divider",
            "spacer": "Spacer"}.get(variant, block.kind.title())


def _sections_panel(shell, reports, report_id, studio) -> None:
    blocks = studio.document.blocks
    st.markdown('<div class="fap-rail-head">Order</div>', unsafe_allow_html=True)
    if not blocks:
        C.render_empty_state("No sections yet", "Add your first section below to start "
                             "building the report.", icon_name="reports")
    else:
        _reorder(shell, reports, report_id, studio)
    st.markdown('<div class="fap-rail-head">Edit</div>', unsafe_allow_html=True)
    for i, b in enumerate(blocks):
        _block_card(shell, reports, report_id, b, i, len(blocks))
    _add_content(shell, reports, report_id)


def _reorder(shell, reports, report_id, studio) -> None:
    """Drag-and-drop section ordering. The component only reports the dropped
    order; ``reorder_blocks`` (pure op) applies it. Falls back silently to the
    per-section Up/Down controls if the component cannot initialise."""
    blocks = studio.document.blocks
    ids = [b.id for b in blocks]
    items = [{"id": b.id, "title": (b.title or _kind_label(b)), "badge": _kind_label(b),
              "kind": b.kind, "hidden": bool(b.hidden)} for b in blocks]
    nonce = hashlib.sha1(("|".join(ids)).encode("utf-8")).hexdigest()[:10]
    colors = {"accent": DEFAULT_PALETTE.primary}
    result = sortable(items, key=f"sp_sort_{report_id}", colors=colors, nonce=nonce)
    if result is None:
        st.caption("Reorder with the Up / Down controls under each section below.")
        return
    if result.get("nonce") == nonce:
        new = result.get("order") or []
        if new and new != ids:
            _apply(shell, reports, report_id, lambda s, o=list(new): _reorder_apply(s, o))
    st.caption("Drag to reorder — changes autosave and refresh the preview.")


def _reorder_apply(studio, ordered_ids: list[str]) -> None:
    from fap.reports.blocks import reorder_blocks
    reorder_blocks(studio.document, ordered_ids)
    _reflow(studio)


# ================================================================ stage (preview / canvas)
_ZOOMS = [0.5, 0.65, 0.75, 0.85, 1.0, 1.25]


def _stage(shell, reports, report_id, studio) -> None:
    """The right-hand stage. A flow page (the default, and every legacy report) shows the
    unchanged live A4 preview; a free-form page shows the interactive drag canvas instead.
    The page bar is the only new chrome for flow reports — it never alters flow rendering."""
    _pages_bar(shell, reports, report_id, studio)
    active = studio.page(studio.editor.active_page or "")
    if active is not None and getattr(active, "kind", "flow") == "free":
        _free_canvas(shell, reports, report_id, studio, active)
    else:
        _preview_pane(shell, reports, report_id, studio)


def _pages_bar(shell, reports, report_id, studio) -> None:
    """Switch between pages and add a free-form page. For a standard single-flow-page report
    this is just an unobtrusive '+ Free-form page' button above the preview."""
    pages = studio.pages
    active_id = studio.editor.active_page or (pages[0].id if pages else None)
    active = studio.page(active_id or "")
    show_delete = active is not None and getattr(active, "kind", "flow") == "free" and len(pages) > 1
    cols = st.columns(len(pages) + (2 if show_delete else 1))
    for i, p in enumerate(pages):
        free = getattr(p, "kind", "flow") == "free"
        label = (p.title or f"Page {i + 1}") + (" ◆" if free else "")
        if cols[i].button(label, key=f"pgsel_{report_id}_{p.id}", use_container_width=True,
                          type="primary" if p.id == active_id else "secondary"):
            _apply(shell, reports, report_id, lambda s, pid=p.id: _set_active_page(s, pid))
    if cols[len(pages)].button("＋ Free-form page", key=f"pgadd_{report_id}",
                               use_container_width=True):
        _apply(shell, reports, report_id,
               lambda s: create_page(s, title="Free-form", kind="free"))
    if show_delete:
        if cols[len(pages) + 1].button("Delete page", key=f"pgdel_{report_id}",
                                       use_container_width=True):
            _apply(shell, reports, report_id, lambda s, pid=active_id: delete_page(s, pid))


def _set_active_page(studio, page_id: str) -> None:
    studio.editor.active_page = page_id


# ---------------------------------------------------------------- free-form canvas
def _free_canvas(shell, reports, report_id, studio, page) -> None:
    """Render a free-form page as an interactive drag surface. Blocks are drawn with the
    EXISTING exporter renderer (reused, not reinvented); the JS only positions and drags
    them and reports ``update_layout`` intent, which Python validates + applies. Degrades to
    the live preview note if the component can't mount."""
    pw, ph = page.dimensions()
    blocks = _canvas_block_data(reports, studio, page)

    bar = st.columns([3, 2, 2], vertical_alignment="center")
    bar[0].markdown(
        f'<div style="font-size:.82rem;color:var(--fap-text-muted)">'
        f'Free-form canvas · <b style="color:var(--fap-text)">{len(blocks)} block'
        f'{"" if len(blocks) == 1 else "s"}</b> · drag to position</div>', unsafe_allow_html=True)
    zoom_key = f"_rc_zoom_{report_id}"
    if zoom_key not in st.session_state:
        st.session_state[zoom_key] = 0.75
    zoom = bar[2].selectbox("Zoom", _ZOOMS, index=_ZOOMS.index(st.session_state[zoom_key]),
                            format_func=lambda z: f"{int(z * 100)}%", key=zoom_key,
                            label_visibility="collapsed")
    snap = float(studio.editor.grid_size) if studio.editor.snap_to_grid else 0.0

    if not blocks:
        C.render_empty_state("Empty canvas", "Add blocks from the Sections tab — they drop "
                             "onto this page where you can drag them anywhere.", icon_name="reports")
        return

    sig = "|".join(f"{b['id']}:{b['x']:.1f},{b['y']:.1f}:{len(b['html'])}" for b in blocks)
    nonce = hashlib.sha1(f"{page.id}|{zoom}|{snap}|{sig}".encode("utf-8")).hexdigest()[:12]
    rendered, intent = report_canvas(
        page={"id": page.id, "w": float(pw), "h": float(ph),
              "background": page.background_color or "#ffffff"},
        blocks=blocks, snap=snap, zoom=float(zoom), editable=True, nonce=nonce,
        key=f"rc_{report_id}")
    if not rendered:
        st.info("The drag canvas couldn't load in this browser. Saved positions still render "
                "in the preview — switch to a flow page to see the full document.")
        return
    if intent is not None:
        ts = intent.get("ts")
        if ts != st.session_state.get(f"_rc_ts_{report_id}"):
            st.session_state[f"_rc_ts_{report_id}"] = ts       # dedup Streamlit re-delivery
            cmds = intent.get("commands") or []
            if cmds:
                _apply(shell, reports, report_id, lambda s, c=list(cmds): _apply_layout_cmds(s, c))
    st.caption("Phase 1: move only. Resize and layering come later. Positions autosave.")


def _canvas_block_data(reports, studio, page) -> list[dict]:
    """Per-block data for the canvas: position/size + the block's HTML, produced by the SAME
    exporter element renderer the live preview uses (so the canvas shows the real content)."""
    from fap.reports.exporters import _element_inner
    from fap.reports.layout import LayoutEngine
    eng = LayoutEngine()
    pw, ph = page.dimensions()

    def resolve(iid):
        return reports.image_bytes(iid) if iid else None

    out: list[dict] = []
    for b in studio.blocks_on(page.id):
        if b.hidden:
            continue
        lay = studio.layouts[b.id]
        render_block = _qr_render_copy(b) if b.kind == "qr" else b
        try:
            el = eng._element_from_block(render_block, lay, pw, ph, resolve)
            html = _element_inner(el)
        except Exception:
            html = (f"<div style='padding:8px;font:600 12px Inter,Arial;color:#5b6472'>"
                    f"{_esc(b.title or _kind_label(b))}</div>")
        out.append({"id": b.id, "x": float(lay.x), "y": float(lay.y),
                    "w": float(lay.width), "h": float(lay.height),
                    "locked": bool(lay.locked), "html": html})
    return out


def _qr_render_copy(block):
    """A shallow copy of a QR block with a freshly generated ``image_b64`` for canvas
    preview only — so we never persist canvas-side materialization onto the saved block."""
    payload = block.payload or {}
    if payload.get("image_b64"):
        return block
    from fap.reports.blocks import qr_png
    png = qr_png(payload.get("url", ""))
    if not png:
        return block
    import base64
    import copy
    nb = copy.copy(block)
    nb.payload = {**payload, "image_b64": base64.b64encode(png).decode("ascii")}
    return nb


def _apply_layout_cmds(studio, cmds: list[dict]) -> None:
    """Apply validated ``update_layout`` commands to block layouts (snap to the editor grid,
    clamp inside the page). Locked blocks are ignored — a second guard behind the JS one."""
    for c in cmds:
        if c.get("op") != "update_layout":
            continue
        lay = studio.layouts.get(c.get("id"))
        if lay is None or lay.locked:
            continue
        x, y = c.get("x"), c.get("y")
        if x is None or y is None:
            continue
        x, y = float(x), float(y)
        g = studio.editor.grid_size
        if studio.editor.snap_to_grid and g > 0:
            x, y = round(x / g) * g, round(y / g) * g
        page = studio.page(lay.page_id)
        if page is not None:
            pw, ph = page.dimensions()
            x = _clampf(x, 0.0, max(0.0, pw - lay.width))
            y = _clampf(y, 0.0, max(0.0, ph - lay.height))
        lay.x, lay.y = x, y


def _preview_pane(shell, reports, report_id, studio) -> None:
    html, pages = preview.get_preview_html(shell, reports, report_id)
    zoom_key = f"_sp_zoom_{report_id}"
    if zoom_key not in st.session_state:
        st.session_state[zoom_key] = 0.85

    bar = st.columns([3, 2, 2], vertical_alignment="center")
    bar[0].markdown(
        f'<div style="font-size:.82rem;color:var(--fap-text-muted)">'
        f'Live A4 preview · <b style="color:var(--fap-text)">{pages or "—"} page'
        f'{"" if pages == 1 else "s"}</b></div>', unsafe_allow_html=True)
    zoom = bar[2].selectbox("Zoom", _ZOOMS, index=_ZOOMS.index(st.session_state[zoom_key]),
                            format_func=lambda z: f"{int(z * 100)}%", key=zoom_key,
                            label_visibility="collapsed")

    if html.startswith("__ERROR__"):
        C.render_alert(f"The preview could not render: {html[9:]}", "danger",
                       title="Preview error")
        return
    if not pages:
        C.render_empty_state("Nothing to preview yet", "Add a cover or a section — the live "
                             "document appears here exactly as it will export.", icon_name="reports")
        return

    _outline_panel(studio)
    st.markdown('<div class="fap-stage-bar"><span class="pg">Document</span>'
                '<span>A4 · portrait</span><span style="flex:1"></span>'
                '<span>WYSIWYG — same engine as the PDF export</span></div>',
                unsafe_allow_html=True)
    st.markdown('<div class="fap-stage-wrap">', unsafe_allow_html=True)
    st.components.v1.html(preview.decorate(html, zoom=zoom), height=1180, scrolling=True)
    st.markdown('</div>', unsafe_allow_html=True)


def _outline_panel(studio) -> None:
    items = preview.outline(studio)
    if not items:
        return
    with st.expander(f"Table of contents · {len(items)} sections", expanded=False):
        rows = []
        for it in items:
            cls = "oi h1" if it["variant"] == "section_header" else "oi"
            if it["hidden"]:
                cls += " muted"
            rows.append(f'<div class="{cls}"><span class="n">{it["index"] + 1}</span>'
                        f'<span>{_esc(it["title"])}</span></div>')
        st.markdown(f'<div class="fap-outline">{"".join(rows)}</div>', unsafe_allow_html=True)


# ================================================================ cover designer
def _cover_editor(shell, reports, report_id, studio) -> None:
    cover = studio.document.cover
    cd = _cover_design(studio)
    with st.expander("Cover designer", expanded=True):
        colf, colp = st.columns([2, 1])
        with colf:
            # -- template gallery + report-type presets + branding suggestions --
            st.markdown("**Cover template** — design only, never content")
            gallery = list(COVER_TEMPLATES)
            cur = next((n for n in gallery if COVER_TEMPLATES[n].get("template") == cd.get("template")),
                       gallery[0])
            g1, g2 = st.columns([3, 1])
            tpl = g1.selectbox("Gallery", gallery, index=gallery.index(cur), key="cv_tpl",
                               label_visibility="collapsed")
            if g2.button("Apply", key="cv_tpl_apply", use_container_width=True):
                _apply_cover_design(shell, reports, report_id, template_design(tpl))
            p1, p2 = st.columns([3, 1])
            preset = p1.selectbox("Report-type preset", list(COVER_PRESETS), key="cv_preset",
                                  label_visibility="collapsed")
            if p2.button("Use", key="cv_preset_apply", use_container_width=True):
                _apply_cover_design(shell, reports, report_id, template_design(COVER_PRESETS[preset]))

            suggestions = _branding_suggestions(shell)
            # palettes extracted from the club logo, if one is set on the cover
            logo_suggestions = {}
            if cover.club_logo:
                data = reports.image_bytes(cover.club_logo)
                if data:
                    logo_suggestions = suggest_from_logo(data)
                    pal = palette_from_image(data)
                    if pal:
                        swatches = "".join(
                            f"<span style='display:inline-block;width:16px;height:16px;background:{c};"
                            f"border-radius:3px;margin-right:4px;vertical-align:middle'></span>" for c in pal)
                        st.markdown(f"<small>Club logo palette: {swatches}</small>",
                                    unsafe_allow_html=True)
            suggestions = {**suggestions, **logo_suggestions}
            if suggestions:
                s1, s2 = st.columns([3, 1])
                sug = s1.selectbox("Club branding suggestions (logo + palette)", list(suggestions),
                                   key="cv_sug", label_visibility="collapsed")
                if s2.button("Apply", key="cv_sug_apply", use_container_width=True):
                    _apply_cover_design(shell, reports, report_id, suggestions[sug])

            # -- content (title/subtitle + images) --
            st.markdown("**Content**")
            title = st.text_input("Title", value=cover.title, key="cv_title")
            subtitle = st.text_input("Subtitle", value=cover.subtitle, key="cv_sub")

            # -- cover details (every field that appears on the rendered cover) --
            dc = st.columns(2)
            club = dc[0].text_input("Club", value=cover.club, key="cv_club")
            organization = dc[1].text_input("Organization", value=cover.organization, key="cv_org")
            player = dc[0].text_input("Player (scouting report)", value=cover.player, key="cv_player",
                                      help="Set this for a player-focused scouting cover; leave "
                                           "empty for an opponent/match report.")
            opponent = dc[1].text_input("Opponent", value=cover.opponent, key="cv_opp")
            competition = dc[0].text_input("Competition", value=cover.competition, key="cv_comp")
            season = dc[1].text_input("Season", value=cover.season, key="cv_season")
            match_date = dc[0].text_input("Match date", value=cover.match_date, key="cv_mdate")
            analyst = dc[1].text_input("Analyst", value=cover.analyst, key="cv_analyst")
            version = dc[0].text_input("Version", value=cover.version, key="cv_version")

            ic = st.columns(2)
            photo = ic[0].file_uploader("Player / background photo",
                                        type=["png", "jpg", "jpeg", "webp"], key="cv_photo")
            badge = ic[1].file_uploader("Club badge", type=["png", "jpg", "jpeg", "webp", "svg"],
                                        key="cv_badge")
            fed = st.file_uploader("Competition / federation logo",
                                   type=["png", "jpg", "jpeg", "webp", "svg"], key="cv_fed")

            # -- customize the design --
            with st.expander("Customize design"):
                d1, d2 = st.columns(2)
                bg = d1.color_picker("Background", cd.get("background_color") or "#ffffff", key="cd_bg")
                accent = d2.color_picker("Accent", cd.get("accent_color") or "#E07B2B", key="cd_ac")
                gradient = d1.checkbox("Gradient", value=cd.get("gradient", False), key="cd_grad")
                gcolor = d2.color_picker("Gradient 2", cd.get("gradient_color") or "#0b1f3a", key="cd_gc")
                overlay = d1.slider("Overlay", 0.0, 1.0, float(cd.get("overlay_opacity", 0.0)), 0.05,
                                    key="cd_ov")
                talign = d2.selectbox("Title align", ["left", "center", "right"],
                                      index=_ai(cd.get("title_align") or cd.get("alignment", "left")),
                                      key="cd_ta")
                salign = d1.selectbox("Subtitle align", ["left", "center", "right"],
                                      index=_ai(cd.get("subtitle_align") or cd.get("alignment", "left")),
                                      key="cd_sa")
                _logo_positions = ["top", "center", "corner", "spread"]
                logo_pos = d2.selectbox("Logo position", _logo_positions,
                                        index=_logo_positions.index(cd.get("logo_position", "top"))
                                        if cd.get("logo_position", "top") in _logo_positions else 0,
                                        key="cd_lp")
                show_logos = d1.checkbox("Show logos", value=cd.get("show_logos", True), key="cd_sl")
                divider = d2.checkbox("Accent divider", value=cd.get("divider", True), key="cd_dv")

            if st.button("Apply cover", type="primary", key="cv_apply"):
                photo_id = cover.cover_image
                badge_id = cover.club_logo
                fed_id = cover.organization_logo
                if photo is not None:
                    photo_id = _upload(shell, reports, report_id, photo)
                if badge is not None:
                    badge_id = _upload(shell, reports, report_id, badge)
                if fed is not None:
                    fed_id = _upload(shell, reports, report_id, fed)
                design = {**cd, "background_color": bg, "accent_color": accent, "gradient": gradient,
                          "gradient_color": gcolor, "overlay_opacity": overlay, "title_align": talign,
                          "subtitle_align": salign, "logo_position": logo_pos, "show_logos": show_logos,
                          "divider": divider}

                def m(s, t=title, sub=subtitle, pid=photo_id, bid=badge_id, fid=fed_id, d=design,
                      club=club, org=organization, player=player, opp=opponent, comp=competition,
                      season=season, mdate=match_date, analyst=analyst, version=version):
                    s.document.cover.title = t
                    s.document.cover.subtitle = sub
                    s.document.cover.club = club
                    s.document.cover.organization = org
                    s.document.cover.player = player
                    s.document.cover.opponent = opp
                    s.document.cover.competition = comp
                    s.document.cover.season = season
                    s.document.cover.match_date = mdate
                    s.document.cover.analyst = analyst
                    s.document.cover.version = version
                    s.document.cover.cover_image = pid
                    s.document.cover.club_logo = bid
                    s.document.cover.organization_logo = fid
                    _set_cover_design(s, d)
                _apply(shell, reports, report_id, m, push=False)

            # -- save / reuse custom cover templates (reuses WorkspaceManager presets) --
            _custom_cover_templates(shell, reports, report_id, cd)
        with colp:
            st.caption("Preview")
            st.markdown(_cover_preview_html(reports, cover, cd), unsafe_allow_html=True)


# ================================================================ add content picker
def _add_content(shell, reports, report_id) -> None:
    """The single Add Content button -> a categorized picker. Nothing is inserted
    unless the user explicitly chooses it (empty-report philosophy)."""
    with st.expander("Add section", expanded=False):
        cats = ["Text", "Charts", "Data", "Media", "Analysis", "Custom"]
        tabs = st.tabs(cats)
        with tabs[0]:
            _insert_grid(shell, reports, report_id, _text_items())
        with tabs[1]:
            _chart_picker_grid(shell, reports, report_id)
        with tabs[2]:
            _insert_grid(shell, reports, report_id, _data_items())
        with tabs[3]:
            _insert_grid(shell, reports, report_id, _media_items())
            st.markdown("**QR Code** — links to a player's video")
            _qr_picker(shell, reports, report_id)
        with tabs[4]:
            _insert_grid(shell, reports, report_id, _analysis_items())
        with tabs[5]:
            _insert_grid(shell, reports, report_id, {"Empty block": lambda: text_block("", title="Block")})


def _insert_grid(shell, reports, report_id, items: dict) -> None:
    cols = st.columns(3)
    for i, (label, factory) in enumerate(items.items()):
        if cols[i % 3].button(label, key=f"ins_{label}", use_container_width=True):
            _apply(shell, reports, report_id, lambda s, f=factory: _add_block(s, f()))


def _section(label: str, body: str = "") -> Callable:
    """A titled section block: the label is a heading in the exported body, with an
    editable placeholder underneath. Renders through the existing text path."""
    return lambda: text_block(f"## {label}\n{body}", title=label)


def _text_items() -> dict:
    return {
        "Heading": lambda: _variant(text_block("Heading", title="Heading"), SECTION_HEADER),
        "Paragraph": lambda: text_block("Write here…", title="Paragraph"),
        "Bullet List": lambda: text_block("- point one\n- point two\n- point three", title="List"),
        "Numbered List": lambda: text_block("1. first\n2. second\n3. third", title="List"),
        "Quote": lambda: _variant(text_block("“Quote…”", title="Quote"), NOTES),
        "Divider": lambda: _variant(text_block("", title="Divider"), DIVIDER),
        "Table": lambda: text_block("| Metric | Value |\n| --- | --- |\n| xG | 1.8 |", title="Table"),
    }


def _data_items() -> dict:
    return {
        "KPI Card": _section("KPIs", "| Metric | Value |\n| --- | --- |\n| xG | 1.8 |\n| Passes | 92% |"),
        "Statistics Table": lambda: text_block("| Stat | Value |\n| --- | --- |\n| Goals | 0 |",
                                               title="Statistics"),
        "Player Card": _section("Player", "Name · Position · Club · Age"),
        "Match Card": _section("Match", "Home vs Away · Competition · Date"),
        "Team Card": _section("Team", "Formation · Style · Key players"),
        "Comparison": _section("Comparison", "| Player | A | B |\n| --- | --- | --- |\n| xG | | |"),
    }


def _media_items() -> dict:
    return {
        "Image": lambda: image_block("", title="Image"),
        "Video": lambda: text_block("[Video](paste YouTube / Hudl / Wyscout link)", title="Video"),
        "Attachment": lambda: text_block("Attachment: describe the file / paste a link", title="Attachment"),
    }


def _analysis_items() -> dict:
    return {
        "Recommendation": _section("Recommendation", "- "),
        "Observation": _section("Observation", "- "),
        "Scout Opinion": _section("Scout Opinion", "- "),
        "Strengths": _section("Strengths", "- "),
        "Weaknesses": _section("Weaknesses", "- "),
        "Tactical Notes": _section("Tactical Notes", "- "),
    }


def _chart_picker_grid(shell, reports, report_id) -> None:
    from fap.visuals.base import load_builtin_visuals, visual_registry
    load_builtin_visuals()
    infos = visual_registry.infos()
    cats = sorted({i.category or "Other" for i in infos})
    cat = st.selectbox("Chart category", cats, key="add_chart_cat")
    options = [i for i in infos if (i.category or "Other") == cat]
    labels = {i.id: i.name for i in options}
    viz_id = st.selectbox("Chart", list(labels), format_func=lambda i: labels[i], key="add_chart_viz")
    if st.button("Insert chart (renders at Export/Refresh)", key="add_chart_ins"):
        name = labels.get(viz_id, "Chart")
        _apply(shell, reports, report_id,
               lambda s, v=viz_id, n=name: _add_block(s, chart_block(v, {}, title=n)))


def _scouting_service(shell):
    """The ScoutingService if the platform exposes one, else None (graceful)."""
    try:
        return getattr(shell.platform, "scouting", None)
    except Exception:
        return None


def _player_external_videos(svc, shell, player_id: str) -> list:
    """A player's external (link-based) videos - the QR's URL source."""
    try:
        return [v for v in svc.list_videos(player_id) if getattr(v, "kind", "") == "external"]
    except Exception:
        return []


def _qr_picker(shell, reports, report_id) -> None:
    """Add a QR-code block. Preferred path: pick a player, then one of their linked
    external videos (auto-fills the URL, and records player_id/video_id for re-editing).
    Fallback path (no scouting service, no linked video, or ad-hoc link): paste any URL.
    Either way this inserts a normal block through the same flow as image/chart."""
    svc = _scouting_service(shell)
    url, player_id, video_id = "", "", ""

    if svc is not None:
        try:
            players = svc.search(shell.user, query="")
        except Exception:
            players = []
        if players:
            plabels = {p.id: (f"{p.name} · {p.club}" if getattr(p, "club", "") else p.name)
                       for p in players}
            pid = st.selectbox("Player", list(plabels), format_func=lambda i: plabels[i],
                               key="qr_player")
            vids = _player_external_videos(svc, shell, pid)
            if vids:
                vlabels = {v.id: (v.title or v.url or v.provider or v.id) for v in vids}
                vid = st.selectbox("Linked video", list(vlabels),
                                   format_func=lambda i: vlabels[i], key="qr_video")
                chosen = next((v for v in vids if v.id == vid), None)
                if chosen is not None:
                    url, player_id, video_id = chosen.url, pid, chosen.id
                st.caption(f"QR will encode: {url or '(this video has no URL)'}")
            else:
                st.caption("This player has no linked external video — paste a URL below.")
        else:
            st.caption("No players found — paste a URL below.")
    else:
        st.caption("Scouting not available — paste a URL below.")

    # manual fallback (always available): a pasted URL overrides, and clears the
    # player/video reference so we don't store a mismatched source.
    manual = st.text_input("…or paste a video / any URL", value="", key="qr_manual_url",
                           placeholder="https://…")
    if manual.strip():
        url, player_id, video_id = manual.strip(), "", ""

    caption = st.text_input("Caption (optional)", value="", key="qr_caption")
    if st.button("Insert QR code", key="qr_insert", use_container_width=True):
        if not url:
            st.warning("Pick a player video or paste a URL first.")
        else:
            _apply(shell, reports, report_id,
                   lambda s, u=url, pi=player_id, vi=video_id, cap=caption:
                       _add_block(s, qr_block(u, player_id=pi, video_id=vi, caption=cap, title="QR Code")))


def _block_card(shell, reports, report_id, block, index, total) -> None:
    variant = (block.payload or {}).get("variant", "")
    kind_label = _kind_label(block)
    header = f"{'(hidden) ' if block.hidden else ''}{block.title or kind_label} · {kind_label}"
    with st.expander(header, expanded=False):
        # row of structural controls (Up/Down double as the drag-and-drop fallback)
        c = st.columns(5)
        if c[0].button("Up", key=f"up_{block.id}", disabled=index == 0, use_container_width=True):
            _apply(shell, reports, report_id, lambda s, b=block.id: _move(s, b, -1))
        if c[1].button("Down", key=f"dn_{block.id}", disabled=index == total - 1,
                       use_container_width=True):
            _apply(shell, reports, report_id, lambda s, b=block.id: _move(s, b, +1))
        if c[2].button("Duplicate", key=f"dup_{block.id}", use_container_width=True):
            _apply(shell, reports, report_id, lambda s, b=block.id: _duplicate(s, b))
        if c[3].button("Show" if block.hidden else "Hide", key=f"hide_{block.id}",
                       use_container_width=True):
            _apply(shell, reports, report_id, lambda s, b=block.id, h=not block.hidden: _hide(s, b, h))
        if c[4].button("Delete", key=f"del_{block.id}", use_container_width=True):
            _apply(shell, reports, report_id, lambda s, b=block.id: _delete(s, b))

        if block.kind == "text":
            _edit_text(shell, reports, report_id, block, variant)
        elif block.kind == "chart":
            _edit_chart(shell, reports, report_id, block)
        elif block.kind == "image":
            _edit_image(shell, reports, report_id, block)
        elif block.kind == "qr":
            _edit_qr(shell, reports, report_id, block)


def _edit_text(shell, reports, report_id, block, variant) -> None:
    if variant in (DIVIDER, SPACER):
        st.caption(f"{variant.title()} — no content.")
        return
    title = st.text_input("Heading", value=block.title, key=f"t_{block.id}")
    body = st.text_area("Text", value=block.payload.get("text", ""), height=160, key=f"x_{block.id}",
                        help="Plain text. Use short lines; the template styles it professionally.")
    if st.button("Apply", key=f"ap_{block.id}"):
        _apply(shell, reports, report_id,
               lambda s, b=block.id, t=title, x=body: _set_text(s, b, t, x))


def _edit_chart(shell, reports, report_id, block) -> None:
    from fap.visuals.base import load_builtin_visuals, visual_registry
    from fap.ui.components.controls import render_controls
    load_builtin_visuals()
    infos = visual_registry.infos()
    ids = [i.id for i in infos]
    labels = {i.id: i.name for i in infos}
    cur = block.payload.get("viz_id", "")
    idx = ids.index(cur) if cur in ids else 0
    viz_id = st.selectbox("Visualization", ids, index=idx, format_func=lambda i: labels.get(i, i),
                          key=f"cv_{block.id}")
    viz = visual_registry.create(viz_id)
    controls = render_controls(getattr(viz, "controls", ()) or (),
                               saved=block.payload.get("controls", {}), key_prefix=f"cc_{block.id}")
    b64 = block.payload.get("image_b64", "")
    if b64:
        st.image(f"data:image/png;base64,{b64}", caption="cached preview", width=280)
    else:
        st.caption("No preview yet — charts render at Export, or click Refresh.")
    cols = st.columns(3)
    if cols[0].button("Apply options", key=f"ca_{block.id}"):
        _apply(shell, reports, report_id,
               lambda s, b=block.id, v=viz_id, c=controls: _set_chart(s, b, v, c))
    if cols[1].button("Refresh chart", key=f"cr_{block.id}"):
        png = _render_chart_once(reports, report_id, viz_id, controls)
        _apply(shell, reports, report_id,
               lambda s, b=block.id, v=viz_id, c=controls, p=png: _set_chart(s, b, v, c, p))


def _edit_image(shell, reports, report_id, block) -> None:
    image_id = block.payload.get("image_id", "")
    if image_id:
        data = reports.image_bytes(image_id)
        if data:
            st.image(data, width=280)
    up = st.file_uploader("Replace / insert image", type=["png", "jpg", "jpeg", "webp", "svg"],
                          key=f"iu_{block.id}")
    caption = st.text_input("Caption", value=block.payload.get("caption", ""), key=f"ic_{block.id}")
    fit = st.selectbox("Fit", ["cover", "contain", "fill"],
                       index=["cover", "contain", "fill"].index(block.payload.get("fit", "cover")),
                       key=f"if_{block.id}")
    if st.button("Apply", key=f"ia_{block.id}"):
        new_id = image_id
        if up is not None:
            img = reports.upload_image(shell.user, up.getvalue(), up.name, up.type or "image/png",
                                       workspace_id=_ws(reports, report_id))
            new_id = img.id
        _apply(shell, reports, report_id,
               lambda s, b=block.id, i=new_id, c=caption, f=fit: _set_image(s, b, i, c, f))


def _edit_qr(shell, reports, report_id, block) -> None:
    from fap.reports import qr_png
    p = block.payload or {}
    url = p.get("url", "")
    # cached preview if already materialized, else generate a live preview from the url
    b64 = p.get("image_b64", "")
    png = None
    if not b64 and url:
        png = qr_png(url)
    if b64:
        st.image(f"data:image/png;base64,{b64}", caption="QR preview", width=180)
    elif png:
        st.image(png, caption="QR preview", width=180)
    else:
        st.caption("Set a URL below — the QR renders at Export/Refresh.")
    # show which player/video this QR is linked to (reference only)
    if p.get("player_id") or p.get("video_id"):
        st.caption(f"Linked to player `{p.get('player_id', '')}` · video `{p.get('video_id', '')}`")
    new_url = st.text_input("URL", value=url, key=f"qru_{block.id}")
    caption = st.text_input("Caption", value=p.get("caption", ""), key=f"qrc_{block.id}")
    if st.button("Apply", key=f"qra_{block.id}"):
        # a manually edited URL detaches the player/video reference (it no longer matches)
        detach = new_url.strip() != url
        _apply(shell, reports, report_id,
               lambda s, b=block.id, u=new_url.strip(), c=caption, d=detach: _set_qr(s, b, u, c, d))


# ================================================================ template / theme
def _template_editor(shell, reports, report_id, studio) -> None:
    st.caption("Choose a professional template. It restyles the whole report instantly — "
               "typography, spacing, margins, cover and branding. You edit content, not design.")
    pub = _publish(studio)
    current = pub.get("preset", "professional")
    names = list(REPORT_TEMPLATES)
    cur_name = next((n for n, slug in REPORT_TEMPLATES.items() if slug == current), names[0])
    choice = st.radio("Template", names, index=names.index(cur_name), key="tpl_choice")
    if st.button("Apply template", type="primary", key="tpl_apply"):
        from fap.reports import publish_preset
        slug = REPORT_TEMPLATES[choice]

        def m(s, sl=slug):
            settings = publish_preset(sl)
            # keep the user's cover alignment/photo choices
            existing = _publish(s)
            data = settings.to_dict()
            if existing.get("cover"):
                data["cover"]["alignment"] = existing["cover"].get("alignment",
                                                                    data["cover"]["alignment"])
            _set_publish(s, data)
        _apply(shell, reports, report_id, m, push=False)
        st.session_state.pop(_PREVIEW, None)
        st.toast(f"Applied {choice}")


# ================================================================ export & share
def _export(shell, reports, report_id) -> None:
    st.markdown('<div class="fap-rail-head">Download</div>', unsafe_allow_html=True)
    C.render_alert("The live preview on the right is the same layout engine used for export — "
                   "what you see is what the PDF will be.", "info")
    formats = reports.available_formats()
    mimes = {"html": "text/html", "markdown": "text/markdown", "pdf": "application/pdf"}
    labels = {"html": "HTML", "markdown": "Markdown", "pdf": "PDF",
              "docx": "Word", "pptx": "PowerPoint"}
    for fmt in formats:
        cc = st.columns([2, 3], vertical_alignment="center")
        if cc[0].button(labels.get(fmt, fmt.upper()), key=f"exp_{fmt}", use_container_width=True,
                        type="primary" if fmt == "pdf" else "secondary"):
            try:
                rendered = reports.render(shell.user, report_id, fmt)
                cc[1].download_button("Download file", rendered.content,
                                      file_name=rendered.filename,
                                      mime=mimes.get(fmt, "application/octet-stream"),
                                      key=f"dl_{fmt}", use_container_width=True)
            except Exception as exc:
                st.error(f"{labels.get(fmt, fmt.upper())} export failed: {exc}")


# ================================================================ pure structural ops
def _variant(block, variant: str):
    block.payload["variant"] = variant
    return block


def _add(studio, block) -> None:
    studio.document.blocks.append(block)
    _reflow(studio)


def _add_block(studio, block) -> None:
    """Add a block onto whichever page is active. On a FREE page it is placed at a sensible
    cascaded position and NOT reflowed; on a FLOW page it takes the classic vertical-stack
    path (``_add``) — so flow behaviour is completely unchanged."""
    page = studio.page(studio.editor.active_page or "")
    if page is not None and getattr(page, "kind", "flow") == "free":
        _place_on_free_page(studio, block, page)
    else:
        _add(studio, block)


def _place_on_free_page(studio, block, page) -> None:
    """Drop a new block onto a free page: centred-ish and cascaded from the blocks already
    there so repeated adds don't land exactly on top of each other. No reflow — the block
    keeps this position until the user drags it."""
    from fap.reports.studio import BlockLayout
    studio.document.blocks.append(block)
    pw, ph = page.dimensions()
    w, h = _FREE_SIZE.get(block.kind, (320.0, 160.0))
    n = sum(1 for l in studio.layouts.values() if l.page_id == page.id)
    off = (n % 8) * _CASCADE
    x = _clampf((pw - w) / 2 + off, _MARGIN, max(_MARGIN, pw - w - _MARGIN))
    y = _clampf(_MARGIN + off, _MARGIN, max(_MARGIN, ph - h - _MARGIN))
    studio.layouts[block.id] = BlockLayout(page_id=page.id, x=x, y=y, width=w, height=h,
                                           z=studio.max_z(page.id) + 1)


def _clampf(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else (hi if v > hi else v)


def _move(studio, block_id: str, delta: int) -> None:
    blocks = studio.document.blocks
    i = next((k for k, b in enumerate(blocks) if b.id == block_id), -1)
    j = max(0, min(len(blocks) - 1, i + delta))
    if i >= 0 and i != j:
        blocks.insert(j, blocks.pop(i))
        _reflow(studio)


def _duplicate(studio, block_id: str) -> None:
    import uuid
    from fap.reports.models import Block
    blocks = studio.document.blocks
    i = next((k for k, b in enumerate(blocks) if b.id == block_id), -1)
    if i < 0:
        return
    src = blocks[i]
    blocks.insert(i + 1, Block(id=str(uuid.uuid4()), kind=src.kind, title=src.title,
                               hidden=src.hidden, payload=dict(src.payload)))
    _reflow(studio)


def _delete(studio, block_id: str) -> None:
    studio.document.blocks = [b for b in studio.document.blocks if b.id != block_id]
    studio.layouts.pop(block_id, None)
    _reflow(studio)


def _hide(studio, block_id: str, hidden: bool) -> None:
    for b in studio.document.blocks:
        if b.id == block_id:
            b.hidden = hidden


def _set_text(studio, block_id: str, title: str, text: str) -> None:
    for b in studio.document.blocks:
        if b.id == block_id:
            b.title = title
            b.payload["text"] = text
    _reflow(studio)


def _set_chart(studio, block_id: str, viz_id: str, controls: dict, image_b64: str | None = None) -> None:
    for b in studio.document.blocks:
        if b.id == block_id:
            b.payload["viz_id"] = viz_id
            b.payload["controls"] = dict(controls)
            if image_b64 is not None:
                b.payload["image_b64"] = image_b64


def _set_image(studio, block_id: str, image_id: str, caption: str, fit: str) -> None:
    for b in studio.document.blocks:
        if b.id == block_id:
            b.payload["image_id"] = image_id
            b.payload["caption"] = caption
            b.payload["fit"] = fit


def _set_qr(studio, block_id: str, url: str, caption: str, detach_ref: bool = False) -> None:
    for b in studio.document.blocks:
        if b.id == block_id:
            b.payload["url"] = url
            b.payload["caption"] = caption
            b.payload.pop("image_b64", None)          # force a fresh QR at next materialize
            if detach_ref:                            # manual URL no longer matches the source
                b.payload["player_id"] = ""
                b.payload["video_id"] = ""


def _reflow(studio) -> None:
    """Auto-stack FLOW-page blocks into a single clean vertical column, so the editor
    order equals the exported order and the 6C LayoutEngine positions them with no manual
    coordinates. This is the 'no positioning' guarantee for flow pages.

    Free-form ("free") pages are the opt-in exception: a block that lives on a free page
    keeps the x/y the user dragged it to and is NEVER touched here — this per-block, by-page
    guard (not a global active-page skip) is what lets flow and free pages coexist. When a
    report has NO free page, ``free_ids`` is empty and the first flow page is ``pages[0]``,
    so the behaviour is byte-identical to before this phase."""
    if not studio.pages:
        return
    free_ids = {p.id for p in studio.pages if getattr(p, "kind", "flow") == "free"}
    # the flow column targets the first FLOW page (today always pages[0]); if every page is
    # free there is nothing to stack.
    flow_page = next((p for p in studio.pages if getattr(p, "kind", "flow") != "free"), None)
    if flow_page is None:
        return
    pid = flow_page.id
    pw, ph = flow_page.dimensions()
    x, width = _MARGIN, pw - 2 * _MARGIN
    y = _MARGIN
    for b in studio.document.blocks:
        lay = studio.layouts.get(b.id)
        # a block on a free page is user-positioned — leave its layout completely alone
        if lay is not None and lay.page_id in free_ids:
            continue
        variant = (b.payload or {}).get("variant", "")
        h = _HEIGHT.get(variant)
        bw = width                                    # blocks span the content width…
        if h is None:
            if b.kind == "chart":
                h = 340.0
            elif b.kind == "image":
                h = 260.0
            elif b.kind == "qr":
                # …except a QR, which renders as a compact SQUARE (equal width/height)
                bw = h = min(_QR_SIDE, width)
            else:
                lines = max(1, (b.payload or {}).get("text", "").count("\n") + 1)
                h = max(120.0, lines * 22.0)
        if lay is None:
            from fap.reports.studio import BlockLayout
            lay = BlockLayout(page_id=pid)
            studio.layouts[b.id] = lay
        lay.page_id, lay.x, lay.y, lay.width, lay.height = pid, x, y, bw, float(h)
        lay.z, lay.rotation, lay.locked = 0, 0.0, False
        if not b.hidden:
            y += h + _GAP


# ================================================================ helpers
def _render_chart_once(reports, report_id, viz_id: str, controls: dict) -> str:
    """Render a chart PNG exactly once (at the user's request), returning base64.
    Never called during a normal rerun."""
    import base64
    if not viz_id:
        return ""
    record = reports.get(report_id)
    frame = reports.dataset_frame(record.dataset_id if record else None)
    if frame is None:
        return ""
    png = reports.preview_chart(viz_id, frame, controls, dpi=140)
    return base64.b64encode(png).decode("ascii") if png else ""


def _publish(studio) -> dict:
    return dict((studio.document.meta or {}).get("publish", {}))


def _set_publish(studio, data: dict) -> None:
    meta = dict(studio.document.meta or {})
    meta["publish"] = data
    studio.document.meta = meta


# ---------------------------------------------------------------- cover design
_COVER_DEFAULTS = {
    "template": "minimal_white", "background_color": "", "gradient": False, "gradient_color": "",
    "accent_color": "", "overlay_color": "#0b1f3a", "overlay_opacity": 0.0, "alignment": "left",
    "title_align": "", "subtitle_align": "", "logo_position": "top", "show_logos": True,
    "divider": True, "text_color": "",
}


def _cover_design(studio) -> dict:
    return {**_COVER_DEFAULTS, **(_publish(studio).get("cover") or {})}


def _set_cover_design(studio, design: dict) -> None:
    pub = _publish(studio)
    pub["cover"] = {**_COVER_DEFAULTS, **(pub.get("cover") or {}), **design}
    _set_publish(studio, pub)


def _apply_cover_design(shell, reports, report_id, design: dict) -> None:
    _apply(shell, reports, report_id, lambda s, d=dict(design): _set_cover_design(s, d), push=False)


def _branding_suggestions(shell) -> dict:
    try:
        from fap.theme import DEFAULT_PALETTE
        p = DEFAULT_PALETTE
        return suggest_from_palette(p.primary, getattr(p, "secondary", ""), getattr(p, "accent", ""),
                                    getattr(p, "on_primary", "#ffffff"))
    except Exception:
        return {}


def _custom_cover_templates(shell, reports, report_id, cd: dict) -> None:
    wm = getattr(shell, "wm", None)
    if wm is None:
        return
    st.markdown("**My cover templates**")
    c1, c2 = st.columns([3, 1])
    name = c1.text_input("Save current cover as…", key="cv_save_name", label_visibility="collapsed",
                         placeholder="e.g. My Club Cover")
    if c2.button("Save", key="cv_save_btn", use_container_width=True) and name.strip():
        try:
            wm.save_preset(shell.user, kind="cover_template", name=name.strip(), document=dict(cd))
            st.toast(f"Saved “{name.strip()}”")
        except Exception as exc:
            st.error(str(exc))
    try:
        saved = wm.list_presets(shell.user, kind="cover_template")
    except Exception:
        saved = []
    if saved:
        names = {p.id: p.name for p in saved}
        l1, l2 = st.columns([3, 1])
        chosen = l1.selectbox("Reuse saved cover", list(names), format_func=lambda i: names[i],
                              key="cv_load", label_visibility="collapsed")
        if l2.button("Apply", key="cv_load_apply", use_container_width=True):
            preset = next((p for p in saved if p.id == chosen), None)
            if preset:
                _apply_cover_design(shell, reports, report_id, preset.document)


def _cover_preview_html(reports, cover, cd: dict) -> str:
    talign = cd.get("title_align") or cd.get("alignment", "left")
    salign = cd.get("subtitle_align") or cd.get("alignment", "left")
    text_color = cd.get("text_color") or ("#ffffff" if _is_dark(cd.get("background_color")) else "#16181d")
    accent = cd.get("accent_color") or "#E07B2B"
    bg = cd.get("background_color") or "#ffffff"
    if cd.get("gradient") and cd.get("gradient_color"):
        bg = f"linear-gradient(135deg, {bg}, {cd['gradient_color']})"
    photo = ""
    if cover.cover_image:
        data = reports.image_bytes(cover.cover_image)
        if data:
            import base64
            mime = reports.image_mime(cover.cover_image) or "image/png"
            photo = (f"<img src='data:{mime};base64,{base64.b64encode(data).decode()}' "
                     f"style='width:100%;height:110px;object-fit:cover;border-radius:6px;margin-bottom:8px'/>")
    logos = ""
    if cd.get("show_logos"):
        for lid in (cover.club_logo, cover.organization_logo):
            b = _logo_uri(reports, lid)
            if b:
                logos += f"<img src='{b}' style='height:26px;margin-right:8px'/>"
    divider = (f"<div style='height:3px;width:60px;background:{accent};margin:8px 0;"
               f"{'margin-left:auto;margin-right:auto' if talign=='center' else ''}'></div>"
               if cd.get("divider") else "")
    return (f"<div style='border:1px solid #d8dee9;border-radius:10px;padding:16px;"
            f"background:{bg};color:{text_color};min-height:230px;text-align:{talign}'>"
            f"<div style='text-align:{cd.get('logo_position')=='center' and 'center' or 'left'}'>{logos}</div>"
            f"{photo}"
            f"<div style='font-size:22px;font-weight:850;margin-top:6px'>{_esc(cover.title)}</div>"
            f"{divider}"
            f"<div style='opacity:.85;font-size:13px;text-align:{salign}'>{_esc(cover.subtitle)}</div>"
            f"<div style='opacity:.6;font-size:11px;margin-top:8px'>"
            f"{_esc(cover.club)} · {_esc(cover.competition)} · {_esc(cover.season)}</div></div>")


def _logo_uri(reports, image_id: str) -> str:
    if not image_id:
        return ""
    data = reports.image_bytes(image_id)
    if not data:
        return ""
    import base64
    mime = reports.image_mime(image_id) or "image/png"
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def _is_dark(color: str | None) -> bool:
    if not color or not color.startswith("#") or len(color) < 7:
        return False
    try:
        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
        return (0.299 * r + 0.587 * g + 0.114 * b) < 140
    except Exception:
        return False


def _ai(align: str) -> int:
    return {"left": 0, "center": 1, "right": 2}.get(align, 0)


def _upload(shell, reports, report_id, file) -> str:
    img = reports.upload_image(shell.user, file.getvalue(), file.name, file.type or "image/png",
                               workspace_id=_ws(reports, report_id))
    return img.id


def _esc(s: Any) -> str:
    import html
    return html.escape(str(s or ""), quote=True)


def _ws(reports, report_id) -> Any:
    rec = reports.get(report_id)
    return rec.workspace_id if rec else None


# ================================================================ apply / undo
def _apply(shell, reports, report_id, mutate: Callable, *, push: bool = True) -> None:
    """Persist one edit through the reused autosave path (with an undo snapshot),
    then rerun. The rerun is cheap: native widgets only, no iframe, no live charts."""
    try:
        if push:
            current = reports.document(report_id)
            if current is not None:
                history.record(report_id, current.to_dict())
        reports.update_studio(shell.user, report_id, mutate)
        st.session_state.pop(_PREVIEW, None)      # content changed -> stale preview
        st.rerun()
    except Exception as exc:
        st.error(str(exc))


def _undo(shell, reports, report_id) -> None:
    from fap.reports.models import ReportDocument
    current = reports.document(report_id)
    snap = history.undo(report_id, current.to_dict() if current else {})
    if snap is not None:
        try:
            reports.save_document(shell.user, report_id, ReportDocument.from_dict(snap))
            st.session_state.pop(_PREVIEW, None)
            st.rerun()
        except Exception as exc:
            st.error(str(exc))


def _redo(shell, reports, report_id) -> None:
    from fap.reports.models import ReportDocument
    current = reports.document(report_id)
    snap = history.redo(report_id, current.to_dict() if current else {})
    if snap is not None:
        try:
            reports.save_document(shell.user, report_id, ReportDocument.from_dict(snap))
            st.session_state.pop(_PREVIEW, None)
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
