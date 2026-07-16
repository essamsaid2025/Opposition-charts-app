"""Key players section."""
from __future__ import annotations

import pandas as pd

from fap.core.plugin import PluginInfo
from fap.reports.builtin._common import count, event_slice, top_counts
from fap.reports.models import KPI, Section, Table
from fap.reports.sections import BuildContext, SectionBuilder, section_builder_registry


@section_builder_registry.register
class KeyPlayers(SectionBuilder):
    info = PluginInfo(id="key_players", name="Key Players", category="report_section")
    order = 800

    def build(self, ctx: BuildContext) -> Section:
        df = ctx.df
        players = 0
        if df is not None and "player" in df.columns:
            players = int(df["player"].astype(str).str.strip().replace("", pd.NA).nunique())
        involvement = top_counts(df, "player", 8, "Involvement (events)")
        shots_by = top_counts(event_slice(df, "shot"), "player", 5, "Top shooters")
        return Section(id=self.info.id, title="Key Players",
                       subtitle="Most involved and most threatening",
                       kpis=[KPI("Players", str(players))],
                       tables=[involvement, shots_by])
