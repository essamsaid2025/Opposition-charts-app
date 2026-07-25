"""First Team Players domain models (Phase 10 · players module).

Plain typed records for OUR squad — completely separate from the scouting module.
A ``Player`` is the single source of truth for a first-team footballer; contracts,
medical, training, media, notes, career and match links reference it by id.
Match statistics are never stored here: ``PlayerMatchLink`` only *links* a player
to an existing match/dataset, and detailed stats come from the event datasets.

``document``/``custom_fields`` hold extensible fields so the schema survives
upgrades without migrations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

POSITIONS = ("GK", "RB", "RWB", "CB", "LB", "LWB", "DM", "CM", "AM", "RM", "LM",
             "RW", "LW", "CF", "ST", "SS")
FEET = ("", "left", "right", "both")
STATUSES = ("active", "injured", "suspended", "loan", "archived")
AVAILABILITY = ("available", "doubtful", "injured", "suspended", "unavailable")
MEDICAL_STATUS = ("open", "recovering", "returned")
VIDEO_KINDS = ("training", "match", "tagged", "coach", "opponent", "external")
DOCUMENT_KINDS = ("passport", "contract", "medical", "document")


@dataclass(slots=True)
class Player:
    id: str
    first_name: str = ""
    last_name: str = ""
    display_name: str = ""
    shirt_number: int | None = None
    dob: str = ""
    nationality: str = ""
    foot: str = ""
    primary_position: str = ""
    secondary_positions: list[str] = field(default_factory=list)
    height: int | None = None
    weight: int | None = None
    join_date: str = ""
    captain: bool = False
    vice_captain: bool = False
    status: str = "active"
    availability: str = "available"
    profile_image_id: str = ""
    club_logo_id: str = ""
    flag: str = ""
    source_scout_player_id: str = ""          # optional link to a scouting record
    tags: list[str] = field(default_factory=list)
    custom_fields: dict[str, Any] = field(default_factory=dict)
    workspace_id: str | None = None
    owner: str = ""
    favorite: bool = False
    archived: bool = False
    document: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    created_by: str = ""

    @property
    def name(self) -> str:
        return self.display_name or f"{self.first_name} {self.last_name}".strip()


@dataclass(slots=True)
class PlayerContract:
    id: str
    player_id: str
    contract_start: str = ""
    contract_end: str = ""
    salary: float | None = None
    market_value: float | None = None
    agent: str = ""
    loan: bool = False
    loan_club: str = ""
    release_clause: float | None = None
    status: str = "active"
    document: dict[str, Any] = field(default_factory=dict)
    created_by: str = ""
    created_at: str = ""


@dataclass(slots=True)
class PlayerMedical:
    id: str
    player_id: str
    injury: str = ""
    injury_type: str = ""
    date: str = ""
    expected_return: str = ""
    status: str = "open"
    availability: str = ""
    severity: str = ""
    medical_notes: str = ""
    document: dict[str, Any] = field(default_factory=dict)
    created_by: str = ""
    created_at: str = ""


@dataclass(slots=True)
class PlayerTraining:
    id: str
    player_id: str
    date: str = ""
    attendance: str = ""
    sprint_distance: float | None = None
    hsr: float | None = None
    accelerations: int | None = None
    decelerations: int | None = None
    load: float | None = None
    rpe: float | None = None
    wellness: float | None = None
    coach_notes: str = ""
    document: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""


@dataclass(slots=True)
class PlayerDocument:
    id: str
    player_id: str
    file_id: str = ""
    filename: str = ""
    mime: str = ""
    size_bytes: int = 0
    kind: str = "document"
    created_by: str = ""
    created_at: str = ""


@dataclass(slots=True)
class PlayerImage:
    id: str
    player_id: str
    image_id: str = ""
    kind: str = "profile"
    caption: str = ""
    created_by: str = ""
    created_at: str = ""


@dataclass(slots=True)
class PlayerVideo:
    id: str
    player_id: str
    kind: str = "external"
    provider: str = ""
    url: str = ""
    file_id: str = ""
    filename: str = ""
    mime: str = ""
    size_bytes: int = 0
    title: str = ""
    created_by: str = ""
    created_at: str = ""


@dataclass(slots=True)
class PlayerNote:
    id: str
    player_id: str
    body: str = ""
    kind: str = "note"
    pinned: bool = False
    private: bool = False
    author: str = ""
    document: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


@dataclass(slots=True)
class PlayerCareer:
    id: str
    player_id: str
    season: str = ""
    club: str = ""
    competition: str = ""
    appearances: int = 0
    goals: int = 0
    assists: int = 0
    minutes: int = 0
    yellow: int = 0
    red: int = 0
    document: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""


@dataclass(slots=True)
class PlayerMatchLink:
    """LINK ONLY — connects a player to an existing match/dataset. No match
    statistics live here; they stay in the linked event dataset."""
    id: str
    player_id: str
    match_id: str = ""
    dataset_id: str = ""
    minutes: int | None = None
    role: str = ""
    availability: str = ""
    created_at: str = ""
