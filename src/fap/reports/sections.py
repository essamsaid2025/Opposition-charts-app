"""Section builders - plugins that turn a dataset into one report Section.

A SectionBuilder is pure: it reads the canonical event frame (and platform
services) and returns a ``Section`` of KPIs/tables/insights/charts. It never
renders. New sections register themselves; the engine never hard-codes a
layout.
"""
from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from fap.core.plugin import Plugin, PluginRegistry
from fap.reports.models import KPI, Section


@dataclass(slots=True)
class BuildContext:
    """What a section builder receives. ``df`` is the canonical event frame;
    everything else is optional context carried onto the cover / meta."""
    df: pd.DataFrame
    branding: Any = None                       # fap.theme.Branding (loose to avoid a cycle)
    workspace_id: str | None = None
    project_id: str | None = None
    dataset_id: str | None = None
    analyst: str = ""
    cover: dict[str, Any] = field(default_factory=dict)   # club/season/competition/opponent/date
    meta: dict[str, Any] = field(default_factory=dict)
    render_charts: bool = False                # builder may pre-render chart images

    @property
    def empty(self) -> bool:
        return self.df is None or self.df.empty


class SectionBuilder(Plugin):
    """Base for a report section. ``order`` places it within a template's list
    when the template does not pin an explicit order."""
    order: int = 100

    @abstractmethod
    def build(self, ctx: BuildContext) -> Section: ...


section_builder_registry: PluginRegistry[SectionBuilder] = PluginRegistry("report_section_builder")


# -- helpers shared by builtin sections (no analytics duplicated) ------------
def kpis_from_metrics(results: list[Any], limit: int | None = None) -> list[KPI]:
    """Turn platform MetricResult objects into report KPIs (reuse, not recompute)."""
    out = [KPI(label=r.label, value=str(r.formatted)) for r in results]
    return out[:limit] if limit else out
