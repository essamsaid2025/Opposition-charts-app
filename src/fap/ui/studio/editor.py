"""The Professional Visual Report Editor (Phase 6B).

A Canva/PowerPoint-style editor built ENTIRELY on the Phase-6A foundation:

* every mutation is a pure :mod:`fap.reports.editor_ops` call applied through
  ``ReportsManager.update_studio`` (autosave straight to the database);
* the interactive canvas is a static custom component that only *reports* drag/
  resize/select intent - Python maps it onto the same ops (with a native control
  fallback if the iframe is unavailable);
* charts reuse the visualization registry + ``preview_chart`` (Renderer byte
  cache); images reuse ImageStorage; controls reuse the generic control renderer;
  chrome colors come from the application theme (no hardcoded colors).

session_state holds only ephemeral UI state (current selection, the last handled
canvas nonce, undo/redo snapshots) - never the report itself.
"""
from __future__ import annotations

from typing import Any, Callable

import streamlit as st

from fap.reports import editor_ops as ops
from fap.reports import text_block
from fap.reports.studio import Align, Axis, Edge
from fap.ui.studio import history
from fap.ui.studio.component import canvas
from fap.ui.studio.render import (
    DIVIDER, NOTES, SECTION_HEADER, SPACER, block_content_html,
)

ZOOM_STEPS = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0]
_SEL = "_studio_sel"                 # set[str] of selected block ids (ephemeral UI)
_NONCE = "_studio_nonce"             # last handled canvas action nonce (dedup)


# ---------------------------------------------------------------- entry point
def render_studio(shell: Any, reports: Any, report_id: str) -> None:
    record = reports.get(report_id)
    if record is None:
        st.warning("That report no longer exists.")
        return
    studio = reports.studio(report_id)
    if studio is None:
        st.info("Report could not be opened.")
        return
    colors = _theme_colors()
    selected = _selection()

    _toolbar(shell, reports, report_id, studio, record)

    left, center, right = st.columns([1.15, 3.0, 1.5], gap="small")
    with left:
        _pages_panel(shell, reports, report_id, studio)
        _layers_panel(shell, reports, report_id, studio, selected)
    with center:
        _canvas(shell, reports, report_id, studio, record, colors, selected)
    with right:
        _inspector(shell, reports, report_id, studio, record, selected, colors)


# ---------------------------------------------------------------- toolbar
def _toolbar(shell, reports, report_id, studio, record) -> None:
    c1, c2, c3, c4, c5, c6 = st.columns([2.4, 1.1, 0.7, 0.7, 1.6, 1.2])
    c1.markdown(f"### {record.title}")
    with c2:
        zoom = st.selectbox("Zoom", ZOOM_STEPS, index=ZOOM_STEPS.index(studio.editor.zoom)
                            if studio.editor.zoom in ZOOM_STEPS else 3,
                            format_func=lambda z: f"{int(z*100)}%", key="studio_zoom",
                            label_visibility="collapsed")
        if zoom != studio.editor.zoom:
            _apply(reports, report_id, shell, lambda s, z=zoom: _set_zoom(s, z), push=False)
    if c3.button("↶", key="studio_undo", disabled=not history.can_undo(report_id), help="Undo"):
        _undo(shell, reports, report_id)
    if c4.button("↷", key="studio_redo", disabled=not history.can_redo(report_id), help="Redo"):
        _redo(shell, reports, report_id)
    with c5:
        add = st.selectbox("Insert", ["+ Insert", "Rich Text", "Section Header", "Notes",
                                      "Divider", "Spacer"], key="studio_add",
                           label_visibility="collapsed")
        if add != "+ Insert":
            _insert_text_like(shell, reports, report_id, add)
    if c6.button("Save version", key="studio_ver"):
        reports.save_version(shell.user, report_id, note="editor snapshot")
        st.toast("Version saved")


def _set_zoom(studio, z: float) -> None:
    studio.editor.zoom = z


