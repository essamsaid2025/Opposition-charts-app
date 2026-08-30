"""Telestration page — draw professional analysis annotations (press arrows, player spotlights,
lines, boxes, freehand, captions) over an uploaded match photo/frame and download the result as a
PNG, in the style of live-analysis overlays.

Unlike the Tactical Board, this is a PURPOSE-BUILT tool: a dedicated HTML5 Canvas editor
(``fap.ui.builtin.telestration_canvas``) that owns the whole interaction — pick a tool, drag on the
image, done — and composites the download PNG client-side at the photo's native resolution, so what
you draw is exactly what you get. Python only persists the annotation list and serves the exported
bytes as a download. The document is a plain dict ``{name, image, anns}`` stored as a
WorkspaceManager preset (kind ``telestration_project``) — no tactical Board involved.
"""
from __future__ import annotations

import base64
import binascii
import io

import streamlit as st

from fap.core.plugin import PluginInfo
from fap.identity.roles import Role
from fap.theme import components as C
from fap.ui.builtin.telestration_canvas import (
    clean_anns, clean_persp, parse_result, telestration_canvas,
)
from fap.ui.page import Page, page_registry

TL_DOC = "_tl_doc"                 # {"name", "image" (data URL), "anns": [...]}
TL_LOAD_NONCE = "_tl_load_nonce"   # bump to make the canvas ADOPT doc["anns"] (mount / new / open)
TL_CANVAS_TS = "_tl_canvas_ts"     # last processed component value (dedup)
TL_KIND = "telestration_project"


# ---------------------------------------------------------------- background image
def _encode_bg(data: bytes, mime: str) -> str:
    """Downscale an uploaded image to a compact data URL (cap 1600px wide, JPEG q82) so it stays
    small and fast; the canvas uses the image's own aspect ratio, so nothing is cropped. Falls back
    to the raw bytes when PIL is unavailable."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data)).convert("RGB")
        iw, ih = img.size
        if iw > 1600 and ih:
            img = img.resize((1600, max(1, round(1600 * ih / iw))), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=82, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")


# ---------------------------------------------------------------- state
def _doc() -> dict:
    if TL_DOC not in st.session_state:
        st.session_state[TL_DOC] = {"name": "Telestration", "image": "", "anns": []}
        st.session_state[TL_LOAD_NONCE] = 1
    st.session_state.setdefault(TL_LOAD_NONCE, 1)
    return st.session_state[TL_DOC]


def _bump_load() -> None:
    st.session_state[TL_LOAD_NONCE] = int(st.session_state.get(TL_LOAD_NONCE, 1)) + 1


def _new_doc() -> None:
    st.session_state[TL_DOC] = {"name": "Telestration", "image": "", "anns": []}
    st.session_state.pop("_tl_bg_sig", None)
    st.session_state.pop("_tl_export", None)
    _bump_load()


def _consume_canvas() -> None:
    """Read the component's latest value and fold it into the document (annotations) / export
    cache. Deduped by the browser's monotonic ``ts`` so a re-delivered value is applied once."""
    raw = st.session_state.get("tl_canvas")
    res = parse_result(raw) if raw is not None else None
    if res is None:
        return
    if res.get("ts") == st.session_state.get(TL_CANVAS_TS):
        return
    st.session_state[TL_CANVAS_TS] = res.get("ts")
    doc = _doc()
    doc["anns"] = res.get("anns") or []                  # keep Python's copy current for Save
    doc["persp"] = res.get("persp")                      # perspective calibration (or None)
    if res.get("kind") == "export" and res.get("png"):
        header, _, b64 = res["png"].partition(",")
        try:
            st.session_state["_tl_export"] = base64.b64decode(b64)
        except (binascii.Error, ValueError):
            st.session_state["_tl_export"] = None


# ---------------------------------------------------------------- persistence (WorkspaceManager)
def _wm(shell):
    return getattr(shell, "wm", None)


def _save(shell, doc: dict) -> str:
    wm = _wm(shell)
    if wm is None:
        return "Saving is unavailable here."
    try:
        wm.save_preset(shell.user, kind=TL_KIND, name=doc.get("name") or "Telestration",
                       document={"name": doc.get("name"), "image": doc.get("image", ""),
                                 "anns": clean_anns(doc.get("anns")),
                                 "persp": clean_persp(doc.get("persp"))})
        return f"Saved '{doc.get('name')}'."
    except Exception as exc:                              # pragma: no cover - surfaced to the UI
        return f"Save failed: {exc}"


def _list(shell) -> list:
    wm = _wm(shell)
    if wm is None:
        return []
    try:
        return wm.list_presets(shell.user, kind=TL_KIND)
    except Exception:
        return []


