"""Dashboard - the landing overview."""
from __future__ import annotations

import streamlit as st

from fap.core.plugin import PluginInfo
from fap.identity.roles import Role
from fap.theme import components as C
from fap.ui.page import Page, page_registry


@page_registry.register
class DashboardPage(Page):
    info = PluginInfo(id="dashboard", name="Dashboard", category="page")
    section = "Overview"
    icon = "dashboard"
    order = 0
    min_role = Role.READ_ONLY

    def render(self, shell) -> None:
        first_name = shell.user.name.split()[0] if shell.user.name else "there"
        C.render_section_title(
            "Dashboard", eyebrow="Overview",
            subtitle=f"Welcome back, {first_name}. Here is your workspace at a glance.",
            icon_name="dashboard")

        if shell.wm is None:
            C.render_alert("Platform services are unavailable in this session.", "warning",
                           title="Limited mode")
            return
        try:
            datasets = shell.wm.list_datasets(workspace_id=shell.workspace_id)
            recents = shell.wm.recents(shell.user)
            audit = shell.wm.audit_trail(limit=8)
        except Exception:
            datasets, recents, audit = [], [], []

        C.render_metric_row([
            C.metric_card_html("Datasets", f"{len(datasets)}", icon_name="datasets",
                               accent="primary", hint="in this workspace"),
            C.metric_card_html("Recent items", f"{len(recents)}", icon_name="clock",
                               accent="info", hint="you touched lately"),
            C.metric_card_html("Your role", shell.user.role_label, icon_name="shield",
                               accent="success", hint="access level"),
        ])

        col_a, col_b = st.columns(2, gap="medium")
        with col_a:
            C.render_section_title("Quick actions", icon_name="lightning")
            _quick(shell, "Open Opponent Analysis", "opponent_analysis", "match")
            _quick(shell, "Manage datasets", "datasets", "datasets")
            _quick(shell, "Browse projects", "projects", "projects")
        with col_b:
            C.render_section_title("Recent activity", icon_name="clock")
            if not audit:
                C.render_alert("No activity recorded yet. Actions you take across the "
                               "platform will appear here.", "info")
            else:
                rows = "".join(
                    f'<div class="fap-activity-row"><code>{e.action}</code>'
                    f'<span class="who">{e.actor or "system"}</span>'
                    f'<span class="ts">{e.ts}</span></div>'
                    for e in audit)
                st.markdown(f'<div class="fap-card fap-activity">{rows}</div>',
                            unsafe_allow_html=True)


def _quick(shell, label: str, page_id: str, icon_name: str) -> None:
    if st.button(label, key=f"qa_{page_id}", use_container_width=True):
        shell.goto(page_id)
