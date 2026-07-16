"""Reports - list saved reports. The report engine (fap.reports) is unchanged;
this page only surfaces report presets and links to build one."""
from __future__ import annotations

import streamlit as st

from fap.core.plugin import PluginInfo
from fap.identity.roles import Role
from fap.ui.page import Page, page_registry


@page_registry.register
class ReportsPage(Page):
    info = PluginInfo(id="reports", name="Reports", category="page")
    section = "Workspace"
    icon = "reports"
    order = 30
    min_role = Role.READ_ONLY

    def render(self, shell) -> None:
        st.title("Reports")
        st.caption("Report layouts are saved as dashboard presets and rendered by the "
                   "existing report engine.")
        if shell.wm is None:
            return
        try:
            layouts = shell.wm.list_presets(shell.user, kind="dashboard")
        except Exception:
            layouts = []
        if not layouts:
            st.info("No saved report layouts yet. Save one from the analysis screen.")
            return
        for layout in layouts:
            st.write(f"• **{layout.name}** · _{layout.scope}_")
