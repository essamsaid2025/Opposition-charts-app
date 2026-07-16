"""Microsoft Entra ID (Azure AD / Microsoft 365)."""
from __future__ import annotations

from fap.core.plugin import PluginInfo
from fap.identity.provider import IdentityProvider, identity_registry


@identity_registry.register
class EntraProvider(IdentityProvider):
    info = PluginInfo(id="microsoft", name="Microsoft Entra ID", category="identity",
                      description="Microsoft 365 / Azure AD sign-in via OpenID Connect.")
    secret_section = "microsoft"
    # Entra: stable id is `oid`; UPN is the reliable email; app roles in `roles`,
    # security groups in `groups` (when the app registration emits them).
    subject_claims = ("oid", "sub")
    email_claims = ("email", "preferred_username", "upn")
    name_claims = ("name", "given_name")
    group_claims = ("roles", "groups")

    def login_label(self) -> str:
        return "Sign in with Microsoft"
