"""Capability-based authorization (enterprise).

The platform already decides *who you are* (Identity) and carries a ranked
``Role``. This module adds the granular, data-driven layer the enterprise admin
needs: fine capabilities, and **roles as configurable collections of
capabilities** rather than a hard-coded switch.

Nothing here replaces the existing ``Role`` enum or the rank-based
``fap.workspaces.permissions`` guards - those keep working. Built-in role
definitions are DERIVED from the existing roles (by rank), so every current user
gets a sensible capability set automatically, and administrators can add custom
roles on top. Pure data: no Streamlit, no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from fap.identity.roles import Role


class Capability(str, Enum):
    """A single permission. String-valued so it round-trips through JSON/DB."""
    # projects
    VIEW_PROJECT = "VIEW_PROJECT"
    CREATE_PROJECT = "CREATE_PROJECT"
    EDIT_PROJECT = "EDIT_PROJECT"
    DELETE_PROJECT = "DELETE_PROJECT"
    # reports
    VIEW_REPORTS = "VIEW_REPORTS"
    CREATE_REPORT = "CREATE_REPORT"
    EDIT_REPORTS = "EDIT_REPORTS"
    DELETE_REPORT = "DELETE_REPORT"
    EXPORT_REPORT = "EXPORT_REPORT"
    SHARE_REPORT = "SHARE_REPORT"
    # datasets
    VIEW_DATASET = "VIEW_DATASET"
    UPLOAD_DATASET = "UPLOAD_DATASET"
    DELETE_DATASET = "DELETE_DATASET"
    EXPORT_DATA = "EXPORT_DATA"
    # scouting / set piece (view/edit gates; features implemented in later phases)
    VIEW_SCOUTING = "VIEW_SCOUTING"
    EDIT_SCOUTING = "EDIT_SCOUTING"
    VIEW_SETPIECE = "VIEW_SETPIECE"
    EDIT_SETPIECE = "EDIT_SETPIECE"
    # administration
    VIEW_ADMIN = "VIEW_ADMIN"
    EDIT_USERS = "EDIT_USERS"
    INVITE_USER = "INVITE_USER"
    EDIT_ROLES = "EDIT_ROLES"
    MANAGE_ROLES = "MANAGE_ROLES"          # create/delete roles (higher than EDIT_ROLES)
    VIEW_AUDIT = "VIEW_AUDIT"
    VIEW_STORAGE = "VIEW_STORAGE"
    MANAGE_STORAGE = "MANAGE_STORAGE"      # cache cleanup etc.
    VIEW_SESSIONS = "VIEW_SESSIONS"
    MANAGE_SESSIONS = "MANAGE_SESSIONS"    # force logout
    MANAGE_PROVIDER = "MANAGE_PROVIDER"
    MANAGE_SETTINGS = "MANAGE_SETTINGS"
    MANAGE_ORG = "MANAGE_ORG"              # org/club/team hierarchy CRUD
    MANAGE_SECURITY = "MANAGE_SECURITY"

    def __str__(self) -> str:              # so f-strings show the value, not "Capability.X"
        return self.value


ALL_CAPABILITIES: frozenset[str] = frozenset(c.value for c in Capability)


# -- capability groups (used to derive built-in roles by rank) ---------------
_VIEW = frozenset({Capability.VIEW_PROJECT, Capability.VIEW_REPORTS, Capability.VIEW_DATASET,
                   Capability.VIEW_SCOUTING, Capability.VIEW_SETPIECE})
_CONTENT = frozenset({Capability.CREATE_PROJECT, Capability.EDIT_PROJECT,
                      Capability.CREATE_REPORT, Capability.EDIT_REPORTS,
                      Capability.EXPORT_REPORT, Capability.SHARE_REPORT,
                      Capability.UPLOAD_DATASET, Capability.EXPORT_DATA})
_DELETE_CONTENT = frozenset({Capability.DELETE_PROJECT, Capability.DELETE_REPORT,
                             Capability.DELETE_DATASET})
_SCOUT = frozenset({Capability.EDIT_SCOUTING})
_ADMIN = frozenset({Capability.VIEW_ADMIN, Capability.EDIT_USERS, Capability.INVITE_USER,
                    Capability.EDIT_ROLES, Capability.VIEW_AUDIT, Capability.VIEW_STORAGE,
                    Capability.MANAGE_STORAGE, Capability.VIEW_SESSIONS,
                    Capability.MANAGE_SESSIONS, Capability.MANAGE_PROVIDER,
                    Capability.MANAGE_SETTINGS, Capability.MANAGE_ORG,
                    Capability.MANAGE_SECURITY})


def _caps(*groups: frozenset) -> frozenset[str]:
    out: set[str] = set()
    for g in groups:
        out.update(c.value for c in g)
    return frozenset(out)


@dataclass(frozen=True, slots=True)
class RoleDefinition:
    """A role = a set of capabilities. ``superuser`` short-circuits to allow-all
    (Super Admin). ``builtin`` roles are seeded and cannot be deleted; custom
    roles are created by administrators. ``rank`` keeps built-ins ordered and
    lets the definition bridge to the legacy rank checks."""
    slug: str
    name: str
    capabilities: frozenset[str] = frozenset()
    superuser: bool = False
    builtin: bool = False
    rank: int = 0

    def allows(self, capability: str) -> bool:
        return self.superuser or str(capability) in self.capabilities

    def to_dict(self) -> dict:
        return {"slug": self.slug, "name": self.name,
                "capabilities": sorted(self.capabilities), "superuser": self.superuser,
                "builtin": self.builtin, "rank": self.rank}

    @classmethod
    def from_dict(cls, d: dict) -> "RoleDefinition":
        return cls(slug=d["slug"], name=d.get("name", d["slug"]),
                   capabilities=frozenset(d.get("capabilities", [])),
                   superuser=bool(d.get("superuser", False)),
                   builtin=bool(d.get("builtin", False)), rank=int(d.get("rank", 0)))


def builtin_role_definitions() -> dict[str, RoleDefinition]:
    """Built-in roles derived from the existing ``Role`` enum by rank, so every
    current user already maps to a capability set. Super Admin is allow-all."""
    defs: dict[str, RoleDefinition] = {}
    for role in Role:
        if role == Role.SUPER_ADMIN:
            caps, sup = ALL_CAPABILITIES, True
        elif role.rank >= Role.CLUB_ADMIN.rank:                 # Club Admin: admin + all content
            caps, sup = _caps(_VIEW, _CONTENT, _DELETE_CONTENT, _SCOUT, _ADMIN), False
        elif role.rank >= Role.MEDICAL_STAFF.rank:              # analysts/coaches: content editors
            extra = _SCOUT if role in (Role.SCOUT, Role.RECRUITMENT_ANALYST) else frozenset()
            caps, sup = _caps(_VIEW, _CONTENT, extra), False
        else:                                                    # Read Only and below
            caps, sup = _caps(_VIEW), False
        defs[role.slug] = RoleDefinition(slug=role.slug, name=role.label, capabilities=caps,
                                         superuser=sup, builtin=True, rank=role.rank)
    return defs


def role_capabilities(role: Role) -> frozenset[str]:
    """Capabilities a built-in ``Role`` grants (convenience for callers holding a
    Role rather than a definition)."""
    return builtin_role_definitions()[role.slug].capabilities


__all__ = ["Capability", "ALL_CAPABILITIES", "RoleDefinition",
           "builtin_role_definitions", "role_capabilities"]
