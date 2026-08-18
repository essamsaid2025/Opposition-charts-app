"""Player identity + recruitment vocabulary (P4.1) - pure, no persistence, no UI.

The scouting module becomes PLAYER-centric: the persistent ``player_id`` is the
identity anchor, and a dataset row is only a data source resolved back to a
player by name/alias. This module owns:

* the professional recruitment vocabulary (status pipeline + priority) with
  back-compatible normalizers from the legacy free-text values, and
* the ONE identity resolver every consumer uses - id first, then an exact
  name/alias match, with ambiguity surfaced rather than guessed.

Identity attributes that the fixed ``players`` table has no column for
(``aliases``, ``display_name``, ``source``) live in the player's existing
``document`` JSON - no migration, no new table, no second persistence layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

# ---------------------------------------------------------------- recruitment vocab
# the professional recruitment pipeline (ordered) + two terminal states.
STATUS_PIPELINE: tuple[str, ...] = (
    "watching", "shortlisted", "scouted", "target", "contacted", "negotiating", "signed",
)
TERMINAL_STATUSES: tuple[str, ...] = ("rejected", "archived")
RECRUITMENT_STATUSES: tuple[str, ...] = STATUS_PIPELINE + TERMINAL_STATUSES

RECRUITMENT_PRIORITIES: tuple[str, ...] = ("low", "medium", "high", "critical")

# legacy (models.PLAYER_STATUSES / PRIORITIES) -> canonical. Back-compat only; we
# never rewrite stored values silently - normalization happens at read/display.
_LEGACY_STATUS: dict[str, str] = {
    "prospect": "watching", "monitoring": "watching", "shortlisted": "shortlisted",
    "recommended": "target", "signed": "signed", "rejected": "rejected",
    "active": "scouted", "": "watching",
}
_LEGACY_PRIORITY: dict[str, str] = {"urgent": "critical", "": ""}


def normalize_status(value: str | None) -> str:
    """Map any stored/legacy status to a canonical one. Unknown values pass through
    lower-cased (never fabricated into a different meaning)."""
    v = str(value or "").strip().lower()
    if v in RECRUITMENT_STATUSES:
        return v
    return _LEGACY_STATUS.get(v, v)


def normalize_priority(value: str | None) -> str:
    v = str(value or "").strip().lower()
    if v in RECRUITMENT_PRIORITIES or v == "":
        return v
    return _LEGACY_PRIORITY.get(v, v)


def status_label(value: str | None) -> str:
    return normalize_status(value).replace("_", " ").title()


def priority_label(value: str | None) -> str:
    p = normalize_priority(value)
    return p.title() if p else ""


def is_terminal(status: str | None) -> bool:
    return normalize_status(status) in TERMINAL_STATUSES


def next_statuses(status: str | None) -> list[str]:
    """The forward pipeline steps available from ``status`` (plus terminals). Used
    later by the recruitment workflow (P4.2); defined here with the vocabulary."""
    cur = normalize_status(status)
    if cur in STATUS_PIPELINE:
        i = STATUS_PIPELINE.index(cur)
        forward = list(STATUS_PIPELINE[i + 1:])
    else:
        forward = list(STATUS_PIPELINE)
    return forward + list(TERMINAL_STATUSES)


# ---------------------------------------------------------------- player pathway
# ONE canonical identity (player_id), TWO pathways. player_type is structured
# identity metadata in document; the operational_id is a stable, human-readable
# club-side identifier whose prefix reflects the pathway. The immutable player_id
# is always the true anchor - the operational id never replaces it.
PLAYER_TYPES: tuple[str, ...] = ("first_team", "academy", "trialist", "scouting")
TYPE_PREFIX: dict[str, str] = {"first_team": "CLB", "academy": "ACD", "trialist": "TRI",
                               "scouting": "SCT"}
TYPE_LABEL: dict[str, str] = {"first_team": "First Team", "academy": "Academy",
                              "trialist": "Trialist", "scouting": "Scouting"}
# academy age-group vocabulary (display metadata; optional per player)
AGE_GROUPS: tuple[str, ...] = ("U9", "U10", "U11", "U12", "U13", "U14", "U15",
                               "U16", "U17", "U18", "U19", "U21", "U23")


def normalize_player_type(value: str | None) -> str:
    v = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    if v in PLAYER_TYPES:
        return v
    return {"club": "first_team", "senior": "first_team", "youth": "academy",
            "trial": "trialist", "scout": "scouting"}.get(v, "first_team")


def player_type_of(player: Any) -> str:
    doc = getattr(player, "document", None) or {}
    return normalize_player_type(doc.get("player_type"))


def type_label(value: str | None) -> str:
    return TYPE_LABEL.get(normalize_player_type(value), "First Team")


def format_operational_id(player_type: str, seq: int) -> str:
    prefix = TYPE_PREFIX.get(normalize_player_type(player_type), "CLB")
    return f"{prefix}-{int(seq):06d}"


def operational_id_of(player: Any) -> str:
    doc = getattr(player, "document", None) or {}
    return _clean(doc.get("operational_id"))


def age_group_of(player: Any) -> str:
    doc = getattr(player, "document", None) or {}
    return _clean(doc.get("age_group"))


def recruitment_profile_of(player: Any) -> str:
    doc = getattr(player, "document", None) or {}
    return _clean(doc.get("recruitment_profile"))


def status_history_of(player: Any) -> list[dict[str, Any]]:
    doc = getattr(player, "document", None) or {}
    return list(doc.get("status_history", []) or [])


def pathway_history_of(player: Any) -> list[dict[str, Any]]:
    doc = getattr(player, "document", None) or {}
    return list(doc.get("pathway_history", []) or [])


def academy_profile_of(player: Any) -> dict[str, Any]:
    doc = getattr(player, "document", None) or {}
    ac = doc.get("academy")
    return dict(ac) if isinstance(ac, dict) else {}


# ---------------------------------------------------------------- analyst rating (A-F)
# The scout's/analyst's recruitment JUDGEMENT — deliberately distinct from the
# data-driven recruitment FIT. Never computed from percentiles or fit; always
# manually assigned. Stored in document['analyst_rating'].
ANALYST_RATINGS: tuple[str, ...] = ("A", "B", "C", "D", "E", "F")
RATING_MEANINGS: dict[str, str] = {
    "A": "Exceptional / highest recommendation", "B": "Strong",
    "C": "Positive / monitor", "D": "Doubtful",
    "E": "Low priority", "F": "Not recommended"}


def normalize_rating(value: str | None) -> str:
    """Canonical A-F rating, or "" when unset/invalid (never fabricated)."""
    v = str(value or "").strip().upper()
    return v if v in ANALYST_RATINGS else ""


def analyst_rating_of(player: Any) -> str:
    doc = getattr(player, "document", None) or {}
    return normalize_rating(doc.get("analyst_rating"))


def rating_label(value: str | None) -> str:
    """'B — Strong' for display, or "" when unset."""
    r = normalize_rating(value)
    return f"{r} — {RATING_MEANINGS[r]}" if r else ""


# ---------------------------------------------------------------- identity helpers
def _clean(s: Any) -> str:
    return str(s or "").strip()


def aliases_of(player: Any) -> list[str]:
    """The player's alternate names (from ``document['aliases']``), de-duplicated
    and order-preserved. Aliases are how a dataset row resolves to a player when
    the spelling differs."""
    doc = getattr(player, "document", None) or {}
    out: list[str] = []
    for a in doc.get("aliases", []) or []:
        a = _clean(a)
        if a and a not in out:
            out.append(a)
    return out


def display_name_of(player: Any) -> str:
    """The name to show in the UI: explicit display_name, else nickname, else name."""
    doc = getattr(player, "document", None) or {}
    return (_clean(doc.get("display_name")) or _clean(getattr(player, "nickname", ""))
            or _clean(getattr(player, "name", "")))


def source_of(player: Any) -> str:
    """Where this player was first added from (free-text provenance)."""
    doc = getattr(player, "document", None) or {}
    return _clean(doc.get("source"))


def identity_keys(player: Any) -> set[str]:
    """Every lower-cased name this player answers to (name + aliases + display
    name). The single matching surface used by resolution and event/metric joins."""
    keys = {_clean(getattr(player, "name", "")).lower()}
    keys |= {a.lower() for a in aliases_of(player)}
    dn = display_name_of(player)
    if dn:
        keys.add(dn.lower())
    keys.discard("")
    return keys


def matches_name(player: Any, name: str) -> bool:
    return _clean(name).lower() in identity_keys(player)


# ---------------------------------------------------------------- resolution
@dataclass(frozen=True, slots=True)
class Resolution:
    """Result of resolving an identity: the matched player (or None), all
    candidates considered, and whether the match was ambiguous."""
    player: Any = None
    candidates: list[Any] = field(default_factory=list)
    ambiguous: bool = False
    reason: str = ""

    @property
    def found(self) -> bool:
        return self.player is not None


def resolve(players: Iterable[Any], *, player_id: str | None = None,
            name: str | None = None) -> Resolution:
    """Resolve an identity against a set of players. ``player_id`` wins (the
    persistent anchor); otherwise an exact name/alias match is used, and multiple
    matches are reported as ambiguous rather than silently picking one."""
    players = list(players)
    if player_id:
        hit = next((p for p in players if getattr(p, "id", None) == player_id), None)
        return Resolution(player=hit, candidates=[hit] if hit else [],
                          ambiguous=False,
                          reason="matched by player_id" if hit else "no player with that id")
    if name:
        cands = [p for p in players if matches_name(p, name)]
        if len(cands) == 1:
            return Resolution(player=cands[0], candidates=cands, ambiguous=False,
                              reason="matched by name/alias")
        if len(cands) > 1:
            return Resolution(player=None, candidates=cands, ambiguous=True,
                              reason=f"{len(cands)} players share this name - disambiguate by id")
        return Resolution(player=None, candidates=[], ambiguous=False,
                          reason="no player matches this name")
    return Resolution(player=None, candidates=[], ambiguous=False, reason="no identity given")


__all__ = [
    "STATUS_PIPELINE", "TERMINAL_STATUSES", "RECRUITMENT_STATUSES", "RECRUITMENT_PRIORITIES",
    "normalize_status", "normalize_priority", "status_label", "priority_label",
    "is_terminal", "next_statuses", "aliases_of", "display_name_of", "source_of",
    "identity_keys", "matches_name", "Resolution", "resolve",
    "PLAYER_TYPES", "TYPE_PREFIX", "TYPE_LABEL", "AGE_GROUPS", "normalize_player_type",
    "player_type_of", "type_label", "format_operational_id", "operational_id_of",
    "age_group_of", "recruitment_profile_of", "status_history_of", "pathway_history_of",
    "academy_profile_of", "ANALYST_RATINGS", "RATING_MEANINGS", "normalize_rating",
    "analyst_rating_of", "rating_label",
]
