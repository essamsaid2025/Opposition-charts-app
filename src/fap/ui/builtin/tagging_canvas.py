"""Interactive tagging canvas — the JS interaction layer ONLY.

A tiny Streamlit static component (same no-build pattern as ``tactical_canvas``).
The pitch and the goal are drawn by the PYTHON canonical renderers (PitchFactory
and ``fap.visuals.goal``) and handed to the browser as a background image; the
component adds pointer interaction (click to place a point, click-drag / two-click
to place a start→end line, hover coordinate readout, click a marker to select,
Delete/Escape) and reports the click as an **interior fraction** (0..1 within the
pitch/goal interior) — never pixels. Python converts that fraction to canonical
football coordinates with the pure ``fap.tagging.coordinates`` engine.

The component contains ZERO business logic. ``parse_result`` is the trust boundary:
it validates and clamps whatever the browser sends before it reaches the session,
and is unit-tested without a browser.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

_ACTIONS = frozenset({"point", "line", "select", "delete", "cancel"})
_DIR = Path(__file__).resolve().parent / "frontend" / "tagging_canvas"
_impl: Any = None


def _component():
    global _impl
    if _impl is None:
        import streamlit.components.v1 as components
        _impl = components.declare_component("fap_tagging_canvas", path=str(_DIR))
    return _impl


def _frac(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    return max(0.0, min(1.0, float(value)))


def parse_result(value: Any) -> dict[str, Any] | None:
    """Normalise the raw component value into a clean intent dict, or ``None``.

    ``ts`` is the browser's monotonic action counter (callers ignore stale reruns).
    Fractions are clamped to ``[0, 1]``. Only allow-listed actions survive; anything
    malformed is dropped. Never raises."""
    if not isinstance(value, dict):
        return None
    ts = value.get("ts")
    if not isinstance(ts, (int, float)):
        return None
    action = value.get("action")
    if action not in _ACTIONS:
        return None
    out: dict[str, Any] = {"ts": float(ts), "action": action}
    if action == "point":
        fx, fy = _frac(value.get("ifx")), _frac(value.get("ify"))
        if fx is None or fy is None:
            return None
        out["ifx"], out["ify"] = fx, fy
    elif action == "line":
        for k in ("ifx", "ify", "ifx2", "ify2"):
            f = _frac(value.get(k))
            if f is None:
                return None
            out[k] = f
    elif action == "select":
        sel = value.get("select")
        if not isinstance(sel, str) or not sel:
            return None
        out["select"] = sel
    # "delete" and "cancel" carry no payload
    return out


def tagging_canvas(*, image: str, overlay: list[dict[str, Any]], mode: str,
                   readout: dict[str, Any], colors: dict[str, str], nonce: str,
                   key: str, editable: bool = True) -> tuple[bool, dict[str, Any] | None]:
    """Render the interactive canvas and return ``(rendered, intent)``.

    ``rendered`` is ``True`` when the iframe mounted (the caller then relies on the
    JS canvas for interaction); ``False`` means the component could not be created
    and the page must show its native coordinate-input fallback. ``image`` is the
    Python-rendered pitch/goal PNG (data URI) — the SAME canonical renderers used by
    every other map. ``overlay`` lists markers in interior-fraction coordinates for
    hit-testing/selection. ``readout`` carries the linear map so the browser can show
    a live canonical coordinate under the cursor. Never raises."""
    try:
        value = _component()(image=image, overlay=overlay, mode=mode, readout=readout,
                             colors=colors, nonce=nonce, editable=bool(editable),
                             key=key, default=None)
    except Exception:
        return False, None
    return True, parse_result(value)
