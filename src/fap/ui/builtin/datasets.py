"""Datasets - the professional Data Manager."""
from __future__ import annotations

import streamlit as st

from fap.core.exceptions import AuthError
from fap.core.plugin import PluginInfo
from fap.identity.roles import Role
from fap.theme import components as C
from fap.ui.page import Page, page_registry


@page_registry.register
class DatasetsPage(Page):
    info = PluginInfo(id="datasets", name="Datasets", category="page")
    section = "Workspace"
    icon = "datasets"
    order = 20
    min_role = Role.READ_ONLY

    def render(self, shell) -> None:
        C.render_section_title(
            "Data Manager", eyebrow="Workspace", icon_name="datasets",
            subtitle="Imported match and event datasets, normalized to the canonical model.")
        if shell.wm is None:
            C.render_alert("Platform services are unavailable.", "warning")
            return
        top = st.columns([1, 3], vertical_alignment="center")
        show_archived = top[0].toggle("Show archived", value=False)
        try:
            datasets = shell.wm.list_datasets(workspace_id=shell.workspace_id,
                                              include_archived=show_archived)
        except Exception:
            datasets = []
        if not datasets:
            if C.render_empty_state(
                    "No datasets yet",
                    "Import a match or event file in the Data Hub — it is validated, cleaned and "
                    "normalized, then appears here as a reusable dataset.",
                    icon_name="datasets", action_label="Open Data Hub", key="ds_go_hub"):
                shell.goto("data_hub")
            return

        active = [d for d in datasets if d.status != "archived"]
        C.render_metric_row([
            C.metric_card_html("Datasets", str(len(active)), icon_name="datasets", accent="primary"),
            C.metric_card_html("Total rows", f"{sum(d.rows for d in active):,}",
                               icon_name="grid", accent="info"),
            C.metric_card_html("Archived", str(len(datasets) - len(active)),
                               icon_name="inbox", accent="warning"),
        ])
        st.write("")

        for ds in datasets:
            head = (f"{ds.name}  ·  {ds.provider_id or 'unknown'}  ·  {ds.rows:,} rows")
            with st.expander(head):
                badges = [C.badge_html(ds.status.title(),
                                       "neutral" if ds.status == "archived" else "success")]
                quality = ds.document.get("quality")
                if quality is not None:
                    qk = "success" if quality >= 80 else "warning" if quality >= 60 else "danger"
                    badges.append(C.badge_html(f"Quality {quality}", qk, icon_name="pulse"))
                st.markdown(" ".join(badges), unsafe_allow_html=True)
                c1, c2, c3 = st.columns(3)
                c1.caption(f"Competition: {ds.competition or '—'}")
                c1.caption(f"Season: {ds.season or '—'}")
                c2.caption(f"Opponent: {ds.opponent or '—'}")
                c2.caption(f"Match date: {ds.match_date or '—'}")
                c3.caption(f"Coord system: {ds.coord_system or '—'}")
                c3.caption(f"Rows: {ds.rows:,}")
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
