"""Access policy - the platform's authorization decision.

Identity says who you are; this decides whether you get in and as what role.
It is deliberately pure (no Streamlit, no I/O) so every branch is unit-tested.

Fail closed: if the policy grants access to no one (no allowed domains and no
whitelisted emails), nobody is admitted. Access is only ever granted by an
explicit rule, never by the absence of one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from fap.identity.models import Identity, User
from fap.identity.roles import DEFAULT_ROLE, Role, role_from_slug


@dataclass(frozen=True, slots=True)
class AccessDecision:
    allowed: bool
    role: Role | None
    reason: str

    def user(self, identity: Identity, organization: str = "") -> User:
        if not self.allowed or self.role is None:
            raise ValueError("cannot build a User from a denied decision")
        return User(email=identity.email, name=identity.name or identity.email,
                    role=self.role, provider_id=identity.provider_id,
                    subject=identity.subject, organization=organization,
                    groups=identity.groups)


@dataclass(frozen=True, slots=True)
class AccessPolicy:
    """Who may sign in, and as what role.

    allowed_domains   email domains admitted (empty -> no domain is admitted)
    email_whitelist   individual emails admitted regardless of domain
    role_assignments  email -> role slug (highest-priority role source)
    group_roles       provider group/app-role name -> role slug
    default_role      role for an admitted user with no explicit assignment
    fail_closed       when True (default) an empty policy admits no one
    organization      display name of the club/tenant for the session
    """
    allowed_domains: frozenset[str] = frozenset()
    email_whitelist: frozenset[str] = frozenset()
    role_assignments: Mapping[str, str] = field(default_factory=dict)
    group_roles: Mapping[str, str] = field(default_factory=dict)
    default_role: Role = DEFAULT_ROLE
    fail_closed: bool = True
    organization: str = ""

    # -- construction from config ------------------------------------
    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "AccessPolicy":
        def _emails(key: str) -> frozenset[str]:
            return frozenset(str(e).strip().lower() for e in data.get(key, []) if str(e).strip())

        def _lower_map(key: str) -> dict[str, str]:
            raw = data.get(key, {}) or {}
            return {str(k).strip().lower(): str(v).strip().lower() for k, v in dict(raw).items()}

        domains = frozenset(str(d).strip().lower().lstrip("@")
                            for d in data.get("allowed_domains", []) if str(d).strip())
        default = role_from_slug(data.get("default_role"), DEFAULT_ROLE) or DEFAULT_ROLE
        return cls(
            allowed_domains=domains,
            email_whitelist=_emails("email_whitelist"),
            role_assignments=_lower_map("role_assignments"),
            group_roles=_lower_map("group_roles"),
            default_role=default,
            fail_closed=bool(data.get("fail_closed", True)),
            organization=str(data.get("organization", "")),
        )

    # -- the decision -------------------------------------------------
    @property
    def admits_no_one(self) -> bool:
        return not self.allowed_domains and not self.email_whitelist

    def _admitted(self, identity: Identity) -> bool:
        if not identity.email:
            return False
        if identity.email in self.email_whitelist:
            return True
        return identity.domain in self.allowed_domains

    def _role_for(self, identity: Identity) -> Role:
        # explicit per-email assignment wins
        assigned = role_from_slug(self.role_assignments.get(identity.email))
        if assigned is not None:
            return assigned
        # else the highest role any of the user's groups maps to
        group_role: Role | None = None
        for group in identity.groups:
            candidate = role_from_slug(self.group_roles.get(group.strip().lower()))
            if candidate is not None and (group_role is None or candidate > group_role):
                group_role = candidate
        return group_role if group_role is not None else self.default_role

    def resolve(self, identity: Identity) -> AccessDecision:
        if self.fail_closed and self.admits_no_one:
            return AccessDecision(False, None,
                                  "Access policy admits no one (fail closed): configure "
                                  "allowed_domains or email_whitelist.")
        if not self._admitted(identity):
            return AccessDecision(
                False, None,
                f"{identity.email or 'This account'} is not permitted: its domain is not in "
                f"allowed_domains and it is not on the email whitelist.")
        return AccessDecision(True, self._role_for(identity),
                              f"Admitted as {self._role_for(identity).label}.")
