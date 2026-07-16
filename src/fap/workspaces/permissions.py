"""Authorization for workspace actions, built on the identity Role.

Capabilities are rank-based, so there is no per-role switch and a new role slots
in by rank alone:

    Super Admin   delete workspaces, manage roles (everything)
    Club Admin    manage the club hierarchy, delete/move projects & datasets
    analysts/...   edit (create & update projects, datasets, presets, versions)
    Read Only     view only - never modifies

``require`` raises AuthError, which the existing UI already handles.
"""
from __future__ import annotations

from enum import Enum

from fap.core.exceptions import AuthError
from fap.identity.roles import Role


class Capability(Enum):
    """A workspace action, mapped to the minimum role that may perform it."""
    VIEW = Role.READ_ONLY
    EDIT = Role.MEDICAL_STAFF          # anyone above Read Only may modify
    DELETE_PROJECT = Role.CLUB_ADMIN
    MANAGE_CLUB = Role.CLUB_ADMIN      # org hierarchy CRUD, move, archive across club
    MANAGE_ROLES = Role.SUPER_ADMIN
    DELETE_WORKSPACE = Role.SUPER_ADMIN

    def __init__(self, minimum: Role) -> None:
        self.minimum = minimum


def can(role: Role, capability: Capability) -> bool:
    """True when ``role`` has at least the authority ``capability`` requires."""
    return role >= capability.minimum


def require(role: Role, capability: Capability) -> None:
    """Guard an action; raise AuthError when the role is insufficient."""
    if not can(role, capability):
        raise AuthError(
            f"{role.label} is not permitted to {capability.name.lower().replace('_', ' ')} "
            f"(requires {capability.minimum.label} or higher).")
