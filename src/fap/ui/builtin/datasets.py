"""Datasets - the professional Data Manager."""
from __future__ import annotations

import streamlit as st

from fap.core.exceptions import AuthError
from fap.core.plugin import PluginInfo
from fap.identity.roles import Role
from fap.ui.page import Page, page_registry


@page_registry.register
class DatasetsPage(Page):
    info = PluginInfo(id="datasets", name="Datasets", category="page")
    section = "Workspace"
    icon = "🗄️"
    order = 20
    min_role = Role.READ_ONLY

    def render(self, shell) -> None:
        st.title("Data Manager")
        if shell.wm is None:
            st.info("Platform services unavailable.")
            return
        show_archived = st.toggle("Show archived", value=False)
        try:
            datasets = shell.wm.list_datasets(workspace_id=shell.workspace_id,
                                              include_archived=show_archived)
        except Exception:
            datasets = []
        if not datasets:
            st.caption("No datasets yet. Import a file from Opponent Analysis.")
            return

        for ds in datasets:
            with st.expander(f"{ds.name}  ·  {ds.provider_id or 'unknown'}  ·  {ds.rows:,} rows"):
                c1, c2, c3 = st.columns(3)
                c1.caption(f"Competition: {ds.competition or '—'}")
                c1.caption(f"Season: {ds.season or '—'}")
                c2.caption(f"Opponent: {ds.opponent or '—'}")
                c2.caption(f"Match date: {ds.match_date or '—'}")
                c3.caption(f"Coord system: {ds.coord_system or '—'}")
                c3.caption(f"Status: {ds.status}")
                quality = ds.document.get("quality")
                if quality is not None:
                    st.caption(f"Data quality: {quality}")
                self._actions(shell, ds)

    def _actions(self, shell, ds) -> None:
        a, b, c, d = st.columns(4)
        try:
            if a.button("Rename", key=f"rn_{ds.id}"):
                st.session_state[f"_rename_{ds.id}"] = True
            if st.session_state.get(f"_rename_{ds.id}"):
                new = st.text_input("New name", value=ds.name, key=f"rnv_{ds.id}")
                if st.button("Save", key=f"rns_{ds.id}"):
                    shell.wm.rename_dataset(shell.user, ds.id, new)
                    st.session_state.pop(f"_rename_{ds.id}", None)
                    st.rerun()
            if b.button("Duplicate", key=f"dup_{ds.id}"):
                shell.wm.duplicate_dataset(shell.user, ds.id)
                st.rerun()
            label = "Unarchive" if ds.status == "archived" else "Archive"
            if c.button(label, key=f"ar_{ds.id}"):
                shell.wm.archive_dataset(shell.user, ds.id, archived=ds.status != "archived")
                st.rerun()
            if d.button("Delete", key=f"del_{ds.id}"):
                shell.wm.delete_dataset(shell.user, ds.id)
                st.rerun()
        except AuthError as exc:
            st.warning(str(exc))
