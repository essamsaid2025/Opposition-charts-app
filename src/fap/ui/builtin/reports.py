"""Reports page - create, open, export and manage reports via the Reports
Engine (fap.reports). Consumes platform services only; no report logic here."""
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
        reports = _reports_manager(shell)
        if reports is None:
            st.info("Reports engine unavailable.")
            return

        tab_list, tab_create = st.tabs(["My reports", "Create"])

        with tab_create:
            self._create(shell, reports)

        with tab_list:
            query = st.text_input("Search reports", key="report_search",
                                  placeholder="title, template, owner…")
            fav_only = st.toggle("Favorites only", key="report_fav_only")
            records = shell.wm and reports.list(
                shell.user, workspace_id=shell.workspace_id,
                favorite=True if fav_only else None, query=query)
            records = records or []
            if not records:
                st.info("No reports yet. Use the Create tab.")
            for r in records:
                self._row(shell, reports, r)

    # ------------------------------------------------------------ create
    def _create(self, shell, reports) -> None:
        # The active dataset comes from the platform (WorkspaceManager) - the one
        # source of truth. No re-upload, and never session_state.
        dataset = shell.wm.active_dataset(shell.user) if shell.wm else None
        df = shell.wm.active_frame(shell.user) if shell.wm else None
        if dataset is None:
            st.info("No active dataset. Import a file in **Opponent Analysis** — it becomes "
                    "the active dataset automatically and every screen reuses it.")
            return
        st.caption(f"Active dataset: **{dataset.name}** · {dataset.provider_id or 'provider n/a'}"
                   f" · {dataset.rows:,} rows")
        if df is None:
            st.warning("The active dataset's data is no longer cached. Re-open "
                       "**Opponent Analysis** to refresh it.")
            return

        templates = reports.templates()
        names = {t.info.id: t.info.name for t in templates}
        template = st.selectbox("Template", list(names), format_func=lambda i: names[i],
                                key="report_template")
        title = st.text_input("Title (optional)", key="report_title")
        opponent = st.text_input("Opponent", key="report_opponent",
                                 value=dataset.opponent or "")
        if st.button("Create report", type="primary", key="report_create_btn"):
            try:
                rec = reports.create(
                    shell.user, template=template, df=df, title=title,
                    workspace_id=shell.workspace_id or dataset.workspace_id,
                    dataset_id=dataset.id,
                    cover={"opponent": opponent, "competition": dataset.competition,
                           "season": dataset.season, "match_date": dataset.match_date})
                st.success(f"Created “{rec.title}”.")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not create report: {exc}")

    # ------------------------------------------------------------ row actions
    def _row(self, shell, reports, r) -> None:
        with st.container(border=True):
            c1, c2 = st.columns([4, 2])
            c1.markdown(f"**{r.title}**  \n_{r.template_id}_ · {r.owner} · {r.updated_at}")
            if c1.button("Open in editor", key=f"open_{r.id}", type="primary"):
                from fap.ui.builtin.report_editor import OPEN_REPORT
                st.session_state[OPEN_REPORT] = r.id      # navigation only
                shell.goto("report_editor")
            with c2:
                fmt = st.selectbox("Export", reports.available_formats(),
                                   key=f"fmt_{r.id}", label_visibility="collapsed")
                if st.button("Export", key=f"exp_{r.id}"):
                    try:
                        rendered = reports.render(shell.user, r.id, fmt)
                        st.download_button("Download", rendered.content, file_name=rendered.filename,
                                           mime=rendered.mime, key=f"dl_{r.id}")
                    except Exception as exc:
                        st.error(str(exc))
                fav = "Unfavorite" if r.favorite else "Favorite"
                if st.button(fav, key=f"fav_{r.id}"):
                    reports.favorite(shell.user, r.id, on=not r.favorite); st.rerun()
                if st.button("Archive" if r.status == "active" else "Restore", key=f"arc_{r.id}"):
                    reports.archive(shell.user, r.id, archived=r.status == "active"); st.rerun()


def _reports_manager(shell):
    try:
        return shell.platform.reports if shell.platform is not None else None
    except Exception:
        return None
