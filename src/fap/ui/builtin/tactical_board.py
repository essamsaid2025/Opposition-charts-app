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
    ARROW_VARIANT_KEYS, Board, History, TacticalService, apply_command, board_svg,
    builtin_names, builtin_template, new_board,
)
from fap.tactical import geometry as _tgeo
from fap.tactical.ops import apply_command as _apply_command
from fap.tactical.ops import default_props
from fap.tactical.render import DEFAULT_COLORS
from fap.tactical.theme_colors import tactical_colors_from_theme
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
TB_DRAW_TOOL = "_tb_draw_tool"    # armed click-drag draw tool ("select" = off); persistent/sticky
TB_MULTI = "_tb_multisel"         # object ids selected in the Objects/Layers panel (Phase 3)

# vector object types the arrow-style / arrowhead editors apply to (UI-side mirror of
# ops._VECTOR_TYPES; kept local so the UI has no import-time coupling to ops internals)
_VECTOR_UI_TYPES = ("arrow", "curved_arrow", "dashed_arrow", "line")

# Every Properties widget that follows the "read the widget, write it back to the model if
# it differs" pattern. Those widgets keep their OWN value in session_state, so after the
# canvas moves/adds/selects an object the widgets hold STALE values and would overwrite the
# model (this was the drag "snap-back": the X/Y sliders wrote the old position back over the
# drop). We pop these whenever the canvas changes state or the selected object changes, which
# forces every widget to re-initialise from the current model object. (tb_selbox handled too.)
_PROP_VALUE_KEYS: tuple[str, ...] = (
    "tb_x", "tb_y", "tb_rot", "tb_sca", "tb_pnum", "tb_pteam", "tb_pname", "tb_pcap", "tb_pgk",
    "tb_ptext", "tb_psize", "tb_px2", "tb_py2", "tb_pcurv", "tb_pw", "tb_ph", "tb_pop",
    "tb_pcolor", "tb_zcolor",
    "tb_pshape", "tb_pfilled", "tb_psw", "tb_psstyle", "tb_zstroke", "tb_battach",
)


def _resync_properties() -> None:
    """Drop the persistent Properties widget state so those widgets re-read the model."""
    for k in ("tb_selbox", *_PROP_VALUE_KEYS):
        st.session_state.pop(k, None)

_LIBRARY = [
    ("Players", "jersey", [("Home player", "player", {"team": "home"}),
                           ("Away player", "player", {"team": "away"}),
                           ("Goalkeeper", "player", {"team": "home", "goalkeeper": True})]),
    ("Balls", "ball", [("Ball", "ball", {})]),
    ("Cones", "cone", [("Cone", "cone", {})]),
    ("Goals", "goal", [("Goal", "goal", {})]),
    ("Mannequins", "mannequin", [("Mannequin", "mannequin", {})]),
    ("Arrows", "arrow-straight", [("Arrow", "arrow", {}), ("Curved arrow", "curved_arrow", {}),
                                  ("Dashed arrow", "dashed_arrow", {})]),
    ("Lines", "line-straight", [("Line", "line", {})]),
    ("Zones", "zone-marker", [("Zone", "zone", {}), ("Highlight", "highlight", {"shape": "ellipse"})]),
    ("Text", "text", [("Text", "text", {"text": "Text"})]),
    ("Shapes", "square", [("Shape", "shape", {})]),
]

# click-drag "draw" tools (key, label). "select" = Select/Move (default, no drawing). The
# mode is PERSISTENT (sticky): the armed tool stays active across multiple draws until the user
# clicks another tool or presses Escape. Drawn geometry maps onto the SAME add_object command.
_DRAW_TOOLS: list[tuple[str, str]] = [
    ("select", "Select / Move"), ("zone", "Zone"), ("shape", "Shape"), ("circle", "Circle"),
    ("arrow", "Arrow"), ("curved_arrow", "Curved arrow"), ("dashed_arrow", "Dashed arrow"),
    ("line", "Line"),
]

# real backing icon for each tool button in the merged rail (all resolve in fap.theme.icons).
# "select" has no cursor glyph in the set, so it uses the crosshair "target" (the pick/aim tool);
# the draw tools reuse the same purpose-built icons as their matching library categories.
_TOOL_ICONS: dict[str, str] = {
    "select": "target", "zone": "zone-marker", "shape": "square", "circle": "target",
    "arrow": "arrow-straight",
    "curved_arrow": "arrow-curved", "dashed_arrow": "arrow-dashed", "line": "line-straight",
}


# ---------------------------------------------------------------- session state
def _state() -> tuple[Board, History]:
    if TB_BOARD not in st.session_state:
        st.session_state[TB_BOARD] = new_board("Untitled Board")
        st.session_state[TB_HIST] = History()
        st.session_state[TB_FRAME] = 0
        st.session_state[TB_SEL] = None
    st.session_state.setdefault(TB_GRID, False)
    st.session_state.setdefault(TB_SNAP, False)
    st.session_state.setdefault(TB_DRAW_TOOL, "select")
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
        st.session_state.pop(TB_MULTI, None)


def _redo() -> None:
    b = st.session_state[TB_HIST].redo(st.session_state[TB_BOARD])
    if b is not None:
        st.session_state[TB_BOARD] = b
        st.session_state.pop(TB_MULTI, None)


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


def _set_draw_tool(tool: str) -> None:
    """Arm a draw tool (sticky). ``TB_DRAW_TOOL`` is a plain session var, so it can be set
    from a button callback here or reset from the Escape handler in ``_commit_canvas``."""
    st.session_state[TB_DRAW_TOOL] = tool


def _set_frame(i: int) -> None:
    st.session_state[TB_FRAME] = i
    st.session_state[TB_SEL] = None


# ---------------------------------------------------------------- canvas (Phase 15)
# The JS canvas emits the SAME JSON commands the model already understands. We feed
# them straight through ``apply_command`` (one undo step per interaction batch) - no
# business logic lives in the browser. Selection is UI-only session state.
def _canvas_colors() -> dict[str, str]:
    """The board's default palette (no theme selected) - unchanged from before."""
    return dict(DEFAULT_COLORS)


