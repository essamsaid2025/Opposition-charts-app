"""Templates - reusable chart / filter / export / dashboard presets."""
from __future__ import annotations

import streamlit as st

from fap.core.exceptions import AuthError
from fap.core.plugin import PluginInfo
from fap.identity.roles import Role
from fap.theme import components as C
from fap.theme import icon
from fap.ui.page import Page, page_registry
from fap.workspaces.models import PRESET_KINDS


@page_registry.register
class TemplatesPage(Page):
    info = PluginInfo(id="templates", name="Templates", category="page")
    section = "Workspace"
    icon = "templates"
    order = 40
    min_role = Role.READ_ONLY

    def render(self, shell) -> None:
        C.render_section_title(
            "Templates & Presets", eyebrow="Workspace", icon_name="templates",
            subtitle="Reusable chart, filter, export and dashboard presets you can apply anywhere.")
        if shell.wm is None:
            C.render_alert("Platform services are unavailable.", "warning")
            return
        tabs = st.tabs([k.capitalize() for k in PRESET_KINDS])
        for tab, kind in zip(tabs, PRESET_KINDS):
            with tab:
                try:
                    presets = shell.wm.list_presets(shell.user, kind=kind)
                except Exception:
                    presets = []
                if not presets:
                    C.render_empty_state(
                        f"No {kind} presets",
                        f"Save a {kind} configuration from its module to reuse it here.",
                        icon_name="templates")
                for preset in presets:
                    cols = st.columns([3, 1], vertical_alignment="center")
                    cols[0].markdown(
                        f'{icon("templates", 13)} <b>{preset.name}</b> '
                        f'{C.badge_html(preset.scope, "neutral")}', unsafe_allow_html=True)
                    try:
                        if cols[1].button("Delete", key=f"delp_{preset.id}"):
                            shell.wm.delete_preset(shell.user, preset.id)
                            st.rerun()
                    except AuthError as exc:
                        cols[1].warning(str(exc))
