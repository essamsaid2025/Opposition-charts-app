"""Okta."""
from __future__ import annotations

from fap.core.plugin import PluginInfo
from fap.identity.provider import IdentityProvider, identity_registry


@identity_registry.register
class OktaProvider(IdentityProvider):
    info = PluginInfo(id="okta", name="Okta", category="identity",
                      description="Okta sign-in via OpenID Connect.")
    secret_section = "okta"
    subject_claims = ("sub",)
    email_claims = ("email", "preferred_username")
    name_claims = ("name",)
    group_claims = ("groups",)

    def login_label(self) -> str:
        return "Sign in with Okta"
