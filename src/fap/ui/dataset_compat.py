"""Active-dataset compatibility helpers for page boundaries.

The Open Play pages (Opponent Analysis, Open Play Studio) consume the active
dataset as an EVENT frame (``add_derived_columns`` reads x/y -> x2). A
player-scouting dataset has no coordinates, so those pages must refuse it at the
page boundary and point the user to Scouting - rather than letting the engine
raise ``KeyError('x2')``. This reads the persisted ``dataset_type`` flag; it never
fabricates columns, suppresses the error, or relaxes the engine's requirements.
"""
from __future__ import annotations

from typing import Any

from fap.datahub.classification import (
    PLAYER_ROSTER, PLAYER_SCOUTING, TEAM_MATCH_STATS,
)

# active-dataset kinds the Open Play engine cannot consume (no x/y/event columns)
NON_EVENT_DATASET_TYPES = frozenset({PLAYER_SCOUTING, PLAYER_ROSTER})


def non_event_active_dataset(shell: Any):
    """The active dataset if it is a non-event (player-scouting) dataset the Open
    Play engine cannot analyse, else ``None``. Event datasets carry no
    ``dataset_type`` flag and pass through untouched."""
    wm = getattr(shell, "wm", None)
    if wm is None:
        return None
    try:
        ds = wm.active_dataset(shell.user)
    except Exception:
        return None
    if ds is None:
        return None
    doc = ds.document if isinstance(getattr(ds, "document", None), dict) else {}
    return ds if doc.get("dataset_type") in NON_EVENT_DATASET_TYPES else None


def team_stats_active_dataset(shell: Any):
    """The active dataset if it is a team-match-stats comparison table, else
    ``None``. Unlike player-scouting data, Open Play does NOT refuse this kind — it
    renders a dedicated team-comparison view for it — so the Open Play page branches
    on this helper before its event-only path."""
    wm = getattr(shell, "wm", None)
    if wm is None:
        return None
    try:
        ds = wm.active_dataset(shell.user)
    except Exception:
        return None
    if ds is None:
        return None
    doc = ds.document if isinstance(getattr(ds, "document", None), dict) else {}
    return ds if doc.get("dataset_type") == TEAM_MATCH_STATS else None


__all__ = ["NON_EVENT_DATASET_TYPES", "non_event_active_dataset",
           "team_stats_active_dataset"]
