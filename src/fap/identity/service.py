"""IdentityService - resolve a signed-in identity to an authorized User.

Pure orchestration over the registry (claim normalization) and the policy
(authorization). No Streamlit here, so the whole who-gets-in-as-what decision
is testable end to end from raw claims.
"""
from __future__ import annotations

from typing import Any

from fap.core.plugin import PluginRegistry
from fap.identity.config import IdentityConfig
from fap.identity.models import Identity, User
from fap.identity.policy import AccessDecision, AccessPolicy
from fap.identity.provider import IdentityProvider, identity_registry


class IdentityService:
    def __init__(self, config: IdentityConfig,
                 registry: PluginRegistry[IdentityProvider] | None = None) -> None:
        self._config = config
        self._registry = registry if registry is not None else identity_registry

    @property
    def config(self) -> IdentityConfig:
        return self._config

    @property
    def policy(self) -> AccessPolicy:
        return self._config.policy

    def provider(self, provider_id: str) -> IdentityProvider:
        return self._registry.create(provider_id)

    def offered_providers(self) -> list[IdentityProvider]:
        """The providers a user may sign in with, in configured order."""
        out: list[IdentityProvider] = []
        for pid in self._config.providers:
            if pid in self._registry:
                out.append(self._registry.create(pid))
        return out

    def normalize(self, provider_id: str, claims: dict[str, Any]) -> Identity:
        return self.provider(provider_id).normalize(claims)

    def authorize(self, identity: Identity) -> AccessDecision:
        return self.policy.resolve(identity)

    def resolve(self, provider_id: str, claims: dict[str, Any]) -> tuple[AccessDecision, User | None]:
        """Claims -> (decision, user). ``user`` is None when access is denied."""
        identity = self.normalize(provider_id, claims)
        decision = self.authorize(identity)
        user = decision.user(identity, self.policy.organization) if decision.allowed else None
        return decision, user
