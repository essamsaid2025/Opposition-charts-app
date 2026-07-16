"""Auth0."""
from __future__ import annotations

from fap.core.plugin import PluginInfo
from fap.identity.provider import IdentityProvider, identity_registry


@identity_registry.register
class Auth0Provider(IdentityProvider):
    info = PluginInfo(id="auth0", name="Auth0", category="identity",
                      description="Auth0 sign-in via OpenID Connect.")
    secret_section = "auth0"
    subject_claims = ("sub",)
    email_claims = ("email",)
    name_claims = ("name", "nickname")
    # Auth0 namespaces custom claims; a rule/action typically emits roles under
    # a namespaced URL - config maps it, this is the common default.
    group_claims = ("https://schemas.fap/roles", "roles", "groups")

    def login_label(self) -> str:
        return "Sign in with Auth0"
