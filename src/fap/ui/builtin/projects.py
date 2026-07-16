"""Projects - list projects and their version history."""
from __future__ import annotations

import streamlit as st

from fap.core.exceptions import AuthError
from fap.core.plugin import PluginInfo
from fap.identity.roles import Role
from fap.ui.page import Page, page_registry


@page_registry.register
class ProjectsPage(Page):
    info = PluginInfo(id="projects", name="Projects", category="page")
    section = "Workspace"
    icon = "📁"
    order = 10
    min_role = Role.READ_ONLY

    def render(self, shell) -> None:
        st.title("Projects")
        if shell.wm is None or not shell.workspace_id:
            st.info("Select a workspace to see its projects.")
            return
        try:
            projects = shell.wm.list_projects(shell.workspace_id)
        except Exception:
            projects = []
        if not projects:
            st.caption("No projects in this workspace yet.")
            return

        for project in projects:
            with st.expander(f"{project.name}"):
                st.caption(f"Visualization: {project.document.get('visual_id', '—')}")
                if st.button("Version history", key=f"vh_{project.id}"):
                    st.session_state[f"_versions_{project.id}"] = True
                if st.session_state.get(f"_versions_{project.id}"):
                    self._versions(shell, project.id)

    def _versions(self, shell, project_id: str) -> None:
        try:
            versions = shell.wm.list_versions(project_id)
        except Exception:
            versions = []
        if not versions:
            st.caption("No saved versions.")
            return
        for v in versions:
            cols = st.columns([3, 1])
            cols[0].write(f"v{v.version} · {v.created_at} · {v.note or 'no note'}")
            try:
                if cols[1].button("Restore", key=f"rs_{project_id}_{v.version}"):
                    shell.wm.restore_version(shell.user, project_id, v.version)
                    st.success(f"Restored v{v.version}")
                    st.rerun()
            except AuthError as exc:
                cols[1].warning(str(exc))
