"""Keycloak."""
from __future__ import annotations

from fap.core.plugin import PluginInfo
from fap.identity.provider import IdentityProvider, identity_registry


@identity_registry.register
class KeycloakProvider(IdentityProvider):
    info = PluginInfo(id="keycloak", name="Keycloak", category="identity",
                      description="Keycloak sign-in via OpenID Connect.")
    secret_section = "keycloak"
    subject_claims = ("sub",)
    email_claims = ("email", "preferred_username")
    name_claims = ("name",)
    # Keycloak realm/client roles arrive under realm_access.roles; a token
    # mapper usually flattens them to a `roles` claim, the common default here.
    group_claims = ("roles", "groups")

    def login_label(self) -> str:
        return "Sign in with Keycloak"
