"""Administration - visible only to administrators (Club Admin and above)."""
from __future__ import annotations

import streamlit as st

from fap.core.exceptions import AuthError
from fap.core.plugin import PluginInfo
from fap.identity.roles import Role, all_roles
from fap.ui.page import Page, page_registry


@page_registry.register
class AdministrationPage(Page):
    info = PluginInfo(id="administration", name="Administration", category="page")
    section = "Admin"
    icon = "admin"
    order = 90
    min_role = Role.CLUB_ADMIN          # hidden from analysts / read-only

    def render(self, shell) -> None:
        st.title("Administration")
        tabs = st.tabs(["Users", "Roles", "Audit", "Storage", "Workspaces", "Clubs"])
        with tabs[0]:
            self._users(shell)
        with tabs[1]:
            self._roles()
        with tabs[2]:
            self._audit(shell)
        with tabs[3]:
            self._storage(shell)
        with tabs[4]:
            self._workspaces(shell)
        with tabs[5]:
            self._clubs(shell)

    def _users(self, shell) -> None:
        st.caption("Identity is owned by your provider (e.g. Microsoft Entra). Users are "
                   "provisioned there; the platform assigns roles via the access policy.")
        st.write(f"Signed-in administrator: **{shell.user.name}** ({shell.user.email})")

    def _roles(self) -> None:
        st.caption("Platform roles, highest authority first:")
        for role in all_roles():
            st.write(f"• **{role.label}** — rank {role.rank}")

    def _audit(self, shell) -> None:
        try:
            entries = shell.wm.audit_trail(limit=100)
        except Exception:
            entries = []
        if not entries:
            st.caption("No audit entries.")
        for e in entries:
            st.write(f"`{e.ts}` · **{e.action}** · {e.actor or 'system'} "
                     f"({e.actor_role or '—'}) · {e.target_type} {e.target_id}")

    def _storage(self, shell) -> None:
        try:
            db = shell.platform.db
            tables = ("datasets", "projects", "workspaces", "presets",
                      "project_versions", "audit_log", "org_nodes")
            for t in tables:
                n = db.query(f"SELECT COUNT(*) AS c FROM {t}")[0]["c"]
                st.write(f"• {t}: **{n}** rows")
        except Exception:
            st.caption("Storage stats unavailable.")

    def _workspaces(self, shell) -> None:
        try:
            for ws in shell.wm.list_workspaces():
                st.write(f"• **{ws.name}** ({ws.id[:8]})")
        except Exception:
            st.caption("Workspaces unavailable.")
        name = st.text_input("New workspace name", key="admin_new_ws")
        if st.button("Create workspace") and name.strip():
            try:
                shell.wm.create_workspace(shell.user, name.strip())
                st.rerun()
            except AuthError as exc:
                st.warning(str(exc))

    def _clubs(self, shell) -> None:
        try:
            clubs = shell.wm.nodes_of_kind("club")
        except Exception:
            clubs = []
        for club in clubs:
            st.write(f"• **{club.name}** ({club.id[:8]})")
        name = st.text_input("New club name", key="admin_new_club")
        if st.button("Create club") and name.strip():
            try:
                shell.wm.create_club(shell.user, name.strip())
                st.rerun()
            except AuthError as exc:
                st.warning(str(exc))
