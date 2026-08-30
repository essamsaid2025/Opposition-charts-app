"""Streamlit static component for the Telestration page — a purpose-built HTML5 Canvas editor for
drawing analysis annotations over a photo (NOT the tactical board component).

The browser owns all interaction and rendering (image + annotations on one canvas) and reports its
state back as plain JSON. ``parse_result`` is the trust boundary: it validates every annotation
before Python stores it. Two value kinds arrive:

* ``sync``  — the current annotation list, after any edit (debounced client-side). Python just
  persists it; it never pushes the list back on a normal rerun (the client keeps its own state,
  gated by ``load_nonce``), so drawing is never interrupted.
* ``export`` — a one-shot ``{png: <data URL>}`` composited at the image's natural resolution when
  the user clicks Download; Python decodes it and offers a real download.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

_DIR = Path(__file__).resolve().parent / "frontend" / "telestration_canvas"
_impl: Any = None

_ANN_TYPES = frozenset({"arrow", "line", "spotlight", "ellipse", "rect", "pen", "text"})


def _component():
    global _impl
    if _impl is None:
        import streamlit.components.v1 as components
        _impl = components.declare_component("fap_telestration_canvas", path=str(_DIR))
    return _impl


def _num(v: Any, d: float = 0.0) -> float:
    return float(v) if isinstance(v, (int, float)) else d


def _clean_ann(a: Any) -> dict[str, Any] | None:
    """Validate one annotation into a tight, typed dict — or ``None``. This is the only path
    annotations take from the browser into Python state, so it is deliberately strict."""
    if not isinstance(a, dict):
        return None
    t = a.get("type")
    if t not in _ANN_TYPES:
        return None
    out: dict[str, Any] = {"type": t}
    col = a.get("c")
    out["c"] = col if isinstance(col, str) and 0 < len(col) <= 9 else "#ffffff"
    out["w"] = max(0.5, min(80.0, _num(a.get("w"), 8.0)))
    if a.get("g") and t in ("spotlight", "ellipse"):     # perspective (ground-plane) mark
        out["g"] = True
        out["gx"] = _num(a.get("gx")); out["gy"] = _num(a.get("gy"))
        out["gr"] = max(0.0, _num(a.get("gr")))
        return out
    if t == "pen":
        pts = a.get("pts")
        if not isinstance(pts, list) or len(pts) < 2:
            return None
        clean: list[list[float]] = []
        for p in pts[:2000]:
            if isinstance(p, (list, tuple)) and len(p) == 2:
                clean.append([_num(p[0]), _num(p[1])])
        if len(clean) < 2:
            return None
        out["pts"] = clean
        return out
    if t == "text":
        txt = a.get("text")
        if not isinstance(txt, str) or not txt.strip():
            return None
        out["text"] = txt[:200]
        out["x1"] = _num(a.get("x1")); out["y1"] = _num(a.get("y1"))
        out["size"] = max(8.0, min(400.0, _num(a.get("size"), 34.0)))
        return out
    # geometric marks carry two endpoints
    for k in ("x1", "y1", "x2", "y2"):
        out[k] = _num(a.get(k))
    return out


def clean_anns(raw: Any) -> list[dict[str, Any]]:
    """Validate a whole annotation list (caps the count)."""
    out: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for a in raw[:500]:
            c = _clean_ann(a)
            if c is not None:
                out.append(c)
    return out


def clean_persp(raw: Any) -> list[list[float]] | None:
    """Validate the 4-point perspective calibration (image pixel corners) or ``None``."""
    if not isinstance(raw, list) or len(raw) != 4:
        return None
    pts: list[list[float]] = []
    for p in raw:
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            return None
        pts.append([_num(p[0]), _num(p[1])])
    return pts


def parse_result(value: Any) -> dict[str, Any] | None:
    """Normalise the raw component value into ``{ts, kind, anns, persp[, png]}`` or ``None``.
    Never raises."""
    if not isinstance(value, dict):
        return None
    ts = value.get("ts")
    kind = value.get("kind")
    if not isinstance(ts, (int, float)) or kind not in ("sync", "export"):
        return None
    out: dict[str, Any] = {"ts": float(ts), "kind": kind, "anns": clean_anns(value.get("anns")),
                           "persp": clean_persp(value.get("persp"))}
    if kind == "export":
        png = value.get("png")
        if isinstance(png, str) and png.startswith("data:image/"):
            out["png"] = png
    return out


def telestration_canvas(*, image: str, anns: list[dict[str, Any]], load_nonce: int,
                        editable: bool, key: str,
                        persp: list[list[float]] | None = None) -> tuple[bool, dict[str, Any] | None]:
    """Render the editor and return ``(rendered, result)``. ``rendered`` is False only when the
    component could not mount. ``image`` is the background data URL (or ""), ``anns`` the saved
    annotations and ``persp`` the saved perspective calibration to adopt when ``load_nonce``
    changes, ``editable`` gates all interaction."""
    try:
        value = _component()(image=image or "", anns=list(anns or []),
                             persp=list(persp) if persp else None,
                             load_nonce=int(load_nonce), editable=bool(editable),
                             key=key, default=None)
    except Exception:
        return False, None
    return True, parse_result(value)
