"""Development provider - no OIDC, no network.

Yields a synthetic signed-in identity so the app runs on a laptop without an
identity provider configured. It activates ONLY in development mode
(environment=development); production never falls back to it, which is what
keeps the platform fail-closed.
"""
from __future__ import annotations

from typing import Any

from fap.core.plugin import PluginInfo
from fap.identity.models import Identity
from fap.identity.provider import IdentityProvider, identity_registry

DEV_EMAIL = "developer@localhost"


@identity_registry.register
class DevProvider(IdentityProvider):
    info = PluginInfo(id="dev", name="Development sign-in", category="identity",
                      description="Synthetic local identity for development mode only.")
    secret_section = "dev"

    def normalize(self, claims: dict[str, Any]) -> Identity:
        email = str(claims.get("email") or DEV_EMAIL).lower()
        return Identity(subject=email, email=email,
                        name=str(claims.get("name") or "Developer"),
                        provider_id=self.info.id,
                        groups=tuple(claims.get("groups") or ()), claims=dict(claims))

    def synthetic_identity(self, email: str = DEV_EMAIL,
                           name: str = "Developer") -> Identity:
        return self.normalize({"email": email, "name": name})

    def login_label(self) -> str:
        return "Continue as developer"
