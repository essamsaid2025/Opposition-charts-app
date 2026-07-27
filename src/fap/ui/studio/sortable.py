"""Drag-and-drop section reordering (UI only).

A tiny Streamlit *static* custom component: the browser renders a draggable list
and, on drop, reports the new id order back to Python. It contains ZERO mutation
logic — exactly like the (now-removed) 6B canvas, it only *reports intent*; Python
maps the reported order onto the pure ``reorder_blocks`` op through
``update_studio`` (autosave). This keeps the single-source-of-truth invariant: the
database document is authoritative.

It is deliberately lightweight (a small list, no charts, no per-run work) so it
never reintroduces the 6B/6D performance problems. If the component cannot
initialise for any reason, ``sortable`` returns ``None`` and the editor falls back
to explicit move controls — the workspace is always usable.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

_DIR = Path(__file__).resolve().parent / "frontend" / "sortable"
_impl: Any = None


def _component():
    global _impl
    if _impl is None:
        import streamlit.components.v1 as components
        _impl = components.declare_component("fap_sortable", path=str(_DIR))
    return _impl


def sortable(items: list[dict[str, Any]], *, key: str, colors: dict[str, str],
             nonce: str) -> dict[str, Any] | None:
    """Render the draggable section list. ``items`` is ``[{id,title,badge,kind,
    hidden}]``; ``nonce`` stamps the current state so the caller can ignore stale
    values Streamlit re-delivers on plain reruns. Returns ``{"order": [ids],
    "nonce": str}`` after a drop, else ``None``. Never raises — a failure to
    initialise degrades to the native fallback controls."""
    try:
        value = _component()(items=items, colors=colors, nonce=nonce, key=key, default=None)
    except Exception:
        return None
    if isinstance(value, dict):
        order = value.get("order")
        if isinstance(order, list) and all(isinstance(x, str) for x in order):
            return {"order": order, "nonce": str(value.get("nonce", ""))}
    return None
