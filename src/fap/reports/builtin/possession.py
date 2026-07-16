"""Possession-phase sections: open play, possession, build-up, pressing."""
from __future__ import annotations

from fap.core.plugin import PluginInfo
from fap.reports.builtin._common import count, event_slice, pct, safe
from fap.reports.models import KPI, Section
from fap.reports.sections import BuildContext, SectionBuilder, section_builder_registry


def _analysis():
    from fap.visuals import analysis
    return analysis


@section_builder_registry.register
class OpenPlay(SectionBuilder):
    info = PluginInfo(id="open_play", name="Open Play", category="report_section")
    order = 30

    def build(self, ctx: BuildContext) -> Section:
        df = ctx.df
        A = safe(_analysis)
        passes = safe(lambda: A.passes(df)) if A else None
        carries = safe(lambda: A.carries(df)) if A else None
        kpis = [KPI("Passes", str(count(passes))), KPI("Carries", str(count(carries))),
                KPI("Open-play events", str(count(df)))]
        return Section(id=self.info.id, title="Open Play",
                       subtitle="In-possession open-play actions", kpis=kpis)


@section_builder_registry.register
class Possession(SectionBuilder):
    info = PluginInfo(id="possession", name="Possession", category="report_section")
    order = 40

    def build(self, ctx: BuildContext) -> Section:
        df = ctx.df
        A = safe(_analysis)
        passes = safe(lambda: A.passes(df)) if A else None
        successful = safe(lambda: A.successful(passes)) if A and passes is not None else None
        kpis = [KPI("Passes", str(count(passes))),
                KPI("Completed", pct(count(successful), count(passes)))]
        return Section(id=self.info.id, title="Possession",
                       subtitle="Ball retention", kpis=kpis)


@section_builder_registry.register
class BuildUp(SectionBuilder):
    info = PluginInfo(id="build_up", name="Build Up", category="report_section")
    order = 50

    def build(self, ctx: BuildContext) -> Section:
        df = ctx.df
        A = safe(_analysis)
        passes = safe(lambda: A.passes(df)) if A else None
        progressive = safe(lambda: A.progressive(passes)) if A and passes is not None else None
        kpis = [KPI("Progressive passes", str(count(progressive))),
                KPI("Share progressive", pct(count(progressive), count(passes)))]
        return Section(id=self.info.id, title="Build Up",
                       subtitle="Progression from the back", kpis=kpis)


@section_builder_registry.register
class Pressing(SectionBuilder):
    info = PluginInfo(id="pressing", name="Pressing", category="report_section")
    order = 110

    def build(self, ctx: BuildContext) -> Section:
        df = ctx.df
        recoveries = event_slice(df, "recovery")
        interceptions = event_slice(df, "interception")
        kpis = [KPI("Recoveries", str(count(recoveries))),
                KPI("Interceptions", str(count(interceptions)))]
        return Section(id=self.info.id, title="Pressing",
                       subtitle="Out-of-possession intensity", kpis=kpis)
