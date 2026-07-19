"""Persistence for the enterprise directory: role definitions, platform users,
scoped permission grants, invitations and sessions.

Repository pattern over the SAME platform ``Database`` (migration 8) - the only
place this SQL lives. Records are plain dataclasses; capability lists are stored
as JSON so they survive schema changes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from fap.db.engine import Database
from fap.identity.capabilities import RoleDefinition


# ---------------------------------------------------------------- records
@dataclass(slots=True)
class PlatformUser:
    email: str
    name: str = ""
    position: str = ""
    role_slug: str = "read_only"
    org_id: str | None = None
    club_id: str | None = None
    team_id: str | None = None
    workspace_id: str | None = None
    status: str = "active"                 # active | suspended | disabled
    provider_id: str = ""
    created_at: str = ""
    last_login_at: str | None = None
    invited_by: str | None = None


@dataclass(slots=True)
class Grant:
    id: str
    email: str
    scope_kind: str = "workspace"          # organization|club|team|workspace|project
    scope_id: str = ""
    capabilities: list[str] = field(default_factory=list)
    effect: str = "allow"                  # allow | deny
    created_at: str = ""
    created_by: str | None = None


@dataclass(slots=True)
class Invitation:
    id: str
    email: str
    role_slug: str = "read_only"
    position: str = ""
    scope_kind: str = ""
    scope_id: str = ""
    status: str = "pending"                # pending|accepted|revoked|expired
    token: str = ""
    invited_by: str | None = None
    created_at: str = ""
    accepted_at: str | None = None


@dataclass(slots=True)
class SessionRecord:
    id: str
    email: str
    provider_id: str = ""
    started_at: str = ""
    last_seen_at: str = ""
    status: str = "active"                 # active|expired|forced_out
    revoked: bool = False


# ---------------------------------------------------------------- role definitions
class RoleRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def save(self, r: RoleDefinition, created_by: str | None = None) -> None:
        self._db.execute(
            """INSERT INTO role_definitions (slug, name, capabilities, superuser, builtin, rank, created_by)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(slug) DO UPDATE SET name=excluded.name,
                 capabilities=excluded.capabilities, superuser=excluded.superuser,
                 rank=excluded.rank""",
            (r.slug, r.name, json.dumps(sorted(r.capabilities)), int(r.superuser),
             int(r.builtin), r.rank, created_by))

    def get(self, slug: str) -> RoleDefinition | None:
        rows = self._db.query("SELECT * FROM role_definitions WHERE slug = ?", (slug,))
        return self._row(rows[0]) if rows else None

    def list(self) -> list[RoleDefinition]:
        rows = self._db.query("SELECT * FROM role_definitions ORDER BY rank DESC, name")
        return [self._row(r) for r in rows]

    def delete(self, slug: str) -> None:
        self._db.execute("DELETE FROM role_definitions WHERE slug = ? AND builtin = 0", (slug,))

    @staticmethod
    def _row(r: Any) -> RoleDefinition:
        return RoleDefinition(slug=r["slug"], name=r["name"],
                              capabilities=frozenset(json.loads(r["capabilities"])),
                              superuser=bool(r["superuser"]), builtin=bool(r["builtin"]),
                              rank=int(r["rank"]))


# ---------------------------------------------------------------- user directory
class UserDirectoryRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def save(self, u: PlatformUser) -> None:
        self._db.execute(
            """INSERT INTO platform_users
                 (email, name, position, role_slug, org_id, club_id, team_id, workspace_id,
                  status, provider_id, last_login_at, invited_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(email) DO UPDATE SET name=excluded.name, position=excluded.position,
                 role_slug=excluded.role_slug, org_id=excluded.org_id, club_id=excluded.club_id,
                 team_id=excluded.team_id, workspace_id=excluded.workspace_id,
                 status=excluded.status, provider_id=excluded.provider_id,
                 last_login_at=excluded.last_login_at, invited_by=excluded.invited_by""",
            (u.email.lower(), u.name, u.position, u.role_slug, u.org_id, u.club_id, u.team_id,
             u.workspace_id, u.status, u.provider_id, u.last_login_at, u.invited_by))

    def get(self, email: str) -> PlatformUser | None:
        rows = self._db.query("SELECT * FROM platform_users WHERE email = ?", (email.lower(),))
        return self._row(rows[0]) if rows else None

    def list(self, *, status: str | None = None, role_slug: str | None = None) -> list[PlatformUser]:
        sql, clauses, params = "SELECT * FROM platform_users", [], []
        if status is not None:
            clauses.append("status = ?"); params.append(status)
        if role_slug is not None:
            clauses.append("role_slug = ?"); params.append(role_slug)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY name, email"
        return [self._row(r) for r in self._db.query(sql, tuple(params))]

    def delete(self, email: str) -> None:
        self._db.execute("DELETE FROM platform_users WHERE email = ?", (email.lower(),))

    @staticmethod
    def _row(r: Any) -> PlatformUser:
        return PlatformUser(
            email=r["email"], name=r["name"], position=r["position"], role_slug=r["role_slug"],
            org_id=r["org_id"], club_id=r["club_id"], team_id=r["team_id"],
            workspace_id=r["workspace_id"], status=r["status"], provider_id=r["provider_id"],
            created_at=r["created_at"], last_login_at=r["last_login_at"], invited_by=r["invited_by"])


# ---------------------------------------------------------------- grants
class GrantRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, g: Grant) -> None:
        self._db.execute(
            """INSERT INTO permission_grants (id, email, scope_kind, scope_id, capabilities, effect, created_by)
               VALUES (?,?,?,?,?,?,?)""",
            (g.id, g.email.lower(), g.scope_kind, g.scope_id, json.dumps(g.capabilities),
             g.effect, g.created_by))

    def for_user(self, email: str) -> list[Grant]:
        rows = self._db.query("SELECT * FROM permission_grants WHERE email = ?", (email.lower(),))
        return [self._row(r) for r in rows]

    def delete(self, grant_id: str) -> None:
        self._db.execute("DELETE FROM permission_grants WHERE id = ?", (grant_id,))

    @staticmethod
    def _row(r: Any) -> Grant:
        return Grant(id=r["id"], email=r["email"], scope_kind=r["scope_kind"],
                     scope_id=r["scope_id"], capabilities=json.loads(r["capabilities"]),
                     effect=r["effect"], created_at=r["created_at"], created_by=r["created_by"])


# ---------------------------------------------------------------- invitations
class InvitationRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, inv: Invitation) -> None:
        self._db.execute(
            """INSERT INTO invitations (id, email, role_slug, position, scope_kind, scope_id,
                 status, token, invited_by)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (inv.id, inv.email.lower(), inv.role_slug, inv.position, inv.scope_kind,
             inv.scope_id, inv.status, inv.token, inv.invited_by))

    def get_pending(self, email: str) -> Invitation | None:
        rows = self._db.query(
            "SELECT * FROM invitations WHERE email = ? AND status = 'pending' "
            "ORDER BY created_at DESC LIMIT 1", (email.lower(),))
        return self._row(rows[0]) if rows else None

    def list(self, *, status: str | None = None) -> list[Invitation]:
        if status:
            rows = self._db.query("SELECT * FROM invitations WHERE status = ? ORDER BY created_at DESC",
                                  (status,))
        else:
            rows = self._db.query("SELECT * FROM invitations ORDER BY created_at DESC")
        return [self._row(r) for r in rows]

    def set_status(self, invite_id: str, status: str, accepted: bool = False) -> None:
        if accepted:
            self._db.execute(
                "UPDATE invitations SET status = ?, accepted_at = datetime('now') WHERE id = ?",
                (status, invite_id))
        else:
            self._db.execute("UPDATE invitations SET status = ? WHERE id = ?", (status, invite_id))

    @staticmethod
    def _row(r: Any) -> Invitation:
        return Invitation(id=r["id"], email=r["email"], role_slug=r["role_slug"],
                          position=r["position"], scope_kind=r["scope_kind"], scope_id=r["scope_id"],
                          status=r["status"], token=r["token"], invited_by=r["invited_by"],
                          created_at=r["created_at"], accepted_at=r["accepted_at"])


