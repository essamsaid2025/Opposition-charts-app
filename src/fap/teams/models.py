"""Plain typed records for the Teams module (migration 14 tables)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

TEAM_KINDS: tuple[str, ...] = ("club", "academy", "opponent")
# the two top-level groups the Teams page shows
OUR_TEAM_KINDS: tuple[str, ...] = ("club", "academy")
OPPONENT_KIND = "opponent"


def team_group(kind: str) -> str:
    """'opponents' for scouted opponents, else 'our_teams' (club + academy)."""
    return "opponents" if kind == OPPONENT_KIND else "our_teams"


@dataclass(slots=True)
class Team:
    id: str
    name: str
    kind: str = "club"                # club | academy | opponent
    age_group: str = ""              # U17 | U19 | … (academy squads)
    competition: str = ""
    season: str = ""
    crest_image_id: str = ""         # ImageStorage id (reused; no new media store)
    info: str = ""
    created_by: str = ""
    created_at: str = ""
    # extensible bag (survives upgrades without migrations). ``document['datasets']``
    # holds active-independent links to Data Hub datasets (opposition data files).
    document: dict[str, Any] = field(default_factory=dict)


VENUES: tuple[str, ...] = ("home", "away", "neutral")


@dataclass(slots=True)
class TeamMatch:
    id: str
    team_id: str
    opponent: str = ""
    match_date: str = ""
    competition: str = ""
    venue: str = "home"              # home | away | neutral
    our_score: int | None = None
    opp_score: int | None = None
    formation: str = ""
    notes: str = ""
    dataset_id: str = ""             # linked event dataset (active-independent)
    match_id: str = ""              # match id within that dataset
    created_by: str = ""
    created_at: str = ""

    @property
    def scoreline(self) -> str:
        if self.our_score is None or self.opp_score is None:
            return ""
        return f"{int(self.our_score)}-{int(self.opp_score)}"

    @property
    def result(self) -> str:
        if self.our_score is None or self.opp_score is None:
            return ""
        if self.our_score > self.opp_score:
            return "W"
        return "L" if self.our_score < self.opp_score else "D"


@dataclass(slots=True)
class TeamMedia:
    id: str
    team_id: str
    match_id: str = ""               # "" = team-level; else the team_matches.id it belongs to
    kind: str = "note"               # note | video | clip | chart | image | document
    member_id: str = ""             # roster player (team_members.id) this belongs to; "" = team/match-level
    title: str = ""
    body: str = ""                  # note text
    url: str = ""                   # external video/link
    file_id: str = ""               # FileStorage id (uploads)
    image_id: str = ""              # ImageStorage id (charts/images)
    created_by: str = ""
    created_at: str = ""


@dataclass(slots=True)
class TeamMember:
    id: str
    team_id: str
    player_id: str = ""              # immutable player anchor when linked to a registry player
    operational_id: str = ""         # ACD-/CLB-/SCT- human id (denormalised for display)
    player_name: str = ""
    source: str = "scouting"         # scouting | first_team
    shirt_number: str = ""
    role: str = ""
    secondary_role: str = ""
    date_of_birth: str = ""
    nationality: str = ""
    preferred_foot: str = ""
    height_cm: int | None = None
    weight_kg: int | None = None
    joined_date: str = ""
    contract_end: str = ""
    availability: str = "available"
    phone: str = ""
    email: str = ""
    emergency_contact: str = ""
    agent: str = ""
    notes: str = ""
    profile_image_id: str = ""      # ImageStorage id; player photo for the club dashboard
    created_at: str = ""