# ---------------------------------------------------------------- page
@page_registry.register
class TelestrationPage(Page):
    info = PluginInfo(id="telestration", name="Telestration", category="page")
    section = "Analysis"
    icon = "edit"
    order = 31
    min_role = Role.READ_ONLY

    def render(self, shell) -> None:
        _consume_canvas()
        doc = _doc()
        can_edit = shell.user.role >= Role.PERFORMANCE_ANALYST

        st.markdown("### Telestration")
        st.caption("Upload a match photo or video frame, pick a tool, and draw press arrows, "
                   "player spotlights, lines and captions on top — then download it as an image.")
        self._background_control(doc, can_edit)
        self._canvas(doc, can_edit)
        with st.expander("Save & open projects", expanded=False):
            self._projects(shell, doc, can_edit)

    # ---- background ------------------------------------------------------
    def _background_control(self, doc: dict, can_edit: bool) -> None:
        cols = st.columns([3, 1])
        up = cols[0].file_uploader("Background image", type=["png", "jpg", "jpeg", "webp"],
                                   key="tl_bg_upload", disabled=not can_edit,
                                   help="The photo/frame you draw on. JPG/PNG.")
        if up is not None and can_edit:
            data = up.getvalue()
            sig = f"{up.name}:{len(data)}"
            if st.session_state.get("_tl_bg_sig") != sig:      # ingest each file once
                doc["image"] = _encode_bg(data, up.type or "image/png")
                doc["anns"] = []                               # fresh image → fresh canvas
                st.session_state["_tl_bg_sig"] = sig
                st.session_state.pop("_tl_export", None)
                _bump_load()
                st.rerun()
        if doc.get("image") and can_edit:
            if cols[1].button("Remove image", key="tl_bg_clear", use_container_width=True):
                doc["image"] = ""; doc["anns"] = []
                st.session_state.pop("_tl_bg_sig", None)
                st.session_state.pop("_tl_export", None)
                _bump_load()
                st.rerun()
        if not doc.get("image"):
            C.render_alert("Upload a background image to start drawing on it.", "info")

    # ---- canvas ----------------------------------------------------------
    def _canvas(self, doc: dict, can_edit: bool) -> None:
        rendered, result = telestration_canvas(
            image=doc.get("image", ""), anns=doc.get("anns", []),
            persp=doc.get("persp"),
            load_nonce=int(st.session_state.get(TL_LOAD_NONCE, 1)),
            editable=can_edit, key="tl_canvas")
        if not rendered:
            C.render_alert("The drawing canvas could not load in this browser.", "warning")
            return
        # a fresh value delivered on THIS run (rare; usually consumed at the top) — fold it in
        if result is not None and result.get("ts") != st.session_state.get(TL_CANVAS_TS):
            _consume_canvas()
        # download button appears once the canvas has sent an exported PNG
        png = st.session_state.get("_tl_export")
        if png:
            fname = "".join(c if c.isalnum() or c in " -_" else "_"
                            for c in (doc.get("name") or "telestration")).strip() or "telestration"
            st.download_button("⬇ Download PNG", data=png, file_name=f"{fname}.png",
                               mime="image/png", key="tl_dl", use_container_width=False)
        elif doc.get("image"):
            st.caption("Draw your annotations, then press **Download PNG** in the toolbar to "
                       "prepare the image — a download button will appear here.")

    # ---- projects (save / open / delete) ---------------------------------
    def _projects(self, shell, doc: dict, can_edit: bool) -> None:
        flash = st.session_state.pop("_tl_flash", "")
        if flash:
            C.render_alert(flash, "success")
        row = st.columns([3, 1, 1])
        nm = row[0].text_input("Project name", value=doc.get("name", ""), key="tl_name")
        if nm != doc.get("name"):
            doc["name"] = nm
        if can_edit and row[1].button("Save", key="tl_save", use_container_width=True):
            st.session_state["_tl_flash"] = _save(shell, doc)
            st.rerun()
        if can_edit and row[2].button("New", key="tl_new", use_container_width=True):
            _new_doc(); st.rerun()

        st.caption("Saved projects")
        projects = _list(shell)
        if not projects:
            st.caption("No saved projects yet." if _wm(shell) is not None
                       else "Saving is unavailable in this view.")
        for pr in projects:
            c = st.columns([4, 1])
            if c[0].button(getattr(pr, "name", "project"), key=f"tlopen_{pr.id}",
                           use_container_width=True):
                self._open(pr)
                st.rerun()
            if can_edit and c[1].button("Delete", key=f"tldel_{pr.id}"):
                wm = _wm(shell)
                if wm is not None:
                    try:
                        wm.delete_preset(shell.user, pr.id)
                    except Exception:
                        pass
                st.rerun()

    def _open(self, preset) -> None:
        d = getattr(preset, "document", None) or {}
        st.session_state[TL_DOC] = {"name": d.get("name") or getattr(preset, "name", "Telestration"),
                                    "image": d.get("image", ""), "anns": clean_anns(d.get("anns")),
                                    "persp": clean_persp(d.get("persp"))}
        st.session_state.pop("_tl_bg_sig", None)
        st.session_state.pop("_tl_export", None)
        _bump_load()
