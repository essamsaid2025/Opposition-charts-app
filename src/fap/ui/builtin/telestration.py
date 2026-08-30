"""Telestration page — draw analysis annotations (arrows, spotlights, captions, lines) over an
uploaded match photo/frame and download the result as PNG/PDF, in the style of live-analysis
overlays (LiveTag-style).

This page is a SECOND, focused consumer of the Tactical Board engine (``fap.tactical``). It does
NOT fork or rewrite any of it: the same JS canvas component, the same command seam
(``apply_command``), the same renderer (``board_svg`` / ``board_pitch_svg``) and the same export
service (``TacticalService``) are reused. The only differences from the Tactical Board page are:

* the board's ``pitch.kind`` is ``"image"`` and the photo lives in ``board.meta["bg_image"]`` (a
  data URL), so the renderer paints the photo as the background and every annotation sits on top;
* the canvas runs in ``mode="telestration"`` (a board_state flag) which hides the tactical-only
  chrome (players / formations / frame timeline) and reveals the Spotlight tool;
* the drawing tools are seeded with telestration presets (white press arrows, a glowing player
  spotlight, outlined captions) via ``board_state["tool_defaults"]``.

Everything is additive: the Tactical Board page and the engine's byte-for-byte behaviour for
non-image boards are untouched. Persistence uses a distinct preset kind (``telestration_board``)
so telestration boards never mix with tactical boards.
"""
from __future__ import annotations

import base64
import io

import streamlit as st

from fap.core.plugin import PluginInfo
from fap.identity.roles import Role
from fap.tactical import (
    Board, History, TacticalService, apply_command, board_svg, new_board,
)
from fap.tactical.ops import apply_command as _apply_command
from fap.tactical.render import DEFAULT_COLORS, board_pitch_svg
from fap.theme import components as C
from fap.ui.builtin.tactical_canvas import parse_result, tactical_canvas
from fap.ui.page import Page, page_registry

# session keys (own namespace so this page never collides with the Tactical Board's ``_tb_*``)
TL_BOARD = "_tl_board"
TL_HIST = "_tl_hist"
TL_SEL = "_tl_sel"
TL_MULTI = "_tl_multisel"
TL_CANVAS_TS = "_tl_canvas_ts"
TL_MODEL_REV = "_tl_model_rev"

# Telestration drawing presets, seeded into the component's sticky tool defaults. White, thick
# press arrows + a glowing player spotlight + outlined captions match the broadcast-analysis look.
# ``arrowhead: filled_triangle`` routes arrows through the renderer's custom-head path so the
# thick white body + big head export exactly (see render._vector_custom / export_render).
_TELE_TOOL_DEFAULTS: dict[str, dict] = {
    "arrow": {"variant": "", "curvature": 0.0, "label": "", "color": "#ffffff",
              "arrowhead": "filled_triangle", "arrowhead_size": 1.5, "stroke_width": 9.0},
    "curved_arrow": {"variant": "", "curvature": 0.3, "label": "", "color": "#ffffff",
                     "arrowhead": "filled_triangle", "arrowhead_size": 1.5, "stroke_width": 9.0},
    "dashed_arrow": {"variant": "", "curvature": 0.0, "label": "", "color": "#ffd23f",
                     "arrowhead": "filled_triangle", "arrowhead_size": 1.3, "stroke_width": 6.0},
    "line": {"variant": "", "curvature": 0.0, "label": "", "color": "#111318", "stroke_width": 8.0},
    "spotlight": {"spotlight": True, "shape": "ellipse", "filled": True, "color": "#ffd23f",
                  "opacity": 0.32, "stroke_width": 5.0, "w": 9.0, "h": 5.0},
    "circle": {"color": "#ffd23f", "filled": False, "opacity": 0.28, "stroke_width": 4.0,
               "shape": "ellipse"},
    "text": {"text": "Label", "size": 22, "color": "#ffffff", "outline": "#0c0e12",
             "outline_width": 3.5},
}


