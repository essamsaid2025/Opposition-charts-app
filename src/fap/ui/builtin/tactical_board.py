"""Tactical Board page (Phase 14) - the interaction layer over the tactical CORE.

A professional coaching workspace: Toolbar / Left Library / Center Board / Right
Properties / Bottom Timeline. It holds NO domain logic - every change is a JSON
command handed to ``fap.tactical.ops.apply_command`` (the same seam the Phase 15 JS
drag-and-drop canvas will use). Board + history live in session_state; persistence
and export go through ``TacticalService`` (WorkspaceManager). Styling is injected
here (no edit to theme/css.py) using the platform's theme tokens.
"""
from __future__ import annotations

import streamlit as st

from fap.core.plugin import PluginInfo
from fap.identity.roles import Role
from fap.tactical import (
    Board, History, TacticalService, apply_command, board_svg, builtin_names,
    builtin_template, new_board,
)
from fap.tactical.ops import apply_command as _apply_command
from fap.tactical.ops import default_props
from fap.tactical.render import DEFAULT_COLORS
from fap.theme import components as C
from fap.ui.builtin.tactical_canvas import parse_result, tactical_canvas
from fap.ui.nav import icon_css
from fap.ui.page import Page, page_registry

TB_BOARD = "_tb_board"
TB_HIST = "_tb_hist"
TB_FRAME = "_tb_frame"
TB_SEL = "_tb_sel"
TB_GRID = "_tb_grid"
TB_SNAP = "_tb_snap"
TB_CANVAS_TS = "_tb_canvas_ts"    # last processed canvas action (dedups Streamlit reruns)
TB_PROP_FOR = "_tb_prop_for"      # object id the Properties widgets are currently synced to

# Every Properties widget that follows the "read the widget, write it back to the model if
# it differs" pattern. Those widgets keep their OWN value in session_state, so after the
# canvas moves/adds/selects an object the widgets hold STALE values and would overwrite the
# model (this was the drag "snap-back": the X/Y sliders wrote the old position back over the
# drop). We pop these whenever the canvas changes state or the selected object changes, which
# forces every widget to re-initialise from the current model object. (tb_selbox handled too.)
_PROP_VALUE_KEYS: tuple[str, ...] = (
    "tb_x", "tb_y", "tb_rot", "tb_sca", "tb_pnum", "tb_pteam", "tb_pname", "tb_pcap", "tb_pgk",
    "tb_ptext", "tb_psize", "tb_px2", "tb_py2", "tb_pcurv", "tb_pw", "tb_ph", "tb_pop",
)


def _resync_properties() -> None:
    """Drop the persistent Properties widget state so those widgets re-read the model."""
    for k in ("tb_selbox", *_PROP_VALUE_KEYS):
        st.session_state.pop(k, None)

_LIBRARY = [
    ("Players", "players", [("Home player", "player", {"team": "home"}),
                            ("Away player", "player", {"team": "away"}),
                            ("Goalkeeper", "player", {"team": "home", "goalkeeper": True})]),
    ("Balls", "target", [("Ball", "ball", {})]),
    ("Cones", "flag", [("Cone", "cone", {})]),
    ("Goals", "shield", [("Goal", "goal", {})]),
    ("Mannequins", "user", [("Mannequin", "mannequin", {})]),
    ("Arrows", "arrow-right", [("Arrow", "arrow", {}), ("Curved arrow", "curved_arrow", {}),
                               ("Dashed arrow", "dashed_arrow", {})]),
    ("Lines", "sliders", [("Line", "line", {})]),
    ("Zones", "grid", [("Zone", "zone", {}), ("Highlight", "highlight", {"shape": "ellipse"})]),
    ("Text", "edit", [("Text", "text", {"text": "Text"})]),
    ("Shapes", "layers", [("Shape", "shape", {})]),
]