def _insert_text_like(shell, reports, report_id, label: str) -> None:
    factory = {
        "Rich Text": lambda: text_block("Write here…", title="Text"),
        "Section Header": lambda: _variant(text_block("# Section title", title="Section"), SECTION_HEADER, h=70),
        "Notes": lambda: _variant(text_block("Coaching notes…", title="Notes"), NOTES, h=140),
        "Divider": lambda: _variant(text_block("", title="Divider"), DIVIDER, h=32),
        "Spacer": lambda: _variant(text_block("", title="Spacer"), SPACER, h=48),
    }[label]
    _apply(reports, report_id, shell,
           lambda s, f=factory: ops.add_block_to_page(s, f(), s.editor.active_page,
                                                       height=_default_h(label)))


def _variant(block, variant: str, h: int):
    block.payload["variant"] = variant
    return block


def _default_h(label: str) -> float:
    return {"Divider": 32, "Spacer": 48, "Section Header": 70, "Notes": 140}.get(label, 220)


# ---------------------------------------------------------------- pages panel
def _pages_panel(shell, reports, report_id, studio) -> None:
    st.markdown("**Pages**")
    b1, b2 = st.columns(2)
    if b1.button("＋ New", key="pg_new", use_container_width=True):
        _apply(reports, report_id, shell, lambda s: ops.create_page(s))
    if b2.button("⧉ Duplicate", key="pg_dup", use_container_width=True):
        _apply(reports, report_id, shell, lambda s: ops.duplicate_page(s, s.editor.active_page))

    for i, page in enumerate(studio.pages):
        active = page.id == studio.editor.active_page
        with st.container(border=True):
            st.markdown(_page_thumb_html(studio, page, active), unsafe_allow_html=True)
            r1, r2, r3, r4 = st.columns(4)
            if r1.button("Open", key=f"pg_open_{page.id}", disabled=active):
                _apply(reports, report_id, shell, lambda s, p=page.id: _activate(s, p), push=False)
            if r2.button("↑", key=f"pg_up_{page.id}", disabled=i == 0):
                _apply(reports, report_id, shell, lambda s, p=page.id: ops.move_page(s, p, -1))
            if r3.button("↓", key=f"pg_dn_{page.id}", disabled=i == len(studio.pages) - 1):
                _apply(reports, report_id, shell, lambda s, p=page.id: ops.move_page(s, p, +1))
            if r4.button("🗑", key=f"pg_del_{page.id}", disabled=len(studio.pages) <= 1):
                _apply(reports, report_id, shell, lambda s, p=page.id: ops.delete_page(s, p))


def _activate(studio, page_id: str) -> None:
    studio.editor.active_page = page_id


def _page_thumb_html(studio, page, active: bool) -> str:
    colors = _theme_colors()
    pw, ph = page.dimensions()
    scale = 120 / ph
    boxes = ""
    for b in studio.blocks_on(page.id):
        lay = studio.layouts[b.id]
        if b.hidden:
            continue
        boxes += (f"<div style='position:absolute;left:{lay.x*scale}px;top:{lay.y*scale}px;"
                  f"width:{lay.width*scale}px;height:{lay.height*scale}px;"
                  f"background:{colors['accent']};opacity:.35;border-radius:2px'></div>")
    border = colors["accent"] if active else colors["border"]
    return (f"<div style='position:relative;width:{pw*scale}px;height:{ph*scale}px;"
            f"background:{colors['surface']};border:2px solid {border};border-radius:4px;"
            f"margin:0 auto 4px'>{boxes}</div>"
            f"<div style='text-align:center;color:{colors['muted']};font-size:12px'>"
            f"{page.title or 'Page'}</div>")


