"""Report Studio v2 — engine-independent document adapter (Phase A).

This module defines the **canonical, engine-independent** editor document used by
the new Konva-based Report Studio, and the seam that maps it to/from the existing
``ReportDocument`` for persistence. Konva (the rendering engine) never appears
here: the document is plain JSON — ``pages[] -> elements[]`` with stable ids and
neutral geometry (x, y, width, height, rotation) plus type-specific props. This
guarantees the persisted format is independent of the editor engine (swappable).

Storage strategy (backward compatible): the v2 document rides inside the existing
``ReportDocument.meta["studio_v2"]`` so persistence/versioning/autosave reuse the
unchanged ``ReportsManager`` path and legacy reports/exporters are untouched.
Phase A does not yet convert elements to/from the classic ``blocks`` (that is a
later phase); it round-trips the v2 document faithfully.
"""
from __future__ import annotations

import os
import uuid
from typing import Any

from fap.reports.models import ReportDocument

SCHEMA_VERSION = 1
META_KEY = "studio_v2"

# A4 at 96 DPI (matches the classic studio's default page pixel geometry).
DEFAULT_PAGE_W = 794
DEFAULT_PAGE_H = 1123
DEFAULT_BACKGROUND = "#ffffff"
DEFAULT_ACCENT = "#2f7bd6"

#: element types understood in Phase A (others are preserved verbatim).
KNOWN_TYPES = ("rect", "text")


# --------------------------------------------------------------------------- #
# Feature flag
# --------------------------------------------------------------------------- #
_TRUTHY = {"1", "true", "yes", "on"}


def v2_enabled() -> bool:
    """True iff the new Report Studio (v2) is enabled via ``FAP_REPORT_STUDIO_V2``.

    Off by default: the classic Report Studio stays the default and the v2 page is
    not even registered when this is false (see ``fap.ui.builtin.report_studio``).
    """
    return os.environ.get("FAP_REPORT_STUDIO_V2", "").strip().lower() in _TRUTHY


# --------------------------------------------------------------------------- #
# Construction / normalization
# --------------------------------------------------------------------------- #
def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def new_page(name: str = "Page 1") -> dict[str, Any]:
    return {
        "id": _uid("page"), "name": name,
        "width": DEFAULT_PAGE_W, "height": DEFAULT_PAGE_H,
        "background": DEFAULT_BACKGROUND, "elements": [],
    }


def new_document(title: str = "Untitled report", doc_id: str | None = None) -> dict[str, Any]:
    page = new_page("Page 1")
    return {
        "schema_version": SCHEMA_VERSION,
        "id": doc_id or _uid("doc"),
        "title": title or "Untitled report",
        "theme": {"background": DEFAULT_BACKGROUND, "accent": DEFAULT_ACCENT},
        "metadata": {},
        "active_page": page["id"],
        "pages": [page],
    }


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def _normalize_element(el: dict[str, Any]) -> dict[str, Any]:
    etype = str(el.get("type", "rect"))
    out: dict[str, Any] = {
        "id": str(el.get("id") or _uid(etype)),
        "type": etype,
        "x": _num(el.get("x", 0)), "y": _num(el.get("y", 0)),
        "width": _num(el.get("width", 120)),
        "rotation": _num(el.get("rotation", 0)),
    }
    if etype == "text":
        out["text"] = str(el.get("text", ""))
        out["fontSize"] = _num(el.get("fontSize", 20), 20)
        out["fill"] = str(el.get("fill", "#1b2430"))
    else:  # rect (and any unknown box-like type keep height/fill/stroke)
        out["height"] = _num(el.get("height", 80))
        out["fill"] = str(el.get("fill", "#eaf2fb"))
        out["stroke"] = str(el.get("stroke", "#2f7bd6"))
    return out


