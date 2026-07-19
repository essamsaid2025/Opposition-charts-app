"""AdministrationService - the enterprise admin façade.

Composes the directory repositories, the PermissionService and the existing
AuditService; it does NOT create a parallel workspace/report manager and never
bypasses identity or audit. Every mutation is capability-checked and audited.

One place seeds the built-in roles and the first Super Admin; everything else
(users, roles, grants, invitations, sessions, storage) is CRUD on top of the
migration-8 tables, reusing the platform Database, DatasetStorage, ImageStorage
and CacheManager already constructed by bootstrap.
"""
from __future__ import annotations

import secrets
import uuid
from typing import Any

from fap.core.exceptions import AuthError
from fap.identity.access import PermissionService
from fap.identity.capabilities import (
    ALL_CAPABILITIES, Capability, RoleDefinition, builtin_role_definitions,
)
from fap.identity.directory import (
    Grant, GrantRepository, Invitation, InvitationRepository, PlatformUser,
    RoleRepository, SessionRecord, SessionRepository, UserDirectoryRepository,
)
from fap.identity.models import User
from fap.identity.positions import normalize_position
from fap.identity.roles import Role, role_from_slug
from fap.workspaces.audit import AuditService


class AdministrationService:
    def __init__(self, db: Any, *, audit: AuditService, permissions: PermissionService,
                 storage: Any = None, images: Any = None, cache: Any = None,
                 email: Any = None, base_url: str = "", platform_name: str = "the platform") -> None:
        self._db = db
        self.roles = RoleRepository(db)
        self.users = UserDirectoryRepository(db)
        self.grants = GrantRepository(db)
        self.invites = InvitationRepository(db)
        self.sessions = SessionRepository(db)
        self.audit = audit
        self.perms = permissions
        self._storage = storage
        self._images = images
        self._cache = cache
        self._email = email
        self._base_url = base_url
        self._platform_name = platform_name
        self.seed_builtin_roles()

    def provision_user(self, email: str, *, name: str = "", provider_id: str = "",
                       role_slug: str = "read_only", status: str = "active") -> PlatformUser:
        """System-level provisioning at first login (no actor / no capability
        check - this is the platform admitting a user per policy, and is audited
        as such). Never elevates: a Super Admin is only ever seeded explicitly."""
        if role_slug == Role.SUPER_ADMIN.slug:
            role_slug = Role.READ_ONLY.slug
        existing = self.users.get(email)
        rec = existing or PlatformUser(email=email.lower(), provider_id=provider_id)
        rec.name = name or rec.name
        rec.role_slug = existing.role_slug if existing else role_slug
        rec.status = status if not existing else existing.status
        rec.provider_id = provider_id or rec.provider_id
        self.users.save(rec)
        self.audit.record(None, "auth.provision", target_type="user", target_id=email,
                          detail={"role": rec.role_slug, "status": rec.status})
        return rec

    # ---------------------------------------------------------------- seeding
    def seed_builtin_roles(self) -> None:
        """Ensure the built-in role definitions exist (idempotent)."""
        existing = {r.slug for r in self.roles.list()}
        for slug, rd in builtin_role_definitions().items():
            if slug not in existing:
                self.roles.save(rd, created_by="system")

    def ensure_super_admin(self, email: str, name: str = "") -> PlatformUser | None:
        """Seed the first Super Admin (idempotent). Called by bootstrap with the
        configured owner email; nothing happens if email is blank."""
        email = (email or "").strip().lower()
        if not email:
            return None
        rec = self.users.get(email)
        if rec and rec.role_slug == Role.SUPER_ADMIN.slug:
            return rec
        user = PlatformUser(email=email, name=name or (rec.name if rec else email),
                            role_slug=Role.SUPER_ADMIN.slug, status="active",
                            position=(rec.position if rec else "Sporting Director"),
                            invited_by="system")
        self.users.save(user)
        return user

    # ---------------------------------------------------------------- guards
    def _require(self, actor: User, capability: Capability) -> None:
        self.perms.require(actor, str(capability))

    # ---------------------------------------------------------------- users
    def list_users(self, actor: User, *, status: str | None = None) -> list[PlatformUser]:
        self._require(actor, Capability.VIEW_ADMIN)
        return self.users.list(status=status)

    def upsert_user(self, actor: User, email: str, *, name: str = "", position: str = "",
                    role_slug: str = "read_only", provider_id: str = "") -> PlatformUser:
        self._require(actor, Capability.EDIT_USERS)
        self._guard_super_admin_assignment(actor, role_slug)
        existing = self.users.get(email)
        user = PlatformUser(
            email=email.lower(), name=name or (existing.name if existing else ""),
            position=normalize_position(position or (existing.position if existing else "")),
            role_slug=role_slug, provider_id=provider_id or (existing.provider_id if existing else ""),
            status=(existing.status if existing else "active"),
            org_id=existing.org_id if existing else None,
            club_id=existing.club_id if existing else None,
            team_id=existing.team_id if existing else None,
            workspace_id=existing.workspace_id if existing else None,
            last_login_at=existing.last_login_at if existing else None,
            invited_by=existing.invited_by if existing else actor.email)
        self.users.save(user)
        self.audit.record(actor, "admin.user.upsert", target_type="user", target_id=email,
                          detail={"role": role_slug, "position": user.position})
        return user

    def set_role(self, actor: User, email: str, role_slug: str) -> None:
        self._require(actor, Capability.EDIT_USERS)
        self._guard_super_admin_assignment(actor, role_slug)
        rec = self._user_or_raise(email)
        rec.role_slug = role_slug
        self.users.save(rec)
        self.audit.record(actor, "admin.user.role", target_type="user", target_id=email,
                          detail={"role": role_slug})

    def set_position(self, actor: User, email: str, position: str) -> None:
        self._require(actor, Capability.EDIT_USERS)
        rec = self._user_or_raise(email)
        rec.position = normalize_position(position)
        self.users.save(rec)
        self.audit.record(actor, "admin.user.position", target_type="user", target_id=email,
                          detail={"position": rec.position})

    def set_status(self, actor: User, email: str, status: str) -> None:
        self._require(actor, Capability.EDIT_USERS)
        if status not in ("active", "suspended", "disabled"):
            raise ValueError(f"invalid status {status!r}")
        rec = self._user_or_raise(email)
        rec.status = status
        self.users.save(rec)
        if status != "active":
            self.sessions.force_logout_user(email)         # suspending ends live sessions
        self.audit.record(actor, f"admin.user.{status}", target_type="user", target_id=email)

    def assign_scope(self, actor: User, email: str, *, org_id: str | None = None,
                     club_id: str | None = None, team_id: str | None = None,
                     workspace_id: str | None = None) -> None:
        self._require(actor, Capability.EDIT_USERS)
        rec = self._user_or_raise(email)
        if org_id is not None: rec.org_id = org_id or None
        if club_id is not None: rec.club_id = club_id or None
        if team_id is not None: rec.team_id = team_id or None
        if workspace_id is not None: rec.workspace_id = workspace_id or None
        self.users.save(rec)
        self.audit.record(actor, "admin.user.scope", target_type="user", target_id=email,
                          detail={"org": rec.org_id, "club": rec.club_id, "team": rec.team_id,
                                  "workspace": rec.workspace_id})

    def delete_user(self, actor: User, email: str) -> None:
        self._require(actor, Capability.EDIT_USERS)
        rec = self._user_or_raise(email)
        if rec.role_slug == Role.SUPER_ADMIN.slug and not self.perms.is_superuser(actor):
            raise AuthError("Only a Super Admin can remove a Super Admin.")
        self.sessions.force_logout_user(email)
        self.users.delete(email)
        self.audit.record(actor, "admin.user.delete", target_type="user", target_id=email)

    def record_login(self, user: User, provider_id: str = "") -> SessionRecord:
        """Record/refresh a user's directory row and open a session on sign-in.
        Auto-provisions a directory row for a first-time SSO user."""
        rec = self.users.get(user.email)
        if rec is None:
            rec = PlatformUser(email=user.email, name=user.name, role_slug=user.role.slug,
                               provider_id=provider_id or user.provider_id, status="active")
        rec.name = user.name or rec.name
        rec.last_login_at = "now"                          # set via SQL default on save path
        self.users.save(rec)
        # last_login stored explicitly (save() upserts the column verbatim)
        self._db.execute("UPDATE platform_users SET last_login_at = datetime('now') WHERE email = ?",
                         (user.email.lower(),))
        session = SessionRecord(id=str(uuid.uuid4()), email=user.email,
                                provider_id=provider_id or user.provider_id)
        self.sessions.start(session)
        self.audit.record(user, "auth.login", target_type="user", target_id=user.email)
        return session

    # ---------------------------------------------------------------- roles
    def list_roles(self) -> list[RoleDefinition]:
        return self.roles.list()

    def create_role(self, actor: User, name: str, capabilities: list[str], *,
                    slug: str = "") -> RoleDefinition:
        self._require(actor, Capability.MANAGE_ROLES)
        slug = (slug or name).strip().lower().replace(" ", "_")
        if not slug:
            raise ValueError("role needs a name")
        caps = frozenset(c for c in capabilities if c in ALL_CAPABILITIES)
        rd = RoleDefinition(slug=slug, name=name.strip(), capabilities=caps,
                            superuser=False, builtin=False, rank=1)
        self.roles.save(rd, created_by=actor.email)
        self.audit.record(actor, "admin.role.create", target_type="role", target_id=slug,
                          detail={"capabilities": sorted(caps)})
        return rd

    def update_role(self, actor: User, slug: str, *, name: str | None = None,
                    capabilities: list[str] | None = None) -> RoleDefinition:
        self._require(actor, Capability.MANAGE_ROLES)
        rd = self.roles.get(slug)
        if rd is None:
            raise ValueError(f"role {slug!r} not found")
        if rd.builtin:
            raise AuthError("Built-in roles cannot be edited; create a custom role instead.")
        new = RoleDefinition(slug=rd.slug, name=name or rd.name,
                             capabilities=(frozenset(c for c in capabilities if c in ALL_CAPABILITIES)
                                           if capabilities is not None else rd.capabilities),
                             superuser=False, builtin=False, rank=rd.rank)
        self.roles.save(new)
        self.audit.record(actor, "admin.role.update", target_type="role", target_id=slug)
        return new

    def delete_role(self, actor: User, slug: str) -> None:
        self._require(actor, Capability.MANAGE_ROLES)
        rd = self.roles.get(slug)
        if rd and rd.builtin:
            raise AuthError("Built-in roles cannot be deleted.")
        self.roles.delete(slug)
        self.audit.record(actor, "admin.role.delete", target_type="role", target_id=slug)

    # ---------------------------------------------------------------- scoped grants
    def grant(self, actor: User, email: str, *, scope_kind: str, scope_id: str,
              capabilities: list[str], effect: str = "allow") -> Grant:
        self._require(actor, Capability.EDIT_ROLES)
        g = Grant(id=str(uuid.uuid4()), email=email.lower(), scope_kind=scope_kind,
                  scope_id=scope_id, capabilities=[c for c in capabilities if c in ALL_CAPABILITIES],
                  effect=("deny" if effect == "deny" else "allow"), created_by=actor.email)
        self.grants.add(g)
        self.audit.record(actor, "admin.grant.add", target_type="user", target_id=email,
                          detail={"scope": f"{scope_kind}:{scope_id}", "effect": g.effect,
                                  "capabilities": g.capabilities})
        return g

    def revoke_grant(self, actor: User, grant_id: str, email: str = "") -> None:
        self._require(actor, Capability.EDIT_ROLES)
        self.grants.delete(grant_id)
        self.audit.record(actor, "admin.grant.revoke", target_type="user", target_id=email,
                          detail={"grant": grant_id})

    def list_grants(self, actor: User, email: str) -> list[Grant]:
        self._require(actor, Capability.VIEW_ADMIN)
        return self.grants.for_user(email)

    # ---------------------------------------------------------------- invitations
    def invite(self, actor: User, email: str, *, role_slug: str = "read_only",
               position: str = "", scope_kind: str = "", scope_id: str = "") -> Invitation:
        self._require(actor, Capability.INVITE_USER)
        self._guard_super_admin_assignment(actor, role_slug)
        inv = Invitation(id=str(uuid.uuid4()), email=email.lower(), role_slug=role_slug,
                         position=normalize_position(position), scope_kind=scope_kind,
                         scope_id=scope_id, status="pending",
                         token=secrets.token_urlsafe(24), invited_by=actor.email)
        self.invites.add(inv)
        self.audit.record(actor, "admin.invite.create", target_type="invitation", target_id=email,
                          detail={"role": role_slug})
        self._send_invitation_email(actor, inv)
        return inv

    def _send_invitation_email(self, actor: User, inv: Invitation) -> None:
        """Deliver the invitation via the injected EmailProvider (Console in dev,
        Microsoft Graph in production). Best-effort: a delivery failure never
        breaks the invite, but is audited."""
        if self._email is None:
            return
        from fap.identity.email import invitation_message
        link = (f"{self._base_url.rstrip('/')}/?invite={inv.token}"
                if self._base_url else f"?invite={inv.token}")
        role = self.roles.get(inv.role_slug)
        msg = invitation_message(to=inv.email, platform_name=self._platform_name,
                                 inviter=actor.name or actor.email,
                                 role_name=role.name if role else inv.role_slug, link=link)
        try:
            ok = bool(self._email.send(msg))
        except Exception:
            ok = False
        self.audit.record(actor, "admin.invite.email_sent" if ok else "admin.invite.email_failed",
                          target_type="invitation", target_id=inv.email,
                          detail={"provider": getattr(getattr(self._email, "info", None), "id", "")})

    def list_invitations(self, actor: User, *, status: str | None = None) -> list[Invitation]:
        self._require(actor, Capability.VIEW_ADMIN)
        return self.invites.list(status=status)

    def revoke_invitation(self, actor: User, invite_id: str) -> None:
        self._require(actor, Capability.INVITE_USER)
        self.invites.set_status(invite_id, "revoked")
        self.audit.record(actor, "admin.invite.revoke", target_type="invitation", target_id=invite_id)

    def accept_pending_invitation(self, user: User) -> PlatformUser | None:
        """On first sign-in, turn a pending invitation into a provisioned user.
        Returns the created directory row, or None if there was no invitation."""
        inv = self.invites.get_pending(user.email)
        if inv is None:
            return None
        rec = PlatformUser(email=user.email, name=user.name, role_slug=inv.role_slug,
                           position=inv.position, provider_id=user.provider_id, status="active",
                           workspace_id=inv.scope_id if inv.scope_kind == "workspace" else None,
                           team_id=inv.scope_id if inv.scope_kind == "team" else None,
                           club_id=inv.scope_id if inv.scope_kind == "club" else None,
                           org_id=inv.scope_id if inv.scope_kind == "organization" else None,
                           invited_by=inv.invited_by)
        self.users.save(rec)
        self.invites.set_status(inv.id, "accepted", accepted=True)
        self.audit.record(user, "admin.invite.accept", target_type="user", target_id=user.email)
        return rec

    # ---------------------------------------------------------------- sessions
    def list_sessions(self, actor: User, *, active_only: bool = False) -> list[SessionRecord]:
        self._require(actor, Capability.VIEW_SESSIONS)
        return self.sessions.list(active_only=active_only)

    def force_logout(self, actor: User, session_id: str) -> None:
        self._require(actor, Capability.MANAGE_SESSIONS)
        self.sessions.force_logout(session_id)
        self.audit.record(actor, "admin.session.force_logout", target_type="session", target_id=session_id)

    def force_logout_user(self, actor: User, email: str) -> None:
        self._require(actor, Capability.MANAGE_SESSIONS)
        self.sessions.force_logout_user(email)
        self.audit.record(actor, "admin.session.force_logout_user", target_type="user", target_id=email)

    # ---------------------------------------------------------------- storage
    def storage_report(self, actor: User) -> dict[str, Any]:
        self._require(actor, Capability.VIEW_STORAGE)
        report: dict[str, Any] = {"tables": {}, "datasets_bytes": 0, "images_bytes": 0}
        for t in ("datasets", "projects", "workspaces", "reports", "report_images",
                  "presets", "audit_log", "org_nodes", "platform_users", "invitations"):
            try:
                report["tables"][t] = self._db.query(f"SELECT COUNT(*) AS c FROM {t}")[0]["c"]
            except Exception:
                report["tables"][t] = None
        report["datasets_bytes"] = self._dir_size(getattr(self._storage, "_root", None))
        report["images_bytes"] = self._dir_size(getattr(self._images, "_root", None))
        return report

    def cleanup_cache(self, actor: User) -> None:
        self._require(actor, Capability.MANAGE_STORAGE)
        if self._cache is not None and hasattr(self._cache, "clear"):
            try:
                self._cache.clear()
            except Exception:
                pass
        self.audit.record(actor, "admin.storage.cache_clear", target_type="cache", target_id="")

    # ---------------------------------------------------------------- helpers
    def _user_or_raise(self, email: str) -> PlatformUser:
        rec = self.users.get(email)
        if rec is None:
            raise ValueError(f"user {email!r} not found")
        return rec

    def _guard_super_admin_assignment(self, actor: User, role_slug: str) -> None:
        """Only a Super Admin may create/assign the Super Admin role."""
        if role_slug == Role.SUPER_ADMIN.slug and not self.perms.is_superuser(actor):
            raise AuthError("Only a Super Admin can grant the Super Admin role.")

    @staticmethod
    def _dir_size(root: Any) -> int:
        if not root:
            return 0
        import os
        total = 0
        try:
            for dirpath, _dirs, files in os.walk(str(root)):
                for f in files:
                    try:
                        total += os.path.getsize(os.path.join(dirpath, f))
                    except OSError:
                        pass
        except Exception:
            return 0
        return total
