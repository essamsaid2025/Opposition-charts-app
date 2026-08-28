"""Phase 15 - the JavaScript drag-and-drop canvas (interaction layer ONLY).

This is a tiny Streamlit *static* custom component - the same lightweight, no-build
pattern as ``fap.ui.studio.sortable``. It swaps ONLY the render+input surface of the
Tactical Board: the pitch is still drawn by the pure Python renderer
(``fap.tactical.render.board_svg``) and handed to the browser as an SVG string; the
component adds pointer interaction (drag a piece, drag an arrow endpoint, drag a
palette chip onto the pitch, click to select, Delete to remove).

The component contains ZERO business logic. It only *reports intent* as the very same
JSON commands the model already understands (``add_object`` / ``update_object`` /
``delete_object``), which Python feeds through ``fap.tactical.ops.apply_command``. The
authoritative board, history, timeline, persistence, templates and export all stay in
Python, untouched. If the component cannot initialise, ``tactical_canvas`` returns
``None`` and the page falls back to the SVG view plus the (fallback-only) sliders.

``parse_result`` is the trust boundary: it validates and normalises whatever the
browser sends before any of it reaches the model, and is unit-tested without a browser.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

# object-level ops the canvas is permitted to emit. Frame/pitch/board ops are driven by
# native Streamlit controls, never by the canvas - so we reject them here defensively.
# Single-object ops (endpoint/rotate/palette add) + the Phase-3 batch ops the marquee /
# keyboard / group-drag layer emits (multi-select delete/duplicate/move/z-order/align/…).
_SINGLE_OPS: frozenset[str] = frozenset(
    {"add_object", "update_object", "delete_object", "duplicate_object"})
_BATCH_OPS: frozenset[str] = frozenset(
    {"delete_objects", "duplicate_objects", "move_objects", "group_objects",
     "ungroup_objects", "reorder_object", "set_hidden", "set_locked",
     "align_objects", "distribute_objects"})
ALLOWED_OPS: frozenset[str] = _SINGLE_OPS | _BATCH_OPS

_DIR = Path(__file__).resolve().parent / "frontend" / "tactical_board"
_impl: Any = None


def _component():
    global _impl
    if _impl is None:
        import streamlit.components.v1 as components
        _impl = components.declare_component("fap_tactical_canvas", path=str(_DIR))
    return _impl


_REORDER_DIRS = frozenset({"front", "back", "forward", "backward"})
_ALIGN_KINDS = frozenset({"left", "right", "top", "bottom", "center_h", "center_v"})


def _clean_command(cmd: Any) -> dict[str, Any] | None:
    """Keep only well-formed, allow-listed commands with sane primitive fields. Single-
    object ops carry an ``id`` + x/y/rotation/props; batch ops carry an ``ids`` list plus
    a tight per-op set of typed scalars. Anything else is dropped."""
    if not isinstance(cmd, dict):
        return None
    op = cmd.get("op")
    if op not in ALLOWED_OPS:
        return None
    out: dict[str, Any] = {"op": op}

    if op in _SINGLE_OPS:
        if isinstance(cmd.get("id"), str):
            out["id"] = cmd["id"]
        if isinstance(cmd.get("type"), str):
            out["type"] = cmd["type"]
        # object-level numeric fields the canvas may set directly (NOT via props). The
        # rotate handle emits rotation; scale is deliberately excluded (resize sends w/h
        # in props) — the trust boundary stays as tight as what is actually used.
        for k in ("x", "y", "rotation"):
            if isinstance(cmd.get(k), (int, float)):
                out[k] = float(cmd[k])
        props = cmd.get("props")
        if isinstance(props, dict):
            out["props"] = {str(pk): pv for pk, pv in props.items()}
        if op == "add_object" and "type" not in out:
            return None
        if op in ("update_object", "delete_object", "duplicate_object") and "id" not in out:
            return None
        return out

    # batch ops: an ``ids`` list (a lone ``id`` is accepted and promoted) + typed scalars.
    ids = cmd.get("ids")
    if isinstance(ids, list):
        out["ids"] = [i for i in ids if isinstance(i, str) and i]
    elif isinstance(cmd.get("id"), str) and cmd["id"]:
        out["ids"] = [cmd["id"]]
    if not out.get("ids"):
        return None
    if op == "move_objects":
        for k in ("dx", "dy"):
            out[k] = float(cmd[k]) if isinstance(cmd.get(k), (int, float)) else 0.0
    elif op == "reorder_object":
        out["dir"] = cmd["dir"] if cmd.get("dir") in _REORDER_DIRS else "forward"
    elif op == "set_hidden":
        out["hidden"] = bool(cmd.get("hidden", True))
    elif op == "set_locked":
        out["locked"] = bool(cmd.get("locked", True))
    elif op == "align_objects":
        out["align"] = cmd["align"] if cmd.get("align") in _ALIGN_KINDS else "left"
    elif op == "distribute_objects":
        out["axis"] = cmd["axis"] if cmd.get("axis") in ("horizontal", "vertical") else "horizontal"
    if op in ("group_objects", "ungroup_objects") and isinstance(cmd.get("group"), str):
        out["group"] = cmd["group"]
    return out


def parse_result(value: Any) -> dict[str, Any] | None:
    """Normalise the raw component value into ``{"ts", "commands", "select"[, "draw_reset"]}``
    or ``None``. ``ts`` is the browser's monotonic action counter used by the caller to ignore
    stale values Streamlit re-delivers on unrelated reruns. Only allow-listed, well-formed
    commands survive; everything else is dropped. ``draw_reset`` is a UI-only intent (like
    ``select`` - NOT a board command / not an ``ops.py`` op) the canvas sets when the user
    presses Escape to leave draw mode; the caller resets the armed tool. Never raises."""
    if not isinstance(value, dict):
        return None
    ts = value.get("ts")
    if not isinstance(ts, (int, float)):
        return None
    commands = []
    for raw in value.get("commands") or []:
        clean = _clean_command(raw)
        if clean is not None:
            commands.append(clean)
    sel = value.get("select", "__keep__")
    if sel is not None and sel != "__keep__":
        if isinstance(sel, list):                      # multi-select (marquee / shift-click)
            sel = [s for s in sel if isinstance(s, str) and s]
        elif not isinstance(sel, str):
            sel = "__keep__"
    draw_reset = value.get("draw_reset") is True
    undo = value.get("undo") is True     # UI-only intents (like draw_reset) — Ctrl+Z / Ctrl+Y on
    redo = value.get("redo") is True     # the canvas; the caller drives History, not the model.
    action = _clean_action(value.get("action"))   # in-board top bar / modals (grid/orientation/…)
    if (not commands and sel == "__keep__" and not draw_reset and not undo and not redo
            and action is None):
        return None                       # nothing actionable
    out: dict[str, Any] = {"ts": float(ts), "commands": commands, "select": sel}
    if draw_reset:
        out["draw_reset"] = True
    if undo:
        out["undo"] = True
    if redo:
        out["redo"] = True
    if action is not None:
        out["action"] = action
    return out


# UI actions the in-board top bar / modals may emit (NOT board ops — the host maps them to the
# same session/service calls the old Streamlit toolbar used). Kept as a tight allow-list with
# typed params, exactly like the batch-op trust boundary.
_ACTION_NAMES: frozenset[str] = frozenset(
    {"new", "grid", "snap", "orientation", "add_frame", "del_frame", "goto_frame",
     "theme", "formation", "template"})


def _clean_action(a: Any) -> dict[str, Any] | None:
    """Validate one UI action into ``{"name", ...typed params}`` or ``None``."""
    if not isinstance(a, dict):
        return None
    name = a.get("name")
    if name not in _ACTION_NAMES:
        return None
    out: dict[str, Any] = {"name": name}
    if name in ("grid", "snap"):
        out["on"] = bool(a.get("on", True))
    elif name == "goto_frame":
        try:
            out["index"] = int(a.get("index", 0))
        except (TypeError, ValueError):
            out["index"] = 0
    elif name in ("theme", "template"):
        out["id"] = str(a.get("id", ""))
    elif name == "formation":
        out["team"] = "away" if str(a.get("team")) == "away" else "home"
        out["formation"] = str(a.get("formation", ""))
        rows = a.get("rows")
        clean_rows: list[dict[str, Any]] = []
        if isinstance(rows, list):
            for r in rows[:40]:
                if not isinstance(r, dict):
                    continue
                clean_rows.append({"name": str(r.get("name", ""))[:40],
                                   "number": str(r.get("number", ""))[:4],
                                   "pos": str(r.get("pos", ""))[:6]})
        out["rows"] = clean_rows
    return out


def tactical_canvas(svg: str, objects: list[dict[str, Any]], *, key: str,
                    colors: dict[str, str], palette: list[dict[str, Any]],
                    selected_id: str | None, snap: float, editable: bool,
                    nonce: str, draw_tool: dict[str, Any] | None = None,
                    selected_ids: list[str] | None = None,
                    board_state: dict[str, Any] | None = None
                    ) -> tuple[bool, dict[str, Any] | None]:
    """Render the interactive board and return ``(rendered, intent)``.

    ``rendered`` is ``True`` when the iframe was mounted (so the caller must NOT also
    draw the static fallback - the browser is already showing the interactive board);
    it is ``False`` only when the component could not be created, in which case the
    page degrades to the static SVG + fallback sliders. ``intent`` is the parsed command
    batch (or ``None`` when the user has not interacted yet).

    ``svg`` is produced by ``board_svg`` (the Python renderer - reused, not rewritten);
    ``objects`` is lightweight metadata ``[{id,type,x,y,x2,y2,locked}]`` used only to
    place endpoint handles and respect locks. ``draw_tool`` (optional) is
    ``{"type": <object type>, "props": <default props>}`` arming the click-drag "draw"
    mode, or ``None`` (the default) for the unchanged behaviour. ``nonce`` stamps the
    current board version so Streamlit pushes a fresh render when state changes. Never
    raises. A drawn object still emits the SAME ``add_object`` command shape as every
    other add - the trust boundary (``parse_result``) is unchanged."""
    try:
        value = _component()(svg=svg, objects=objects, colors=colors, palette=palette,
                             selected_id=selected_id, selected_ids=list(selected_ids or []),
                             snap=float(snap), editable=bool(editable), draw_tool=draw_tool,
                             board_state=dict(board_state or {}),
                             nonce=nonce, key=key, default=None)
    except Exception:
        return False, None
    return True, parse_result(value)
