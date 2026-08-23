"""Export adapters — the tagging session's outputs.

* :func:`session_to_csv` writes the STABLE analytical CSV (fixed column order,
  blank/NULL for irrelevant fields, ``coordinate_space`` marking pitch vs goal).
* :func:`session_to_canonical_frame` bridges the tags into the canonical event
  DataFrame the FAP visualization engine consumes (so a Pass/Shot/Goal-mouth/
  Penalty map can render tagged data with no bespoke pipeline).
* :func:`to_project_dict` / :func:`project_from_dict` are the JSON project format
  (session + metadata + presets + history + UI state) — never mixed into the CSV.
"""
from __future__ import annotations

import csv
import io
from typing import Any

from fap.tagging.models import TaggingSession
from fap.tagging.schema import tag_by_key

# Stable, deterministic CSV schema (section 23). Never varies by event type.
CSV_COLUMNS: tuple[str, ...] = (
    "event_id", "match_id", "team", "player", "period", "minute", "second",
    "event_type", "outcome", "coordinate_space", "x", "y", "x2", "y2",
    "goal_x", "goal_y", "notes",
)


def _cell(value: Any) -> Any:
    return "" if value is None else value


def session_to_rows(session: TaggingSession) -> list[dict[str, Any]]:
    """One dict per event with exactly ``CSV_COLUMNS`` keys (unused fields blank)."""
    rows: list[dict[str, Any]] = []
    for e in session.events:
        rows.append({
            "event_id": e.id, "match_id": session.match_id, "team": e.team,
            "player": e.player, "period": e.period, "minute": _cell(e.minute),
            "second": _cell(e.second), "event_type": e.event_type,
            "outcome": e.outcome, "coordinate_space": e.coordinate_space,
            "x": _cell(e.x), "y": _cell(e.y), "x2": _cell(e.x2), "y2": _cell(e.y2),
            "goal_x": _cell(e.goal_x), "goal_y": _cell(e.goal_y), "notes": e.notes,
        })
    return rows


def session_to_csv(session: TaggingSession) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(CSV_COLUMNS), extrasaction="ignore",
                            lineterminator="\n")
    writer.writeheader()
    writer.writerows(session_to_rows(session))
    return buf.getvalue()


# ------------------------------------------------------------------ viz bridge
# Map a goal_x (0..100 across the goal) onto the canonical goal-mouth y where the
# GoalMouthMap draws the posts (canonical end_y 44..56), and onto the 3x3 penalty
# grid used by the set-piece placement maps. Purely a rendering convenience — the
# stored canonical coordinates are unchanged.
def _end_y_from_goal_x(goal_x: float) -> float:
    return round(44.0 + max(0.0, min(100.0, goal_x)) / 100.0 * 12.0, 3)


def _grid(v: float) -> int:
    return max(0, min(2, int(max(0.0, min(100.0, v)) / 100.0 * 3.0)))


def session_to_canonical_frame(session: TaggingSession):
    """A canonical event DataFrame consumable by the FAP visualization engine.

    Pitch events map to ``x/y`` (+ ``end_x/end_y`` for lines); shots carry
    ``shot_result``. Goal events are emitted as ``event_type='shot'`` with
    ``end_y`` across the goal and ``gx/gy`` for penalty grids, while keeping the
    original ``goal_x/goal_y`` columns.
    """
    import numpy as np
    import pandas as pd

    records: list[dict[str, Any]] = []
    for e in session.events:
        tag = tag_by_key(e.event_type)
        space = e.coordinate_space
        rec: dict[str, Any] = {
            "event_id": e.id, "event_type": e.event_type, "team": e.team,
            "player": e.player, "period": e.period, "minute": e.minute,
            "second": e.second, "outcome": e.outcome, "coordinate_space": space,
            "notes": e.notes, "video_timestamp": e.video_timestamp,
            "x": np.nan, "y": np.nan, "end_x": np.nan, "end_y": np.nan,
            "goal_x": np.nan, "goal_y": np.nan, "gx": np.nan, "gy": np.nan,
            "shot_result": "",
        }
        if space == "goal":
            rec["event_type"] = "shot"                 # so GoalMouthMap consumes it
            rec["goal_x"], rec["goal_y"] = e.goal_x, e.goal_y
            if e.goal_x is not None:
                rec["end_y"] = _end_y_from_goal_x(e.goal_x)
                rec["gx"] = _grid(e.goal_x)
            if e.goal_y is not None:
                rec["gy"] = _grid(e.goal_y)
            rec["end_x"] = 100.0
            rec["shot_result"] = e.outcome or ("Goal" if e.event_type == "goal" else "Saved")
            rec["saved"] = bool(e.outcome == "Saved" or e.event_type in ("save", "gk_save_location"))
        else:
            rec["x"], rec["y"] = e.x, e.y
            if tag is not None and tag.geometry == "line":
                rec["end_x"], rec["end_y"] = e.x2, e.y2
            if e.event_type == "shot":
                rec["shot_result"] = e.outcome or "Saved"
        records.append(rec)
    columns = ["event_id", "event_type", "team", "player", "period", "minute",
               "second", "outcome", "coordinate_space", "x", "y", "end_x", "end_y",
               "goal_x", "goal_y", "gx", "gy", "shot_result", "notes",
               "video_timestamp"]
    return pd.DataFrame(records, columns=columns) if records else pd.DataFrame(columns=columns)


# ------------------------------------------------------------------ project json
PROJECT_FORMAT = "fap_tagging_project"
PROJECT_VERSION = 1


def to_project_dict(session: TaggingSession, *, ui_state: dict[str, Any] | None = None,
                    name: str = "") -> dict[str, Any]:
    return {"format": PROJECT_FORMAT, "version": PROJECT_VERSION, "name": name,
            "session": session.to_dict(include_history=True),
            "ui_state": dict(ui_state or {})}


def project_from_dict(d: dict[str, Any]) -> tuple[TaggingSession, dict[str, Any]]:
    d = d or {}
    session = TaggingSession.from_dict(d.get("session") or d)
    return session, dict(d.get("ui_state") or {})
