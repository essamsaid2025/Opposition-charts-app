"""Opponent Analysis - the existing Open Play visualization engine.

The page body is app.py's ``run_app``, injected at startup via
``register_renderer`` so this module never imports app (which would be
circular) and the visualization code is not touched.
"""
from __future__ import annotations

import streamlit as st

from fap.core.plugin import PluginInfo
from fap.identity.roles import Role
from fap.ui.page import Page, get_renderer, page_registry


@page_registry.register
class OpponentAnalysisPage(Page):
    info = PluginInfo(id="opponent_analysis", name="Opponent Analysis", category="page")
    section = "Analysis"
    icon = "🎯"
    order = 0
    min_role = Role.READ_ONLY

    def render(self, shell) -> None:
        renderer = get_renderer("opponent_analysis")
        if renderer is None:
            st.title("Opponent Analysis")
            st.info("The Open Play visualization engine is not connected.")
            return
        renderer()               # app.run_app: draws its own controls + charts