# ---------------------------------------------------------------- session state
def _state() -> tuple[Board, History]:
    if TB_BOARD not in st.session_state:
        st.session_state[TB_BOARD] = new_board("Untitled Board")
        st.session_state[TB_HIST] = History()
        st.session_state[TB_FRAME] = 0
        st.session_state[TB_SEL] = None
    st.session_state.setdefault(TB_GRID, False)
    st.session_state.setdefault(TB_SNAP, False)
    return st.session_state[TB_BOARD], st.session_state[TB_HIST]


def _frame_index() -> int:
    board = st.session_state[TB_BOARD]
    return max(0, min(len(board.frames) - 1, int(st.session_state.get(TB_FRAME, 0))))


# ---------------------------------------------------------------- command callbacks
def _apply(cmd: dict, *, record: bool = True) -> None:
    board, hist = st.session_state[TB_BOARD], st.session_state[TB_HIST]
    if record:
        hist.record(board)
    res = apply_command(board, cmd)
    if cmd.get("op") in ("add_object", "duplicate_object") and res.get("id"):
        st.session_state[TB_SEL] = res["id"]
    if cmd.get("op") == "add_frame":
        st.session_state[TB_FRAME] = res.get("index", _frame_index())
    if cmd.get("op") == "delete_frame":
        st.session_state[TB_FRAME] = max(0, _frame_index() - 1)


def _add(obj_type: str, extra: dict) -> None:
    props = default_props(obj_type)
    props.update(extra)
    _apply({"op": "add_object", "frame": _frame_index(), "type": obj_type,
            "x": 50.0, "y": 50.0, "props": props})


def _undo() -> None:
    b = st.session_state[TB_HIST].undo(st.session_state[TB_BOARD])
    if b is not None:
        st.session_state[TB_BOARD] = b
        st.session_state[TB_SEL] = None


def _redo() -> None:
    b = st.session_state[TB_HIST].redo(st.session_state[TB_BOARD])
    if b is not None:
        st.session_state[TB_BOARD] = b


def _new_board() -> None:
    st.session_state[TB_BOARD] = new_board("Untitled Board")
    st.session_state[TB_HIST] = History()
    st.session_state[TB_FRAME] = 0
    st.session_state[TB_SEL] = None


def _load(board: Board) -> None:
    st.session_state[TB_BOARD] = board
    st.session_state[TB_HIST] = History()
    st.session_state[TB_FRAME] = 0
    st.session_state[TB_SEL] = None


def _toggle(flag: str) -> None:
    st.session_state[flag] = not st.session_state.get(flag, False)


def _set_frame(i: int) -> None:
    st.session_state[TB_FRAME] = i
    st.session_state[TB_SEL] = None


# ---------------------------------------------------------------- canvas (Phase 15)
# The JS canvas emits the SAME JSON commands the model already understands. We feed
# them straight through ``apply_command`` (one undo step per interaction batch) - no
# business logic lives in the browser. Selection is UI-only session state.
def _canvas_colors() -> dict[str, str]:
    return dict(DEFAULT_COLORS)


def _canvas_palette() -> list[dict]:
    """Flatten the object Library into draggable chips (data only - the drag simply
    emits an ``add_object`` command at the drop point)."""
    colors = _canvas_colors()
    out: list[dict] = []
    for _title, _ic, items in _LIBRARY:
        for label, otype, extra in items:
            if otype == "player":
                col = colors["away"] if extra.get("team") == "away" else colors["home"]
            elif otype == "ball":
                col = colors["ball"]
            elif otype == "cone":
                col = colors["cone"]
            elif otype in ("zone", "highlight", "shape"):
                col = colors["zone"]
            else:
                col = colors["accent"]
            out.append({"label": label, "type": otype, "props": extra, "color": col})
    return out


