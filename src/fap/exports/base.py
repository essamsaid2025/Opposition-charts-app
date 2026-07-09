"""Export format plugins. An exporter serializes an ExportPayload (figure
and/or frame and/or report) to bytes + mime + filename. The download UI simply
iterates the registry, so a new format = one new module."""
from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from matplotlib.figure import Figure

from fap.core.plugin import Plugin, PluginRegistry


@dataclass(slots=True)
class ExportPayload:
    figure: Figure | None = None
    frame: pd.DataFrame | None = None
    title: str = "export"
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExportResult:
    data: bytes
    mime: str
    filename: str


class Exporter(Plugin):
    @abstractmethod
    def can_export(self, payload: ExportPayload) -> bool: ...

    @abstractmethod
    def export(self, payload: ExportPayload) -> ExportResult: ...


export_registry: PluginRegistry[Exporter] = PluginRegistry("exporter")


def load_builtin_exporters() -> None:
    from fap.core.discovery import discover_plugins
    from fap.exports import builtin
    discover_plugins(builtin)
