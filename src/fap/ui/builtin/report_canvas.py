"""Report Studio free-form canvas (Phase 1 — MOVE only).

A tiny Streamlit *static* custom component — the exact same lightweight, no-build pattern
as ``fap.ui.builtin.tactical_canvas`` and ``fap.ui.studio.sortable``. It is the interaction
surface for a **free-form page**: blocks (already rendered to HTML by the existing exporter
logic) are placed at their stored x/y and made draggable. Dragging a block emits INTENT
ONLY — a ``{"op": "update_layout", "id", "x", "y"}`` command — which Python validates and
applies to the block's ``BlockLayout``. The component contains ZERO business logic; Python
owns every mutation, exactly like the Tactical Board canvas.

Phase 1 is deliberately move-only: no resize, no z-order (those are later phases).

``parse_result`` is the trust boundary: it validates/normalises whatever the browser sends
before any of it reaches the model, and is unit-tested without a browser. Never raises.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

# the only op the canvas may emit in Phase 1 (move). Resize/z-order come later and are
# rejected here defensively so a stray/forged message can never reach the model.
ALLOWED_OPS: frozenset[str] = frozenset({"update_layout"})

_DIR = Path(__file__).resolve().parent / "frontend" / "report_canvas"
_impl: Any = None


def _component():
    global _impl
    if _impl is None:
        import streamlit.components.v1 as components
        _impl = components.declare_component("fap_report_canvas", path=str(_DIR))
    return _impl


def _clean_command(cmd: Any) -> dict[str, Any] | None:
    """Keep only a well-formed, allow-listed ``update_layout`` with numeric x/y."""
    if not isinstance(cmd, dict):
        return None
    if cmd.get("op") not in ALLOWED_OPS:
        return None
    if not isinstance(cmd.get("id"), str) or not cmd["id"]:
        return None
    out: dict[str, Any] = {"op": "update_layout", "id": cmd["id"]}
    for k in ("x", "y"):
        v = cmd.get(k)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None                    # x/y are mandatory numbers for a move
        out[k] = float(v)
    return out


def parse_result(value: Any) -> dict[str, Any] | None:
    """Normalise the raw component value into ``{"ts", "commands"}`` or ``None``.

    ``ts`` is the browser's monotonic action counter the caller uses to ignore stale values
    Streamlit re-delivers on unrelated reruns. Only allow-listed, well-formed commands
    survive; everything else is dropped. Returns ``None`` when there is nothing actionable.
    Never raises."""
    if not isinstance(value, dict):
        return None
    ts = value.get("ts")
    if isinstance(ts, bool) or not isinstance(ts, (int, float)):
        return None
    commands = []
    for raw in value.get("commands") or []:
        clean = _clean_command(raw)
        if clean is not None:
            commands.append(clean)
    if not commands:
        return None                        # nothing actionable
    return {"ts": float(ts), "commands": commands}


def report_canvas(page: dict[str, Any], blocks: list[dict[str, Any]], *, key: str,
                  snap: float, zoom: float, editable: bool,
                  nonce: str) -> tuple[bool, dict[str, Any] | None]:
    """Render the free-form page and return ``(rendered, intent)``.

    ``rendered`` is ``True`` when the iframe mounted; ``False`` only when the component could
    not be created (the page then degrades to the static preview — positions are still
    saved). ``intent`` is the parsed command batch (or ``None`` when the user hasn't dragged).

    ``page`` = ``{"id","w","h","background"}`` (pixel dimensions from ``Page.dimensions()``).
    ``blocks`` = ``[{"id","x","y","w","h","locked","html"}]`` — each block's position/size in
    page pixels plus the HTML the EXISTING exporter renderer produced for it (reused, not
    reinvented). ``snap`` is the grid step in px (0 = off); ``zoom`` scales the display only.
    ``nonce`` stamps the current layout so Streamlit pushes a fresh render on change. Never
    raises."""
    try:
        value = _component()(page=page, blocks=blocks, snap=float(snap), zoom=float(zoom),
                             editable=bool(editable), nonce=nonce, key=key, default=None)
    except Exception:
        return False, None
    return True, parse_result(value)