def _canvas_objects(board: Board) -> list[dict]:
    """Lightweight metadata the canvas uses to place endpoint handles / respect locks."""
    fr = board.frame(_frame_index())
    meta = []
    for o in fr.objects:
        m = {"id": o.id, "type": o.type, "x": o.x, "y": o.y, "locked": o.locked}
        if o.type in ("arrow", "curved_arrow", "dashed_arrow", "line"):
            m["x2"] = float(o.props.get("x2", o.x + 12))
            m["y2"] = float(o.props.get("y2", o.y))
        meta.append(m)
    return meta


def _commit_canvas(result: dict, can_edit: bool) -> bool:
    """Apply one validated canvas intent batch to the AUTHORITATIVE board. Returns True if
    anything changed. Deduplicated by the browser's monotonic ``ts`` (so a value Streamlit
    re-delivers on an unrelated rerun is ignored, and a non-idempotent add is never applied
    twice). Does NOT rerun — the caller decides."""
    ts = result.get("ts")
    if ts is None or ts == st.session_state.get(TB_CANVAS_TS):
        return False
    st.session_state[TB_CANVAS_TS] = ts
    commands = result.get("commands") or []
    sel = result.get("select", "__keep__")

    changed = False
    if commands and can_edit:
        board, hist = st.session_state[TB_BOARD], st.session_state[TB_HIST]
        hist.record(board)                       # one undo step for the whole interaction
        f = _frame_index()
        last_id = None
        for cmd in commands:
            cmd.setdefault("frame", f)
            res = _apply_command(board, cmd)
            if cmd.get("op") in ("add_object", "duplicate_object") and res.get("id"):
                last_id = res["id"]
        if last_id:
            st.session_state[TB_SEL] = last_id   # keep a freshly added piece selected
        changed = True

    if sel != "__keep__":
        st.session_state[TB_SEL] = sel
        changed = True
    if changed:
        # the canvas changed the board/selection — force every Properties widget to re-read
        # the model so a stale slider/field can't overwrite the drop on this same run
        _resync_properties()
    return changed


def _consume_canvas_intent(can_edit: bool) -> None:
    """Apply any pending canvas intent BEFORE the board is rendered this run.

    This is the fix for drops "snapping back": the JS canvas stores its reported intent in
    ``st.session_state["tb_canvas"]`` (the component key). Reading + committing it here, at
    the very top of the page run, means the board SVG we later hand back to the canvas is
    ALREADY at the dropped position — there is no stale render that repaints the piece at
    its old spot. ``parse_result`` is the trust boundary. Runs before Properties too, so the
    whole page reflects the drop in a single run (no extra ``st.rerun``)."""
    raw = st.session_state.get("tb_canvas")
    result = parse_result(raw) if raw is not None else None
    if result is not None:
        _commit_canvas(result, can_edit)


