"""Export adapters — the tagging session's outputs.

The CSV is a STABLE, Open-Play-compatible **canonical event** schema: it carries
the columns the FAP pipeline requires (``event_type``, ``x``, ``y``) plus
``end_x/end_y`` and ``shot_result`` so that a file exported here imports through the
Data Hub as an *event* dataset and renders directly on the Open Play maps (Shot Map,
Goal Mouth Map, Pass Map, …). Goal-mouth tags are emitted as ``event_type="shot"``
with the across-goal position written to ``end_y`` (the Goal Mouth Map's coordinate)
while the original tag and the raw ``goal_x/goal_y`` are preserved in their own
columns — nothing is lost, and no coordinate is fabricated.

* :func:`session_to_csv` — the analysis-ready / Open-Play-ready CSV.
* :func:`session_to_canonical_frame` — the same mapping as an in-memory DataFrame
  (adds ``gx/gy`` for penalty-grid maps), for direct rendering / tests.
* :func:`to_project_dict` / :func:`project_from_dict` — the JSON project format
  (session + history + UI state), never mixed into the CSV.
"""
from __future__ import annotations

import csv
import io
from typing import Any

from fap.tagging.models import TaggingSession
from fap.tagging.schema import tag_by_key

# Stable, deterministic CSV schema. Canonical event columns first (so the Open Play
# pipeline ingests it), then the tagging-specific columns.
CSV_COLUMNS: tuple[str, ...] = (
    "event_id", "match_id", "team", "player", "period", "minute", "second",
    "event_type", "tag_type", "outcome", "shot_result", "coordinate_space",
    "x", "y", "end_x", "end_y", "goal_x", "goal_y", "notes",
)

_PERIOD_NUM = {"1H": 1, "2H": 2, "ET1": 3, "ET2": 4, "Unknown": 1, "": 1}


def _cell(value: Any) -> Any:
    return "" if value is None else value


def _period_num(label: str) -> int:
    return _PERIOD_NUM.get(str(label), 1)


def _end_y_from_goal_x(goal_x: float) -> float:
    """Across-goal position (canonical goal-mouth ``end_y`` where the Goal Mouth Map
    draws the posts, 44..56) from ``goal_x`` (0..100 across the goal)."""
    return round(44.0 + max(0.0, min(100.0, goal_x)) / 100.0 * 12.0, 3)


def _grid(v: float) -> int:
    return max(0, min(2, int(max(0.0, min(100.0, v)) / 100.0 * 3.0)))


def _canonical_row(session: TaggingSession, e: Any) -> dict[str, Any]:
    """One event as a canonical, Open-Play-ingestible row (+ tagging columns)."""
    tag = tag_by_key(e.event_type)
    row: dict[str, Any] = {
        "event_id": e.id, "match_id": session.match_id, "team": e.team,
        "player": e.player, "period": _period_num(e.period), "minute": _cell(e.minute),
        "second": _cell(e.second), "event_type": e.event_type, "tag_type": e.event_type,
        "outcome": e.outcome, "shot_result": "", "coordinate_space": e.coordinate_space,
        "x": "", "y": "", "end_x": "", "end_y": "",
        "goal_x": _cell(e.goal_x), "goal_y": _cell(e.goal_y), "notes": e.notes,
    }
    if e.coordinate_space == "goal":
        # emit as a shot so A.shots / the Goal Mouth Map consume it; the across-goal
        # position becomes end_y (the map's coordinate). Pitch origin is unknown -> left blank.
        row["event_type"] = "shot"
        row["shot_result"] = e.outcome or ("Goal" if e.event_type == "goal" else "Saved")
        if e.goal_x is not None:
            row["end_x"] = 100.0
            row["end_y"] = _end_y_from_goal_x(e.goal_x)
    else:
        row["x"], row["y"] = _cell(e.x), _cell(e.y)
        if tag is not None and tag.geometry == "line":
            row["end_x"], row["end_y"] = _cell(e.x2), _cell(e.y2)
        if e.event_type == "shot":
            row["shot_result"] = e.outcome
    return row


def session_to_rows(session: TaggingSession) -> list[dict[str, Any]]:
    return [_canonical_row(session, e) for e in session.events]


def session_to_csv(session: TaggingSession) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(CSV_COLUMNS), extrasaction="ignore",
                            lineterminator="\n")
    writer.writeheader()
    writer.writerows(session_to_rows(session))
    return buf.getvalue()


# ------------------------------------------------------------------ viz frame
def session_to_canonical_frame(session: TaggingSession):
    """The same canonical mapping as an in-memory DataFrame, plus ``gx/gy`` (penalty
    grid) and ``saved`` for the set-piece maps. Blank cells become NaN."""
    import numpy as np
    import pandas as pd

    records: list[dict[str, Any]] = []
    for e in session.events:
        row = _canonical_row(session, e)
        for f in ("x", "y", "end_x", "end_y", "goal_x", "goal_y", "minute", "second"):
            if row.get(f) == "":
                row[f] = np.nan
        row["gx"] = _grid(e.goal_x) if (e.coordinate_space == "goal" and e.goal_x is not None) else np.nan
        row["gy"] = _grid(e.goal_y) if (e.coordinate_space == "goal" and e.goal_y is not None) else np.nan
        row["saved"] = bool(e.coordinate_space == "goal"
                            and (e.outcome == "Saved" or e.event_type in ("save", "gk_save_location")))
        row["video_timestamp"] = e.video_timestamp
        records.append(row)
    columns = list(CSV_COLUMNS) + ["gx", "gy", "saved", "video_timestamp"]
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
