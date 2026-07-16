"""Identity and user models.

``Identity`` is who an external provider says you are - raw, un-trusted for
authorization. ``User`` is what the platform grants you after the access policy
runs: an identity plus a resolved role and organization. Pages only ever see
``User``; they never touch provider claims.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fap.identity.roles import Role


@dataclass(frozen=True, slots=True)
class Identity:
    """A normalized external identity (from OIDC claims). Provider-agnostic:
    every IdentityProvider maps its own token shape into this."""
    subject: str                              # stable unique id from the provider (oid/sub)
    email: str
    name: str = ""
    provider_id: str = ""                     # which identity provider vouched for this
    groups: tuple[str, ...] = ()              # group / app-role claims, if any
    claims: dict[str, Any] = field(default_factory=dict)

    @property
    def domain(self) -> str:
        return self.email.split("@", 1)[1].lower() if "@" in self.email else ""


@dataclass(frozen=True, slots=True)
class User:
    """An authenticated, authorized platform user. Immutable per session."""
    email: str
    name: str
    role: Role
    provider_id: str
    subject: str = ""
    organization: str = ""
    groups: tuple[str, ...] = ()

    # -- authorization helpers pages can use --------------------------
    def has_role(self, minimum: Role) -> bool:
        """True when this user's role is at least ``minimum`` by authority."""
        return self.role >= minimum

    def is_at_least(self, minimum: Role) -> bool:
        return self.has_role(minimum)

    @property
    def role_slug(self) -> str:
        return self.role.slug

    @property
    def role_label(self) -> str:
        return self.role.label

    def to_dict(self) -> dict[str, Any]:
        return {"email": self.email, "name": self.name, "role": self.role.slug,
                "role_label": self.role.label, "provider": self.provider_id,
                "organization": self.organization, "groups": list(self.groups)}
