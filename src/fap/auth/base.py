"""Authentication is itself a plugin family: local accounts today, SSO/OAuth
tomorrow, without touching call sites."""
from __future__ import annotations

from abc import abstractmethod

from fap.core.plugin import Plugin, PluginRegistry
from fap.db.models import User


class Authenticator(Plugin):
    @abstractmethod
    def authenticate(self, username: str, password: str) -> User | None: ...

    @abstractmethod
    def create_user(self, username: str, password: str, role: str = "analyst") -> User: ...


auth_registry: PluginRegistry[Authenticator] = PluginRegistry("authenticator")