# ---------------------------------------------------------------- sessions
class SessionRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def start(self, s: SessionRecord) -> None:
        self._db.execute(
            """INSERT INTO user_sessions (id, email, provider_id) VALUES (?,?,?)
               ON CONFLICT(id) DO UPDATE SET last_seen_at=datetime('now'), status='active', revoked=0""",
            (s.id, s.email.lower(), s.provider_id))

    def touch(self, session_id: str) -> None:
        self._db.execute(
            "UPDATE user_sessions SET last_seen_at=datetime('now') WHERE id=? AND revoked=0",
            (session_id,))

    def list(self, *, active_only: bool = False) -> list[SessionRecord]:
        sql = "SELECT * FROM user_sessions"
        if active_only:
            sql += " WHERE status='active' AND revoked=0"
        sql += " ORDER BY last_seen_at DESC"
        return [self._row(r) for r in self._db.query(sql)]

    def force_logout(self, session_id: str) -> None:
        self._db.execute(
            "UPDATE user_sessions SET status='forced_out', revoked=1 WHERE id=?", (session_id,))

    def force_logout_user(self, email: str) -> None:
        self._db.execute(
            "UPDATE user_sessions SET status='forced_out', revoked=1 WHERE email=? AND revoked=0",
            (email.lower(),))

    def is_revoked(self, session_id: str) -> bool:
        rows = self._db.query("SELECT revoked FROM user_sessions WHERE id=?", (session_id,))
        return bool(rows and rows[0]["revoked"])

    @staticmethod
    def _row(r: Any) -> SessionRecord:
        return SessionRecord(id=r["id"], email=r["email"], provider_id=r["provider_id"],
                             started_at=r["started_at"], last_seen_at=r["last_seen_at"],
                             status=r["status"], revoked=bool(r["revoked"]))