# ---------------------------------------------------------------- background image
def _encode_bg(data: bytes, mime: str) -> tuple[str, float]:
    """Turn uploaded image bytes into ``(data_url, aspect)`` where ``aspect = width/height``. The
    image is downscaled (cap 1600px wide, JPEG q82) so the data URL stays small — a multi-MB photo
    re-sent to the canvas on every rerun would choke the component and make drawing feel dead — but
    its aspect ratio is KEPT (no crop), so the render plane matches the photo. Falls back to the raw
    bytes + a 1.544 (1050/680) aspect if PIL is unavailable."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data)).convert("RGB")
        iw, ih = img.size
        aspect = (iw / ih) if ih else (1050.0 / 680.0)
        if iw > 1600:
            img = img.resize((1600, max(1, round(1600 / aspect))), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=82, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii"), aspect
    except Exception:
        return (f"data:{mime};base64," + base64.b64encode(data).decode("ascii"), 1050.0 / 680.0)


# ---------------------------------------------------------------- colours
def _tele_colors() -> dict[str, str]:
    """Palette for a telestration board. Grass roles are irrelevant (the pitch is a photo); text
    and lines default to white so a freshly placed caption/line reads over most footage, and the
    accent is a warm spotlight yellow. Individual objects still carry their own colours."""
    return {**DEFAULT_COLORS, "bg": "#0b0d10", "text": "#ffffff", "line": "#ffffff",
            "accent": "#ffd23f", "zone": "#ffd23f"}


# ---------------------------------------------------------------- state
def _bump_model_rev() -> None:
    st.session_state[TL_MODEL_REV] = int(st.session_state.get(TL_MODEL_REV, 0)) + 1


def _state() -> tuple[Board, History]:
    if TL_BOARD not in st.session_state:
        st.session_state[TL_BOARD] = new_board("Telestration", pitch_kind="image")
        st.session_state[TL_HIST] = History()
        st.session_state[TL_SEL] = None
    return st.session_state[TL_BOARD], st.session_state[TL_HIST]


def _new_board() -> None:
    st.session_state[TL_BOARD] = new_board("Telestration", pitch_kind="image")
    st.session_state[TL_HIST] = History()
    st.session_state[TL_SEL] = None
    st.session_state.pop(TL_MULTI, None)
    _bump_model_rev()


def _load(board: Board) -> None:
    if board.pitch.kind != "image":                      # a loaded board is always a telestration board
        board.pitch.kind = "image"
    st.session_state[TL_BOARD] = board
    st.session_state[TL_HIST] = History()
    st.session_state[TL_SEL] = None
    st.session_state.pop(TL_MULTI, None)
    _bump_model_rev()


def _undo() -> None:
    b = st.session_state[TL_HIST].undo(st.session_state[TL_BOARD])
    if b is not None:
        st.session_state[TL_BOARD] = b
        st.session_state[TL_SEL] = None
        st.session_state.pop(TL_MULTI, None)
        _bump_model_rev()


def _redo() -> None:
    b = st.session_state[TL_HIST].redo(st.session_state[TL_BOARD])
    if b is not None:
        st.session_state[TL_BOARD] = b
        st.session_state.pop(TL_MULTI, None)
        _bump_model_rev()


# ---------------------------------------------------------------- canvas metadata
def _canvas_objects(board: Board) -> list[dict]:
    """Lightweight per-object metadata the canvas uses to place endpoint / resize handles and to
    respect locks (same shape the Tactical Board page builds)."""
    fr = board.frame(0)
    meta: list[dict] = []
    for o in fr.objects:
        m = {"id": o.id, "type": o.type, "x": o.x, "y": o.y, "locked": o.locked,
             "rotation": float(o.rotation), "props": dict(o.props or {})}
        if o.type in ("arrow", "curved_arrow", "dashed_arrow", "line"):
            m["x2"] = float(o.props.get("x2", o.x + 12))
            m["y2"] = float(o.props.get("y2", o.y))
        if o.type == "curved_arrow":
            m["curvature"] = float(o.props.get("curvature", 0.3))
        if o.type in ("zone", "highlight", "shape", "circle"):
            m["w"] = float(o.props.get("w", 20))
            m["h"] = float(o.props.get("h", 16))
        meta.append(m)
    return meta


# ---------------------------------------------------------------- canvas intent
def _handle_action(act: dict) -> bool:
    """Apply an in-board UI action. Telestration only needs ``sync_board`` (the client is
    authoritative for the current frame's annotations) plus the plain ``new`` / ``grid``; the
    tactical-only actions (formation / template / frames / orientation) are inert here because the
    component hides that chrome in telestration mode, but we ignore them defensively."""
    from fap.tactical.models import TacticalObject, new_id
    name = act.get("name")
    board = st.session_state[TL_BOARD]
    if name == "sync_board":
        fr = board.frame(0)
        st.session_state[TL_HIST].record(board)
        fr.objects = [TacticalObject(
            id=(str(o.get("id")) or new_id()), type=str(o.get("type", "arrow")),
            x=float(o.get("x", 50.0)), y=float(o.get("y", 50.0)),
            rotation=float(o.get("rotation", 0.0)), scale=float(o.get("scale", 1.0)),
            z=int(o.get("z", 0)), props=dict(o.get("props") or {}))
            for o in (act.get("objects") or [])]
        board.touch()
        return True
    if name == "new":
        _new_board()
        return True
    return False


def _commit_canvas(result: dict, can_edit: bool) -> bool:
    """Apply one validated canvas intent batch to the authoritative board. Deduplicated by the
    browser's monotonic ``ts``. Mirrors the Tactical Board page's commit seam (trimmed to what
    telestration uses). Does not rerun — the caller decides."""
    ts = result.get("ts")
    if ts is None or ts == st.session_state.get(TL_CANVAS_TS):
        return False
    st.session_state[TL_CANVAS_TS] = ts

    if result.get("undo") and can_edit:
        _undo(); return True
    if result.get("redo") and can_edit:
        _redo(); return True
    if result.get("action") and can_edit:
        return _handle_action(result["action"])

    changed = False
    commands = result.get("commands") or []
    if commands and can_edit:
        board, hist = st.session_state[TL_BOARD], st.session_state[TL_HIST]
        hist.record(board)                               # one undo step per interaction batch
        last_id = None
        for cmd in commands:
            cmd.setdefault("frame", 0)
            res = _apply_command(board, cmd)
            if cmd.get("op") in ("add_object", "duplicate_object") and res.get("id"):
                last_id = res["id"]
        if last_id:
            st.session_state[TL_SEL] = last_id
            st.session_state[TL_MULTI] = [last_id]
        changed = True

    sel = result.get("select", "__keep__")
    if sel != "__keep__":
        if isinstance(sel, list):
            st.session_state[TL_MULTI] = list(sel)
            st.session_state[TL_SEL] = sel[-1] if sel else None
        else:
            st.session_state[TL_SEL] = sel
            st.session_state[TL_MULTI] = [sel] if sel else []
        changed = True
    return changed


def _consume_canvas_intent(can_edit: bool) -> None:
    """Apply any pending canvas intent stored under the component key BEFORE the board is
    rendered this run, so the SVG we hand back is already at the dropped/drawn state (the same
    'no snap-back' fix the Tactical Board page uses). ``parse_result`` is the trust boundary."""
    raw = st.session_state.get("tl_canvas")
    result = parse_result(raw) if raw is not None else None
    if result is not None:
        _commit_canvas(result, can_edit)


# ---------------------------------------------------------------- page
@page_registry.register
class TelestrationPage(Page):
    info = PluginInfo(id="telestration", name="Telestration", category="page")
    section = "Analysis"
    icon = "edit"
    order = 31
    min_role = Role.READ_ONLY

    def render(self, shell) -> None:
        board, hist = _state()
        svc = TacticalService(getattr(shell, "wm", None))
        can_edit = shell.user.role >= Role.PERFORMANCE_ANALYST

        # commit any drag/draw the canvas reported last interaction BEFORE we render
        _consume_canvas_intent(can_edit)

        st.markdown("### Telestration")
        st.caption("Upload a match photo or video frame, then draw press arrows, player "
                   "spotlights, lines and captions on top — and download it as an image.")
        self._background_control(board, can_edit)
        self._board_view(shell, board, can_edit)
        with st.expander("File — save, load & download", expanded=False):
            self._file_controls(shell, svc, board, can_edit)

    # ---- background image ------------------------------------------------
    def _background_control(self, board: Board, can_edit: bool) -> None:
        has_bg = bool((board.meta or {}).get("bg_image"))
        cols = st.columns([3, 1])
        up = cols[0].file_uploader(
            "Background image", type=["png", "jpg", "jpeg", "webp"],
            key="tl_bg_upload", disabled=not can_edit,
            help="The photo/frame you draw on. JPG/PNG. Replaces the current background.")
        if up is not None and can_edit:
            data = up.getvalue()
            sig = f"{up.name}:{len(data)}"
            if st.session_state.get("_tl_bg_sig") != sig:      # only ingest each file once
                url, aspect = _encode_bg(data, up.type or "image/png")
                board.meta["bg_image"] = url
                board.meta["bg_aspect"] = aspect               # render plane matches the photo shape
                board.pitch.kind = "image"
                board.touch()
                st.session_state["_tl_bg_sig"] = sig
                _bump_model_rev()
                st.rerun()
        if has_bg and can_edit:
            if cols[1].button("Remove background", key="tl_bg_clear", use_container_width=True):
                board.meta.pop("bg_image", None)
                board.meta.pop("bg_aspect", None)
                board.touch()
                st.session_state.pop("_tl_bg_sig", None)
                _bump_model_rev()
                st.rerun()
        if not has_bg:
            C.render_alert("Upload a background image to start drawing on it.", "info")
        elif can_edit:
            st.caption("Pick a tool from the left rail (arrow · spotlight · line · text), then "
                       "**drag on the image** to draw. Press Esc to go back to Select.")

    # ---- interactive canvas ---------------------------------------------
    def _board_view(self, shell, board: Board, can_edit: bool) -> None:
        flash = st.session_state.pop("_tl_flash", "")
        if flash:
            C.render_alert(flash, "success")
        from fap.tactical.render import plane_height
        colors = _tele_colors()
        sel = st.session_state.get(TL_SEL)
        # Python owns the pitch (here: the background photo); the JS component renders + edits every
        # annotation and syncs the model back. board_pitch_svg embeds the photo via _pitch_svg.
        svg = board_pitch_svg(board, colors=colors, grid=False)
        plane_h = plane_height(board)                        # canvas coord height = photo-matched plane

        import hashlib as _hashlib
        model_rev = int(st.session_state.get(TL_MODEL_REV, 0))
        fr = board.frame(0)
        model = [{"id": o.id, "type": o.type, "x": o.x, "y": o.y, "rotation": o.rotation,
                  "scale": o.scale, "z": o.z, "props": dict(o.props or {})} for o in fr.objects]
        _svg_sig = _hashlib.md5(svg.encode("utf-8")).hexdigest()[:16]
        nonce = f"{_svg_sig}|{int(bool(can_edit))}|{model_rev}"
        board_state = {
            "frames": [{"name": "Frame 1"}], "frame_index": 0, "grid": False,
            "orientation": "horizontal", "theme": "",
            "formations": [], "templates": [],
            "colors": {"home": "#e23b3b", "away": "#2f6fd6",
                       "grass": colors.get("grass", "#1f7a3f"), "line": colors.get("line", "#ffffff")},
            "model": model, "model_rev": model_rev,
            "mode": "telestration",                      # hides tactical chrome, shows Spotlight tool
            "tool_defaults": _TELE_TOOL_DEFAULTS,        # seeds the sticky drawing presets
            "plane_h": plane_h,                          # SVG viewBox height → correct coord mapping
        }
        rendered, result = tactical_canvas(
            svg, _canvas_objects(board), key="tl_canvas", colors=colors,
            palette=[], selected_id=sel, selected_ids=([sel] if sel else []),
            snap=0.0, editable=can_edit, nonce=nonce, draw_tool=None,
            board_state=board_state)
        if not rendered:
            full = board_svg(board, 0, colors=colors)
            st.markdown(f'<div class="tb-board">{full}</div>', unsafe_allow_html=True)
            st.caption("Interactive canvas unavailable — the static preview is shown above.")
        elif result is not None and _commit_canvas(result, can_edit):
            st.rerun()

    # ---- file (name / save / load / export) -----------------------------
    def _file_controls(self, shell, svc, board: Board, can_edit: bool) -> None:
        row = st.columns([3, 1])
        nm = row[0].text_input("Name", value=board.name, key="tl_name")
        if nm != board.name and can_edit:
            board.name = nm
            board.touch()
        if can_edit and row[1].button("Save", key="tl_save", use_container_width=True):
            try:
                svc.save_telestration(shell.user, board, name=board.name)
                st.session_state["_tl_flash"] = f"Saved '{board.name}'."
            except Exception as exc:                     # pragma: no cover - storage failure surfaced to UI
                st.session_state["_tl_flash"] = f"Save failed: {exc}"
            st.rerun()

        # export: PNG first (the telestration deliverable), then PDF/SVG when available
        fmts = svc.export_formats()
        fmts = [f for f in ("png", "pdf", "svg") if f in fmts] or fmts
        ec = st.columns([1, 1])
        fmt = ec[0].selectbox("Download format", fmts, key="tl_fmt")
        sig = f"{board.updated_at}|{fmt}"
        prep = st.session_state.get("_tl_export_cache")
        if prep and prep.get("sig") == sig:
            ec[1].download_button("Download", data=prep["data"], file_name=prep["fname"],
                                  mime=prep["mime"], key="tl_dl", use_container_width=True)
        elif ec[1].button("Prepare download", key="tl_prep", use_container_width=True):
            data, mime, fname = svc.export(board, 0, fmt=fmt, colors=_tele_colors())
            st.session_state["_tl_export_cache"] = {"sig": sig, "data": data, "mime": mime,
                                                    "fname": fname}
            st.rerun()

        st.divider()
        st.caption("Saved telestrations")
        c1, c2 = st.columns([3, 1])
        if can_edit and c2.button("New", key="tl_new", use_container_width=True):
            _new_board(); st.rerun()
        boards = svc.list_telestration(shell.user)
        if not boards:
            st.caption("No saved telestrations yet.")
        for pr in boards:
            bcols = st.columns([4, 1])
            bcols[0].button(getattr(pr, "name", "telestration"), key=f"tlopen_{pr.id}",
                            use_container_width=True, on_click=lambda p=pr: _load(svc.board_of(p)))
            if can_edit:
                bcols[1].button("Delete", key=f"tldel_{pr.id}",
                                on_click=lambda pid=pr.id: svc.delete(shell.user, pid))
