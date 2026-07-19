"""PermissionService - the capability-based authorization decision.

Answers "may this user do X (optionally within scope S)?" from data, not a
role switch:

  * the user's role is resolved to a ``RoleDefinition`` (built-in or custom) and
    its capability set;
  * Super Admin (``superuser``) is allowed everything;
  * scoped ``Grant`` rows add or remove capabilities on an org node and INHERIT
    down the ``org_nodes`` tree (a grant on a club applies to its teams/
    workspaces); ``deny`` always beats ``allow``.

Pure decision logic over the repositories; org-tree traversal is injected as a
``node_parent`` callable so this module never imports the workspace layer.
"""
from __future__ import annotations

from typing import Callable

from fap.core.exceptions import AuthError
from fap.identity.capabilities import RoleDefinition, builtin_role_definitions
from fap.identity.directory import GrantRepository, RoleRepository, UserDirectoryRepository
from fap.identity.models import User
from fap.identity.roles import Role

NodeParent = Callable[[str], "str | None"]


class PermissionService:
    def __init__(self, roles: RoleRepository, users: UserDirectoryRepository,
                 grants: GrantRepository, node_parent: NodeParent | None = None) -> None:
        self._roles = roles
        self._users = users
        self._grants = grants
        self._node_parent = node_parent or (lambda _id: None)
        self._builtin = builtin_role_definitions()

    # -- role resolution ---------------------------------------------
    def role_definition(self, slug: str) -> RoleDefinition:
        """A role by slug: the stored definition if present, else the built-in,
        else a view-only fallback (fail safe, never crash on an unknown slug)."""
        stored = None
        try:
            stored = self._roles.get(slug)
        except Exception:
            stored = None
        return stored or self._builtin.get(slug) or self._builtin[Role.READ_ONLY.slug]

    def role_slug_for(self, user: User) -> str:
        """The user's effective role slug: their directory assignment (which may be
        a custom role) if present, else the role carried on the session User."""
        rec = None
        try:
            rec = self._users.get(user.email)
        except Exception:
            rec = None
        return (rec.role_slug if rec else None) or user.role.slug

    def capabilities_for(self, user: User) -> frozenset[str]:
        return self.role_definition(self.role_slug_for(user)).capabilities

    def is_superuser(self, user: User) -> bool:
        if user.role == Role.SUPER_ADMIN:
            return True
        return self.role_definition(self.role_slug_for(user)).superuser

    # -- the decision -------------------------------------------------
    def can(self, user: User, capability: str, scope_id: str | None = None) -> bool:
        capability = str(capability)
        if self.is_superuser(user):
            return True                                    # Super Admin: everything
        base = self.role_definition(self.role_slug_for(user)).allows(capability)

        chain = self._scope_chain(scope_id)                # scope + ancestors (+ global "")
        allow = deny = False
        try:
            grants = self._grants.for_user(user.email)
        except Exception:
            grants = []
        for g in grants:
            if g.scope_id not in chain:
                continue
            if capability in g.capabilities:
                if g.effect == "deny":
                    deny = True
                else:
                    allow = True
        if deny:
            return False                                   # explicit deny wins
        return base or allow

    def require(self, user: User, capability: str, scope_id: str | None = None) -> None:
        if not self.can(user, capability, scope_id):
            raise AuthError(
                f"{user.name or user.email} lacks capability {capability}"
                + (f" in this scope" if scope_id else "") + ".")

    # -- scope inheritance -------------------------------------------
    def _scope_chain(self, scope_id: str | None) -> set[str]:
        """The set of scope ids a grant may match for this request: the node
        itself, all its ancestors, and "" (a global grant applies everywhere)."""
        chain: set[str] = {""}
        node = scope_id
        seen: set[str] = set()
        while node and node not in seen:
            seen.add(node)
            chain.add(node)
            try:
                node = self._node_parent(node)
            except Exception:
                break
        return chain
