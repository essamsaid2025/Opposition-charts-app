"""Streamlit session facade - the ONLY identity module that imports Streamlit.

Pages call ``current_user()`` / ``require_login()`` / ``logout()`` and never see
a provider name, a claim, or ``st.user``. Production runs Streamlit's native OIDC
(Authlib) via ``st.login`` / ``st.logout``; development skips OAuth with a local
email form. EITHER WAY the authorization path is identical and DIRECTORY-FIRST:

    authenticate (Microsoft or dev email)
        -> normalize identity
        -> Platform Directory lookup   (role/status assigned by an admin)
        -> else accept pending invitation (provision)
        -> else unknown-user policy    (reject | pending | read_only)
        -> record session + enforce revocation/idle-timeout on every request

Microsoft only AUTHENTICATES; the platform AUTHORIZES from the directory. When no
enterprise backend is bound (pure tests), the module falls back to the policy-only
decision so the identity layer stays testable without a database.
"""
from __future__ import annotations

import time
from typing import Any

import streamlit as st

from fap.identity import enterprise
from fap.identity.builtin.dev import DevProvider
from fap.identity.config import IdentityConfig, development_mode, load_identity_config
from fap.identity.models import Identity, User
from fap.identity.provider import load_builtin_identity_providers
from fap.identity.roles import DEFAULT_ROLE, Role, role_from_slug
from fap.identity.service import IdentityService

_USER_KEY = "_fap_identity_user"
_LOGIN_TS_KEY = "_fap_identity_login_ts"
_PROVIDER_KEY = "_fap_identity_provider"
_SESSION_ID_KEY = "_fap_identity_session_id"
_DEV_EMAIL_KEY = "_fap_dev_email"
_DEV_NAME_KEY = "_fap_dev_name"
_DEV_REMEMBER_KEY = "_fap_dev_remember"
_DENIED_KEY = "_fap_denied_reason"


# ---------------------------------------------------------------- pure helpers
def is_session_expired(login_ts: float | None, now: float, timeout_minutes: int,
                       remember: bool) -> bool:
    """Idle-timeout check. ``remember`` keeps a session alive across the idle
    window; a non-positive timeout disables expiry entirely."""
    if remember or timeout_minutes <= 0 or login_ts is None:
        return False
    return (now - login_ts) > (timeout_minutes * 60)


def _secrets() -> dict[str, Any]:
    try:
        return {k: st.secrets[k] for k in st.secrets}      # Streamlit Secrets -> dict
    except Exception:
        return {}


def _config() -> IdentityConfig:
    load_builtin_identity_providers()
    return load_identity_config(_secrets(), development=development_mode())


def _service() -> IdentityService:
    return IdentityService(_config())


# ---------------------------------------------------------------- public API
def current_user() -> User | None:
    """The authorized user for this session, or None if not signed in / denied.
    Never raises and never renders."""
    cfg = _config()
    provider_id, claims = _pending_identity(cfg)
    if provider_id is None or claims is None:
        return None

    remember = cfg.remember_session or bool(st.session_state.get(_DEV_REMEMBER_KEY))
    login_ts = st.session_state.get(_LOGIN_TS_KEY)
    if is_session_expired(login_ts, time.time(), cfg.session_timeout_minutes, remember):
        logout()
        return None
    st.session_state.setdefault(_LOGIN_TS_KEY, time.time())

    identity = _service().normalize(provider_id, claims)
    if not identity.email:
        return None
    return _authorize(cfg, identity, provider_id)


def require_login() -> User:
    """Gate the page: return the user, or render sign-in / access-denied and stop."""
    user = current_user()
    if user is not None:
        return user

    cfg = _config()
    if cfg.development:
        _render_dev_login(cfg)
    else:
        user_obj = st.user if hasattr(st, "user") else None
        if user_obj is not None and getattr(user_obj, "is_logged_in", False):
            _render_denied(cfg)          # authenticated but not authorized
        else:
            _render_login(cfg)           # not authenticated
    st.stop()
    raise RuntimeError("unreachable")


