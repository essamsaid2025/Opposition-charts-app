"""Identity providers as a plugin family.

An IdentityProvider knows how to turn ONE vendor's OIDC claims into the
platform's normalized ``Identity``. It does not perform the OAuth flow - the
host (Streamlit's native authentication, via Authlib) does that and hands us
the verified claims. The provider's only job is claim mapping, which is why it
is pure and fully testable without any browser or network.

Adding Okta/Auth0/Keycloak/... = one subclass + one registration. The session
layer and the access policy never learn a provider's name.
"""
from __future__ import annotations

from abc import abstractmethod
from typing import Any

from fap.core.plugin import Plugin, PluginInfo, PluginRegistry
from fap.identity.models import Identity


def _first(claims: dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = claims.get(key)
        if value not in (None, "", []):
            return str(value)
    return default


def _groups(claims: dict[str, Any], *keys: str) -> tuple[str, ...]:
    for key in keys:
        value = claims.get(key)
        if isinstance(value, (list, tuple)):
            return tuple(str(v) for v in value if str(v).strip())
        if isinstance(value, str) and value.strip():
            return tuple(part.strip() for part in value.split(",") if part.strip())
    return ()


class IdentityProvider(Plugin):
    """Maps a provider's verified OIDC claims to a normalized Identity.

    ``secret_section`` is the ``[auth.<section>]`` block in secrets.toml that
    Streamlit's native login uses for this provider - it is read from config,
    never hard-coded, so tenant ids and domains live only in secrets.
    """

    #: default secrets.toml [auth.<section>] key; overridable via config
    secret_section: str = ""

    #: claim names this provider commonly uses (subclasses override)
    subject_claims: tuple[str, ...] = ("sub", "oid")
    email_claims: tuple[str, ...] = ("email", "preferred_username", "upn")
    name_claims: tuple[str, ...] = ("name", "given_name")
    group_claims: tuple[str, ...] = ("groups", "roles")

    def normalize(self, claims: dict[str, Any]) -> Identity:
        return Identity(
            subject=_first(claims, *self.subject_claims),
            email=_first(claims, *self.email_claims).lower(),
            name=_first(claims, *self.name_claims),
            provider_id=self.info.id,
            groups=_groups(claims, *self.group_claims),
            claims=dict(claims),
        )

    @abstractmethod
    def login_label(self) -> str:
        """Text for this provider's sign-in button (e.g. 'Sign in with Microsoft')."""


identity_registry: PluginRegistry[IdentityProvider] = PluginRegistry("identity_provider")


def load_builtin_identity_providers() -> None:
    from fap.core.discovery import discover_plugins
    from fap.identity import builtin
    discover_plugins(builtin)
