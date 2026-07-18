"""Bidirectional canvas component (no build step).

Streamlit's ``declare_component(path=...)`` serves the static ``frontend/`` dir in
an iframe; ``frontend/index.html`` speaks the component postMessage protocol by
hand, so there is no Node/React toolchain. The frontend returns ONLY geometry and
intent (move/resize/select/delete/...); it never mutates the document. Python maps
each returned action onto a pure :mod:`fap.reports.editor_ops` call, so all report
truth continues to flow through the Phase-6A operations and ``update_studio``.

If the component cannot initialize for any reason, ``canvas`` returns ``None`` and
the editor falls back to its native control surface - the editor is fully usable
without the iframe.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

_FRONTEND = Path(__file__).parent / "frontend"
_component = None


class _Unavailable:
    """Sentinel: the custom component could not be created/rendered at all (as
    opposed to being rendered fine but returning None because the user has not
    produced a new action this run)."""
    __slots__ = ()


UNAVAILABLE = _Unavailable()


def _get_component():
    global _component
    if _component is None:
        import streamlit.components.v1 as components
        _component = components.declare_component("fap_report_canvas", path=str(_FRONTEND))
    return _component


def canvas(*, page: dict[str, Any], blocks: list[dict[str, Any]], zoom: float,
           grid: int, snap: bool, guides: bool, rulers_grid: bool, aspect: bool,
           selected: list[str], theme: dict[str, str], key: str) -> Any:
    """Render the interactive canvas and return the last user action.

    Returns the action dict when the user just did something, ``None`` when the
    canvas rendered fine but there is no new action this run, or ``UNAVAILABLE``
    when the component itself could not be created/rendered (so the caller shows
    its native fallback controls).

    Action shape (examples): {"action":"move","block_id":..,"x":..,"y":..,"nonce":..},
    {"action":"resize","id":..,"x":..,"y":..,"w":..,"h":..}, {"action":"select",..},
    {"action":"multiselect","ids":[..]}, {"action":"delete","ids":[..]},
    {"action":"duplicate","ids":[..]}, {"action":"nudge","ids":[..],"dx":..,"dy":..},
    {"action":"deselect"}.
    """
    try:
        comp = _get_component()
        return comp(page=page, blocks=blocks, zoom=zoom, grid=grid, snap=snap,
                    guides=guides, rulers_grid=rulers_grid, aspect=aspect,
                    selected=selected, theme=theme, key=key, default=None)
    except Exception:
        return UNAVAILABLE
