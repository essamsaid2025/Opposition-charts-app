"""Metric plugins. A metric is a pure computation over the canonical event
frame that returns a MetricResult. KPI strips, insight panels and reports all
consume metrics through the registry - none of them know concrete classes."""
from __future__ import annotations

from abc import abstractmethod

import pandas as pd

from fap.core.plugin import Plugin, PluginRegistry
from fap.core.types import MetricResult


class Metric(Plugin):
    @abstractmethod
    def compute(self, df: pd.DataFrame) -> MetricResult: ...


metric_registry: PluginRegistry[Metric] = PluginRegistry("metric")


def load_builtin_metrics() -> None:
    from fap.core.discovery import discover_plugins
    from fap.metrics import builtin
    discover_plugins(builtin)


def compute_all(df: pd.DataFrame, ids: list[str] | None = None) -> list[MetricResult]:
    chosen = ids or metric_registry.ids()
    return [metric_registry.create(mid).compute(df) for mid in chosen]
