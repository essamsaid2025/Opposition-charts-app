"""Report Editor page - the Professional Visual Report Studio (Phase 6B).

This page is a thin shell: it resolves *which* report is open (navigation, the
only thing in session_state) and delegates the entire editing experience to
``fap.ui.studio`` - the interactive Canva/PowerPoint-style editor built on the
Phase-6A foundation. All mutation flows through editor_ops + update_studio; charts
regenerate from the saved dataset; images are referenced by id.
"""
from __future__ import annotations

import streamlit as st

from fap.core.plugin import PluginInfo
from fap.identity.roles import Role
from fap.ui.page import Page, page_registry

OPEN_REPORT = "_open_report_id"        # navigation state only


@page_registry.register
class ReportEditorPage(Page):
    info = PluginInfo(id="report_editor", name="Report Studio", category="page")
    section = "Workspace"
    icon = "reports"
    order = 31
    min_role = Role.READ_ONLY          # viewing is open; edits are permission-checked

    def render(self, shell) -> None:
        reports = getattr(shell.platform, "reports", None) if shell.platform else None
        report_id = st.session_state.get(OPEN_REPORT)
        if reports is None:
            st.info("Reports engine unavailable.")
            return
        if not report_id:
            st.title("Report Studio")
            st.info("Open a report from **Reports** to start editing.")
            return
        if reports.get(report_id) is None:
            st.warning("That report no longer exists.")
            st.session_state.pop(OPEN_REPORT, None)
            return

        from fap.ui.studio import render_studio
        render_studio(shell, reports, report_id)
