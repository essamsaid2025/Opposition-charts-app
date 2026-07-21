"""Read identity configuration from a mapping (Streamlit ``st.secrets`` in the
app, a plain dict in tests). Nothing here is Streamlit-specific.

Expected shape (see .streamlit/secrets.toml.example):

    [auth]                      # Streamlit-native OIDC (Authlib) - the app reads this
    redirect_uri = "..."
    cookie_secret = "..."
    [auth.microsoft]
    client_id = "..."
    server_metadata_url = "https://login.microsoftonline.com/<tenant>/v2.0/.well-known/openid-configuration"

    [identity]                  # the platform's access policy - read here
    providers = ["microsoft"]
    allowed_domains = ["club.com"]
    default_role = "read_only"
    session_timeout_minutes = 480
    remember_session = true
    [identity.role_assignments]
    "sporting.director@club.com" = "club_admin"
    [identity.group_roles]
    "First Team Analysts" = "first_team_analyst"

Tenant ids and domains live only in secrets; none are hard-coded here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping

from fap.identity.policy import AccessPolicy

DEFAULT_SESSION_TIMEOUT_MINUTES = 480


def development_mode() -> bool:
    """Is the login gate bypassed for local development?

    Entirely configuration-driven, and true when ANY of these hold:

      * ``FAP_AUTH_PROVIDER=dev``       (pick the dev identity provider), or
      * ``FAP_ENVIRONMENT=development`` (the platform's dev-mode convention), or
      * ``environment: development``    in settings (defaults.yaml / settings.local.yaml).

    In development the session is a synthetic Super Admin - no Microsoft, no
    OAuth, no secrets.toml. Production sets none of these, so it never enters
    this path and continues to require Microsoft Entra ID sign-in.
    """
    if os.environ.get("FAP_AUTH_PROVIDER", "").strip().lower() == "dev":
        return True
    if os.environ.get("FAP_ENVIRONMENT", "").strip().lower() == "development":
        return True
    try:
        from fap.config import load_settings
        return load_settings().environment.strip().lower() == "development"
    except Exception:
        return False


#: how an authenticated but unknown user (no directory row, no invitation) is treated
VALID_UNKNOWN_POLICIES = ("reject", "pending", "read_only")


@dataclass(frozen=True, slots=True)
class IdentityConfig:
    providers: tuple[str, ...]                # identity provider ids offered at sign-in
    policy: AccessPolicy
    session_timeout_minutes: int = DEFAULT_SESSION_TIMEOUT_MINUTES
    remember_session: bool = False
    development: bool = False
    unknown_user_policy: str = "reject"       # reject | pending | read_only
    base_url: str = ""                        # for invitation links
    super_admin: str = ""                     # platform owner email; ALWAYS admitted

    @property
    def configured(self) -> bool:
        """Is at least one real (non-dev) provider offered?"""
        return any(p != "dev" for p in self.providers)

    def is_owner(self, email: str) -> bool:
        """True when ``email`` is the configured platform owner (case-insensitive).
        The owner is never subject to allowed_domains/email_whitelist."""
        return bool(self.super_admin) and (email or "").strip().lower() == self.super_admin


def _configured_auth_sections(secrets: Mapping[str, Any]) -> list[str]:
    """Provider sections present under [auth.*] in Streamlit's native config."""
    auth = secrets.get("auth", {}) or {}
    reserved = {"redirect_uri", "cookie_secret", "client_id", "client_secret",
                "server_metadata_url"}
    return [k for k, v in dict(auth).items() if isinstance(v, Mapping) and k not in reserved]


def load_identity_config(secrets: Mapping[str, Any], *, development: bool = False) -> IdentityConfig:
    identity = dict(secrets.get("identity", {}) or {})

    # provider list: explicit `identity.providers`, else infer from [auth.*] sections
    providers = [str(p).strip().lower() for p in identity.get("providers", []) if str(p).strip()]
    if not providers:
        providers = _configured_auth_sections(secrets)
    if development and "dev" not in providers:
        providers = [*providers, "dev"]

    timeout = int(identity.get("session_timeout_minutes", DEFAULT_SESSION_TIMEOUT_MINUTES))
    policy_name = str(identity.get("unknown_user_policy",
                                  os.environ.get("FAP_UNKNOWN_USER_POLICY", "reject"))).strip().lower()
    if policy_name not in VALID_UNKNOWN_POLICIES:
        policy_name = "reject"
    return IdentityConfig(
        providers=tuple(dict.fromkeys(providers)),   # de-dup, keep order
        policy=AccessPolicy.from_mapping(identity),
        session_timeout_minutes=timeout,
        remember_session=bool(identity.get("remember_session", False)),
        development=development,
        unknown_user_policy=policy_name,
        base_url=str(identity.get("base_url", os.environ.get("FAP_BASE_URL", ""))).strip(),
        # platform owner: [identity].super_admin in secrets, else FAP_SUPER_ADMIN env.
        # This is config, not one-shot bootstrap state, so it survives restarts.
        super_admin=str(identity.get("super_admin",
                                    os.environ.get("FAP_SUPER_ADMIN", ""))).strip().lower(),
    )
