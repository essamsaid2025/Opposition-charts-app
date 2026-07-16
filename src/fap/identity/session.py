"""Streamlit session facade - the ONLY identity module that imports Streamlit.

Pages call ``current_user()`` / ``require_login()`` / ``logout()`` and never see
a provider name, a claim, or ``st.user``. The actual OAuth2/OIDC flow is run by
Streamlit's native authentication (Authlib) via ``st.login`` / ``st.logout``;
this module maps its result through the pure IdentityService + AccessPolicy.
"""
from __future__ import annotations

import time
from typing import Any

import streamlit as st

from fap.identity.builtin.dev import DEV_EMAIL, DevProvider
from fap.identity.config import IdentityConfig, development_mode, load_identity_config
from fap.identity.models import User
from fap.identity.provider import load_builtin_identity_providers
from fap.identity.roles import Role
from fap.identity.service import IdentityService

_USER_KEY = "_fap_identity_user"
_LOGIN_TS_KEY = "_fap_identity_login_ts"
_PROVIDER_KEY = "_fap_identity_provider"


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

    Never raises and never renders: safe to call anywhere (e.g. to decide what
    to show). Use ``require_login()`` to gate a page.
    """
    cfg = _config()

    # development bypass: a synthetic Super Admin so the app runs with no IdP.
    if cfg.development:
        dev = DevProvider()
        return User(email=DEV_EMAIL, name="Developer", role=Role.SUPER_ADMIN,
                    provider_id=dev.info.id, subject=DEV_EMAIL,
                    organization=cfg.policy.organization or "Development")

    user_obj = st.user if hasattr(st, "user") else None
    if not user_obj or not getattr(user_obj, "is_logged_in", False):
        _clear_session()
        return None

    # idle timeout (unless "remember session")
    login_ts = st.session_state.get(_LOGIN_TS_KEY)
    if is_session_expired(login_ts, time.time(), cfg.session_timeout_minutes,
                          cfg.remember_session):
        logout()
        return None
    st.session_state.setdefault(_LOGIN_TS_KEY, time.time())

    claims = dict(user_obj)
    provider_id = st.session_state.get(_PROVIDER_KEY) or _sole_provider(cfg)
    if not provider_id:
        return None
    _decision, user = _service().resolve(provider_id, claims)
    st.session_state[_USER_KEY] = user.to_dict() if user else None
    return user


def require_login() -> User:
    """Gate the page: return the user, or render sign-in / access-denied and stop."""
    user = current_user()
    if user is not None:
        return user

    cfg = _config()
    user_obj = st.user if hasattr(st, "user") else None
    if user_obj is not None and getattr(user_obj, "is_logged_in", False):
        _render_denied(cfg)          # authenticated but not authorized
    else:
        _render_login(cfg)           # not authenticated
    st.stop()
    raise RuntimeError("unreachable")   # for type-checkers; st.stop() halts the script


def logout() -> None:
    """Sign out of the platform and the identity provider."""
    _clear_session()
    if hasattr(st, "logout"):
        try:
            st.logout()
        except Exception:
            pass


def roles() -> list[Role]:
    """Every role the platform defines, highest authority first."""
    from fap.identity.roles import all_roles
    return all_roles()


# ---------------------------------------------------------------- internals
def _sole_provider(cfg: IdentityConfig) -> str | None:
    real = [p for p in cfg.providers if p != "dev"]
    return real[0] if len(real) == 1 else None


def _clear_session() -> None:
    for key in (_USER_KEY, _LOGIN_TS_KEY, _PROVIDER_KEY):
        st.session_state.pop(key, None)


def _render_login(cfg: IdentityConfig) -> None:
    st.title("Sign in")
    if not cfg.configured:
        st.error("Sign-in is not configured. An administrator must set up an identity "
                 "provider (e.g. Microsoft Entra ID) in `.streamlit/secrets.toml`.")
        st.caption("For local development, set `FAP_AUTH_PROVIDER=dev` (or "
                   "`FAP_ENVIRONMENT=development`) to bypass sign-in and run as Super Admin.")
        return
    if cfg.policy.fail_closed and cfg.policy.admits_no_one:
        st.error("Access policy admits no one (fail closed). Configure `allowed_domains` "
                 "or `email_whitelist` under `[identity]`.")
        return
    st.write("Use your club account to continue.")
    for provider in _service().offered_providers():
        if provider.info.id == "dev":
            continue
        if st.button(provider.login_label(), key=f"login_{provider.info.id}",
                     type="primary"):
            st.session_state[_PROVIDER_KEY] = provider.info.id
            st.session_state[_LOGIN_TS_KEY] = time.time()
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
    claims = dict(st.user) if hasattr(st, "user") else {}
    provider_id = st.session_state.get(_PROVIDER_KEY) or _sole_provider(cfg) or "dev"
    decision, _ = _service().resolve(provider_id, claims)
    st.title("Access denied")
    st.error(decision.reason)
    st.caption("Contact your club administrator if you believe you should have access.")
    if st.button("Sign out"):
        logout()
        st.rerun()
