"""Professional preview view-model (pure).

Turns a normalized frame into a paginated, filterable, sortable, searchable table
description with per-cell error/warning highlighting. This is presentation logic
the pipeline does not provide (not analytics, not validation logic) — it *reads*
the frame and reuses the platform's schema + known-event vocabulary to decide
what to highlight. Only the requested page is materialized, so a 200k-row frame
previews instantly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from fap.pipeline.schema import REQUIRED
from fap.pipeline.validation import KNOWN_EVENTS


@dataclass(slots=True)
class PreviewRequest:
    page: int = 1
    page_size: int = 25
    sort_by: str = ""
    sort_desc: bool = False
    search: str = ""
    columns: tuple[str, ...] = ()          # empty = all
    highlight: bool = True


@dataclass(slots=True)
class PreviewResult:
    columns: list[str]
    rows: list[dict[str, Any]]             # index 0..n of the page, col -> value
    flags: list[dict[str, str]]            # parallel to rows: col -> "error"|"warning"
    total: int
    page: int
    pages: int
    page_size: int
    freeze: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"columns": self.columns, "rows": self.rows, "flags": self.flags,
                "total": self.total, "page": self.page, "pages": self.pages,
                "page_size": self.page_size, "freeze": self.freeze}


def build_preview(frame: pd.DataFrame, request: PreviewRequest | None = None) -> PreviewResult:
    req = request or PreviewRequest()
    if frame is None or frame.empty:
        return PreviewResult(columns=[], rows=[], flags=[], total=0, page=1, pages=0,
                             page_size=req.page_size)

    cols = [c for c in (req.columns or list(frame.columns)) if c in frame.columns]
    view = frame[cols] if cols else frame

    # search: case-insensitive substring across all selected columns
    if req.search.strip():
        needle = req.search.strip().lower()
        mask = pd.Series(False, index=view.index)
        for c in view.columns:
            mask = mask | view[c].astype(str).str.lower().str.contains(needle, na=False, regex=False)
        view = view[mask]

    # sort
    if req.sort_by and req.sort_by in view.columns:
        view = view.sort_values(req.sort_by, ascending=not req.sort_desc, kind="stable")

    total = int(len(view))
    page_size = max(1, int(req.page_size))
    pages = max(1, (total + page_size - 1) // page_size)
    page = min(max(1, int(req.page)), pages)
    start = (page - 1) * page_size
    page_df = view.iloc[start:start + page_size]

    rows: list[dict[str, Any]] = []
    flags: list[dict[str, str]] = []
    for _, r in page_df.iterrows():
        row: dict[str, Any] = {}
        flag: dict[str, str] = {}
        for c in view.columns:
            val = r[c]
            row[c] = "" if pd.isna(val) else val
            if req.highlight:
                level = _cell_flag(c, val)
                if level:
                    flag[c] = level
        rows.append(row)
        flags.append(flag)

    freeze = [c for c in ("match_id", "team", "player", "event_type") if c in view.columns][:2]
    return PreviewResult(columns=list(view.columns), rows=rows, flags=flags, total=total,
                         page=page, pages=pages, page_size=page_size, freeze=freeze)


def _cell_flag(col: str, value: Any) -> str:
    """error = breaks a hard requirement; warning = suspicious but usable.

    x/y are required, so a missing or out-of-range value is an error. end_x/end_y
    are optional (many event types have no end point), so a blank is NOT flagged —
    only a present-but-out-of-range value warns. This avoids marking every row of
    a dataset that simply has no pass end coordinates.
    """
    if col in ("x", "y"):
        try:
            v = float(value)
        except (TypeError, ValueError):
            return "error"
        if pd.isna(v) or not (0 <= v <= 100):
            return "error"
        return ""
    if col in ("end_x", "end_y"):
        if value == "" or pd.isna(value):
            return ""                      # optional — blank is fine
        try:
            v = float(value)
        except (TypeError, ValueError):
            return "warning"
        return "" if 0 <= v <= 100 else "warning"
    if col == "event_type":
        s = str(value).strip().lower()
        if not s:
            return "error"
        return "warning" if s not in KNOWN_EVENTS else ""
    return ""


__all__ = ["PreviewRequest", "PreviewResult", "build_preview"]
