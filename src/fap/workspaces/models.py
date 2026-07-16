"""Workspace & data-management records. Plain typed rows; rich payloads are
versioned JSON in ``document`` so old saves keep loading after upgrades."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# the club hierarchy kinds, ordered parent -> child
ORG_KINDS: tuple[str, ...] = ("club", "season", "competition", "team", "opponent", "match")
PRESET_KINDS: tuple[str, ...] = ("chart", "filter", "export", "dashboard")


@dataclass(slots=True)
class OrgNode:
    """One node in the club tree (club/season/competition/team/opponent/match)."""
    id: str
    kind: str
    name: str
    parent_id: str | None = None
    document: dict[str, Any] = field(default_factory=dict)
    created_by: str | None = None


@dataclass(slots=True)
class Dataset:
    """A managed dataset in the Data Manager: import history + metadata."""
    id: str
    name: str
    workspace_id: str | None = None
    project_id: str | None = None
    node_id: str | None = None
    provider_id: str = ""
    coord_system: str = ""
    rows: int = 0
    size_bytes: int = 0
    content_hash: str = ""
    season: str = ""
    competition: str = ""
    opponent: str = ""
    match_date: str = ""
    document: dict[str, Any] = field(default_factory=dict)   # columns, mapping, validation, quality
    status: str = "active"                                    # active | archived
    created_by: str | None = None
    created_at: str = ""


@dataclass(slots=True)
class Preset:
    """A reusable chart / filter / export / dashboard preset."""
    id: str
    kind: str
    name: str
    owner_id: str | None = None
    scope: str = "user"                                       # user | club | global
    document: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProjectVersion:
    id: str
    project_id: str
    version: int
    document: dict[str, Any] = field(default_factory=dict)
    note: str = ""
    created_by: str | None = None
    created_at: str = ""


@dataclass(slots=True)
class AuditEntry:
    id: str
    action: str
    actor: str = ""
    actor_role: str = ""
    target_type: str = ""
    target_id: str = ""
    detail: dict[str, Any] = field(default_factory=dict)
    ts: str = ""
