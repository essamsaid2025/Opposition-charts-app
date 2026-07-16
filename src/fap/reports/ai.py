"""AI extension points - interfaces ONLY (no implementation).

These let a future AI layer contribute narrative summaries, recommendations and
extra insights to a report without changing the engine. Providers register in
their registry; the builder/sections can consult registered providers when any
are present. Nothing here calls a model - it is architecture for later.
"""
from __future__ import annotations

from abc import abstractmethod

from fap.core.plugin import Plugin, PluginRegistry
from fap.reports.models import Insight, Section
from fap.reports.sections import BuildContext


class SummarySectionProvider(Plugin):
    """Generates an executive/narrative summary Section from the data + context."""
    @abstractmethod
    def summarize(self, ctx: BuildContext) -> Section: ...


class RecommendationProvider(Plugin):
    """Produces actionable recommendations (as insights) for a report."""
    @abstractmethod
    def recommend(self, ctx: BuildContext) -> list[Insight]: ...


class InsightProvider(Plugin):
    """Contributes extra insights to any section."""
    @abstractmethod
    def insights(self, ctx: BuildContext) -> list[Insight]: ...


summary_provider_registry: PluginRegistry[SummarySectionProvider] = PluginRegistry("report_summary_provider")
recommendation_provider_registry: PluginRegistry[RecommendationProvider] = PluginRegistry("report_recommendation_provider")
insight_provider_registry: PluginRegistry[InsightProvider] = PluginRegistry("report_insight_provider")


def has_ai_providers() -> bool:
    return bool(len(summary_provider_registry) or len(recommendation_provider_registry)
                or len(insight_provider_registry))
