"""Exception hierarchy. Every layer raises subclasses of FAPError so the UI
can catch a single type at the boundary and render a friendly message."""
from __future__ import annotations


class FAPError(Exception):
    """Base class for all platform errors."""


class ConfigurationError(FAPError):
    """Invalid or missing configuration."""


class PluginError(FAPError):
    """A plugin failed to load, register or execute."""


class PluginNotFoundError(PluginError):
    """Requested plugin id is not registered."""


class ProviderError(FAPError):
    """A data provider could not read or parse a source."""


class DataValidationError(FAPError):
    """Input data failed schema validation."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


class PersistenceError(FAPError):
    """Database / file persistence failure."""


class AuthError(FAPError):
    """Authentication or authorization failure."""