def _theme_manager(shell):
    """Same accessor viz_workspace uses; None when themes aren't available."""
    try:
        return shell.platform.services.get("themes")
    except Exception:
        return None


def _resolve_board_colors(shell, board) -> dict[str, str]:
    """Colours the board renders + exports with. A board with NO theme in its meta
    is byte-identical to today (``DEFAULT_COLORS``); a selected theme is mapped onto
    the tactical roles. Any failure (missing theme, bad shape) degrades to the
    default palette rather than breaking the board."""
    tid = str((getattr(board, "meta", None) or {}).get("theme") or "").strip()
    if not tid:
        return dict(DEFAULT_COLORS)                 # critical: existing boards unchanged
    try:
        themes = _theme_manager(shell)
        theme = themes.get(tid) if themes else None
        if theme is None:
            return dict(DEFAULT_COLORS)
        return tactical_colors_from_theme(theme)
    except Exception:
        return dict(DEFAULT_COLORS)


def _canvas_palette(colors: dict[str, str]) -> list[dict]:
    """Flatten the object Library into draggable chips (data only - the drag simply
    emits an ``add_object`` command at the drop point).

    RETIRED from the default board wiring: ``_board_view`` now passes ``palette=[]`` so the
    JS ``renderPalette()`` hides the old always-on drag-chip strip (its ``display:none``
    fallback). The builder is KEPT (its output is still exercised by the unit tests, and it is
    the one place that maps a library item to its colour) so re-enabling an opt-in drag palette
    later is a one-line change; nothing else consumes it today."""
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
        # rotation (every type) lets the canvas place a rotate handle + orient resize handles
        m = {"id": o.id, "type": o.type, "x": o.x, "y": o.y, "locked": o.locked,
             "rotation": float(o.rotation),
             # full props so the in-board (Tacticalista-style) context panel can populate its
             # controls for the selected object and emit update_object with the right keys.
             "props": dict(o.props or {})}
        if o.type in ("arrow", "curved_arrow", "dashed_arrow", "line"):
            m["x2"] = float(o.props.get("x2", o.x + 12))
            m["y2"] = float(o.props.get("y2", o.y))
        if o.type == "curved_arrow":
            # lets the canvas place the draggable curve handle exactly on the current
            # control point (same default as render.py's _vector)
            m["curvature"] = float(o.props.get("curvature", 0.3))
        if o.type in ("zone", "highlight", "shape"):
            # bounding-box size (same 0-100 units as x/y) so the canvas can place corner
            # resize handles without guessing (matches render.py's _zone box)
            m["w"] = float(o.props.get("w", 20))
            m["h"] = float(o.props.get("h", 16))
        meta.append(m)
    return meta