# ---------------------------------------------------------------- layers panel
def _layers_panel(shell, reports, report_id, studio, selected) -> None:
    st.markdown("**Layers**")
    blocks = list(reversed(studio.blocks_on(studio.editor.active_page)))  # front -> back
    if not blocks:
        st.caption("No blocks on this page.")
        return
    for b in blocks:
        lay = studio.layouts[b.id]
        mark = "●" if b.id in selected else "○"
        label = b.title or f"{b.kind.title()}"
        cols = st.columns([0.5, 2.2, 0.6, 0.6, 0.6, 0.6])
        if cols[0].button(mark, key=f"ly_sel_{b.id}", help="Select"):
            _select_only(b.id)
        cols[1].markdown(f"<span style='font-size:13px'>{label}</span>"
                         + ("  ·hidden" if b.hidden else ""), unsafe_allow_html=True)
        if cols[2].button("↑", key=f"ly_fwd_{b.id}", help="Bring forward"):
            _apply(reports, report_id, shell, lambda s, x=b.id: ops.bring_forward(s, x))
        if cols[3].button("↓", key=f"ly_bwd_{b.id}", help="Send backward"):
            _apply(reports, report_id, shell, lambda s, x=b.id: ops.send_backward(s, x))
        if cols[4].button("🔒" if lay.locked else "🔓", key=f"ly_lock_{b.id}"):
            _apply(reports, report_id, shell, lambda s, x=b.id, v=not lay.locked: ops.lock_block(s, x, v))
        if cols[5].button("👁" if not b.hidden else "🚫", key=f"ly_hide_{b.id}"):
            _apply(reports, report_id, shell, lambda s, x=b.id, v=not b.hidden: ops.hide_block(s, x, v))


# ---------------------------------------------------------------- canvas
def _canvas(shell, reports, report_id, studio, record, colors, selected) -> None:
    page = studio.page(studio.editor.active_page)
    if page is None:
        st.info("No page selected.")
        return
    pw, ph = page.dimensions()
    chart_cache = st.session_state.setdefault(f"_studio_charts::{report_id}", {})
    theme_id = _chart_theme(studio)
    dataset_id = record.dataset_id
    bg_image = ""
    if page.background:
        data = reports.image_bytes(page.background)
        if data:
            import base64
            bg_image = f"data:{reports.image_mime(page.background)};base64,{base64.b64encode(data).decode()}"

    blocks = []
    for b in studio.blocks_on(page.id):
        if b.hidden:
            continue
        lay = studio.layouts[b.id]
        p = b.payload or {}
        blocks.append({
            "id": b.id, "x": lay.x, "y": lay.y, "w": lay.width, "h": lay.height,
            "z": lay.z, "rotation": lay.rotation, "locked": lay.locked,
            "opacity": float(p.get("opacity", 1) or 1), "radius": int(p.get("radius", 0) or 0),
            "kind": b.kind,
            "html": block_content_html(b, reports=reports, dataset_id=dataset_id,
                                       theme_id=theme_id, colors=colors, chart_cache=chart_cache),
        })

    action = canvas(
        page={"w": pw, "h": ph, "background_color": page.background_color,
              "bg_image": bg_image},
        blocks=blocks, zoom=studio.editor.zoom, grid=studio.editor.grid_size,
        snap=studio.editor.snap_to_grid, guides=studio.editor.guides,
        rulers_grid=studio.editor.rulers, aspect=st.session_state.get("_studio_aspect", False),
        selected=list(selected), theme=colors, key=f"canvas_{report_id}_{page.id}")

    from fap.ui.studio.component import UNAVAILABLE
    if action is UNAVAILABLE:
        st.caption("Interactive canvas unavailable in this environment — use the "
                   "Inspector controls to move, resize and arrange blocks.")
        return
    if action is None:
        return                     # canvas rendered; no new action this run
    _dispatch(shell, reports, report_id, action)


def _dispatch(shell, reports, report_id, action: dict) -> None:
    """Map ONE canvas action onto editor_ops. Dedup by nonce so a rerun that
    re-delivers the same action does not re-apply it."""
    nonce = action.get("nonce")
    kind = action.get("action")
    if kind in (None,):
        return
    # selection actions: ephemeral, no DB write
    if kind == "select":
        _select_only(action.get("block_id")); return
    if kind == "multiselect":
        st.session_state[_SEL] = set(action.get("ids", [])); st.rerun()
    if kind == "deselect":
        st.session_state[_SEL] = set(); st.rerun()
    # structural/geometry actions: dedup then apply through ops
    if nonce and st.session_state.get(_NONCE) == nonce:
        return
    st.session_state[_NONCE] = nonce
    if kind == "move":
        bid, x, y = action["block_id"], action["x"], action["y"]
        _apply(reports, report_id, shell, lambda s: ops.move_block(s, bid, x, y))
    elif kind == "resize":
        bid = action["id"]
        _apply(reports, report_id, shell,
               lambda s: (ops.move_block(s, bid, action["x"], action["y"]),
                          ops.resize_block(s, bid, action["w"], action["h"])))
    elif kind == "nudge":
        ids, dx, dy = action.get("ids", []), action.get("dx", 0), action.get("dy", 0)
        _apply(reports, report_id, shell,
               lambda s: [ops.nudge_block(s, i, dx, dy) for i in ids])
    elif kind == "delete":
        ids = action.get("ids", [])
        _apply(reports, report_id, shell, lambda s: [ops.delete_block(s, i) for i in ids])
    elif kind == "duplicate":
        ids = action.get("ids", [])
        _apply(reports, report_id, shell, lambda s: [ops.duplicate_block(s, i) for i in ids])