def logout() -> None:
    """Sign out of the platform and the identity provider, revoking the session."""
    sid = st.session_state.get(_SESSION_ID_KEY)
    if sid:
        be = enterprise.backend()
        if be is not None:
            saved = st.session_state.get(_USER_KEY) or {}
            actor = User(email=saved.get("email", ""), name=saved.get("name", ""),
                         role=role_from_slug(saved.get("role"), DEFAULT_ROLE) or DEFAULT_ROLE,
                         provider_id=saved.get("provider", "")) if saved else None
            be.revoke(actor, sid) if actor else None
    _clear_session()
    if hasattr(st, "logout"):
        try:
            st.logout()
        except Exception:
            pass


def roles() -> list[Role]:
    from fap.identity.roles import all_roles
    return all_roles()


# ---------------------------------------------------------------- authorization
def _pending_identity(cfg: IdentityConfig) -> tuple[str | None, dict[str, Any] | None]:
    """The authenticated-but-not-yet-authorized identity for this request:
    the dev email form in development, Streamlit's native ``st.user`` in prod."""
    if cfg.development:
        email = st.session_state.get(_DEV_EMAIL_KEY)
        if not email:
            return None, None
        return "dev", {"email": email, "name": st.session_state.get(_DEV_NAME_KEY) or email}

    user_obj = st.user if hasattr(st, "user") else None
    if not user_obj or not getattr(user_obj, "is_logged_in", False):
        _clear_session()
        return None, None
    provider_id = st.session_state.get(_PROVIDER_KEY) or _sole_provider(cfg)
    if not provider_id:
        return None, None
    return provider_id, dict(user_obj)


def _authorize(cfg: IdentityConfig, identity: Identity, provider_id: str) -> User | None:
    be = enterprise.backend()
    if be is None:                                    # policy-only fallback (tests/headless)
        _decision, user = _service().resolve(provider_id, identity.claims or {"email": identity.email})
        return user

    email = identity.email
    entry = be.directory(email)
    if entry is None:
        entry = be.accept_invitation(email, identity.name, provider_id)   # pending invite
    if entry is None:
        entry = _admit_unknown(cfg, be, identity, provider_id)
    if entry is None:
        return None
    if getattr(entry, "status", "active") != "active":
        _deny(be, email, f"status_{entry.status}", provider_id)
        return None

    role = role_from_slug(entry.role_slug, DEFAULT_ROLE) or DEFAULT_ROLE
    user = User(email=email, name=entry.name or identity.name or email, role=role,
                provider_id=provider_id, subject=identity.subject,
                organization=cfg.policy.organization, groups=identity.groups)

    sid = st.session_state.get(_SESSION_ID_KEY)
    if not sid:
        sid = be.record_login(user, provider_id)
        if sid:
            st.session_state[_SESSION_ID_KEY] = sid
    elif be.is_revoked(sid):
        logout()
        return None
    else:
        be.heartbeat(sid)
    st.session_state[_USER_KEY] = user.to_dict()
    st.session_state.pop(_DENIED_KEY, None)
    return user


def _admit_unknown(cfg: IdentityConfig, be: Any, identity: Identity, provider_id: str):
    """An authenticated user with no directory row and no invitation: enforce the
    access policy (domain/whitelist = organization restriction), then the
    configured unknown-user policy."""
    decision = _service().authorize(identity)
    if not decision.allowed:
        _deny(be, identity.email, "not_admitted", provider_id, decision.reason)
        return None
    policy = cfg.unknown_user_policy
    if policy == "read_only":
        return be.provision_read_only(identity.email, identity.name, provider_id)
    if policy == "pending":
        be.register_pending(identity.email, identity.name, provider_id)
        _deny(be, identity.email, "pending_approval", provider_id,
              "Your account is pending administrator approval.")
        return None
    _deny(be, identity.email, "rejected", provider_id,
          "This account is not provisioned on the platform.")
    return None


