"""Legacy dataset bridge (Phase 12.1).

The old ``fap.ui.shell`` flow stored a separate ``CANONICAL_DATASET`` dataframe in
its StateManager. There is now ONE source of truth for event data — the
``WorkspaceManager`` active dataset. This bridge lets the deprecated legacy pages
read that single source WITHOUT storing a second frame, so no duplicated state
remains. Production (``app.py`` → ``app_shell``) never imports this module; it
exists only so the legacy shell delegates correctly instead of holding its own
copy of the dataframe.
"""
from __future__ import annotations

from typing import Any

from fap.state import keys

_platform: Any = None


def _wm():
    """The fully-wired platform WorkspaceManager (built once). It owns the active
    dataset pointer (user_state table) and the frame (DatasetStorage)."""
    global _platform
    if _platform is None:
        from fap.bootstrap import init_platform
        _platform = init_platform()
    return _platform.workspace_manager


def _legacy_user(ctx: Any):
    from fap.identity.models import User
    from fap.identity.roles import Role
    cur = ctx.state.get(keys.CURRENT_USER) or {}
    email = cur.get("email") or cur.get("username")
    if not email:
        return None
    role = cur.get("role")
    return User(email=email, name=cur.get("username", email),
                role=role if isinstance(role, Role) else Role.READ_ONLY, provider_id="dev")


def legacy_active_frame(ctx: Any):
    """The WorkspaceManager active frame for the legacy current user, or ``None``.
    Reads the single source of truth; never stores a dataframe."""
    try:
        user = _legacy_user(ctx)
        if user is None:
            return None
        return _wm().active_frame(user)
    except Exception:
        return None