def _detach_ball_on_manual_move(board: Board, cmd: dict) -> None:
    """A sticky ball dragged directly on the canvas should FREE itself (the user wants manual
    control) — otherwise ``resolve_position`` would keep snapping it back to the player on the
    next render. So when an ``update_object`` sets a sticky ball's x/y, fold ``attached_to=""``
    into the SAME command (Python-only, no new op, no JS change). Silent no-op otherwise."""
    if cmd.get("op") != "update_object" or (cmd.get("x") is None and cmd.get("y") is None):
        return
    obj = board.frame(int(cmd.get("frame", 0))).object(str(cmd.get("id", "")))
    if obj is not None and obj.type == "ball" and str((obj.props or {}).get("attached_to") or ""):
        props = dict(cmd.get("props") or {})
        props.setdefault("attached_to", "")
        cmd["props"] = props


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

    # Ctrl+Z / Ctrl+Y on the canvas are UI-only intents that drive the SAME History as the
    # toolbar buttons (never the model directly).
    if result.get("undo") and can_edit:
        _undo(); return True
    if result.get("redo") and can_edit:
        _redo(); return True

    changed = False
    # Escape in draw mode: the canvas sent a UI-only ``draw_reset`` (not a board command) —
    # return to Select/Move. Safe from either caller: TB_DRAW_TOOL is a plain session var
    # (the mode buttons are st.buttons, not a keyed widget), and this runs once per ts.
    if result.get("draw_reset"):
        st.session_state[TB_DRAW_TOOL] = "select"
        changed = True
    if commands and can_edit:
        board, hist = st.session_state[TB_BOARD], st.session_state[TB_HIST]
        hist.record(board)                       # one undo step for the whole interaction
        f = _frame_index()
        last_id = None
        for cmd in commands:
            cmd.setdefault("frame", f)
            _detach_ball_on_manual_move(board, cmd)   # dragging a sticky ball frees it (stays put)
            res = _apply_command(board, cmd)
            if cmd.get("op") in ("add_object", "duplicate_object") and res.get("id"):
                last_id = res["id"]
        if last_id:
            st.session_state[TB_SEL] = last_id   # keep a freshly added piece selected
            st.session_state[TB_MULTI] = [last_id]
        changed = True

    # selection is ONE session concept shared by the canvas and the Objects/Layers panel:
    # a string (single), a list (multi/marquee), or None (cleared). TB_SEL keeps the primary.
    if sel != "__keep__":
        if isinstance(sel, list):
            st.session_state[TB_MULTI] = list(sel)
            st.session_state[TB_SEL] = sel[-1] if sel else None
        else:
            st.session_state[TB_SEL] = sel
            st.session_state[TB_MULTI] = [sel] if sel else []
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
        # PERSISTENT draw mode: a completed draw does NOT disarm the tool - it stays sticky so
        # the user can draw several of the same object in a row. The tool only changes when the
        # user clicks a different mode button or presses Escape (which emits ``draw_reset`` ->
        # handled in _commit_canvas). So there is nothing to reset here.
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

        # The Tacticalista-style editor chrome (tool rail + context panels + top bar) now lives
        # INSIDE the board component, so the board takes the full width. Formations / saved boards
        # (which need Python) stay as a slim expander; the old Streamlit rail/properties/objects
        # panels are retired — their capabilities moved in-board.
        self._board_view(shell, board, can_edit)
        with st.expander("Templates, formations & saved boards", expanded=False):
            self._templates_and_saved(shell, svc, board, can_edit)
        self._timeline(board, can_edit)

    # ------------------------------------------------------------ toolbar
    def _toolbar(self, shell, svc, board, hist, can_edit) -> None:
        # Functional clusters — History · Board · View · Object · File — so the bar reads
        # as a professional editor toolbar, not one flat row of glyphs. Every button keeps
        # its ORIGINAL key + callback, so the command/history seam is untouched; only the
        # layout (grouping + labels) changed. The per-button masked icons still resolve via
        # the single icon_css() call below (its .st-key-tb_toolbar rules match by descendant,
        # so the new nested columns don't affect them).
        def _dup():
            _apply({"op": "duplicate_object", "frame": _frame_index(),
                    "id": st.session_state.get(TB_SEL) or ""})

        def _snap():
            _toggle(TB_SNAP)
            if st.session_state[TB_SNAP]:
                _apply({"op": "snap", "step": 5.0})

        def _lock():
            _apply({"op": "update_object", "frame": _frame_index(),
                    "id": st.session_state.get(TB_SEL) or "", "locked": True,
                    "force": True}, record=False)

        is_vertical = getattr(board.pitch, "orientation", "horizontal") == "vertical"
        fmt = None
        with st.container(key="tb_toolbar"):
            hist_c, board_c, view_c, obj_c, file_c = st.columns(
                [1.7, 1.7, 2.5, 1.1, 4.6], gap="small")
            # -- History -------------------------------------------------------
            with hist_c:
                st.markdown('<div class="tb-cluster">History</div>', unsafe_allow_html=True)
                bc = st.columns(2, gap="small")
                bc[0].button("", key="tb_undo", help="Undo  ·  Ctrl+Z", on_click=_undo,
                             disabled=not hist.can_undo() or not can_edit, use_container_width=True)
                bc[1].button("", key="tb_redo", help="Redo  ·  Ctrl+Y", on_click=_redo,
                             disabled=not hist.can_redo() or not can_edit, use_container_width=True)
            # -- Board ---------------------------------------------------------
            with board_c:
                st.markdown('<div class="tb-cluster">Board</div>', unsafe_allow_html=True)
                bc = st.columns(2, gap="small")
                bc[0].button("", key="tb_new", help="New board — clear and start over",
                             on_click=_new_board, disabled=not can_edit, use_container_width=True)
                bc[1].button("", key="tb_dup", help="Duplicate selection  ·  Ctrl+D",
                             on_click=_dup, disabled=not can_edit, use_container_width=True)
            # -- View ----------------------------------------------------------
            with view_c:
                st.markdown('<div class="tb-cluster">View</div>', unsafe_allow_html=True)
                bc = st.columns(3, gap="small")
                bc[0].button("", key="tb_snap",
                             help="Snap to grid — align pieces to a 5-unit grid",
                             on_click=_snap, disabled=not can_edit, use_container_width=True)
                bc[1].button("", key="tb_grid", help="Toggle grid overlay",
                             on_click=lambda: _toggle(TB_GRID), use_container_width=True)
                # orientation glyph shows the CURRENT state (↔ horizontal / ↕ vertical); the
                # tooltip names the action. Default "horizontal" keeps existing boards identical.
                bc[2].button("↕" if is_vertical else "↔", key="tb_orient",
                             help=("Pitch: Vertical — switch to Horizontal" if is_vertical
                                   else "Pitch: Horizontal — switch to Vertical"),
                             disabled=not can_edit, use_container_width=True,
                             on_click=lambda t=("horizontal" if is_vertical else "vertical"):
                                 _apply({"op": "set_pitch", "orientation": t}))
            # -- Object --------------------------------------------------------
            with obj_c:
                st.markdown('<div class="tb-cluster">Object</div>', unsafe_allow_html=True)
                st.button("", key="tb_lock", help="Lock selection — prevent moving/editing",
                          on_click=_lock, disabled=not can_edit, use_container_width=True)
            # -- File ----------------------------------------------------------
            with file_c:
                st.markdown('<div class="tb-cluster">File</div>', unsafe_allow_html=True)
                bc = st.columns([1.1, 1.7, 1.2], gap="small")
                bc[0].button("", key="tb_save", help="Save board to your saved boards",
                             disabled=not can_edit, on_click=self._save_cb, args=(svc, shell),
                             use_container_width=True)
                fmts = svc.export_formats()
                fmt = bc[1].selectbox("fmt", fmts, key="tb_fmt", label_visibility="collapsed")
                # LAZY export: rendering PNG/PDF/GIF is expensive (matplotlib). Computing it on
                # EVERY rerun made dragging a piece feel like a page reload, because each drop
                # re-ran the exporter. Now the bytes are prepared ONLY when the user clicks
                # Export, cached by a board+frame+format signature, and then offered as a real
                # download. Moving/selecting pieces recomputes nothing.
                sig = f"{board.updated_at}|{_frame_index()}|{fmt}"
                prep = st.session_state.get("_tb_export_cache")
                if prep and prep.get("sig") == sig:
                    bc[2].download_button("", data=prep["data"], file_name=prep["fname"],
                                          mime=prep["mime"], key="tb_export", help="Download export",
                                          use_container_width=True)
                elif bc[2].button("", key="tb_export_prep",
                                  help="Prepare export (PNG/PDF/GIF), then download",
                                  use_container_width=True):
                    colors = _resolve_board_colors(shell, board)
                    if fmt == "gif":
                        data, mime, fname = self._gif_export(svc, board, colors)
                    else:
                        data, mime, fname = svc.export(board, _frame_index(), fmt=fmt, colors=colors)
                    st.session_state["_tb_export_cache"] = {"sig": sig, "data": data,
                                                            "mime": mime, "fname": fname}
                    st.rerun()
        if fmt == "gif":
            st.caption(f"GIF exports all {len(board.frames)} frame(s) as an animation "
                       f"(PNG/PDF export the current frame only).")
        # inject the per-button icon masks (the return value MUST be rendered, and the
        # tb_toolbar base ::before rule in _inject_css gives them size + currentColor)
        st.markdown(icon_css([
            ("tb_undo", "chevron-left"), ("tb_redo", "chevron-right"), ("tb_new", "plus"),
            ("tb_dup", "layers"), ("tb_snap", "grid"), ("tb_grid", "grid"),
            ("tb_lock", "shield"), ("tb_save", "check"), ("tb_export", "download"),
            ("tb_export_prep", "download")]),
            unsafe_allow_html=True)

    def _save_cb(self, svc, shell) -> None:
        board = st.session_state[TB_BOARD]
        try:
            svc.save_board(shell.user, board, name=board.name)
            st.session_state["_tb_flash"] = f"Saved '{board.name}'."
        except Exception as exc:
            st.session_state["_tb_flash"] = f"Save failed: {exc}"

    @staticmethod
    def _gif_export(svc, board, colors):
        """Build (and cache) the animated GIF. Rendering every frame per rerun would be
        wasteful, so the bytes are cached by a signature of the board + colours and only
        regenerated when something actually changes. Tactical boards are small, so this
        stays snappy; a very large frame count simply produces a bigger file, no hang."""
        import hashlib
        import json
        sig = hashlib.sha1(json.dumps({"b": board.to_dict(), "c": colors},
                                      sort_keys=True, default=str).encode("utf-8")).hexdigest()
        cache = st.session_state.get("_tb_gif_cache")
        if not cache or cache.get("sig") != sig:
            data, mime, fname = svc.export(board, 0, fmt="gif", colors=colors)
            cache = {"sig": sig, "data": data, "mime": mime, "fname": fname}
            st.session_state["_tb_gif_cache"] = cache
        return cache["data"], cache["mime"], cache["fname"]

    # ------------------------------------------------------------ rail (tools + library)
    def _rail(self, can_edit) -> None:
        """ONE compact vertical icon rail — the single surface for adding & drawing objects.

        Top: the Select/Move pointer + the sticky click-drag DRAW tools (Zone, Shape, Arrow,
        Curved/Dashed arrow, Line). Below a divider: the object LIBRARY, one icon per _LIBRARY
        category, each opening a popover of click-to-add items. This merges what used to be two
        stacked blocks (the separate ``_draw_tool_control`` grid + the ``_library`` rail), and
        the old always-on drag-chip palette strip above the pitch is retired (see ``_board_view``
        passing ``palette=[]``). So there is now exactly ONE place to add pieces: click a category
        item (adds at centre) or arm a tool and click-drag on the pitch. Read-only keeps the rail
        browsable with add actions disabled, as before. Active-tool highlight is the same sticky
        ``type="primary"`` on ``TB_DRAW_TOOL`` as before — only the layout changed, not behaviour."""
        if not can_edit:
            C.render_alert("Read-only: you can view but not edit this board.", "info")
        cur = st.session_state.get(TB_DRAW_TOOL, "select")
        with st.container(key="tb_rail"):
            # -- TOOLS: Select/Move + sticky draw tools — now icon + LABEL (a readable
            #    palette, not bare glyphs). Same keys/callbacks/active-highlight as before.
            st.markdown('<div class="tb-panel-title">Tools</div>', unsafe_allow_html=True)
            for key, label in _DRAW_TOOLS:
                st.button(label, key=f"tbtool_{key}", help=label, use_container_width=True,
                          type="primary" if key == cur else "secondary",
                          disabled=not can_edit, on_click=_set_draw_tool, args=(key,))
            st.markdown('<div class="tb-panel-title" style="margin-top:12px">Objects</div>',
                        unsafe_allow_html=True)
            # -- LIBRARY: one popover trigger per category — now icon + CATEGORY NAME ------
            for title, ic, items in _LIBRARY:
                # sub-divider between placement objects and drawing objects (reference grouping)
                if title == "Arrows":
                    st.markdown('<div class="tb-rail-sep"></div>', unsafe_allow_html=True)
                with st.container(key=f"tbrail_{title}"):
                    # trigger is NOT disabled read-only (items stay browsable, like the old
                    # expanders); only the add buttons inside are gated, as before.
                    with st.popover(title, help=f"Add {title.lower()}", use_container_width=True):
                        for label, otype, extra in items:
                            st.button(label, key=f"tblib_{title}_{label}",
                                      use_container_width=True, disabled=not can_edit,
                                      on_click=_add, args=(otype, extra))
        # wire every glyph in ONE icon_css call: the tool buttons (each ``st-key-tbtool_*``) and
        # each category popover trigger (``st-key-tbrail_*``). The ::before boxes that paint them
        # come from _inject_css's tb_rail rules (tool box re-enabled there; trigger box as before).
        st.markdown(icon_css(
            [(f"tbtool_{k}", _TOOL_ICONS[k]) for k, _ in _DRAW_TOOLS]
            + [(f"tbrail_{title}", ic) for title, ic, _ in _LIBRARY]),
            unsafe_allow_html=True)
        if can_edit and cur != "select":
            st.caption("Draw mode — click-drag on empty pitch. Press Esc to exit.")

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

    def _theme_selector(self, shell, board, col) -> None:
        """Pick the board's colour theme. The default option keeps today's exact
        DEFAULT_COLORS palette; a chosen theme is remembered in ``board.meta`` (so it
        persists per board on Save, like the board name)."""
        themes = _theme_manager(shell)
        try:
            ids = list(themes.ids()) if themes else []
        except Exception:
            ids = []
        options = ["Default (board colors)"] + ids
        current = str((board.meta or {}).get("theme") or "")
        index = options.index(current) if current in options else 0
        choice = col.selectbox("Theme", options, index=index, key="tb_theme",
                               help="Colour the board from an app theme. 'Default' keeps the "
                                    "classic tactical palette. Applies on screen and to exports.")
        chosen = "" if choice == "Default (board colors)" else choice
        if chosen != current:
            board.meta["theme"] = chosen             # plain meta preference; saved with the board
            board.touch()                            # bump updated_at so the canvas re-renders
            st.rerun()

    # ------------------------------------------------------------ board
    def _board_view(self, shell, board, can_edit) -> None:
        flash = st.session_state.pop("_tb_flash", "")
        if flash:
            C.render_alert(flash, "success")
        hcols = st.columns([4, 1.6])
        name = hcols[0].text_input("Board name", value=board.name, key="tb_name",
                                   label_visibility="collapsed")
        if name != board.name:
            _apply({"op": "rename_board", "name": name}, record=False)
        self._theme_selector(shell, board, hcols[1])

        grid = st.session_state.get(TB_GRID, False)
        sel = st.session_state.get(TB_SEL)
        colors = _resolve_board_colors(shell, board)
        svg = board_svg(board, _frame_index(), colors=colors, grid=grid, selected_id=sel)

        # Phase 15: the JS drag-and-drop canvas is the primary renderer + interaction.
        # It reuses the Python SVG above and only reports intent (JSON commands); if it
        # cannot initialise it returns None and we fall back to the static SVG + sliders.
        snap = 5.0 if st.session_state.get(TB_SNAP, False) else 0.0
        # the armed draw tool (persistent). "select" (default) => None => unchanged behaviour.
        tool = st.session_state.get(TB_DRAW_TOOL, "select")
        draw_tool = {"type": tool, "props": default_props(tool)} if (can_edit and tool != "select") else None
        # The canvas re-renders ONLY when this nonce changes (the JS gates on it), so it must
        # change iff something the user should SEE or interact-with changed — and must stay STABLE
        # across the unrelated / duplicate reruns Streamlit fires (re-rendering on those is exactly
        # what snapped a just-dragged piece back to its old position and churned/froze the board).
        # The rendered SVG string already encodes every visual (positions, colours, selection
        # highlight, grid, pitch), so hashing it is an EXACT content signature — immune to the
        # same-second timestamp collisions the old updated_at-based nonce could hit. Interaction-
        # only params that are NOT drawn into the SVG (armed draw tool, snap, multi-selection,
        # editability) are appended so arming a tool or changing selection still pushes a fresh
        # render.
        import hashlib as _hashlib
        multi = [i for i in (st.session_state.get(TB_MULTI) or []) if board.frame(_frame_index()).object(i)]
        if not multi and sel:
            multi = [sel]
        _svg_sig = _hashlib.md5(svg.encode("utf-8")).hexdigest()[:16]
        nonce = f"{_svg_sig}|{tool}|{int(bool(snap))}|{','.join(multi)}|{int(bool(can_edit))}"
        # palette=[] retires the old always-on drag-chip strip (option a): adding pieces now
        # lives solely in the left rail (click a category item, or arm a draw tool). The JS
        # renderPalette() hides the strip when the palette is empty — no JS change needed.
        rendered, result = tactical_canvas(
            svg, _canvas_objects(board), key="tb_canvas", colors=colors,
            palette=[], selected_id=sel, selected_ids=multi,
            snap=snap, editable=can_edit, nonce=nonce, draw_tool=draw_tool)
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
            st.caption("Drag pieces to move · click to select · Delete removes. Add pieces "
                       "from the left rail (click a category, or arm a draw tool to click-drag "
                       "shapes). Fine-tune anything in Properties.")

    # ------------------------------------------------------------ objects / layers (Phase 3)
    def _objects_panel(self, board, can_edit) -> None:
        """The Objects/Layers manager: multi-select every object on the current frame,
        then group/ungroup, reorder (z), show/hide, lock/unlock, duplicate/delete — each
        a single undo step via the shared command seam. Button-driven so it never
        clobbers the mirror-on-diff Properties widgets. Also sets the arrow variant."""
        st.markdown('<div class="tb-panel-title">Objects</div>', unsafe_allow_html=True)
        fr = board.frame(_frame_index())
        if not fr.objects:
            st.caption("No objects on this frame yet.")
            return
        options = [o.id for o in sorted(fr.objects, key=lambda o: o.z, reverse=True)]
        # canvas selection is shared via TB_MULTI (one selection concept); drop any ids that no
        # longer exist on this frame BEFORE the widget reads them (avoids a stale-option error).
        if TB_MULTI in st.session_state:
            valid = set(options)
            kept = [i for i in st.session_state[TB_MULTI] if i in valid]
            if kept != list(st.session_state[TB_MULTI]):
                st.session_state[TB_MULTI] = kept

        def _fmt(oid: str) -> str:
            o = fr.object(oid)
            if o is None:
                return oid
            props = o.props or {}
            tags = [t for t, on in (("locked", o.locked), ("hidden", props.get("hidden")),
                                    ("grouped", props.get("group"))) if on]
            base = f"{o.label()} · {o.type}"
            return base + (f"  [{', '.join(tags)}]" if tags else "")
        sel = st.multiselect("Objects on this frame", options, format_func=_fmt, key=TB_MULTI)
        if not can_edit:
            return
        ids = [i for i in sel if fr.object(i) is not None]
        f = _frame_index()

        def cmd(op: str, **kw):
            return lambda: _apply({"op": op, "frame": f, "ids": ids, **kw})
        r1 = st.columns(4)
        r1[0].button("Front", key="tb_front", disabled=not ids, on_click=cmd("reorder_object", dir="front"))
        r1[1].button("Back", key="tb_back", disabled=not ids, on_click=cmd("reorder_object", dir="back"))
        r1[2].button("Group", key="tb_group", disabled=len(ids) < 2, on_click=cmd("group_objects"))
        r1[3].button("Ungroup", key="tb_ungroup", disabled=not ids, on_click=cmd("ungroup_objects"))
        r2 = st.columns(4)
        r2[0].button("Hide", key="tb_hide", disabled=not ids, on_click=cmd("set_hidden", hidden=True))
        r2[1].button("Show", key="tb_show", disabled=not ids, on_click=cmd("set_hidden", hidden=False))
        r2[2].button("Lock", key="tb_lockm", disabled=not ids, on_click=cmd("set_locked", locked=True))
        r2[3].button("Unlock", key="tb_unlockm", disabled=not ids, on_click=cmd("set_locked", locked=False))
        r3 = st.columns(2)
        r3[0].button("Duplicate", key="tb_dupm", disabled=not ids, on_click=cmd("duplicate_objects"))
        r3[1].button("Delete", key="tb_delm", disabled=not ids, on_click=cmd("delete_objects"))
        if len(ids) >= 2:                                # align / distribute the selection
            st.caption("Align")
            a = st.columns(6)
            a[0].button("L", key="tb_al", help="Align left", on_click=cmd("align_objects", align="left"))
            a[1].button("R", key="tb_ar", help="Align right", on_click=cmd("align_objects", align="right"))
            a[2].button("T", key="tb_at", help="Align top", on_click=cmd("align_objects", align="top"))
            a[3].button("B", key="tb_ab", help="Align bottom", on_click=cmd("align_objects", align="bottom"))
            a[4].button("H", key="tb_ach", help="Centre horizontally",
                        on_click=cmd("align_objects", align="center_h"))
            a[5].button("V", key="tb_acv", help="Centre vertically",
                        on_click=cmd("align_objects", align="center_v"))
            if len(ids) >= 3:
                d = st.columns(2)
                d[0].button("Distribute H", key="tb_dh",
                            on_click=cmd("distribute_objects", axis="horizontal"))
                d[1].button("Distribute V", key="tb_dv",
                            on_click=cmd("distribute_objects", axis="vertical"))
        # arrow style (variant) on a single selected vector object
        if len(ids) == 1:
            o = fr.object(ids[0])
            if o is not None and o.type in ("arrow", "curved_arrow", "dashed_arrow", "line"):
                choices = [""] + list(ARROW_VARIANT_KEYS)
                cur = (o.props or {}).get("variant") or ""
                v = st.selectbox("Arrow style", choices,
                                 index=choices.index(cur) if cur in choices else 0,
                                 format_func=lambda x: "Default" if not x else x.title(),
                                 key="tb_variant")
                lbl = st.text_input("Arrow label", value=(o.props or {}).get("label", ""),
                                    key="tb_alabel")
                if st.button("Apply arrow style", key="tb_applyvar"):
                    _apply({"op": "update_object", "frame": f, "id": o.id,
                            "props": {"variant": v, "label": lbl}})
                    st.rerun()
        # arrowhead editor — independent of the variant; works on ONE or MANY selected arrows,
        # applied as a single set_arrow_properties command (one undo step; locked arrows skipped)
        arrow_ids = [i for i in ids
                     if (o := fr.object(i)) is not None and o.type in _VECTOR_UI_TYPES]
        if arrow_ids:
            st.markdown('<div class="tb-panel-title" style="margin-top:8px">Arrowhead</div>',
                        unsafe_allow_html=True)
            if len(arrow_ids) > 1:
                st.caption(f"{len(arrow_ids)} arrows selected")
            first = fr.object(arrow_ids[0]).props or {}
            heads = list(_tgeo.ARROWHEAD_KINDS)
            cur_h = first.get("arrowhead") or _tgeo.ARROWHEAD_DEFAULT
            head = st.selectbox("Head", heads, index=heads.index(cur_h) if cur_h in heads else 0,
                                format_func=lambda k: _tgeo.ARROWHEAD_LABELS.get(k, k),
                                key="tb_head")
            hc = st.columns(2)
            hsize = hc[0].slider("Size", 0.5, 2.5, float(first.get("arrowhead_size", 1.0)),
                                 0.1, key="tb_hsize")
            hstroke = hc[1].slider("Stroke", 0.5, 4.0,
                                   float(first.get("stroke_width", 4.0)), 0.5, key="tb_hstroke")
            if st.button("Apply arrowhead", key="tb_applyhead", disabled=not can_edit):
                _apply({"op": "set_arrow_properties", "frame": f, "ids": arrow_ids,
                        "arrowhead": head, "arrowhead_size": hsize, "stroke_width": hstroke})
                st.rerun()

    # ------------------------------------------------------------ properties
    def _properties(self, shell, board, can_edit) -> None:
        st.markdown('<div class="tb-panel-title">Properties</div>', unsafe_allow_html=True)
        colors = _resolve_board_colors(shell, board)
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

        self._type_props(obj, upd, can_edit, colors, fr)

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

    def _type_props(self, obj, upd, can_edit, colors, fr) -> None:
        p = obj.props
        if obj.type == "ball":
            from fap.tactical.models import nearest_player, resolve_position
            players = [o for o in fr.objects if o.type == "player"]
            attached = str(p.get("attached_to") or "")
            if not players:
                st.checkbox("Sticky on Player", value=bool(attached), key="tb_battach",
                            disabled=True)
                st.caption("No players in this frame to attach to.")
            else:
                sticky = st.checkbox("Sticky on Player", value=bool(attached), key="tb_battach",
                                     disabled=not can_edit,
                                     help="Attach the ball to the nearest player so it moves with "
                                          "them (across frames too). Dragging the ball frees it.")
                if can_edit and sticky != bool(attached):
                    if sticky:                       # attach to the CURRENT nearest player
                        near = nearest_player(obj.x, obj.y, players)
                        if near is not None:
                            upd(props={"attached_to": near.id})
                    else:                            # detach: freeze at last on-screen spot first
                        rx, ry = resolve_position(fr, obj)
                        upd(x=float(rx), y=float(ry), props={"attached_to": ""})
                if attached:
                    ap = fr.object(attached)
                    st.caption(f"Stuck to {ap.label()}." if ap is not None
                               else "Attached player was removed — the ball is free.")
        elif obj.type == "player":
            prev_team = p.get("team", "home")
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
            # per-player colour override (layered on top of the resolved team/theme colour)
            self._color_override(obj, upd, can_edit, colors,
                                 default_key=("away" if team == "away" else "home"),
                                 pkey="tb_pcolor", reseed=(team != prev_team))
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
            # shape picker only for free "shape" objects: zones stay rectangles and highlights
            # stay ellipses (their identity), and a highlight ignores the shape prop anyway.
            shape = p.get("shape", "rect")
            if obj.type == "shape":
                opts = ["rect", "ellipse", "triangle"]
                labels = {"rect": "Rectangle", "ellipse": "Ellipse", "triangle": "Triangle"}
                shape = st.selectbox("Shape", opts, index=opts.index(shape if shape in opts else "rect"),
                                     format_func=lambda s: labels[s], key="tb_pshape",
                                     disabled=not can_edit)
            # fill toggle + opacity (opacity has no effect with no fill, so grey it out)
            filled = st.checkbox("Filled", value=bool(p.get("filled", True)), key="tb_pfilled",
                                 disabled=not can_edit)
            op = st.slider("Opacity", 5, 90, int(float(p.get("opacity", 0.28)) * 100),
                           key="tb_pop", disabled=not can_edit or not filled) / 100.0
            # stroke (border) width + style
            sc1, sc2 = st.columns(2)
            swid = sc1.slider("Border width", 0, 10, int(float(p.get("stroke_width", 2))),
                              key="tb_psw", disabled=not can_edit, help="0 = no border.")
            sstyle = sc2.selectbox("Border style", ["solid", "dashed"],
                                   index=1 if p.get("stroke_style", "solid") == "dashed" else 0,
                                   key="tb_psstyle", disabled=not can_edit)
            if can_edit:
                upd(props={"w": float(w), "h": float(h), "opacity": op, "shape": shape,
                           "filled": bool(filled), "stroke_width": float(swid),
                           "stroke_style": sstyle})
            # per-zone FILL colour override (falls back to the resolved theme "zone" colour)
            self._color_override(obj, upd, can_edit, colors, default_key="zone",
                                 pkey="tb_zcolor")
            # per-zone BORDER colour override (falls back to the resolved fill colour)
            self._stroke_color_override(obj, upd, can_edit, colors)

    def _swatch_row(self, colors, can_edit, upd, prop_key: str, pkey: str) -> None:
        """A compact row of quick-pick colour squares — the resolved theme home/away/ball/zone/
        accent colours plus black & white — that write the SAME ``props[prop_key]`` override the
        picker below does (via ``upd``). Purely additive convenience; the picker + Reset are
        untouched. Works for both the fill (``prop_key='color'``) and stroke overrides."""
        swatches = [("home", colors.get("home")), ("away", colors.get("away")),
                    ("ball", colors.get("ball")), ("zone", colors.get("zone")),
                    ("accent", colors.get("accent")), ("black", "#000000"), ("white", "#ffffff")]
        swatches = [(n, c) for n, c in swatches if c]     # drop any theme colour that's missing
        cols = st.columns(len(swatches))
        css = []
        for col, (name, hexc) in zip(cols, swatches):
            k = f"{pkey}_sw_{name}"
            css.append(f".st-key-{k} button{{background:{hexc} !important;color:transparent "
                       f"!important;min-height:26px;padding:0 !important;"
                       f"border:1px solid rgba(128,128,128,.55) !important}}")
            col.button(" ", key=k, help=name.title(), disabled=not can_edit,
                       on_click=lambda h=hexc, pk=prop_key: upd(props={pk: h}))
        st.markdown("<style>" + "".join(css) + "</style>", unsafe_allow_html=True)

    def _color_override(self, obj, upd, can_edit, colors, *, default_key, pkey,
                        reseed: bool = False) -> None:
        """A per-object colour override layered ON TOP of the theme/team colour system.

        The picker is seeded with the current override, or the resolved theme colour when
        there is none. We only WRITE an override when the user actually changes the swatch
        (so merely opening the panel never pins a colour and breaks theme-following), and a
        Reset button clears it back to ``""`` -> ``render.py`` then falls back to the resolved
        team/zone colour again. ``reseed`` re-reads the swatch next run when the underlying
        default changed (e.g. the player's team was just switched)."""
        default_col = colors.get(default_key) or DEFAULT_COLORS.get(default_key, "#888888")
        override = str(obj.props.get("color") or "").strip()
        resolved = override or default_col
        if reseed:
            st.session_state.pop(pkey, None)          # re-seed to the new default next run
        self._swatch_row(colors, can_edit, upd, "color", pkey)
        ca, cb = st.columns([3, 2])
        picked = ca.color_picker("Colour", value=resolved, key=pkey, disabled=not can_edit)
        reset = cb.button("Reset to theme", key=pkey + "_reset", use_container_width=True,
                          disabled=not can_edit or not override,
                          help="Clear this override and follow the team/theme colour.")
        if not can_edit or reseed:
            return                                    # don't act on a stale swatch this run
        if reset:
            upd(props={"color": ""})
        elif picked and picked.lower() != resolved.lower():
            upd(props={"color": picked})

    def _stroke_color_override(self, obj, upd, can_edit, colors) -> None:
        """Border-colour override for zone/highlight/shape, mirroring ``_color_override`` but
        writing ``props["stroke_color"]``. Seeded with the resolved FILL colour (so the border
        matches the fill until changed); Reset clears it back to ``""`` -> the renderer falls
        back to the fill colour again. Only written on an actual change."""
        fill = str(obj.props.get("color") or "").strip() \
            or colors.get("zone") or DEFAULT_COLORS.get("zone", "#888888")
        override = str(obj.props.get("stroke_color") or "").strip()
        resolved = override or fill
        self._swatch_row(colors, can_edit, upd, "stroke_color", "tb_zstroke")
        ca, cb = st.columns([3, 2])
        picked = ca.color_picker("Border colour", value=resolved, key="tb_zstroke",
                                 disabled=not can_edit)
        reset = cb.button("Reset to fill", key="tb_zstroke_reset", use_container_width=True,
                          disabled=not can_edit or not override,
                          help="Clear the border-colour override and follow the fill colour.")
        if not can_edit:
            return
        if reset:
            upd(props={"stroke_color": ""})
        elif picked and picked.lower() != resolved.lower():
            upd(props={"stroke_color": picked})

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
        # optional per-frame hold time for animated GIF export (defaults to 800ms)
        if can_edit and board.frames:
            fr_cur = board.frame(cur)
            prev = int(getattr(fr_cur, "duration_ms", 800))
            dur = st.number_input("Frame hold for GIF (ms)", min_value=100, max_value=10000,
                                  value=prev, step=100, key=f"tbfr_dur_{fr_cur.id}",
                                  help="How long this frame is shown in an animated GIF export.")
            if int(dur) != prev:
                fr_cur.duration_ms = int(dur)         # plain per-frame preference; saved with board
                board.touch()
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
/* the orientation toggle shows a text glyph (↔/↕), not a masked icon: hide the base
   ::before box (which would otherwise paint a solid square) and size the glyph. */