# ---------------------------------------------------------------- inspector
def _inspector(shell, reports, report_id, studio, record, selected, colors) -> None:
    tabs = st.tabs(["Properties", "Charts", "Images", "Theme"])
    with tabs[0]:
        if len(selected) == 0:
            _page_properties(shell, reports, report_id, studio)
        elif len(selected) == 1:
            _block_properties(shell, reports, report_id, studio, next(iter(selected)))
        else:
            _multi_properties(shell, reports, report_id, selected)
    with tabs[1]:
        _charts_tab(shell, reports, report_id, studio, record, selected)
    with tabs[2]:
        _images_tab(shell, reports, report_id, studio, record, selected)
    with tabs[3]:
        _theme_tab(shell, reports, report_id, studio)


def _page_properties(shell, reports, report_id, studio) -> None:
    page = studio.page(studio.editor.active_page)
    if page is None:
        return
    st.caption("Page properties")
    title = st.text_input("Page name", value=page.title, key="pp_title")
    size = st.selectbox("Size", ["A4", "Letter"], index=0 if page.size == "A4" else 1, key="pp_size")
    orient = st.radio("Orientation", ["portrait", "landscape"], horizontal=True,
                      index=0 if page.orientation == "portrait" else 1, key="pp_orient")
    bg = st.color_picker("Background", value=page.background_color or "#ffffff", key="pp_bg")
    cols = st.number_input("Column guides", 1, 6, page.columns, key="pp_cols")
    snap = st.checkbox("Snap to grid", value=studio.editor.snap_to_grid, key="pp_snap")
    guides = st.checkbox("Alignment guides", value=studio.editor.guides, key="pp_guides")
    grid_on = st.checkbox("Show grid", value=studio.editor.rulers, key="pp_grid")
    if st.button("Apply", type="primary", key="pp_apply"):
        def m(s):
            pg = s.page(s.editor.active_page)
            pg.title, pg.size, pg.orientation = title, size, orient
            pg.background_color = "" if bg.lower() == "#ffffff" else bg
            pg.columns = int(cols)
            s.editor.snap_to_grid, s.editor.guides, s.editor.rulers = snap, guides, grid_on
        _apply(reports, report_id, shell, m)


