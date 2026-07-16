"""Identity & authorization layer.

Provider-agnostic sign-in (Microsoft Entra ID, Google, Okta, Auth0, Keycloak,
or a development bypass) plus the platform's own role-based access policy.

Pages import ONLY this facade - never a provider, never Microsoft:

    from fap.identity import current_user, require_login, logout, Role

Identity (who you are) is owned by the provider; authorization (what you may
do) is owned here. Everything below the facade is pure and testable without a
browser: fap.identity.roles, .policy, .service, .provider, .config.
"""
from fap.identity.roles import DEFAULT_ROLE, Role, all_roles, role_from_slug
from fap.identity.models import Identity, User
from fap.identity.session import current_user, logout, require_login, roles

__all__ = [
    "current_user", "require_login", "logout", "roles",
    "Role", "DEFAULT_ROLE", "all_roles", "role_from_slug",
    "Identity", "User",
]
