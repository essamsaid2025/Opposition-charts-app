"""Scouting domain models - plain typed records (no persistence, no UI).

A ``Player`` is the single source of truth for a footballer; notes, videos,
media, attachments, report links and watchlists all reference the player by id -
the record is never duplicated. ``document`` holds extensible custom fields so
the schema survives upgrades without migrations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# scouting workflow status (distinct from the archived soft-delete flag)
PLAYER_STATUSES = ("prospect", "monitoring", "shortlisted", "recommended",
                   "signed", "rejected", "active")
PRIORITIES = ("", "low", "medium", "high", "urgent")
MEDIA_KINDS = ("profile", "medical", "training", "match", "scouting")
VIDEO_PROVIDERS = ("file", "youtube", "vimeo", "hudl", "wyscout", "skillcorner",
                   "statsbomb", "url")


@dataclass(slots=True)
class Player:
    id: str
    name: str
    nickname: str = ""
    club: str = ""
    league: str = ""
    country: str = ""
    nationality: str = ""
    age: int | None = None
    dob: str = ""
    position: str = ""
    secondary_positions: list[str] = field(default_factory=list)
    foot: str = ""
    height: int | None = None
    weight: int | None = None
    shirt_number: int | None = None
    contract_until: str = ""
    market_value: float | None = None
    agent: str = ""
    status: str = "prospect"
    profile_image_id: str = ""
    club_logo_id: str = ""
    flag: str = ""
    tags: list[str] = field(default_factory=list)
    custom_fields: dict[str, Any] = field(default_factory=dict)
    availability: str = ""
    medical_notes: str = ""
    internal_rating: float | None = None
    priority: str = ""
    workspace_id: str | None = None
    owner: str = ""
    favorite: bool = False
    archived: bool = False
    document: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    created_by: str = ""


@dataclass(slots=True)
class PlayerNote:
    id: str
    player_id: str
    body: str = ""
    kind: str = "note"                 # note | checklist
    pinned: bool = False
    private: bool = False
    author: str = ""
    document: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


@dataclass(slots=True)
class PlayerVideo:
    id: str
    player_id: str
    kind: str = "external"             # upload | external
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
class PlayerMedia:
    id: str
    player_id: str
    image_id: str
    kind: str = "scouting"
    caption: str = ""
    created_by: str = ""
    created_at: str = ""


@dataclass(slots=True)
class PlayerAttachment:
    id: str
    player_id: str
    file_id: str
    filename: str = ""
    mime: str = ""
    size_bytes: int = 0
    kind: str = "document"
    created_by: str = ""
    created_at: str = ""


@dataclass(slots=True)
class ScoutingReportLink:
    id: str
    player_id: str
    report_id: str
    title: str = ""
    created_by: str = ""
    created_at: str = ""


@dataclass(slots=True)
class Watchlist:
    id: str
    name: str
    owner: str = ""
    workspace_id: str | None = None
    document: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    member_count: int = 0
