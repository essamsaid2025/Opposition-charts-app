"""Set-piece derivation from the canonical active frame (Phase 12.2).

Projects set-piece deliveries (corners, free kicks, throw-ins, penalties) out of
the platform's canonical event frame into ``SetPiece`` records - IN MEMORY, never
persisted. This is the bridge that lets the Set Piece module read from the single
source of truth (``WorkspaceManager.active_frame``) with NO duplicated state,
while the existing analytics and visualization plugins keep consuming ``SetPiece``
objects unchanged.

Box positions and contact events are a separate manual/tracking tagging layer and
are not present in a plain event frame; the existing coverage guidance surfaces
that honestly (a derived set piece simply has no positions/contacts yet).
"""
from __future__ import annotations

import hashlib
from typing import Any

import pandas as pd

from fap.setpieces.models import SetPiece

# Bump whenever the derivation OUTPUT changes (id scheme, fields, classification).
# It is part of the derived-set-piece cache key, so a logic fix is never masked by
# a stale cached result computed by an older version. v2: unique per-row derived ids.
DERIVATION_VERSION = 2

# canonical event_type / set_piece values -> the module's controlled type
_TYPE_MAP = {
    "corner": "corner", "corner_kick": "corner", "from corner": "corner",
    "free_kick": "free_kick", "free-kick": "free_kick", "freekick": "free_kick",
    "from free kick": "free_kick", "direct_free_kick": "free_kick",
    "throw-in": "throw_in", "throw_in": "throw_in", "throwin": "throw_in",
    "throw in": "throw_in", "from throw in": "throw_in",
    "penalty": "penalty", "penalty_kick": "penalty",
}
_GOALISH = {"goal"}
_SHOTISH = {"goal", "shot", "on_target", "off_target", "saved", "blocked", "post"}


def _num(value: Any):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(f) else f


def _int(value: Any):
    f = _num(value)
    return int(f) if f is not None else None


def _did(row_key: Any, match_id: Any, minute: Any, second: Any, t: str,
         x: Any, y: Any, player: Any) -> str:
    # ``row_key`` is the source event's stable identity in the frame; it makes the id
    # unique even when two set-piece events share match/minute/second/type/x/y/player
    # (e.g. sparse frames where those fields are blank). Deterministic: the same
    # immutable frame -> the same ids, so the per-dataset derivation cache stays valid.
    raw = f"{row_key}|{match_id}|{minute}|{second}|{t}|{x}|{y}|{player}"
    return "af_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _classify(row: dict[str, Any]) -> str | None:
    et = str(row.get("event_type", "") or "").strip().lower()
    if et in _TYPE_MAP:
        return _TYPE_MAP[et]
    sp = str(row.get("set_piece", "") or "").strip().lower()
    return _TYPE_MAP.get(sp)


def derive_set_pieces(frame: pd.DataFrame, *, workspace_id: str | None = "",
                      source: str = "active_dataset") -> list[SetPiece]:
    """Every set-piece delivery in ``frame`` as a ``SetPiece``. Own/opposition and
    offensive/defensive are assigned by a primary-team heuristic (the most active
    team in the frame is treated as the analysed subject); teams flip accordingly.
    Fast: it masks to the set-piece rows first (a small fraction) and only builds
    objects for those."""
    if frame is None or getattr(frame, "empty", True):
        return []
    df = frame
    keys = set(_TYPE_MAP)
    mask = pd.Series(False, index=df.index)
    if "event_type" in df.columns:
        mask = mask | df["event_type"].astype(str).str.lower().str.strip().isin(keys)
    if "set_piece" in df.columns:
        mask = mask | df["set_piece"].astype(str).str.lower().str.strip().isin(keys)
    subset = df[mask]
    if subset.empty:
        return []

    primary = ""
    if "team" in df.columns:
        teams = df["team"].astype(str).str.strip()
        teams = teams[teams != ""]
        if not teams.empty:
            primary = teams.value_counts().idxmax()

    out: list[SetPiece] = []
    # enumerate gives each event a stable ordinal within this (immutable) frame, so
    # the derived id is unique per source row even when the event attributes collide
    # - and deterministic, since df[mask] preserves order for the same frame.
    for row_key, row in enumerate(subset.to_dict("records")):
        t = _classify(row)
        if t is None:
            continue
        team = str(row.get("team", "") or "").strip()
        own = bool(primary) and team == primary
        shot_result = str(row.get("shot_result", "") or "").strip().lower()
        outcome = str(row.get("outcome", "") or "").strip().lower()
        goal = shot_result in _GOALISH or outcome in _GOALISH
        shot = goal or shot_result in _SHOTISH or (shot_result not in ("", "nan"))
        x, y = _num(row.get("x")), _num(row.get("y"))
        out.append(SetPiece(
            id=_did(row_key, row.get("match_id", ""), row.get("minute"), row.get("second"),
                    t, x, y, row.get("player", "")),
            workspace_id=workspace_id or None,
            match_id=str(row.get("match_id", "") or ""),
            season=str(row.get("season", "") or ""),
            competition=str(row.get("competition", "") or ""),
            team=team, opponent=str(row.get("opponent", "") or ""),
            perspective="own" if own else "opposition",
            phase="offensive" if own else "defensive",
            type=t, taker=str(row.get("player", "") or ""),
            minute=_int(row.get("minute")), period=_int(row.get("period")),
            start_x=x, start_y=y, end_x=_num(row.get("end_x")), end_y=_num(row.get("end_y")),
            outcome=("goal" if goal else outcome), shot=shot, goal=goal, source=source))
    return out
