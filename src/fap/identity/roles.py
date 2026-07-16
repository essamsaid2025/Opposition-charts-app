"""Authorization roles - the platform's own concern.

Identity (who you are) comes from Microsoft/Google/Okta; authorization (what
you may do) is decided here from a role. Roles are ranked so a page can ask
``user.role >= Role.HEAD_COACH`` without hard-coding a list. Adding a role is
one enum member; nothing else in the platform needs to change.
"""
from __future__ import annotations

from enum import Enum


class Role(Enum):
    """A club role and its authority rank (higher = more authority)."""
    SUPER_ADMIN = ("super_admin", "Super Admin", 100)
    CLUB_ADMIN = ("club_admin", "Club Admin", 90)
    HEAD_COACH = ("head_coach", "Head Coach", 80)
    ASSISTANT_COACH = ("assistant_coach", "Assistant Coach", 70)
    GOALKEEPER_COACH = ("goalkeeper_coach", "Goalkeeper Coach", 65)
    PERFORMANCE_ANALYST = ("performance_analyst", "Performance Analyst", 60)
    FIRST_TEAM_ANALYST = ("first_team_analyst", "First Team Analyst", 55)
    ACADEMY_ANALYST = ("academy_analyst", "Academy Analyst", 50)
    RECRUITMENT_ANALYST = ("recruitment_analyst", "Recruitment Analyst", 45)
    SCOUT = ("scout", "Scout", 40)
    MEDICAL_STAFF = ("medical_staff", "Medical Staff", 30)
    READ_ONLY = ("read_only", "Read Only", 10)

    def __init__(self, slug: str, label: str, rank: int) -> None:
        self.slug = slug
        self.label = label
        self.rank = rank

    # -- ordering by authority ---------------------------------------
    def __ge__(self, other: "Role") -> bool:
        if not isinstance(other, Role):
            return NotImplemented
        return self.rank >= other.rank

    def __gt__(self, other: "Role") -> bool:
        if not isinstance(other, Role):
            return NotImplemented
        return self.rank > other.rank

    def __le__(self, other: "Role") -> bool:
        if not isinstance(other, Role):
            return NotImplemented
        return self.rank <= other.rank

    def __lt__(self, other: "Role") -> bool:
        if not isinstance(other, Role):
            return NotImplemented
        return self.rank < other.rank


DEFAULT_ROLE: Role = Role.READ_ONLY

_BY_SLUG: dict[str, Role] = {r.slug: r for r in Role}


def role_from_slug(slug: str | None, default: Role | None = None) -> Role | None:
    """Look a role up by its slug. Unknown/blank -> ``default`` (fail closed:
    callers pass no default when an unrecognized role must be rejected)."""
    if slug is None:
        return default
    return _BY_SLUG.get(str(slug).strip().lower(), default)


def all_roles() -> list[Role]:
    """Every role, highest authority first."""
    return sorted(Role, key=lambda r: r.rank, reverse=True)