.st-key-tb_toolbar .st-key-tb_orient button::before { display: none; }
.st-key-tb_toolbar .st-key-tb_orient button { font-size: 18px; font-weight: 700; }
.tb-panel-title { font-size: 11px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase;
  color: var(--fap-text-subtle); margin: 2px 2px 8px; }
/* ---- Object Library icon rail --------------------------------------------------
   Each category is an st.popover whose icon-only TRIGGER (data-testid="stPopoverButton")
   shows the category's real icon via the same mask-image mechanism as the toolbar
   (icon_css sets mask-image; the rule below gives the ::before box + currentColor). The
   popover's item buttons (data-testid="stBaseButton-secondary") render inline in the same
   container, so we hide the icon box on every rail button by default and re-enable it ONLY
   on the trigger — items keep their plain text labels. */
.st-key-tb_rail button::before { display: none; }
.st-key-tb_rail [data-testid="stPopoverButton"]::before {
  content: ""; display: inline-block; width: 22px; height: 22px; background-color: currentColor;
  -webkit-mask-repeat: no-repeat; mask-repeat: no-repeat;
  -webkit-mask-position: center; mask-position: center;
  -webkit-mask-size: contain; mask-size: contain; }
/* the trigger is icon-only: hide Streamlit's default 'expand_more' chevron glyph */
.st-key-tb_rail [data-testid="stPopoverButton"] [data-testid="stIconMaterial"] { display: none; }
/* trigger styled like the toolbar icon buttons */
.st-key-tb_rail [data-testid="stPopoverButton"] {
  min-height: 40px; color: var(--fap-text); background: var(--fap-surface);
  border: 1px solid var(--fap-border); }
