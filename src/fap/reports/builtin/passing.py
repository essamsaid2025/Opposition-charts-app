"""Passing / final-third / chance-creation sections."""
from __future__ import annotations

from fap.core.plugin import PluginInfo
from fap.reports.builtin._common import count, event_slice, pct, safe, top_counts
from fap.reports.models import KPI, Section
from fap.reports.sections import BuildContext, SectionBuilder, section_builder_registry


def _analysis():
    from fap.visuals import analysis
    return analysis


@section_builder_registry.register
class Passing(SectionBuilder):
    info = PluginInfo(id="passing", name="Passing", category="report_section")
    order = 60

    def build(self, ctx: BuildContext) -> Section:
        df = ctx.df
        A = safe(_analysis)
        passes = safe(lambda: A.passes(df)) if A else None
        forward = safe(lambda: A.forward(passes)) if A and passes is not None else None
        longp = safe(lambda: A.long_passes(passes)) if A and passes is not None else None
        kpis = [KPI("Passes", str(count(passes))),
                KPI("Forward", pct(count(forward), count(passes))),
                KPI("Long", str(count(longp)))]
        return Section(id=self.info.id, title="Passing",
                       subtitle="Distribution profile", kpis=kpis,
                       tables=[top_counts(passes, "player", 6, "Top passers")])


@section_builder_registry.register
class FinalThird(SectionBuilder):
    info = PluginInfo(id="final_third", name="Final Third", category="report_section")
    order = 70

    def build(self, ctx: BuildContext) -> Section:
        df = ctx.df
        in_final = safe(lambda: df[df["x"] >= 66.67]) if df is not None and "x" in df.columns else None
        kpis = [KPI("Final-third actions", str(count(in_final))),
                KPI("Share of play", pct(count(in_final), count(df)))]
        return Section(id=self.info.id, title="Final Third",
                       subtitle="Attacking-third presence", kpis=kpis)


@section_builder_registry.register
class ChanceCreation(SectionBuilder):
    info = PluginInfo(id="chance_creation", name="Chance Creation", category="report_section")
    order = 80

    def build(self, ctx: BuildContext) -> Section:
        df = ctx.df
        A = safe(_analysis)
        passes = safe(lambda: A.passes(df)) if A else None
        key = safe(lambda: A.key_passes(passes)) if A and passes is not None else None
        crosses = event_slice(df, "cross")
        kpis = [KPI("Key passes", str(count(key))), KPI("Crosses", str(count(crosses)))]
        return Section(id=self.info.id, title="Chance Creation",
                       subtitle="Openings created", kpis=kpis)