@page_registry.register
class TacticalBoardPage(Page):
    info = PluginInfo(id="tactical_board", name="Tactical Board", category="page")
    section = "Analysis"
    icon = "setpiece"
    order = 30
    min_role = Role.READ_ONLY

    # ------------------------------------------------------------ entry
    def render(self, shell) -> None:
        self._inject_css()
        board, hist = _state()
        svc = TacticalService(getattr(shell, "wm", None))
        can_edit = shell.user.role >= Role.PERFORMANCE_ANALYST

        # commit any drag/drop/add the canvas reported last interaction BEFORE we render,
        # so every panel (board + properties) reflects it in this same run
        _consume_canvas_intent(can_edit)

        C.render_section_title(
            "Tactical Board", eyebrow="Analysis", icon_name="setpiece",
            subtitle="Design routines, animate frames and share professional coaching boards.")

        self._toolbar(shell, svc, board, hist, can_edit)

        left, center, right = st.columns([2.3, 6.2, 2.6], gap="small")
        with left:
            self._library(can_edit)
            self._templates_and_saved(shell, svc, board, can_edit)
        with right:
            self._properties(board, can_edit)
        with center:
            self._board_view(board, can_edit)
        self._timeline(board, can_edit)

    # ------------------------------------------------------------ toolbar
    def _toolbar(self, shell, svc, board, hist, can_edit) -> None:
        with st.container(key="tb_toolbar"):
            cols = st.columns(12, gap="small")
            specs = [
                ("tb_undo", "refresh", "Undo", _undo, not hist.can_undo() or not can_edit),
                ("tb_redo", "refresh", "Redo", _redo, not hist.can_redo() or not can_edit),
                ("tb_new", "plus", "New board", _new_board, not can_edit),
                ("tb_dup", "layers", "Duplicate selection",
                 lambda: _apply({"op": "duplicate_object", "frame": _frame_index(),
                                 "id": st.session_state.get(TB_SEL) or ""}), not can_edit),
                ("tb_snap", "grid", "Snap to grid",
                 lambda: (_toggle(TB_SNAP), _apply({"op": "snap", "step": 5.0}) if st.session_state[TB_SNAP] else None), not can_edit),
                ("tb_grid", "grid", "Toggle grid", lambda: _toggle(TB_GRID), False),
                ("tb_lock", "shield", "Lock selection",
                 lambda: _apply({"op": "update_object", "frame": _frame_index(),
                                 "id": st.session_state.get(TB_SEL) or "", "locked": True,
                                 "force": True}, record=False), not can_edit),
            ]
            for col, (key, ic, tip, cb, disabled) in zip(cols, specs):
                with col:
                    st.button("", key=key, help=tip, on_click=cb, disabled=disabled,
                              use_container_width=True)
            # save + export live at the right end of the toolbar
            with cols[8]:
                st.button("", key="tb_save", help="Save board", disabled=not can_edit,
                          on_click=self._save_cb, args=(svc, shell), use_container_width=True)
            with cols[9]:
                fmts = svc.export_formats()
                fmt = st.selectbox("fmt", fmts, key="tb_fmt", label_visibility="collapsed")
            with cols[10]:
                data, mime, fname = svc.export(board, _frame_index(), fmt=fmt)
                st.download_button("", data=data, file_name=fname, mime=mime, key="tb_export",
                                   help="Export", use_container_width=True)
        # inject the per-button icon masks (the return value MUST be rendered, and the
        # tb_toolbar base ::before rule in _inject_css gives them size + currentColor)
        st.markdown(icon_css([
            ("tb_undo", "chevron-left"), ("tb_redo", "chevron-right"), ("tb_new", "plus"),
            ("tb_dup", "layers"), ("tb_snap", "grid"), ("tb_grid", "grid"),
            ("tb_lock", "shield"), ("tb_save", "check"), ("tb_export", "download")]),
            unsafe_allow_html=True)

    def _save_cb(self, svc, shell) -> None:
        board = st.session_state[TB_BOARD]
        try:
            svc.save_board(shell.user, board, name=board.name)
            st.session_state["_tb_flash"] = f"Saved '{board.name}'."
        except Exception as exc:
            st.session_state["_tb_flash"] = f"Save failed: {exc}"

    # ------------------------------------------------------------ library
    def _library(self, can_edit) -> None:
        st.markdown('<div class="tb-panel-title">Object Library</div>', unsafe_allow_html=True)
        if not can_edit:
            C.render_alert("Read-only: you can view but not edit this board.", "info")
        for title, ic, items in _LIBRARY:
            with st.expander(title, expanded=(title == "Players")):
                for label, otype, extra in items:
                    st.button(label, key=f"tblib_{title}_{label}", use_container_width=True,
                              disabled=not can_edit, on_click=_add, args=(otype, extra))

    def _templates_and_saved(self, shell, svc, board, can_edit) -> None:
        with st.expander("Templates", expanded=False):
            for name in builtin_names():
                st.button(name, key=f"tbtpl_{name}", use_container_width=True,
                          disabled=not can_edit, on_click=lambda n=name: _load(builtin_template(n)))
        with st.expander("Saved boards", expanded=False):
            boards = svc.list_boards(shell.user)
            if not boards:
                st.caption("No saved boards yet.")
            for pr in boards:
                cols = st.columns([4, 1])
                cols[0].button(getattr(pr, "name", "board"), key=f"tbopen_{pr.id}",
                               use_container_width=True,
                               on_click=lambda p=pr: _load(svc.board_of(p)))
                if can_edit:
                    cols[1].button("", key=f"tbdel_{pr.id}", help="Delete", icon=":material/delete:",
                                   on_click=lambda pid=pr.id: svc.delete(shell.user, pid))

    # ------------------------------------------------------------ board
    def _board_view(self, board, can_edit) -> None:
        flash = st.session_state.pop("_tb_flash", "")
        if flash:
            C.render_alert(flash, "success")
        name = st.text_input("Board name", value=board.name, key="tb_name",
                             label_visibility="collapsed")
        if name != board.name:
            _apply({"op": "rename_board", "name": name}, record=False)

        grid = st.session_state.get(TB_GRID, False)
        sel = st.session_state.get(TB_SEL)
        colors = _canvas_colors()
        svg = board_svg(board, _frame_index(), colors=colors, grid=grid, selected_id=sel)

        # Phase 15: the JS drag-and-drop canvas is the primary renderer + interaction.
        # It reuses the Python SVG above and only reports intent (JSON commands); if it
        # cannot initialise it returns None and we fall back to the static SVG + sliders.
        snap = 5.0 if st.session_state.get(TB_SNAP, False) else 0.0
        # include the last processed action stamp so the nonce ALWAYS changes after a
        # commit (updated_at only has 1s resolution) — guarantees the post-commit SVG is
        # pushed to the canvas so a dropped piece settles at its committed position.
        nonce = (f"{board.updated_at}|{_frame_index()}|{sel}|{int(grid)}|{int(bool(snap))}"
                 f"|{st.session_state.get(TB_CANVAS_TS)}")
        rendered, result = tactical_canvas(
            svg, _canvas_objects(board), key="tb_canvas", colors=colors,
            palette=_canvas_palette() if can_edit else [], selected_id=sel,
            snap=snap, editable=can_edit, nonce=nonce)
        if not rendered:
            # true fallback: the component could not mount, so draw the static SVG. The
            # interaction-agnostic core is still fully usable via Library + Properties.
            st.markdown(f'<div class="tb-board">{svg}</div>', unsafe_allow_html=True)
            st.caption("Drag-and-drop canvas unavailable — use the Library to add pieces "
                       "and the Precise positioning controls in Properties.")
        else:
            # normal path: the drop was already committed at the top of render() from
            # session_state, so the SVG above is current. This only fires in the rare run
            # where the value wasn't in session_state yet — a graceful catch-up.
            if result is not None and _commit_canvas(result, can_edit):
                st.rerun()
            st.caption("Drag pieces to move · drag a chip onto the pitch to add · click to "
                       "select · Delete removes. Fine-tune anything in Properties.")

    # ------------------------------------------------------------ properties
    def _properties(self, board, can_edit) -> None:
        st.markdown('<div class="tb-panel-title">Properties</div>', unsafe_allow_html=True)
        fr = board.frame(_frame_index())
        if not fr.objects:
            C.render_empty_state("Nothing on the board", "Add objects from the Library.",
                                 icon_name="layers")
            return
        labels = {o.id: f"{o.label()} · {o.type}" for o in fr.objects}
        ids = list(labels)
        sel = st.session_state.get(TB_SEL)
        if sel not in ids:
            sel = ids[-1]
        sel = st.selectbox("Object", ids, index=ids.index(sel),
                           format_func=lambda i: labels[i], key="tb_selbox")
        st.session_state[TB_SEL] = sel
        obj = fr.object(sel)
        if obj is None:
            return
        # if the shown object changed (dropdown pick, or a canvas select), drop the value
        # widgets' persistent state so they re-read THIS object rather than write the
        # previously-shown object's values back onto it
        if st.session_state.get(TB_PROP_FOR) != obj.id:
            for k in _PROP_VALUE_KEYS:
                st.session_state.pop(k, None)
            st.session_state[TB_PROP_FOR] = obj.id
        f = _frame_index()

        def upd(**kw):
            _apply({"op": "update_object", "frame": f, "id": sel, **kw}, record=False)

        # rotation / scale: not positional, so they stay as direct controls
        c3, c4 = st.columns(2)
        rot = c3.slider("Rotate", 0, 360, int(obj.rotation), key="tb_rot", disabled=not can_edit)
        sca = c4.slider("Scale", 50, 200, int(obj.scale * 100), 10, key="tb_sca", disabled=not can_edit)
        if can_edit and (rot != int(obj.rotation) or sca != int(obj.scale * 100)):
            upd(rotation=float(rot), scale=sca / 100.0)

        self._type_props(obj, upd, can_edit)

        # Position is driven by dragging on the canvas; the X/Y sliders are an internal
        # fallback only (kept collapsed) for precise nudges or when the canvas is off.
        with st.expander("Precise positioning (fallback)", expanded=False):
            c1, c2 = st.columns(2)
            nx = c1.slider("X", 0, 100, int(obj.x), key="tb_x", disabled=not can_edit)
            ny = c2.slider("Y", 0, 100, int(obj.y), key="tb_y", disabled=not can_edit)
            if can_edit and (nx != int(obj.x) or ny != int(obj.y)):
                upd(x=float(nx), y=float(ny))

        b1, b2 = st.columns(2)
        b1.button("Duplicate", key="tb_p_dup", use_container_width=True, disabled=not can_edit,
                  on_click=lambda: _apply({"op": "duplicate_object", "frame": f, "id": sel}))
        b2.button("Delete", key="tb_p_del", use_container_width=True, disabled=not can_edit,
                  on_click=lambda: _apply({"op": "delete_object", "frame": f, "id": sel}))

    def _type_props(self, obj, upd, can_edit) -> None:
        p = obj.props
        if obj.type == "player":
            c1, c2 = st.columns(2)
            num = c1.number_input("Number", 0, 99, int(p.get("number", 0) or 0), key="tb_pnum",
                                  disabled=not can_edit)
            team = c2.selectbox("Team", ["home", "away"],
                                index=0 if p.get("team", "home") == "home" else 1,
                                key="tb_pteam", disabled=not can_edit)
            name = st.text_input("Name", value=p.get("name", ""), key="tb_pname", disabled=not can_edit)
            cc1, cc2 = st.columns(2)
            cap = cc1.checkbox("Captain", value=bool(p.get("captain")), key="tb_pcap", disabled=not can_edit)
            gk = cc2.checkbox("Goalkeeper", value=bool(p.get("goalkeeper")), key="tb_pgk", disabled=not can_edit)
            if can_edit:
                upd(props={"number": int(num), "team": team, "name": name,
                           "captain": bool(cap), "goalkeeper": bool(gk)})
        elif obj.type in ("text", "number"):
            txt = st.text_input("Text", value=p.get("text", ""), key="tb_ptext", disabled=not can_edit)
            size = st.slider("Size", 8, 40, int(p.get("size", 14)), key="tb_psize", disabled=not can_edit)
            if can_edit:
                upd(props={"text": txt, "size": size})
        elif obj.type in ("arrow", "curved_arrow", "dashed_arrow", "line"):
            c1, c2 = st.columns(2)
            x2 = c1.slider("End X", 0, 100, int(p.get("x2", obj.x + 12)), key="tb_px2", disabled=not can_edit)
            y2 = c2.slider("End Y", 0, 100, int(p.get("y2", obj.y)), key="tb_py2", disabled=not can_edit)
            curv = 0.0
            if obj.type == "curved_arrow":
                curv = st.slider("Curve", -100, 100, int(float(p.get("curvature", 0.3)) * 100),
                                 key="tb_pcurv", disabled=not can_edit) / 100.0
            if can_edit:
                upd(props={"x2": float(x2), "y2": float(y2), "curvature": curv})
        elif obj.type in ("zone", "highlight", "shape"):
            c1, c2 = st.columns(2)
            w = c1.slider("Width", 4, 60, int(p.get("w", 20)), key="tb_pw", disabled=not can_edit)
            h = c2.slider("Height", 4, 60, int(p.get("h", 16)), key="tb_ph", disabled=not can_edit)
            op = st.slider("Opacity", 5, 90, int(float(p.get("opacity", 0.28)) * 100),
                           key="tb_pop", disabled=not can_edit) / 100.0
            if can_edit:
                upd(props={"w": float(w), "h": float(h), "opacity": op})

    # ------------------------------------------------------------ timeline / frames
    def _timeline(self, board, can_edit) -> None:
        st.markdown('<div class="tb-timeline-wrap">', unsafe_allow_html=True)
        st.markdown('<div class="tb-panel-title">Timeline · Frames</div>', unsafe_allow_html=True)
        cur = _frame_index()
        cols = st.columns(max(6, len(board.frames) + 3))
        for i, fr in enumerate(board.frames):
            with cols[i]:
                st.button(f"Frame {i + 1}", key=f"tbfr_{i}", use_container_width=True,
                          type="primary" if i == cur else "secondary",
                          on_click=_set_frame, args=(i,))
        with cols[len(board.frames)]:
            st.button("Add frame", key="tbfr_add", use_container_width=True, disabled=not can_edit,
                      on_click=lambda: _apply({"op": "add_frame", "from": cur}))
        with cols[len(board.frames) + 1]:
            st.button("Delete", key="tbfr_del", use_container_width=True,
                      disabled=not can_edit or len(board.frames) <= 1,
                      on_click=lambda: _apply({"op": "delete_frame", "index": cur}))
        st.markdown('</div>', unsafe_allow_html=True)

    # ------------------------------------------------------------ styling (self-contained)
    def _inject_css(self) -> None:
        st.markdown("""
<style>
.st-key-tb_toolbar { background: var(--fap-surface); border: 1px solid var(--fap-border);
  border-radius: 12px; padding: 6px 10px; margin-bottom: 12px; }
.st-key-tb_toolbar .stButton button, .st-key-tb_toolbar [data-testid="stDownloadButton"] button {
  min-height: 38px; color: var(--fap-text); background: var(--fap-surface);
  border: 1px solid var(--fap-border); display: flex; align-items: center; justify-content: center; }
/* base icon glyph: the per-button mask-image comes from nav.icon_css; this gives it a
   box + paints it with the button's currentColor so the icons are actually visible.
   NOTE: descendant (not '>') so tooltip-wrapped buttons (help=) still match — Streamlit
   nests the <button> under stTooltipIcon/stTooltipHoverTarget when a tooltip is set. */
.st-key-tb_toolbar .stButton button::before,
.st-key-tb_toolbar [data-testid="stDownloadButton"] button::before {
  content: ""; display: inline-block; width: 18px; height: 18px; background-color: currentColor;
  -webkit-mask-repeat: no-repeat; mask-repeat: no-repeat;
  -webkit-mask-position: center; mask-position: center;
  -webkit-mask-size: contain; mask-size: contain; }
.st-key-tb_toolbar .stButton button:hover,
.st-key-tb_toolbar [data-testid="stDownloadButton"] button:hover { color: var(--fap-primary); }
.tb-panel-title { font-size: 11px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase;
  color: var(--fap-text-subtle); margin: 2px 2px 8px; }
.tb-board { background: var(--fap-surface); border: 1px solid var(--fap-border);
  border-radius: 14px; padding: 10px; box-shadow: var(--fap-shadow-sm); }
.tb-timeline-wrap { background: var(--fap-surface); border: 1px solid var(--fap-border);
  border-radius: 12px; padding: 10px 12px; margin-top: 14px; }
</style>
""", unsafe_allow_html=True)