.st-key-tb_rail [data-testid="stPopoverButton"]:hover {
  color: var(--fap-primary); border-color: var(--fap-primary); }
/* the Select/Move + draw TOOL buttons at the TOP of the same rail: re-enable the masked-icon
   ::before box (the blanket rail rule above hides every rail button's box), and give the
   SECONDARY (inactive) variant the same surface look as the category triggers. The ACTIVE tool
   is type="primary", so we deliberately DON'T set its background here — Streamlit's primary fill
   is the active highlight, exactly as before the merge. */
.st-key-tb_rail [class*="st-key-tbtool_"] button::before {
  content: ""; display: inline-block; width: 22px; height: 22px; background-color: currentColor;
  -webkit-mask-repeat: no-repeat; mask-repeat: no-repeat;
  -webkit-mask-position: center; mask-position: center;
  -webkit-mask-size: contain; mask-size: contain; }
.st-key-tb_rail [class*="st-key-tbtool_"] button { min-height: 40px; }
.st-key-tb_rail [class*="st-key-tbtool_"] [data-testid="stBaseButton-secondary"] {
  color: var(--fap-text); background: var(--fap-surface); border: 1px solid var(--fap-border); }
.st-key-tb_rail [class*="st-key-tbtool_"] [data-testid="stBaseButton-secondary"]:hover {
  color: var(--fap-primary); border-color: var(--fap-primary); }
