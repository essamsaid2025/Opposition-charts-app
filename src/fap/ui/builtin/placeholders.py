"""Registered-but-not-yet-built pages.

They appear in the navigation and participate in the plugin architecture, but
their body is an honest placeholder - no fabricated analysis. Each becomes a
real page by replacing its ``render`` when the feature lands.
"""
from __future__ import annotations

import streamlit as st

from fap.core.plugin import PluginInfo
from fap.identity.roles import Role
from fap.ui.page import Page, page_registry


class _Placeholder(Page):
    min_role = Role.READ_ONLY
    _blurb = ""

    def render(self, shell) -> None:
        st.title(self.info.name)
        st.info(f"{self.info.name} is planned. {self._blurb}")
        st.caption("This screen is registered in the shell; its analysis is on the roadmap.")


@page_registry.register
class MatchAnalysisPage(_Placeholder):
    info = PluginInfo(id="match_analysis", name="Match Analysis", category="page")
    section = "Analysis"; icon = "match"; order = 10
    _blurb = "Single-match breakdowns will build on the Open Play engine."


@page_registry.register
class SetPieceAnalysisPage(_Placeholder):
    info = PluginInfo(id="set_piece_analysis", name="Set Piece Analysis", category="page")
    section = "Analysis"; icon = "setpiece"; order = 20
    _blurb = "Corners, free kicks and throw-ins."


# NOTE: the Scouting page is no longer a placeholder - the real implementation
# lives in fap.ui.builtin.scouting (Phase 8.0), registered under id="scouting".
# The placeholder was removed so it no longer collides with (and shadows) the
# real page during plugin discovery.


@page_registry.register
class PlayersPage(_Placeholder):
    info = PluginInfo(id="players", name="Players", category="page")
    section = "Squad"; icon = "players"; order = 10
    _blurb = "Per-player profiles across datasets."


@page_registry.register
class TeamsPage(_Placeholder):
    info = PluginInfo(id="teams", name="Teams", category="page")
    section = "Squad"; icon = "teams"; order = 20
    _blurb = "Team-level aggregates and comparisons."
