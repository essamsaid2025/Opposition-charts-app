"""Set Piece domain models - plain typed records (no persistence, no UI).

A ``SetPiece`` is the single source of truth for one dead-ball situation (corner,
free kick, throw-in, penalty or kick-off). The players standing in the box at
delivery (``SetPiecePosition``) and the ball/contact events that follow
(``SetPieceContact``) reference it by id - never duplicated. ``document`` holds
extensible fields so the schema survives upgrades without migrations.

The model is deliberately provider-agnostic: the same records are produced by the
manual tagging engine and by CSV/Excel/JSON import, so nothing downstream cares
where a set piece came from.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# -- controlled vocabularies (used by tagging UI and import normalization) ----
PERSPECTIVES = ("own", "opposition")
PHASES = ("offensive", "defensive")
SET_PIECE_TYPES = ("corner", "free_kick", "throw_in", "penalty", "kick_off")
SET_PIECE_TYPE_LABELS = {
    "corner": "Corner", "free_kick": "Free Kick", "throw_in": "Throw-In",
    "penalty": "Penalty", "kick_off": "Kick Off",
}
SIDES = ("", "left", "right", "central")
DELIVERY_TYPES = ("", "inswing", "outswing", "straight", "driven", "lofted",
                  "ground", "short", "long")
DELIVERY_HEIGHTS = ("", "ground", "low", "high", "lofted")
DELIVERY_LENGTHS = ("", "short", "long")
DELIVERY_SPEEDS = ("", "fast", "slow")
TEAMS = ("attack", "defence", "none")
OUTCOMES = ("", "goal", "shot", "clearance", "retained", "lost", "blocked",
            "off_target", "other")
MARKING_SCHEMES = ("", "man", "zonal", "hybrid", "mixed")
SOURCES = ("manual", "import", "tracking")

# box occupancy roles (the zones professional analysts label at delivery)
OCCUPANCY_ROLES = ("near_post", "far_post", "penalty_spot", "six_yard",
                   "edge_box", "gk_area", "back_post", "central",
                   "half_space_left", "half_space_right")
OCCUPANCY_ROLE_LABELS = {
    "near_post": "Near Post", "far_post": "Far Post", "penalty_spot": "Penalty Spot",
    "six_yard": "Six Yard", "edge_box": "Edge of Box", "gk_area": "Goalkeeper Area",
    "back_post": "Back Post", "central": "Central Zone",
    "half_space_left": "Half Space (L)", "half_space_right": "Half Space (R)",
}
MOMENTS = ("before", "delivery", "after")
RUN_TYPES = ("", "near_post", "far_post", "screen", "block", "late", "edge", "decoy")
CONTACT_KINDS = ("first_contact", "second_ball", "shot", "clearance", "save", "rebound")
BODY_PARTS = ("", "head", "foot", "other")
CONTACT_OUTCOMES = ("", "success", "miss", "loss", "save", "goal", "clearance", "block")


@dataclass(slots=True)
class SetPiece:
    id: str
    workspace_id: str | None = None
    # match context
    match_id: str = ""
    match_label: str = ""
    season: str = ""
    competition: str = ""
    team: str = ""
    opponent: str = ""
    match_date: str = ""
    venue: str = ""                    # home | away | neutral
    # classification
    perspective: str = "own"           # own | opposition
    phase: str = "offensive"           # offensive | defensive
    type: str = "corner"               # corner | free_kick | throw_in | penalty | kick_off
    subtype: str = ""
    side: str = ""                     # left | right | central
    taker: str = ""
    taker_id: str = ""
    foot: str = ""
    minute: int | None = None
    period: int | None = None
    # delivery (canonical 0-100 pitch, attacking toward x=100)
    start_x: float | None = None
    start_y: float | None = None
    end_x: float | None = None
    end_y: float | None = None
    delivery_type: str = ""
    delivery_height: str = ""
    delivery_length: str = ""
    delivery_speed: str = ""
    players_in_box: int | None = None
    # outcome
    first_contact_team: str = ""       # attack | defence | none
    first_contact_x: float | None = None
    first_contact_y: float | None = None
    outcome: str = ""
    shot: bool = False
    goal: bool = False
    xg: float | None = None
    second_ball_team: str = ""         # attack | defence | none
    retained: bool = False
    time_to_first_contact: float | None = None
    time_to_shot: float | None = None
    routine: str = ""
    marking: str = ""                  # man | zonal | hybrid | mixed
    video_url: str = ""
    source: str = "manual"             # manual | import | tracking
    import_id: str = ""
    owner: str = ""
    archived: bool = False
    tags: list[str] = field(default_factory=list)
    document: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    created_by: str = ""


@dataclass(slots=True)
class SetPiecePosition:
    id: str
    set_piece_id: str
    moment: str = "delivery"           # before | delivery | after
    team: str = "attack"               # attack | defence
    player: str = ""
    player_id: str = ""
    role: str = ""                     # OCCUPANCY_ROLES
    zone: str = ""                     # computed occupancy zone
    x: float | None = None
    y: float | None = None
    is_gk: bool = False
    marking: str = ""                  # man | zonal | none
    run_type: str = ""                 # RUN_TYPES
    document: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""


@dataclass(slots=True)
class SetPieceContact:
    id: str
    set_piece_id: str
    kind: str = "first_contact"        # CONTACT_KINDS
    sequence: int = 0
    team: str = ""                     # attack | defence
    player: str = ""
    player_id: str = ""
    x: float | None = None
    y: float | None = None
    body_part: str = ""                # head | foot | other
    outcome: str = ""                  # CONTACT_OUTCOMES
    won: bool = False
    distance: float | None = None
    document: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""


@dataclass(slots=True)
class SetPieceImport:
    id: str
    workspace_id: str | None = None
    filename: str = ""
    provider: str = ""
    rows: int = 0
    imported: int = 0
    skipped: int = 0
    mapping: dict[str, Any] = field(default_factory=dict)
    document: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    created_by: str = ""


@dataclass(slots=True)
class ImportResult:
    """What an import returns to the caller (and the page renders)."""
    batch: SetPieceImport
    set_pieces: list[SetPiece] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def imported(self) -> int:
        return len(self.set_pieces)
