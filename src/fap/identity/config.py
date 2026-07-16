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

from dataclasses import dataclass
from typing import Any, Mapping

from fap.identity.policy import AccessPolicy

DEFAULT_SESSION_TIMEOUT_MINUTES = 480


@dataclass(frozen=True, slots=True)
class IdentityConfig:
    providers: tuple[str, ...]                # identity provider ids offered at sign-in
    policy: AccessPolicy
    session_timeout_minutes: int = DEFAULT_SESSION_TIMEOUT_MINUTES
    remember_session: bool = False
    development: bool = False

    @property
    def configured(self) -> bool:
        """Is at least one real (non-dev) provider offered?"""
        return any(p != "dev" for p in self.providers)


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
    return IdentityConfig(
        providers=tuple(dict.fromkeys(providers)),   # de-dup, keep order
        policy=AccessPolicy.from_mapping(identity),
        session_timeout_minutes=timeout,
        remember_session=bool(identity.get("remember_session", False)),
        development=development,
    )
