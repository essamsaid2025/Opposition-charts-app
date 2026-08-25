"""Opponent Analysis - the existing Open Play visualization engine.

The page body is app.py's ``run_app``, injected at startup via
``register_renderer`` so this module never imports app (which would be
circular) and the visualization code is not touched.

This is the OPPONENT ANALYSIS page (Open Play / event data). It is a distinct
route from the Scouting page (``id="scouting"``, the player recruitment + player-
scouting workspace) - the two must never share a label or renderer, or a click on
"Scouting" ends up in the Open Play engine (which then fails on the missing event
column ``x2`` when a player-scouting dataset is active).
"""
from __future__ import annotations

import streamlit as st

from fap.core.plugin import PluginInfo
from fap.identity.roles import Role
from fap.theme import components as C
from fap.ui.dataset_compat import (
    non_event_active_dataset, team_stats_active_dataset,
)
from fap.ui.page import Page, get_renderer, page_registry


@page_registry.register
class OpponentAnalysisPage(Page):
    info = PluginInfo(id="opponent_analysis", name="Opponent Analysis", category="page")
    section = "Analysis"
    icon = "analysis"
    order = 0
    min_role = Role.READ_ONLY

    def render(self, shell) -> None:
        # Page-boundary compatibility gate: the Open Play engine needs an event
        # dataset (its transforms read x/y -> x2). A player-scouting dataset has no
        # coordinates, so route the user to Scouting instead of letting run_app raise
        # KeyError('x2'). This checks the persisted dataset_type - it never fabricates
        # columns, suppresses the error, or relaxes the engine's requirements.
        # Team-match-stats datasets have no events but ARE supported in Open Play via
        # a dedicated comparison workspace — render it here instead of run_app.
        team_ds = team_stats_active_dataset(shell)
        if team_ds is not None:
            C.render_section_title(
                "Opponent Analysis", eyebrow="Analysis", icon_name="analysis",
                subtitle="Team match stats — comparison charts.")
            from fap.ui.components.team_compare_workspace import (
                render_team_compare_workspace,
            )
            render_team_compare_workspace(shell, team_ds, key="_oa_team_cmp")
            return

        blocked = non_event_active_dataset(shell)
        if blocked is not None:
            self._render_incompatible(shell, blocked)
            return

        renderer = get_renderer("opponent_analysis")
        if renderer is None:
            C.render_section_title(
                "Opponent Analysis", eyebrow="Analysis", icon_name="analysis",
                subtitle="Open Play visualization engine.")
            C.render_alert("The Open Play visualization engine is not connected.", "warning")
            return
        renderer()               # app.run_app: draws its own controls + charts

    def _render_incompatible(self, shell, ds) -> None:
        C.render_section_title(
            "Opponent Analysis", eyebrow="Analysis", icon_name="analysis",
            subtitle="Open Play visualization engine (event data).")
        C.render_alert(
            f"The active dataset '{ds.name}' is a player-scouting dataset (one row per "
            f"player, no match events), so it cannot be analysed in Opponent Analysis. "
            f"Open it in Scouting for player-level analysis, or activate an event "
            f"dataset in the Data Hub.", "info", title="Not an event dataset")
        cols = st.columns(2)
        if cols[0].button("Open Scouting", type="primary", use_container_width=True,
                          key="_oa_goto_scouting"):
            shell.goto("scouting")
        if cols[1].button("Open Data Hub", use_container_width=True, key="_oa_goto_hub"):
            shell.goto("data_hub")
