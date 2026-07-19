"""Bridge between the (Streamlit) session layer and the enterprise services.

The session module must stay provider-agnostic and must not import bootstrap.
The app injects a ``platform getter`` (the same one the shell already uses); this
bridge lazily resolves the AdministrationService + PermissionService from it and
exposes the narrow operations login needs: directory lookup, invitation
acceptance, auto-provisioning, session record/heartbeat/revoke, and audit.

If nothing is bound (pure unit tests, headless tools), ``backend()`` returns
None and the session layer falls back to the policy-only behaviour - so the
identity layer stays testable without a database.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from fap.identity.directory import PlatformUser
from fap.identity.models import User
from fap.identity.roles import Role

logger = logging.getLogger("fap.identity.enterprise")

_platform_getter: "Callable[[], Any] | None" = None


def bind(platform_getter: "Callable[[], Any] | None") -> None:
    """Called once by the shell/app with the platform accessor."""
    global _platform_getter
    _platform_getter = platform_getter


def _mini_user(email: str, name: str, provider_id: str) -> User:
    # a placeholder session User for audit/accept; real capabilities are resolved
    # from the directory by PermissionService, never from this enum.
    return User(email=email, name=name or email, role=Role.READ_ONLY,
                provider_id=provider_id, subject=email)


class AuthBackend:
    """Thin, exception-safe wrapper over the enterprise services for login."""

    def __init__(self, admin: Any, permissions: Any) -> None:
        self._admin = admin
        self._perms = permissions

    # -- directory-first authorization --------------------------------
    def directory(self, email: str) -> PlatformUser | None:
        try:
            return self._admin.users.get(email)
        except Exception:
            return None

    def accept_invitation(self, email: str, name: str, provider_id: str) -> PlatformUser | None:
        try:
            return self._admin.accept_pending_invitation(_mini_user(email, name, provider_id))
        except Exception:
            logger.exception("invitation acceptance failed for %s", email)
            return None

    def provision_read_only(self, email: str, name: str, provider_id: str) -> PlatformUser | None:
        try:
            return self._admin.provision_user(email, name=name, provider_id=provider_id,
                                               role_slug="read_only")
        except Exception:
            logger.exception("read-only provisioning failed for %s", email)
            return None

    def register_pending(self, email: str, name: str, provider_id: str) -> None:
        try:
            self._admin.provision_user(email, name=name, provider_id=provider_id,
                                       role_slug="read_only", status="suspended")
        except Exception:
            pass

    # -- sessions -----------------------------------------------------
    def record_login(self, user: User, provider_id: str) -> str | None:
        try:
            return self._admin.record_login(user, provider_id).id
        except Exception:
            logger.exception("record_login failed for %s", user.email)
            return None

    def is_revoked(self, session_id: str) -> bool:
        try:
            return self._admin.sessions.is_revoked(session_id)
        except Exception:
            return False

    def heartbeat(self, session_id: str) -> None:
        try:
            self._admin.sessions.touch(session_id)
        except Exception:
            pass

    def revoke(self, user: User, session_id: str) -> None:
        try:
            self._admin.sessions.force_logout(session_id)
            self._admin.audit.record(user, "auth.logout", target_type="user", target_id=user.email)
        except Exception:
            pass

    # -- audit --------------------------------------------------------
    def audit_failed_login(self, email: str, reason: str, provider_id: str = "") -> None:
        try:
            self._admin.audit.record(None, "auth.login_failed", target_type="user",
                                     target_id=email, detail={"reason": reason,
                                                              "provider": provider_id})
        except Exception:
            pass


def backend() -> AuthBackend | None:
    """Resolve the enterprise backend from the bound platform getter, or None."""
    if _platform_getter is None:
        return None
    try:
        platform = _platform_getter()
        if platform is None:
            return None
        return AuthBackend(platform.administration, platform.permissions)
    except Exception:
        logger.exception("could not resolve enterprise backend")
        return None
