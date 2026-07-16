"""Defensive + set-piece sections."""
from __future__ import annotations

from fap.core.plugin import PluginInfo
from fap.reports.builtin._common import count, event_slice, safe, top_counts
from fap.reports.models import KPI, Section
from fap.reports.sections import BuildContext, SectionBuilder, section_builder_registry

_DEF = ("duel", "recovery", "interception", "clearance", "tackle", "block")


@section_builder_registry.register
class Defensive(SectionBuilder):
    info = PluginInfo(id="defensive", name="Defensive", category="report_section")
    order = 100

    def build(self, ctx: BuildContext) -> Section:
        df = ctx.df
        A = safe(lambda: __import__("fap.visuals.analysis", fromlist=["defensive"]))
        actions = safe(lambda: A.defensive(df)) if A else None
        kpis = [KPI(k.title(), str(count(event_slice(df, k)))) for k in ("tackle", "interception", "clearance")]
        kpis.insert(0, KPI("Defensive actions", str(count(actions))))
        return Section(id=self.info.id, title="Defensive",
                       subtitle="Out-of-possession actions", kpis=kpis,
                       tables=[top_counts(actions, "player", 6, "Top defenders")])


@section_builder_registry.register
class SetPieces(SectionBuilder):
    info = PluginInfo(id="set_pieces", name="Set Pieces", category="report_section")
    order = 105

    def build(self, ctx: BuildContext) -> Section:
        df = ctx.df
        corners = event_slice(df, "corner")
        frees = event_slice(df, "free-kick")
        throws = event_slice(df, "throw-in")
        kpis = [KPI("Corners", str(count(corners))), KPI("Free kicks", str(count(frees))),
                KPI("Throw-ins", str(count(throws)))]
        return Section(id=self.info.id, title="Set Pieces",
                       subtitle="Dead-ball situations", kpis=kpis)
