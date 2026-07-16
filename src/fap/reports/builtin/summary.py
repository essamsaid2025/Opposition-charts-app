"""Summary / overview sections: executive, tactical, team stats, notes, appendix."""
from __future__ import annotations

from fap.core.plugin import PluginInfo
from fap.reports.builtin._common import (
    count, event_slice, pct, platform_insights, platform_metric_kpis, top_counts,
)
from fap.reports.models import KPI, Section
from fap.reports.sections import BuildContext, SectionBuilder, section_builder_registry


@section_builder_registry.register
class ExecutiveSummary(SectionBuilder):
    info = PluginInfo(id="executive_summary", name="Executive Summary", category="report_section")
    order = 10

    def build(self, ctx: BuildContext) -> Section:
        df = ctx.df
        kpis, seen = [KPI("Events", str(count(df)))], {"events"}
        for kpi in platform_metric_kpis(df, limit=6):   # reuse platform metrics, dedup labels
            if kpi.label.strip().lower() not in seen:
                kpis.append(kpi)
                seen.add(kpi.label.strip().lower())
        return Section(id=self.info.id, title="Executive Summary",
                       subtitle="Headline metrics and automated insights",
                       kpis=kpis, insights=platform_insights(df))


@section_builder_registry.register
class TacticalSummary(SectionBuilder):
    info = PluginInfo(id="tactical_summary", name="Tactical Summary", category="report_section")
    order = 20

    def build(self, ctx: BuildContext) -> Section:
        df = ctx.df
        passes, shots = event_slice(df, "pass"), event_slice(df, "shot")
        kpis = [KPI("Passes", str(count(passes))), KPI("Shots", str(count(shots))),
                KPI("Events/shot", str(round(count(df) / max(count(shots), 1), 1)))]
        return Section(id=self.info.id, title="Tactical Summary",
                       subtitle="How the team plays", kpis=kpis,
                       tables=[top_counts(df, "event_type", 8, "Action distribution")])


@section_builder_registry.register
class TeamStatistics(SectionBuilder):
    info = PluginInfo(id="team_statistics", name="Team Statistics", category="report_section")
    order = 900

    def build(self, ctx: BuildContext) -> Section:
        df = ctx.df
        return Section(id=self.info.id, title="Team Statistics",
                       subtitle="Full metric table",
                       kpis=platform_metric_kpis(df, limit=10),
                       tables=[top_counts(df, "team", 6, "Events by team")])


@section_builder_registry.register
class Notes(SectionBuilder):
    info = PluginInfo(id="notes", name="Notes", category="report_section")
    order = 950

    def build(self, ctx: BuildContext) -> Section:
        return Section(id=self.info.id, title="Notes",
                       notes=ctx.meta.get("notes", "Add analyst notes here."))


@section_builder_registry.register
class Appendix(SectionBuilder):
    info = PluginInfo(id="appendix", name="Appendix", category="report_section")
    order = 999

    def build(self, ctx: BuildContext) -> Section:
        df = ctx.df
        cols = [] if df is None else list(df.columns)[:24]
        return Section(id=self.info.id, title="Appendix",
                       subtitle="Data provenance",
                       tables=[top_counts(df, "player", 10, "Most active players")],
                       markdown="Columns: " + ", ".join(cols))
