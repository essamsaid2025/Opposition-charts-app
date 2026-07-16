"""Shooting section."""
from __future__ import annotations

from fap.core.plugin import PluginInfo
from fap.reports.builtin._common import count, event_slice, pct
from fap.reports.models import KPI, Section
from fap.reports.sections import BuildContext, SectionBuilder, section_builder_registry


@section_builder_registry.register
class Shooting(SectionBuilder):
    info = PluginInfo(id="shooting", name="Shooting", category="report_section")
    order = 90

    def build(self, ctx: BuildContext) -> Section:
        df = ctx.df
        shots = event_slice(df, "shot")
        goals = 0
        if shots is not None and "shot_result" in getattr(shots, "columns", []):
            goals = int(shots["shot_result"].astype(str).str.lower().eq("goal").sum())
        kpis = [KPI("Shots", str(count(shots))), KPI("Goals", str(goals)),
                KPI("Conversion", pct(goals, count(shots)))]
        return Section(id=self.info.id, title="Shooting",
                       subtitle="Shot volume and conversion", kpis=kpis)
