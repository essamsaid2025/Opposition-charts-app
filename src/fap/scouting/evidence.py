"""Scouting match & evidence architecture (P4.4) - pure, no persistence, no UI.

The production-safety invariant this module enforces:

    PLAYER IDENTITY  !=  DATASET ID  !=  MATCH ID  !=  EVENT ID

    player_id -> match_id -> dataset_id -> event_id

Evidence is anchored to the persistent ``player_id`` and a persistent
(``dataset_id``, ``match_id``) scope - NEVER to the currently active dataset. A
player is linked to the datasets that hold their evidence; each dataset's frame is
retrieved by ``dataset_id`` (which survives regardless of what is active), so
importing or switching a dataset can never hide, overwrite or reassign evidence
from another. This mirrors the first-team ``player_match_links`` pattern, but is
stored additively in the scouting player's ``document`` (no new table).

Event evidence is DERIVED live from an event dataset's frame (there is no separate
tagged-event store to duplicate); this module only records the *links* and scopes
the query. Player-scouting datasets never yield event evidence (capability
boundary). Nothing here fabricates match or event ids.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# a link whose dataset predates the match architecture (legacy, unscoped) - kept
# accessible, never assigned a fabricated match id.
LEGACY_MATCH = "legacy"


@dataclass(slots=True)
class EvidenceLink:
    """A persistent, active-dataset-independent link: this player has evidence in
    this dataset (optionally pinned to one match). ``event_count`` is cached at link
    time so a profile open needn't rescan every frame."""
    id: str
    player_id: str
    dataset_id: str
    dataset_type: str = "event"                 # event | player_scouting | ...
    dataset_name: str = ""
    match_id: str = ""                          # "" => matches read from the frame's match_id column
    team: str = ""                              # optional team scope
    role: str = ""
    minutes: int | None = None
    note: str = ""
    competition: str = ""
    season: str = ""
    opponent: str = ""
    match_date: str = ""
    result: str = ""
    event_count: int = 0
    tags: list[dict[str, Any]] = field(default_factory=list)
    created_by: str = ""
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "player_id": self.player_id, "dataset_id": self.dataset_id,
            "dataset_type": self.dataset_type, "dataset_name": self.dataset_name,
            "match_id": self.match_id, "team": self.team, "role": self.role,
            "minutes": self.minutes, "note": self.note, "competition": self.competition,
            "season": self.season, "opponent": self.opponent, "match_date": self.match_date,
            "result": self.result, "event_count": self.event_count, "tags": list(self.tags),
            "created_by": self.created_by, "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "EvidenceLink":
        known = {f for f in cls.__slots__}
        return cls(**{k: v for k, v in d.items() if k in known})


# ---------------------------------------------------------------- pure queries
def _norm_series(frame, col):
    return frame[col].astype(str).str.strip()


def event_rows(frame, keys: set[str], *, team: str = "", match_id: str = ""):
    """The player's event rows in a frame, scoped by identity keys (name+aliases),
    and optionally by team and by an exact match_id from the frame's own column.
    Returns the filtered frame (empty if the frame is not event-shaped or no match).
    Never falls back to a wider scope."""
    if frame is None or getattr(frame, "empty", True) or "player" not in getattr(frame, "columns", []):
        return frame.iloc[0:0] if frame is not None else None
    mask = _norm_series(frame, "player").str.lower().isin({k.lower() for k in keys})
    if team and "team" in frame.columns:
        mask = mask & (_norm_series(frame, "team").str.lower() == team.lower().strip())
    if match_id and match_id != LEGACY_MATCH and "match_id" in frame.columns:
        mask = mask & (_norm_series(frame, "match_id") == str(match_id).strip())
    return frame[mask]


def _mode(series) -> str:
    s = series.astype(str).str.strip()
    s = s[s.ne("")]
    if s.empty:
        return ""
    return str(s.mode().iloc[0])


def matches_in(frame, keys: set[str], *, team: str = "",
               pinned_match_id: str = "", descriptor: dict[str, Any] | None = None
               ) -> list[dict[str, Any]]:
    """Enumerate the matches a player has evidence for within ONE dataset frame.

    * ``pinned_match_id`` set -> the whole dataset is that single match.
    * else group by the frame's real ``match_id`` column (never fabricated); a frame
      with no match_id column collapses to one match keyed ``LEGACY_MATCH``.
    Each match carries an event count and best-effort opponent/date/competition read
    from the frame (falling back to the dataset ``descriptor``)."""
    rows = event_rows(frame, keys, team=team)
    if rows is None or rows.empty:
        return []
    desc = descriptor or {}
    out: list[dict[str, Any]] = []
    if pinned_match_id:
        out.append(_match_summary(rows, pinned_match_id, desc))
        return out
    if "match_id" in rows.columns:
        ids = [m for m in dict.fromkeys(_norm_series(rows, "match_id").tolist()) if m]
        if ids:
            for mid in ids:
                sub = rows[_norm_series(rows, "match_id") == mid]
                out.append(_match_summary(sub, mid, desc))
            return out
    # no usable match_id column -> single legacy/unscoped match for this dataset
    out.append(_match_summary(rows, LEGACY_MATCH, desc))
    return out


def _match_summary(rows, match_id: str, desc: dict[str, Any]) -> dict[str, Any]:
    def pick(col, key):
        if col in rows.columns:
            v = _mode(rows[col])
            if v:
                return v
        return desc.get(key, "")
    return {
        "match_id": match_id,
        "event_count": int(len(rows)),
        "opponent": pick("opponent", "opponent"),
        "match_date": pick("date", "match_date"),
        "competition": pick("competition", "competition"),
        "team": pick("team", "team"),
    }


def group_by_match(links: list[EvidenceLink]) -> list[dict[str, Any]]:
    """Group cached links by match_id for the 'matches with evidence' list (uses the
    stored event_count; does not read frames)."""
    grouped: dict[str, dict[str, Any]] = {}
    for link in links:
        mid = link.match_id or LEGACY_MATCH
        g = grouped.setdefault(mid, {"match_id": mid, "dataset_ids": [], "datasets": [],
                                     "event_count": 0, "opponent": "", "match_date": "",
                                     "competition": ""})
        if link.dataset_id not in g["dataset_ids"]:
            g["dataset_ids"].append(link.dataset_id)
            g["datasets"].append({"dataset_id": link.dataset_id, "dataset_name": link.dataset_name,
                                  "dataset_type": link.dataset_type, "event_count": link.event_count})
        g["event_count"] += int(link.event_count or 0)
        for k in ("opponent", "match_date", "competition"):
            if not g[k] and getattr(link, k, ""):
                g[k] = getattr(link, k)
    return list(grouped.values())


__all__ = ["LEGACY_MATCH", "EvidenceLink", "event_rows", "matches_in", "group_by_match"]
