"""Dashboard - the landing overview."""
from __future__ import annotations

import streamlit as st

from fap.core.plugin import PluginInfo
from fap.identity.roles import Role
from fap.ui.page import Page, page_registry


@page_registry.register
class DashboardPage(Page):
    info = PluginInfo(id="dashboard", name="Dashboard", category="page")
    section = "Overview"
    icon = "🏠"
    order = 0
    min_role = Role.READ_ONLY

    def render(self, shell) -> None:
        st.title("Dashboard")
        st.caption(f"Welcome, {shell.user.name}.")
        if shell.wm is None:
            st.info("Platform services unavailable.")
            return
        try:
            datasets = shell.wm.list_datasets(workspace_id=shell.workspace_id)
            recents = shell.wm.recents(shell.user)
            audit = shell.wm.audit_trail(limit=8)
        except Exception:
            datasets, recents, audit = [], [], []

        c1, c2, c3 = st.columns(3)
        c1.metric("Datasets", len(datasets))
        c2.metric("Recent items", len(recents))
        c3.metric("Your role", shell.user.role_label)

        col_a, col_b = st.columns(2)
        with col_a:
            st.subheader("Quick actions")
            if st.button("Open Opponent Analysis", use_container_width=True):
                shell.goto("opponent_analysis")
            if st.button("Manage datasets", use_container_width=True):
                shell.goto("datasets")
            if st.button("Browse projects", use_container_width=True):
                shell.goto("projects")
        with col_b:
            st.subheader("Recent activity")
            if not audit:
                st.caption("No activity yet.")
            for entry in audit:
                st.write(f"• `{entry.action}` — {entry.actor or 'system'} · {entry.ts}")
