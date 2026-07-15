from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Any, BinaryIO

import pandas as pd

from fap.core.plugin import Plugin, PluginInfo, PluginRegistry
from fap.providers.signature import ProviderSignature


@dataclass(frozen=True, slots=True)
class RawDataset:
    frame: pd.DataFrame
    column_mapping: dict[str, str] = field(default_factory=dict)  # source col -> canonical col
    native_coord_system: str = "0-100"                            # id of a CoordinateSystem plugin
    meta: dict[str, Any] = field(default_factory=dict)


class DataProvider(Plugin):
    """Contract: recognize a source, load it, describe how its columns map to
    the canonical schema. Providers never normalize - the pipeline does.
    ``options`` carries wizard choices (sheet name, delimiter, encoding...).

    ``signature`` is optional recognition evidence for the intelligence engine
    (fap.providers.intelligence). A provider without one is still detected the
    way it always was, by ``supports(filename)``; declaring one lets the engine
    recognize the format from its content when the filename says nothing.
    """

    signature: ProviderSignature | None = None

    @abstractmethod
    def supports(self, filename: str) -> bool: ...

    @abstractmethod
    def load(self, source: BinaryIO, filename: str,
             options: dict[str, Any] | None = None) -> RawDataset: ...


provider_registry: PluginRegistry[DataProvider] = PluginRegistry("provider")


def load_builtin_providers() -> None:
    from fap.core.discovery import discover_plugins
    from fap.providers import builtin
    discover_plugins(builtin)
