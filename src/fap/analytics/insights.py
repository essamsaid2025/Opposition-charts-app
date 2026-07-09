"""Insight rules as plugins: each rule inspects the frame and may emit a
sentence. The 'Auto Insights' panel = InsightEngine over the registry, so new
insight logic never touches the engine or the UI."""
from __future__ import annotations

from abc import abstractmethod

import pandas as pd

from fap.core.plugin import Plugin, PluginRegistry


class InsightRule(Plugin):
    @abstractmethod
    def evaluate(self, df: pd.DataFrame) -> str | None:
        """Return a markdown sentence, or None if not applicable."""


insight_registry: PluginRegistry[InsightRule] = PluginRegistry("insight_rule")


class InsightEngine:
    def __init__(self, registry: PluginRegistry[InsightRule] = insight_registry) -> None:
        self._registry = registry

    def run(self, df: pd.DataFrame) -> list[str]:
        if df.empty:
            return ["No data after filters."]
        results: list[str] = []
        for rule_cls in self._registry:
            sentence = rule_cls().evaluate(df)
            if sentence:
                results.append(sentence)
        return results
