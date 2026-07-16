"""Templates - reusable chart / filter / export / dashboard presets."""
from __future__ import annotations

import streamlit as st

from fap.core.exceptions import AuthError
from fap.core.plugin import PluginInfo
from fap.identity.roles import Role
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
        st.title("Templates & Presets")
        if shell.wm is None:
            st.info("Platform services unavailable.")
            return
        tabs = st.tabs([k.capitalize() for k in PRESET_KINDS])
        for tab, kind in zip(tabs, PRESET_KINDS):
            with tab:
                try:
                    presets = shell.wm.list_presets(shell.user, kind=kind)
                except Exception:
                    presets = []
                if not presets:
                    st.caption(f"No {kind} presets saved.")
                for preset in presets:
                    cols = st.columns([3, 1])
                    cols[0].write(f"**{preset.name}** · _{preset.scope}_")
                    try:
                        if cols[1].button("Delete", key=f"delp_{preset.id}"):
                            shell.wm.delete_preset(shell.user, preset.id)
                            st.rerun()
                    except AuthError as exc:
                        cols[1].warning(str(exc))
