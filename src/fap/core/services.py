"""Lazy singleton container for platform services.

A service is registered as a *factory*, never as an instance: nothing is
constructed until someone asks for it, and once constructed it is reused for
the life of the registry. Factories receive the registry itself, so a service
resolves its collaborators through the container instead of building them -
one Database, one CacheManager, one TemplateRepository, no matter how many
services depend on them.

Distinct from ``fap.core.plugin.PluginRegistry``: that one registers plugin
*classes* by id for the user to pick from; this one owns the lifetime of the
platform's own long-lived collaborators.
"""
from __future__ import annotations

import threading
from typing import Any, Callable, Iterator

from fap.core.exceptions import ConfigurationError

Factory = Callable[["ServiceRegistry"], Any]


class ServiceRegistry:
    """Name -> factory, resolved lazily and memoized. Thread-safe: one cached
    registry is shared by every Streamlit session, which may resolve in
    parallel, and a service must never be built twice."""

    def __init__(self) -> None:
        self._factories: dict[str, Factory] = {}
        self._instances: dict[str, Any] = {}
        self._lock = threading.RLock()

    # -- registration -------------------------------------------------
    def register(self, name: str, factory: Factory, *, replace: bool = False) -> None:
        if name in self._factories and not replace:
            raise ConfigurationError(f"Service {name!r} is already registered")
        with self._lock:
            self._factories[name] = factory
            self._instances.pop(name, None)

    # -- resolution ---------------------------------------------------
    def get(self, name: str) -> Any:
        """The single instance of ``name``, building it on first request."""
        try:
            return self._instances[name]
        except KeyError:
            pass
        with self._lock:
            if name not in self._instances:           # re-check under the lock
                try:
                    factory = self._factories[name]
                except KeyError:
                    raise ConfigurationError(
                        f"No service registered as {name!r}. Registered: "
                        f"{', '.join(sorted(self._factories)) or '(none)'}"
                    ) from None
                self._instances[name] = factory(self)
            return self._instances[name]

    # -- introspection ------------------------------------------------
    def created(self, name: str) -> bool:
        """Has this service been built yet? (lifetime assertions, tests)"""
        return name in self._instances

    def names(self) -> list[str]:
        return sorted(self._factories)

    def __contains__(self, name: str) -> bool:
        return name in self._factories

    def __iter__(self) -> Iterator[str]:
        return iter(self.names())

    def __len__(self) -> int:
        return len(self._factories)