def _block_properties(shell, reports, report_id, studio, block_id) -> None:
    b = studio.block(block_id)
    lay = studio.layouts.get(block_id)
    if b is None or lay is None:
        st.caption("Select a block.")
        return
    st.caption(f"{b.kind.title()} block")
    title = st.text_input("Title", value=b.title, key=f"bp_t_{block_id}")

    # geometry (native drag/resize fallback + precision)
    g1, g2 = st.columns(2)
    x = g1.number_input("X", value=float(lay.x), step=1.0, key=f"bp_x_{block_id}")
    y = g2.number_input("Y", value=float(lay.y), step=1.0, key=f"bp_y_{block_id}")
    w = g1.number_input("Width", value=float(lay.width), min_value=24.0, step=1.0, key=f"bp_w_{block_id}")
    h = g2.number_input("Height", value=float(lay.height), min_value=24.0, step=1.0, key=f"bp_h_{block_id}")
    rot = st.slider("Rotation", -180, 180, int(lay.rotation), key=f"bp_r_{block_id}")

    payload_update: dict[str, Any] = {}
    if b.kind == "text":
        variant = b.payload.get("variant", "")
        if variant not in (DIVIDER, SPACER):
            body = st.text_area("Text ( # heading · - bullet )", value=b.payload.get("text", ""),
                                height=200, key=f"bp_body_{block_id}")
            payload_update["text"] = body
    elif b.kind == "image":
        payload_update["caption"] = st.text_input("Caption", value=b.payload.get("caption", ""),
                                                   key=f"bp_cap_{block_id}")
        payload_update["opacity"] = st.slider("Opacity", 0.0, 1.0, float(b.payload.get("opacity", 1)),
                                              0.05, key=f"bp_op_{block_id}")
        payload_update["radius"] = st.slider("Rounded corners", 0, 60, int(b.payload.get("radius", 0)),
                                             key=f"bp_rad_{block_id}")
        payload_update["fit"] = st.selectbox("Crop fit", ["cover", "contain", "fill"],
                                             index=["cover", "contain", "fill"].index(b.payload.get("fit", "cover")),
                                             key=f"bp_fit_{block_id}")
    elif b.kind == "chart":
        st.caption(f"Visualization: `{b.payload.get('viz_id', '')}` — edit options in the **Charts** tab.")

    if st.button("Apply", type="primary", key=f"bp_apply_{block_id}"):
        def m(s, bid=block_id, t=title, pu=dict(payload_update), gx=x, gy=y, gw=w, gh=h, gr=rot):
            blk = s.block(bid)
            blk.title = t
            blk.payload.update(pu)
            ops.move_block(s, bid, gx, gy)
            ops.resize_block(s, bid, gw, gh)
            ops.rotate_block(s, bid, gr)
        _apply(reports, report_id, shell, m)

    st.divider()
    l1, l2, l3, l4 = st.columns(4)
    if l1.button("⤒ Front", key=f"bp_front_{block_id}"):
        _apply(reports, report_id, shell, lambda s: ops.bring_to_front(s, block_id))
    if l2.button("⤓ Back", key=f"bp_back_{block_id}"):
        _apply(reports, report_id, shell, lambda s: ops.send_to_back(s, block_id))
    if l3.button("⧉ Dup", key=f"bp_dup_{block_id}"):
        _apply(reports, report_id, shell, lambda s: ops.duplicate_block(s, block_id))
    if l4.button("🗑 Del", key=f"bp_del_{block_id}"):
        _apply(reports, report_id, shell, lambda s: ops.delete_block(s, block_id))


def _multi_properties(shell, reports, report_id, selected) -> None:
    ids = list(selected)
    st.caption(f"{len(ids)} blocks selected")
    st.markdown("**Align**")
    a = st.columns(3)
    mapping = [("Left", Edge.LEFT), ("Center", Edge.CENTER_X), ("Right", Edge.RIGHT),
               ("Top", Edge.TOP), ("Middle", Edge.CENTER_Y), ("Bottom", Edge.BOTTOM)]
    for i, (label, edge) in enumerate(mapping):
        if a[i % 3].button(label, key=f"al_{edge}"):
            _apply(reports, report_id, shell, lambda s, e=edge: ops.align_blocks(s, ids, e))
    st.markdown("**Distribute**")
    d1, d2 = st.columns(2)
    if d1.button("Horizontally", key="dist_h"):
        _apply(reports, report_id, shell, lambda s: ops.distribute_blocks(s, ids, Axis.HORIZONTAL))
    if d2.button("Vertically", key="dist_v"):
        _apply(reports, report_id, shell, lambda s: ops.distribute_blocks(s, ids, Axis.VERTICAL))
    st.divider()
    if st.button("🗑 Delete selected", key="multi_del"):
        _apply(reports, report_id, shell, lambda s: [ops.delete_block(s, i) for i in ids])