def _deny(be: Any, email: str, reason: str, provider_id: str, message: str = "") -> None:
    be.audit_failed_login(email, reason, provider_id)
    st.session_state[_DENIED_KEY] = message or reason.replace("_", " ")


# ---------------------------------------------------------------- internals
def _sole_provider(cfg: IdentityConfig) -> str | None:
    real = [p for p in cfg.providers if p != "dev"]
    return real[0] if len(real) == 1 else None


def _clear_session() -> None:
    for key in (_USER_KEY, _LOGIN_TS_KEY, _PROVIDER_KEY, _SESSION_ID_KEY,
                _DEV_EMAIL_KEY, _DEV_NAME_KEY):
        st.session_state.pop(key, None)


# ---------------------------------------------------------------- login screens
def _render_dev_login(cfg: IdentityConfig) -> None:
    st.title("Sign in (development)")
    st.caption("Development mode skips Microsoft OAuth but uses the SAME authorization: "
               "your email is looked up in the platform directory and you get exactly the "
               "role assigned there - never an automatic Super Admin.")
    reason = st.session_state.get(_DENIED_KEY)
    if reason:
        st.error(f"Access denied: {reason}")
    email = st.text_input("Email", key="_dev_login_email")
    name = st.text_input("Display name (optional)", key="_dev_login_name")
    remember = st.checkbox("Remember me", key="_dev_login_remember")
    if st.button("Login", type="primary", key="_dev_login_btn") and email.strip():
        st.session_state[_DEV_EMAIL_KEY] = email.strip().lower()
        st.session_state[_DEV_NAME_KEY] = name.strip()
        st.session_state[_DEV_REMEMBER_KEY] = bool(remember)
        st.session_state[_LOGIN_TS_KEY] = time.time()
        st.session_state.pop(_SESSION_ID_KEY, None)
        st.rerun()


def _render_login(cfg: IdentityConfig) -> None:
    st.title("Sign in")
    if not cfg.configured:
        st.error("Sign-in is not configured. An administrator must set up an identity "
                 "provider (e.g. Microsoft Entra ID) in `.streamlit/secrets.toml`.")
        st.caption("For local development, set `FAP_AUTH_PROVIDER=dev` (or "
                   "`FAP_ENVIRONMENT=development`) to sign in with an email instead of OAuth.")
        return
    if cfg.policy.fail_closed and cfg.policy.admits_no_one and cfg.unknown_user_policy == "reject":
        st.info("Sign in with your Microsoft work account. If you have not been invited, "
                "contact your club administrator.")
    st.write("Use your club account to continue.")
    for provider in _service().offered_providers():
        if provider.info.id == "dev":
            continue
        if st.button(provider.login_label(), key=f"login_{provider.info.id}", type="primary"):
            st.session_state[_PROVIDER_KEY] = provider.info.id
            st.session_state[_LOGIN_TS_KEY] = time.time()
            st.session_state.pop(_SESSION_ID_KEY, None)
            _login(provider.info.id)


def _login(provider_id: str) -> None:
    if not hasattr(st, "login"):
        st.error("This Streamlit version does not support native authentication "
                 "(needs Streamlit >= 1.42).")
        return
    try:
        st.login(provider_id)
    except Exception as exc:                 # Authlib missing / misconfigured secrets
        st.error(f"Sign-in could not start: {exc}")
        st.caption("Ensure Authlib is installed and `[auth]` is configured in secrets.")


def _render_denied(cfg: IdentityConfig) -> None:
    st.title("Access denied")
    reason = st.session_state.get(_DENIED_KEY)
    if not reason:
        claims = dict(st.user) if hasattr(st, "user") else {}
        provider_id = st.session_state.get(_PROVIDER_KEY) or _sole_provider(cfg) or "dev"
        decision, _ = _service().resolve(provider_id, claims)
        reason = decision.reason
    st.error(reason)
    st.caption("Contact your club administrator if you believe you should have access.")
    if st.button("Sign out"):
        logout()
        st.rerun()