def _normalize_page(p: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(p.get("id") or _uid("page")),
        "name": str(p.get("name", "Page")),
        "width": int(_num(p.get("width", DEFAULT_PAGE_W), DEFAULT_PAGE_W)),
        "height": int(_num(p.get("height", DEFAULT_PAGE_H), DEFAULT_PAGE_H)),
        "background": str(p.get("background", DEFAULT_BACKGROUND)),
        "elements": [_normalize_element(e) for e in (p.get("elements") or []) if isinstance(e, dict)],
    }


def normalize(doc: dict[str, Any] | None) -> dict[str, Any]:
    """Return a valid, engine-independent v2 document (stable ids, ≥1 page,
    numeric geometry, valid ``active_page``). Never raises; never mutates input."""
    if not isinstance(doc, dict) or not doc.get("pages"):
        return new_document(str((doc or {}).get("title", "")) or "Untitled report",
                            doc_id=str((doc or {}).get("id")) if isinstance(doc, dict) and doc.get("id") else None)
    pages = [_normalize_page(p) for p in doc["pages"] if isinstance(p, dict)]
    if not pages:
        pages = [new_page()]
    page_ids = {p["id"] for p in pages}
    active = doc.get("active_page")
    theme = doc.get("theme") if isinstance(doc.get("theme"), dict) else {}
    return {
        "schema_version": int(_num(doc.get("schema_version", SCHEMA_VERSION), SCHEMA_VERSION)),
        "id": str(doc.get("id") or _uid("doc")),
        "title": str(doc.get("title", "") or "Untitled report"),
        "theme": {"background": str(theme.get("background", DEFAULT_BACKGROUND)),
                  "accent": str(theme.get("accent", DEFAULT_ACCENT))},
        "metadata": doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {},
        "active_page": active if active in page_ids else pages[0]["id"],
        "pages": pages,
    }


def validate(doc: dict[str, Any]) -> list[str]:
    """Lightweight structural check — returns a list of problems (empty = ok)."""
    problems: list[str] = []
    if not isinstance(doc, dict):
        return ["document is not an object"]
    if not doc.get("pages"):
        problems.append("document has no pages")
    for p in doc.get("pages", []):
        if not p.get("id"):
            problems.append("a page has no id")
        for e in p.get("elements", []):
            if not e.get("id"):
                problems.append("an element has no id")
    return problems


# --------------------------------------------------------------------------- #
# Persistence seam: v2 document <-> existing ReportDocument
# --------------------------------------------------------------------------- #
def to_report_document(v2doc: dict[str, Any], *, report_id: str | None = None,
                       title: str | None = None) -> ReportDocument:
    """Fold a v2 document into a ``ReportDocument`` for storage.

    The v2 payload is stored under ``meta["studio_v2"]`` (additive, backward
    compatible). Classic ``blocks``/``sections`` are left empty in Phase A, so
    existing exporters/renderers see a valid, empty document and are unaffected.
    """
    v2 = normalize(v2doc)
    rid = report_id or v2["id"]
    rd = ReportDocument(id=rid, title=title or v2.get("title") or "Untitled report")
    meta = dict(rd.meta or {})
    meta[META_KEY] = v2
    rd.meta = meta
    return rd


def from_report_document(rd: ReportDocument | dict[str, Any]) -> dict[str, Any]:
    """Extract (or synthesize) the v2 document from a ``ReportDocument``.

    If the report carries a v2 overlay it is returned (normalized). Otherwise a
    fresh, empty v2 document is synthesized with the report's id/title — a legacy
    report opens as an empty v2 canvas (element migration from ``blocks`` is a
    later phase; Phase A never loses or fabricates classic content)."""
    meta = (rd.get("meta") if isinstance(rd, dict) else (rd.meta or {})) or {}
    rid = rd.get("id") if isinstance(rd, dict) else rd.id
    title = rd.get("title") if isinstance(rd, dict) else rd.title
    overlay = meta.get(META_KEY)
    if isinstance(overlay, dict) and overlay.get("pages"):
        doc = normalize(overlay)
        doc["id"] = str(rid or doc["id"])
        return doc
    return new_document(str(title or "Untitled report"), doc_id=str(rid) if rid else None)