# ---------------------------------------------------------------- charts tab
def _charts_tab(shell, reports, report_id, studio, record, selected) -> None:
    from fap.visuals.base import load_builtin_visuals, visual_registry
    from fap.ui.components.controls import render_controls

    load_builtin_visuals()
    infos = visual_registry.infos()
    # editing an existing chart block?
    sel_block = studio.block(next(iter(selected))) if len(selected) == 1 else None
    editing = sel_block if (sel_block and sel_block.kind == "chart") else None

    categories = sorted({i.category or "Other" for i in infos})
    default_cat = 0
    if editing:
        cur = next((i for i in infos if i.id == editing.payload.get("viz_id")), None)
        if cur:
            default_cat = categories.index(cur.category or "Other")
    category = st.selectbox("Category", categories, index=default_cat, key="ct_cat")
    options = [i for i in infos if (i.category or "Other") == category]
    labels = {i.id: i.name for i in options}
    idx = 0
    if editing and editing.payload.get("viz_id") in labels:
        idx = list(labels).index(editing.payload["viz_id"])
    viz_id = st.selectbox("Visualization", list(labels), index=idx,
                          format_func=lambda i: labels[i], key="ct_viz")
    info = next(i for i in options if i.id == viz_id)
    if info.description:
        st.caption(info.description)

    # controls reused from the plugin's own declaration (same renderer as everywhere)
    viz = visual_registry.create(viz_id)
    saved = editing.payload.get("controls", {}) if editing else {}
    controls = render_controls(getattr(viz, "controls", ()) or (), saved=saved,
                               key_prefix=f"ct_{viz_id}")

    frame = reports.dataset_frame(record.dataset_id)
    if st.toggle("Preview", key="ct_prev") and frame is not None:
        png = reports.preview_chart(viz_id, frame, controls, dpi=110)
        if png:
            st.image(png, use_container_width=True)
        else:
            st.caption("This visualization needs a dataset/controls to preview.")

    if editing:
        c1, c2 = st.columns(2)
        if c1.button("Update options", type="primary", key="ct_update"):
            _apply(reports, report_id, shell,
                   lambda s, c=controls: _set_chart(s, editing.id, controls=c))
        if c2.button("Replace visualization", key="ct_replace"):
            _apply(reports, report_id, shell,
                   lambda s, v=viz_id, c=controls: _set_chart(s, editing.id, viz_id=v, controls=c))
        st.caption("Replacing keeps the same block (position, size, layer).")
    else:
        if st.button("Insert chart", type="primary", key="ct_insert"):
            from fap.reports import chart_block
            _apply(reports, report_id, shell,
                   lambda s, v=viz_id, n=info.name, c=controls:
                   ops.add_block_to_page(s, chart_block(v, c, title=n), s.editor.active_page,
                                         width=520, height=360))


def _set_chart(studio, block_id, *, viz_id: str | None = None,
               controls: dict | None = None) -> None:
    blk = studio.block(block_id)
    if blk is None:
        return
    if viz_id is not None:
        blk.payload["viz_id"] = viz_id
    if controls is not None:
        blk.payload["controls"] = dict(controls)


# ---------------------------------------------------------------- images tab
def _images_tab(shell, reports, report_id, studio, record, selected) -> None:
    sel_block = studio.block(next(iter(selected))) if len(selected) == 1 else None
    editing = sel_block if (sel_block and sel_block.kind == "image") else None

    upload = st.file_uploader("Upload image", type=["png", "jpg", "jpeg", "svg", "webp"],
                              key="im_up")
    if upload is not None and st.button("Add to page", type="primary", key="im_add"):
        try:
            img = reports.upload_image(shell.user, upload.getvalue(), upload.name,
                                       upload.type or "image/png", workspace_id=record.workspace_id)
            from fap.reports import image_block
            _apply(reports, report_id, shell,
                   lambda s, i=img.id, n=upload.name:
                   ops.add_block_to_page(s, image_block(i, caption=n), s.editor.active_page,
                                         width=400, height=300))
        except Exception as exc:
            st.error(f"Could not add image: {exc}")

    existing = reports.list_images(record.workspace_id)
    if existing:
        names = {i.id: f"{i.filename} ({i.size_bytes // 1024}KB)" for i in existing}
        chosen = st.selectbox("Library", list(names), format_func=lambda i: names[i], key="im_lib")
        c1, c2 = st.columns(2)
        if c1.button("Insert", key="im_ins"):
            from fap.reports import image_block
            _apply(reports, report_id, shell,
                   lambda s, i=chosen: ops.add_block_to_page(s, image_block(i), s.editor.active_page,
                                                             width=400, height=300))
        if editing and c2.button("Replace selected", key="im_replace"):
            _apply(reports, report_id, shell,
                   lambda s, i=chosen: _set_image(s, editing.id, i))
            st.caption("Replaced image keeps the same block.")


