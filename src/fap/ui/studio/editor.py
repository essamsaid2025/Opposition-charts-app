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

from typing import Any, Callable

import streamlit as st

from fap.reports import chart_block, image_block, text_block
from fap.ui.studio import history
from fap.ui.studio.covers import (
    COVER_PRESETS, COVER_TEMPLATES, suggest_from_palette, template_design,
)

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
_PREVIEW = "_studio_preview_html"       # cached export-preview HTML (session, per report)


# ================================================================ entry point
def render_studio(shell: Any, reports: Any, report_id: str) -> None:
    record = reports.get(report_id)
    if record is None:
        st.warning("That report no longer exists.")
        return
    studio = reports.studio(report_id)
    if studio is None:
        st.info("Report could not be opened.")
        return

    _header(shell, reports, report_id, record, studio)
    tab_content, tab_template, tab_export = st.tabs(["✎ Content", "◨ Template", "⭳ Export"])
    with tab_content:
        _cover_editor(shell, reports, report_id, studio)
        st.divider()
        _body_editor(shell, reports, report_id, studio)
    with tab_template:
        _template_editor(shell, reports, report_id, studio)
    with tab_export:
        _export(shell, reports, report_id)


# ================================================================ header
def _header(shell, reports, report_id, record, studio) -> None:
    c1, c2, c3 = st.columns([5, 1, 1])
    c1.markdown(f"### {record.title}")
    c1.caption(f"{record.template_id or 'report'} · updated {record.updated_at} · v{record.version}")
    if c2.button("↶ Undo", disabled=not history.can_undo(report_id), use_container_width=True):
        _undo(shell, reports, report_id)
    if c3.button("Save version", use_container_width=True):
        reports.save_version(shell.user, report_id, note="editor snapshot")
        st.toast("Version saved")


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
            if suggestions:
                s1, s2 = st.columns([3, 1])
                sug = s1.selectbox("Club branding suggestions", list(suggestions), key="cv_sug",
                                   label_visibility="collapsed")
                if s2.button("Apply", key="cv_sug_apply", use_container_width=True):
                    _apply_cover_design(shell, reports, report_id, suggestions[sug])

            # -- content (title/subtitle + images) --
            st.markdown("**Content**")
            title = st.text_input("Title", value=cover.title, key="cv_title")
            subtitle = st.text_input("Subtitle", value=cover.subtitle, key="cv_sub")
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
                logo_pos = d2.selectbox("Logo position", ["top", "center", "corner"],
                                        index=["top", "center", "corner"].index(cd.get("logo_position", "top")),
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

                def m(s, t=title, sub=subtitle, pid=photo_id, bid=badge_id, fid=fed_id, d=design):
                    s.document.cover.title = t
                    s.document.cover.subtitle = sub
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


# ================================================================ body
def _body_editor(shell, reports, report_id, studio) -> None:
    blocks = studio.document.blocks
    st.markdown("**Sections**")
    if not blocks:
        st.caption("Empty report — add a section below.")
    for i, b in enumerate(blocks):
        _block_card(shell, reports, report_id, b, i, len(blocks))

    _add_content(shell, reports, report_id)


# ================================================================ add content picker
def _add_content(shell, reports, report_id) -> None:
    """The single Add Content button -> a categorized picker. Nothing is inserted
    unless the user explicitly chooses it (empty-report philosophy)."""
    with st.expander("➕ Add Content", expanded=False):
        cats = ["Text", "Charts", "Media", "Data", "Custom"]
        tabs = st.tabs(cats)
        with tabs[0]:
            _insert_grid(shell, reports, report_id, _text_items())
        with tabs[1]:
            _chart_picker_grid(shell, reports, report_id)
        with tabs[2]:
            _insert_grid(shell, reports, report_id, _media_items())
        with tabs[3]:
            _insert_grid(shell, reports, report_id, _data_items())
        with tabs[4]:
            _insert_grid(shell, reports, report_id, {"Empty block": lambda: text_block("", title="Block")})


def _insert_grid(shell, reports, report_id, items: dict) -> None:
    cols = st.columns(3)
    for i, (label, factory) in enumerate(items.items()):
        if cols[i % 3].button(label, key=f"ins_{label}", use_container_width=True):
            _apply(shell, reports, report_id, lambda s, f=factory: _add(s, f()))


def _text_items() -> dict:
    return {
        "Title": lambda: _variant(text_block("Title", title="Title"), SECTION_HEADER),
        "Heading": lambda: _variant(text_block("Heading", title="Heading"), SECTION_HEADER),
        "Paragraph": lambda: text_block("Write here…", title="Paragraph"),
        "Quote": lambda: _variant(text_block("“Quote…”", title="Quote"), NOTES),
        "Divider": lambda: _variant(text_block("", title="Divider"), DIVIDER),
        "Table": lambda: text_block("| Metric | Value |\n| --- | --- |\n| xG | 1.8 |", title="Table"),
    }


def _media_items() -> dict:
    return {
        "Image": lambda: image_block("", title="Image"),
        "Video link": lambda: text_block("Video: paste link (YouTube / Hudl / Wyscout)", title="Video"),
    }


def _data_items() -> dict:
    def card(name):
        return lambda: _variant(text_block(f"{name} details…", title=name), SECTION_HEADER)
    return {
        "Player Card": card("Player Card"), "Match Card": card("Match Card"),
        "Team Card": card("Team Card"), "Comparison": card("Comparison"),
        "Statistics Table": lambda: text_block("| Stat | Value |\n| --- | --- |\n| Goals | 0 |",
                                               title="Statistics"),
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
               lambda s, v=viz_id, n=name: _add(s, chart_block(v, {}, title=n)))


def _block_card(shell, reports, report_id, block, index, total) -> None:
    variant = (block.payload or {}).get("variant", "")
    kind_label = {"section_header": "Section", "notes": "Notes", "divider": "Divider",
                  "spacer": "Spacer"}.get(variant, block.kind.title())
    header = f"{'🙈 ' if block.hidden else ''}{block.title or kind_label} · {kind_label}"
    with st.expander(header, expanded=False):
        # row of structural controls (no pixel editing)
        c = st.columns(6)
        if c[0].button("↑", key=f"up_{block.id}", disabled=index == 0, help="Move up"):
            _apply(shell, reports, report_id, lambda s, b=block.id: _move(s, b, -1))
        if c[1].button("↓", key=f"dn_{block.id}", disabled=index == total - 1, help="Move down"):
            _apply(shell, reports, report_id, lambda s, b=block.id: _move(s, b, +1))
        if c[2].button("⧉", key=f"dup_{block.id}", help="Duplicate"):
            _apply(shell, reports, report_id, lambda s, b=block.id: _duplicate(s, b))
        if c[3].button("👁" if not block.hidden else "🚫", key=f"hide_{block.id}", help="Hide/Show"):
            _apply(shell, reports, report_id, lambda s, b=block.id, h=not block.hidden: _hide(s, b, h))
        if c[4].button("🗑", key=f"del_{block.id}", help="Delete"):
            _apply(shell, reports, report_id, lambda s, b=block.id: _delete(s, b))

        if block.kind == "text":
            _edit_text(shell, reports, report_id, block, variant)
        elif block.kind == "chart":
            _edit_chart(shell, reports, report_id, block)
        elif block.kind == "image":
            _edit_image(shell, reports, report_id, block)


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


# ================================================================ export (render only here)
def _export(shell, reports, report_id) -> None:
    st.caption("Charts and images render here — the export is the same engine the preview uses, "
               "so the PDF looks like the report.")
    formats = reports.available_formats()
    cols = st.columns(len(formats) or 1)
    mimes = {"html": "text/html", "markdown": "text/markdown", "pdf": "application/pdf"}
    for i, fmt in enumerate(formats):
        if cols[i].button(fmt.upper(), key=f"exp_{fmt}", use_container_width=True):
            try:
                rendered = reports.render(shell.user, report_id, fmt)
                st.download_button(f"Download {fmt.upper()}", rendered.content,
                                   file_name=rendered.filename,
                                   mime=mimes.get(fmt, "application/octet-stream"),
                                   key=f"dl_{fmt}")
            except Exception as exc:
                st.error(f"{fmt.upper()} export failed: {exc}")

    st.divider()
    if st.button("Refresh preview", key="prev_refresh"):
        try:
            st.session_state[_PREVIEW] = reports.render(shell.user, report_id, "html").text
        except Exception as exc:
            st.error(f"Preview failed: {exc}")
    html = st.session_state.get(_PREVIEW)
    if html:
        st.components.v1.html(html, height=900, scrolling=True)
    else:
        st.caption("Click **Refresh preview** to render the full report (renders charts once).")


# ================================================================ pure structural ops
def _variant(block, variant: str):
    block.payload["variant"] = variant
    return block


def _add(studio, block) -> None:
    studio.document.blocks.append(block)
    _reflow(studio)


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


def _reflow(studio) -> None:
    """Auto-stack every block into a single clean vertical flow on the first page,
    so the editor order equals the exported order and the 6C LayoutEngine positions
    everything with no manual coordinates. This is the 'no positioning' guarantee."""
    if not studio.pages:
        return
    page = studio.pages[0]
    pid = page.id
    pw, ph = page.dimensions()
    x, width = _MARGIN, pw - 2 * _MARGIN
    y = _MARGIN
    for b in studio.document.blocks:
        variant = (b.payload or {}).get("variant", "")
        h = _HEIGHT.get(variant)
        if h is None:
            if b.kind == "chart":
                h = 340.0
            elif b.kind == "image":
                h = 260.0
            else:
                lines = max(1, (b.payload or {}).get("text", "").count("\n") + 1)
                h = max(120.0, lines * 22.0)
        lay = studio.layouts.get(b.id)
        if lay is None:
            from fap.reports.studio import BlockLayout
            lay = BlockLayout(page_id=pid)
            studio.layouts[b.id] = lay
        lay.page_id, lay.x, lay.y, lay.width, lay.height = pid, x, y, width, float(h)
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
