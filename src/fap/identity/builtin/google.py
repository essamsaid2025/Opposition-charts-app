"""Google Workspace."""
from __future__ import annotations

from fap.core.plugin import PluginInfo
from fap.identity.provider import IdentityProvider, identity_registry


@identity_registry.register
class GoogleProvider(IdentityProvider):
    info = PluginInfo(id="google", name="Google Workspace", category="identity",
                      description="Google Workspace sign-in via OpenID Connect.")
    secret_section = "google"
    subject_claims = ("sub",)
    email_claims = ("email",)
    name_claims = ("name", "given_name")
    group_claims = ("groups",)          # requires Workspace groups claim configuration

    def login_label(self) -> str:
        return "Sign in with Google"
