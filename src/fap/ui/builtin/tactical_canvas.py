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
ALLOWED_OPS: frozenset[str] = frozenset(
    {"add_object", "update_object", "delete_object", "duplicate_object"})

_DIR = Path(__file__).resolve().parent / "frontend" / "tactical_board"
_impl: Any = None


def _component():
    global _impl
    if _impl is None:
        import streamlit.components.v1 as components
        _impl = components.declare_component("fap_tactical_canvas", path=str(_DIR))
    return _impl


def _clean_command(cmd: Any) -> dict[str, Any] | None:
    """Keep only well-formed, allow-listed commands with sane primitive fields."""
    if not isinstance(cmd, dict):
        return None
    op = cmd.get("op")
    if op not in ALLOWED_OPS:
        return None
    out: dict[str, Any] = {"op": op}
    if "id" in cmd and isinstance(cmd["id"], str):
        out["id"] = cmd["id"]
    if "type" in cmd and isinstance(cmd["type"], str):
        out["type"] = cmd["type"]
    for k in ("x", "y"):
        if isinstance(cmd.get(k), (int, float)):
            out[k] = float(cmd[k])
    props = cmd.get("props")
    if isinstance(props, dict):
        out["props"] = {str(pk): pv for pk, pv in props.items()}
    # add_object needs a type; the mutating ops need an id
    if op == "add_object" and "type" not in out:
        return None
    if op in ("update_object", "delete_object", "duplicate_object") and "id" not in out:
        return None
    return out


def parse_result(value: Any) -> dict[str, Any] | None:
    """Normalise the raw component value into ``{"ts", "commands", "select"}`` or
    ``None``. ``ts`` is the browser's monotonic action counter used by the caller to
    ignore stale values Streamlit re-delivers on unrelated reruns. Only allow-listed,
    well-formed commands survive; everything else is dropped. Never raises."""
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
    if sel is not None and sel != "__keep__" and not isinstance(sel, str):
        sel = "__keep__"
    if not commands and sel == "__keep__":
        return None                       # nothing actionable
    return {"ts": float(ts), "commands": commands, "select": sel}


def tactical_canvas(svg: str, objects: list[dict[str, Any]], *, key: str,
                    colors: dict[str, str], palette: list[dict[str, Any]],
                    selected_id: str | None, snap: float, editable: bool,
                    nonce: str) -> tuple[bool, dict[str, Any] | None]:
    """Render the interactive board and return ``(rendered, intent)``.

    ``rendered`` is ``True`` when the iframe was mounted (so the caller must NOT also
    draw the static fallback - the browser is already showing the interactive board);
    it is ``False`` only when the component could not be created, in which case the
    page degrades to the static SVG + fallback sliders. ``intent`` is the parsed command
    batch (or ``None`` when the user has not interacted yet).

    ``svg`` is produced by ``board_svg`` (the Python renderer - reused, not rewritten);
    ``objects`` is lightweight metadata ``[{id,type,x,y,x2,y2,locked}]`` used only to
    place endpoint handles and respect locks. ``nonce`` stamps the current board version
    so Streamlit pushes a fresh render when state changes. Never raises."""
    try:
        value = _component()(svg=svg, objects=objects, colors=colors, palette=palette,
                             selected_id=selected_id, snap=float(snap),
                             editable=bool(editable), nonce=nonce, key=key, default=None)
    except Exception:
        return False, None
    return True, parse_result(value)