def _set_image(studio, block_id, image_id: str) -> None:
    blk = studio.block(block_id)
    if blk is not None:
        blk.payload["image_id"] = image_id


# ---------------------------------------------------------------- theme tab
def _theme_tab(shell, reports, report_id, studio) -> None:
    st.caption("Chart rendering theme (reuses the visualization themes).")
    themes = getattr(shell.platform, "themes", None) if shell.platform else None
    ids = []
    if themes is not None:
        try:
            ids = list(themes.ids())
        except Exception:
            ids = []
    current = _chart_theme(studio)
    if ids:
        choice = st.selectbox("Theme", ids, index=ids.index(current) if current in ids else 0,
                              key="th_choice")
        if st.button("Apply theme", key="th_apply"):
            _apply(reports, report_id, shell, lambda s, c=choice: _set_meta(s, "chart_theme_id", c))
            st.session_state.pop(f"_studio_charts::{report_id}", None)  # invalidate chart cache
    else:
        st.caption("No visualization themes available.")


def _chart_theme(studio) -> str:
    return (studio.document.meta or {}).get("chart_theme_id", "opta_light")


def _set_meta(studio, key: str, value: Any) -> None:
    meta = dict(studio.document.meta or {})
    meta[key] = value
    studio.document.meta = meta


# ---------------------------------------------------------------- apply / history / undo
def _apply(reports, report_id, shell, mutate: Callable, *, push: bool = True) -> None:
    """Persist one edit through the reused autosave path, recording an undo
    snapshot first. Selection stays; the page reruns to reflect the change."""
    try:
        if push:
            current = reports.document(report_id)
            if current is not None:
                history.record(report_id, current.to_dict())
        reports.update_studio(shell.user, report_id, mutate)
        st.rerun()
    except Exception as exc:
        st.error(str(exc))


def _undo(shell, reports, report_id) -> None:
    current = reports.document(report_id)
    snap = history.undo(report_id, current.to_dict() if current else {})
    if snap is not None:
        _restore(shell, reports, report_id, snap)


def _redo(shell, reports, report_id) -> None:
    current = reports.document(report_id)
    snap = history.redo(report_id, current.to_dict() if current else {})
    if snap is not None:
        _restore(shell, reports, report_id, snap)


def _restore(shell, reports, report_id, snapshot: dict) -> None:
    from fap.reports.models import ReportDocument
    try:
        reports.save_document(shell.user, report_id, ReportDocument.from_dict(snapshot))
        st.session_state.pop(f"_studio_charts::{report_id}", None)
        st.rerun()
    except Exception as exc:
        st.error(str(exc))


# ---------------------------------------------------------------- selection (ephemeral UI)
def _selection() -> set[str]:
    return st.session_state.setdefault(_SEL, set())


def _select_only(block_id: str | None) -> None:
    st.session_state[_SEL] = {block_id} if block_id else set()
    st.rerun()


# ---------------------------------------------------------------- theme colors
def _theme_colors() -> dict[str, str]:
    """Editor chrome colors from the application palette - never hardcoded."""
    try:
        from fap.theme import DEFAULT_PALETTE, resolve_mode
        mode = resolve_mode(st.session_state.get("_theme_mode"))
        if mode == "auto":
            mode = "light"
        s = DEFAULT_PALETTE.surface_for(mode)
        return {"bg": s.bg, "surface": s.surface, "surface_alt": s.surface_alt,
                "border": s.border, "text": s.text, "muted": s.text_muted,
                "accent": DEFAULT_PALETTE.primary}
    except Exception:
        return {"bg": "#eef1f6", "surface": "#ffffff", "surface_alt": "#f4f6fa",
                "border": "#e2e8f0", "text": "#16181d", "muted": "#5b6472",
                "accent": "#2563EB"}
