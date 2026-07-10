"""Authentication workflow policy - kept out of the UI so it is unit-testable.

* Development mode: `environment: development` -> login is bypassed and the
  session runs as a temporary Developer user (never persisted to the DB).
* First-run bootstrap: if the user table is empty, one administrator account
  (admin / admin123) is created with must_change_password=True. It is NEVER
  recreated once any user exists.
"""
from __future__ import annotations

import logging
from typing import Any

from fap.auth.base import Authenticator
from fap.config.settings import AppSettings

logger = logging.getLogger(__name__)

BOOTSTRAP_ADMIN_USERNAME = "admin"
BOOTSTRAP_ADMIN_PASSWORD = "admin123"   # first-run only; forced change on first login

DEV_USER: dict[str, Any] = {
    "id": "dev-session",
    "username": "developer",
    "role": "admin",
    "must_change_password": False,
    "dev_mode": True,
}


def is_development(settings: AppSettings) -> bool:
    return settings.environment.strip().lower() == "development"


def ensure_bootstrap_admin(authenticator: Authenticator) -> bool:
    """Create the first-run admin if and only if no users exist.
    Returns True when the account was created."""
    if authenticator.has_any_users():
        return False
    authenticator.create_user(
        BOOTSTRAP_ADMIN_USERNAME, BOOTSTRAP_ADMIN_PASSWORD,
        role="admin", must_change_password=True,
    )
    logger.warning(
        "First run: created administrator %r with the default password. "
        "The password change is enforced at first login.",
        BOOTSTRAP_ADMIN_USERNAME,
    )
    return True


def session_user(user: Any) -> dict[str, Any]:
    """Serialize a User for session state."""
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "must_change_password": user.must_change_password,
        "dev_mode": False,
    }
