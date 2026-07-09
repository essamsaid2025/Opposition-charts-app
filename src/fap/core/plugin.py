"""Generic plugin engine.

Every extensible concept in the platform (visualization, metric, provider,
exporter, coordinate system, report section, theme source ...) is a Plugin
registered in a typed PluginRegistry. Adding a capability = dropping a new
module into the right package. No existing file is edited (Open/Closed).
"""
from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from typing import Callable, Generic, Iterator, Type, TypeVar

from fap.core.exceptions import PluginError, PluginNotFoundError


@dataclass(frozen=True, slots=True)
class PluginInfo:
    """Static metadata describing a plugin."""
    id: str                       # unique, stable, machine-readable (e.g. "pass_map")
    name: str                     # human readable label shown in the UI
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    category: str = ""            # free grouping key (e.g. "maps", "bars")
    tags: tuple[str, ...] = field(default_factory=tuple)


class Plugin(ABC):
    """Base class for all plugins. Subclasses must define ``info``."""
    info: PluginInfo


T = TypeVar("T", bound=Plugin)


class PluginRegistry(Generic[T]):
    """Typed registry with decorator-based registration.

    Usage::

        visual_registry: PluginRegistry[Visualization] = PluginRegistry("visualization")

        @visual_registry.register
        class PassMap(Visualization):
            info = PluginInfo(id="pass_map", name="Pass Map", category="maps")
    """

    def __init__(self, kind: str) -> None:
        self._kind = kind
        self._plugins: dict[str, Type[T]] = {}

    # -- registration -------------------------------------------------
    def register(self, cls: Type[T]) -> Type[T]:
        info = getattr(cls, "info", None)
        if not isinstance(info, PluginInfo):
            raise PluginError(f"{cls.__name__} must define a PluginInfo `info` attribute")
        if info.id in self._plugins and self._plugins[info.id] is not cls:
            raise PluginError(f"Duplicate {self._kind} plugin id: {info.id!r}")
        self._plugins[info.id] = cls
        return cls

    # -- lookup -------------------------------------------------------
    def get(self, plugin_id: str) -> Type[T]:
        try:
            return self._plugins[plugin_id]
        except KeyError:
            raise PluginNotFoundError(f"No {self._kind} plugin registered with id {plugin_id!r}") from None

    def create(self, plugin_id: str, **kwargs: object) -> T:
        return self.get(plugin_id)(**kwargs)  # type: ignore[call-arg]

    def ids(self) -> list[str]:
        return sorted(self._plugins)

    def infos(self) -> list[PluginInfo]:
        return sorted((c.info for c in self._plugins.values()), key=lambda i: (i.category, i.name))

    def by_category(self, category: str) -> list[PluginInfo]:
        return [i for i in self.infos() if i.category == category]

    def filter(self, predicate: Callable[[PluginInfo], bool]) -> list[PluginInfo]:
        return [i for i in self.infos() if predicate(i)]

    def __iter__(self) -> Iterator[Type[T]]:
        return iter(self._plugins.values())

    def __len__(self) -> int:
        return len(self._plugins)

    def __contains__(self, plugin_id: str) -> bool:
        return plugin_id in self._plugins