/* tighten the vertical gaps so tools + library read as ONE cohesive panel, not stacked blocks */
.st-key-tb_rail [data-testid="stVerticalBlock"] { gap: .35rem; }
.tb-rail-sep { height: 1px; background: var(--fap-border); margin: 7px 4px; }
.tb-board { background: var(--fap-surface); border: 1px solid var(--fap-border);
  border-radius: 14px; padding: 10px; box-shadow: var(--fap-shadow-sm); }
.tb-timeline-wrap { background: var(--fap-surface); border: 1px solid var(--fap-border);
  border-radius: 12px; padding: 10px 12px; margin-top: 14px; }
/* ---- Phase 5: dominant pitch --------------------------------------------------
   Let the Tactical Board use the FULL viewport width so the pitch is the dominant
   element (the global brand cap on .block-container leaves ~half the screen empty).
   This <style> lives in the DOM only while THIS page renders, so it is page-scoped:
   navigating away removes it and every other page keeps the brand max-width. */
[data-testid="stMainBlockContainer"], .block-container { max-width: 100% !important; }
/* ---- Phase 5: toolbar cluster labels (History · Board · View · Object · File) -- */
.tb-cluster { font-size: 10px; font-weight: 700; letter-spacing: .09em; text-transform: uppercase;
  color: var(--fap-text-subtle); margin: 0 2px 5px; text-align: center; }
/* ---- Phase 5: palette rail reads as icon + LABEL rows (left-aligned) ----------- */
.st-key-tb_rail [class*="st-key-tbtool_"] button { justify-content: flex-start; gap: 10px;
  padding-left: 12px; font-weight: 600; text-align: left; }
.st-key-tb_rail [data-testid="stPopoverButton"] { justify-content: flex-start; gap: 10px;
  padding-left: 12px; font-weight: 600; }
</style>
""", unsafe_allow_html=True)
