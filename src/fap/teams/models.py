"""Plain typed records for the Teams module (migration 14 tables)."""
from __future__ import annotations

from dataclasses import dataclass

TEAM_KINDS: tuple[str, ...] = ("club", "academy")


@dataclass(slots=True)
class Team:
    id: str
    name: str
    kind: str = "club"                # club | academy
    age_group: str = ""              # U17 | U19 | … (academy squads)
    competition: str = ""
    season: str = ""
    crest_image_id: str = ""         # ImageStorage id (reused; no new media store)
    info: str = ""
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
    created_at: str = ""
