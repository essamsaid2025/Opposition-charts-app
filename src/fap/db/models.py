"""Persistence models: plain typed records. Domain 'documents' (project and
workspace payloads) are versioned JSON so old saves keep loading after upgrades."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DOCUMENT_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class User:
    id: str
    username: str
    role: str = "analyst"
    must_change_password: bool = False


@dataclass(slots=True)
class Project:
    """A saved analysis: data source reference + filters + visual + controls."""
    id: str
    workspace_id: str
    name: str
    document: dict[str, Any] = field(default_factory=lambda: {
        "schema_version": DOCUMENT_SCHEMA_VERSION,
        "source": {},          # provider id + source descriptor (path / upload token)
        "filters": {},         # serialized FilterSet
        "visual_id": None,     # active visualization plugin id
        "controls": {},        # control values keyed by control key
        "theme_id": None,
    })


@dataclass(slots=True)
class Workspace:
    """A container of projects + shared preferences (e.g. club theme, coordinate
    convention). One workspace per opponent, per competition, per department..."""
    id: str
    name: str
    owner_id: str | None = None
    document: dict[str, Any] = field(default_factory=lambda: {
        "schema_version": DOCUMENT_SCHEMA_VERSION,
        "default_theme_id": None,
        "default_coord_system": "0-100",
        "project_order": [],
    })
