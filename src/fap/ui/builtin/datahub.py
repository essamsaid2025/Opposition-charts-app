"""Data Hub - the Universal Import Center and Dataset Library (Phase 12).

A first-class page directly under Dashboard. A thin view over ``DataHubService``:
no import/validation/cleaning/mapping/quality/storage logic lives here - it all
runs in the platform engine the service reuses. The page delivers the 10-step
wizard, the dataset library, and per-dataset health / compatibility / lineage /
versions. Every module consumes a dataset by the service's ``choose`` (which sets
the active dataset all modules already read) - no duplicated import anywhere.
"""
from __future__ import annotations

import html as _html
import logging
from typing import Any

import streamlit as st

from fap.core.exceptions import AuthError
from fap.core.plugin import PluginInfo
from fap.datahub.importers import SUPPORTED_FORMATS
from fap.datahub.preview import PreviewRequest
from fap.identity.roles import Role
from fap.theme import components as C
from fap.theme import icon
from fap.ui.page import Page, page_registry

SEL = "_dh_selected"
RESULT = "_dh_import_result"
RAW = "_dh_import_bytes"
RAWNAME = "_dh_import_name"

_HEALTH_KIND = {"green": "success", "yellow": "warning", "red": "danger"}
_RATING_KIND = {"Excellent": "success", "Good": "success", "Fair": "warning", "Poor": "danger"}

logger = logging.getLogger(__name__)


@page_registry.register
class DataHubPage(Page):
    info = PluginInfo(id="data_hub", name="Data Hub", category="page")
    section = "Overview"
    icon = "datasets"
    order = 1                       # directly under Dashboard (order 0)
    min_role = Role.READ_ONLY       # edits are capability-checked by the manager

    def render(self, shell) -> None:
        hub = getattr(shell.platform, "datahub", None) if shell.platform else None
        if hub is None:
            st.info("Data Hub is unavailable in this session.")
            return
        C.render_section_title(
            "Data Hub", eyebrow="Universal Import Center",
            subtitle="Import, validate and manage every dataset in one place - "
                     "then any module simply chooses one.", icon_name="datasets")

        if st.session_state.get(SEL) and hub.get(st.session_state[SEL]):
            self._detail(shell, hub, st.session_state[SEL])
            return

        tab_import, tab_library = st.tabs(["Import", "Dataset Library"])
        with tab_import:
            self._wizard(shell, hub)
        with tab_library:
            self._library(shell, hub)

    # ============================================================ import wizard
    def _wizard(self, shell, hub) -> None:
        C.render_section_title("Import a dataset", eyebrow="Step 1 - Upload", icon_name="upload")
        up = st.file_uploader("Drop a file", type=list(SUPPORTED_FORMATS),
                              key="_dh_upload", label_visibility="collapsed")
        sources = [s for s in hub.sources() if s.available]
        labels = {s.id: s.label for s in sources}
        pick = st.selectbox("Provider", ["auto", *[s.id for s in sources if s.id != "auto"]],
                            format_func=lambda i: labels.get(i, i), key="_dh_provider")
        st.caption("Supported: " + ", ".join(s.label for s in hub.sources()))

        if up is not None:
            if st.button("Analyze file", type="primary", key="_dh_analyze",
                         use_container_width=True):
                try:
                    provider_id = None if pick == "auto" else next(
                        (s.provider_id for s in sources if s.id == pick), None) or None
                    data = up.getvalue()
                    with st.spinner("Detecting provider, validating, cleaning and scoring..."):
                        result = hub.run_import(data, up.name, provider_id=provider_id)
                    st.session_state[RESULT] = result
                    st.session_state[RAW] = data
                    st.session_state[RAWNAME] = up.name
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not analyze the file: {exc}")

        result = st.session_state.get(RESULT)
        if result is None:
            C.render_alert("Upload a file and click Analyze. The Data Hub detects the provider, "
                           "validates and cleans the data, maps columns, normalizes coordinates "
                           "and scores quality - then you save it as a reusable dataset.", "info")
            return
        self._wizard_report(shell, hub, result)

    def _wizard_report(self, shell, hub, result) -> None:
        summary = result.summary or {}
        # Step 2 - provider detection + confidence
        C.render_section_title("Provider detection", eyebrow="Step 2", icon_name="target")
        conf = summary.get("provider_confidence")
        conf_txt = f"{conf:.0%}" if isinstance(conf, (int, float)) else "explicit"
        st.markdown(
            f'{C.badge_html(summary.get("provider_name", result.provider_id) or "Unknown", "info")}'
            f' &nbsp; confidence <b>{conf_txt}</b> &nbsp; '
            f'<span style="color:var(--fap-text-muted)">{_html.escape(str(summary.get("provider_reasoning","")))}</span>',
            unsafe_allow_html=True)

        # Step 3 - validation (never silently fix)
        C.render_section_title("Validation", eyebrow="Step 3", icon_name="shield")
        v = result.validation
        vc = st.columns(3)
        vc[0].metric("Rows checked", f"{v.rows_checked:,}")
        vc[1].metric("Errors", len(v.errors))
        vc[2].metric("Warnings", len(v.warnings))
        for iss in v.issues[:12]:
            kind = {"error": "danger", "warning": "warning"}.get(iss.severity, "info")
            st.markdown(C.badge_html(f"{iss.code} ({iss.count})", kind) + " " +
                        _html.escape(iss.message), unsafe_allow_html=True)
        if not v.issues:
            C.render_alert("No validation issues found.", "success")

        # Step 4 - cleaning (show exactly what changed)
        C.render_section_title("Cleaning", eyebrow="Step 4", icon_name="sliders")
        if result.cleaning_log:
            for change in result.cleaning_log:
                st.markdown(f"{icon('check', 13)} {_html.escape(change)}", unsafe_allow_html=True)
        else:
            st.caption("No changes were required.")

        # Step 5 + 6 - mapping + coordinates
        cols = st.columns(2)
        with cols[0]:
            C.render_section_title("Column mapping", eyebrow="Step 5", icon_name="layers")
            st.caption(f"Confidence {result.mapping_confidence:.0%}")
            inferred = summary.get("inferred_event_type")
            if inferred:
                C.render_alert(
                    f"This file has no event-type column - it was read as "
                    f"**{summary.get('inferred_shape', 'a single event kind')}** and every "
                    f"row set to event type **{inferred}** ({summary.get('inferred_reason', '')}).",
                    "info")
            rows = [{"source": s, "canonical": c} for s, c in list(result.mapping.items())[:20]]
            if rows:
                st.dataframe(rows, use_container_width=True, hide_index=True)
        with cols[1]:
            C.render_section_title("Coordinates", eyebrow="Step 6", icon_name="map-pin")
            st.markdown(f'Detected system: {C.badge_html(result.coord_system or "unknown", "info")} '
                        f'&nbsp; confidence <b>{result.coord_confidence:.0%}</b>',
                        unsafe_allow_html=True)
            st.caption("Normalized to the platform standard (0-100).")

        # Step 7 - quality
        C.render_section_title("Quality report", eyebrow="Step 7", icon_name="pulse")
        q = result.quality
        from fap.datahub import quality as dq
        rating = dq.rating(q.overall)
        qc = st.columns([1, 3])
        qc[0].markdown(C.metric_card_html("Score", f"{q.overall:.0f}", hint="0-100",
                                          accent="primary"), unsafe_allow_html=True)
        with qc[1]:
            st.markdown(f'Rating: {C.badge_html(rating, _RATING_KIND.get(rating, "neutral"))}',
                        unsafe_allow_html=True)
            comp_cards = [C.metric_card_html(k.replace("_", " ").title(), f"{val:.0f}")
                          for k, val in q.components.items()]
            C.render_metric_row(comp_cards)

        # Step 8 - preview
        C.render_section_title("Preview", eyebrow="Step 8", icon_name="grid")
        pv = hub.preview_frame(result.frame, PreviewRequest(page=1, page_size=15))
        st.markdown(self._preview_table(pv), unsafe_allow_html=True)
        st.caption(f"{pv.total:,} rows - errors and warnings highlighted")

        # Step 9 - save
        C.render_section_title("Save dataset", eyebrow="Step 9", icon_name="download")
        self._save_form(shell, hub, result, summary)

    def _save_form(self, shell, hub, result, summary) -> None:
        with st.form("_dh_save"):
            a, b = st.columns(2)
            name = a.text_input("Dataset name", value=st.session_state.get(RAWNAME, "dataset"))
            competition = b.text_input("Competition")
            c, d, e = st.columns(3)
            season = c.text_input("Season")
            opponent = d.text_input("Opponent")
            match_date = e.text_input("Match date")
            f, g = st.columns(2)
            pitch = f.text_input("Pitch size", value="105x68")
            units = g.text_input("Units", value="meters")
            tags = st.text_input("Tags (comma separated)")
            visibility = st.selectbox("Visibility", ["workspace", "private", "club"])
            description = st.text_area("Description", height=68)
            tr, gp = st.columns(2)
            tracking = tr.checkbox("Contains tracking data")
            gps = gp.checkbox("Contains GPS data")
            if st.form_submit_button("Save dataset", type="primary"):
                try:
                    ds = hub.save_dataset(
                        shell.user, result, name=name or "dataset",
                        workspace_id=shell.workspace_id,
                        metadata={"competition": competition, "season": season,
                                  "opponent": opponent, "match_date": match_date,
                                  "pitch": pitch, "units": units,
                                  "tags": [t.strip() for t in tags.split(",") if t.strip()],
                                  "visibility": visibility, "description": description,
                                  "tracking": tracking, "gps": gps})
                    for key in (RESULT, RAW, RAWNAME):
                        st.session_state.pop(key, None)
                    st.session_state[SEL] = ds.id
                    st.toast(f"Saved dataset '{ds.name}'")
                    st.rerun()
                except AuthError as exc:
                    st.error(str(exc))
                except Exception as exc:
                    st.error(f"Could not save the dataset: {exc}")

    # ============================================================ library
    def _library(self, shell, hub) -> None:
        top = st.columns([3, 1], vertical_alignment="center")
        top[0].caption("Every saved dataset. Open one for its health, compatibility, "
                       "lineage and versions - or choose it for the whole platform.")
        show_archived = top[1].toggle("Show archived", value=False, key="_dh_arch")
        try:
            datasets = hub.list_datasets(workspace_id=shell.workspace_id,
                                         include_archived=show_archived)
        except Exception as exc:
            # Do NOT disguise a backend failure as an empty library: log it and show
            # a distinct error, so the user knows their datasets may still exist.
            logger.exception("list_datasets failed for workspace %r", shell.workspace_id)
            C.render_alert(f"Could not load your datasets: {exc}. This is a load error, "
                           "not an empty library - please retry.", "danger")
            return
        if not datasets:
            C.render_empty_state("No datasets yet", "Import your first file in the Import tab - "
                                 "it becomes a reusable dataset every module can open.",
                                 icon_name="datasets")
            return
        for ds in datasets:
            self._card(shell, hub, ds)

    def _card(self, shell, hub, ds) -> None:
        doc = ds.document if isinstance(ds.document, dict) else {}
        quality = doc.get("quality")
        rating = doc.get("quality_rating", "")
        try:
            modules = hub.modules_supported(ds.id)
        except Exception:
            modules = []
        try:
            is_active = shell.wm.active_dataset_id(shell.user) == ds.id
        except Exception:
            is_active = False
        with st.container(border=True):
            qbadge = (C.badge_html(f"Quality {quality:.0f} - {rating}",
                                   _RATING_KIND.get(rating, "neutral"))
                      if isinstance(quality, (int, float)) else "")
            if is_active:
                qbadge = C.badge_html("Active Dataset", "success", icon_name="check") + " " + qbadge
            tags = "".join(C.badge_html(t, "neutral") for t in doc.get("tags", []))
            mods = " ".join(C.badge_html(m, "success", icon_name="check") for m in modules) \
                or C.badge_html("no modules ready", "warning")
            st.markdown(
                f'<div class="fap-dh-card"><div class="head"><span class="nm">{_html.escape(ds.name)}</span>'
                f'{qbadge}</div>'
                f'<div class="meta"><span>{icon("datasets",13)} {_html.escape(ds.provider_id or "unknown")}</span>'
                f'<span>{icon("trophy",13)} {_html.escape(ds.competition or "-")}</span>'
                f'<span>{icon("calendar",13)} {_html.escape(ds.season or "-")}</span>'
                f'<span>{icon("flag",13)} {_html.escape(ds.opponent or "-")}</span>'
                f'<span>{icon("user",13)} {_html.escape(ds.created_by or "-")}</span>'
                f'<span>{ds.rows:,} rows</span></div>'
                f'<div>{mods}</div>'
                f'<div>{tags}</div></div>', unsafe_allow_html=True)
            bcols = st.columns(6)
            if bcols[0].button("Open", key=f"dh_open_{ds.id}", use_container_width=True):
                st.session_state[SEL] = ds.id
                st.rerun()
            if bcols[1].button("Active" if is_active else "Set Active",
                               key=f"dh_choose_{ds.id}", type="secondary" if is_active else "primary",
                               disabled=is_active, use_container_width=True):
                try:
                    hub.choose(shell.user, ds.id)
                    st.toast(f"'{ds.name}' is now the active dataset for every module")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
            if bcols[2].button("Duplicate", key=f"dh_dup_{ds.id}", use_container_width=True):
                self._safe(lambda: hub.duplicate(shell.user, ds.id))
            label = "Unarchive" if ds.status == "archived" else "Archive"
            if bcols[3].button(label, key=f"dh_arch_{ds.id}", use_container_width=True):
                self._safe(lambda: hub.archive(shell.user, ds.id, archived=ds.status != "archived"))
            if bcols[4].button("Delete", key=f"dh_del_{ds.id}", use_container_width=True):
                self._safe(lambda: hub.delete(shell.user, ds.id))

    # ============================================================ dataset detail
    def _detail(self, shell, hub, dataset_id) -> None:
        ds = hub.get(dataset_id)
        if st.button("Back to library", key="_dh_back"):
            st.session_state.pop(SEL, None)
            st.rerun()
        st.markdown(f"### {_html.escape(ds.name)}")
        st.caption(f"{ds.provider_id or 'unknown'} - {ds.competition or '-'} - "
                   f"{ds.season or '-'} - {ds.rows:,} rows")

        tabs = st.tabs(["Health", "Compatibility", "Preview", "Lineage", "Versions"])
        with tabs[0]:
            self._health(hub, dataset_id)
        with tabs[1]:
            self._compat(hub, dataset_id)
        with tabs[2]:
            pv = hub.preview(dataset_id, PreviewRequest(
                page=st.number_input("Page", 1, 10000, 1, key="_dh_pv_page"), page_size=25,
                search=st.text_input("Search", key="_dh_pv_search")))
            st.markdown(self._preview_table(pv), unsafe_allow_html=True)
            st.caption(f"Page {pv.page} / {pv.pages} - {pv.total:,} rows")
        with tabs[3]:
            self._lineage(hub, dataset_id)
        with tabs[4]:
            self._versions(shell, hub, dataset_id)

    def _health(self, hub, dataset_id) -> None:
        health = hub.health(dataset_id)
        st.markdown(f"Overall: {C.badge_html(health.overall.upper(), _HEALTH_KIND.get(health.overall, 'neutral'))}",
                    unsafe_allow_html=True)
        cells = "".join(
            f'<div class="fap-health-axis"><span class="dot {a.status}"></span>'
            f'<span class="lbl">{_html.escape(a.label)}</span>'
            f'<span class="sub">{_html.escape(a.detail)}</span></div>' for a in health.axes)
        st.markdown(f'<div class="fap-health-grid">{cells}</div>', unsafe_allow_html=True)

    def _compat(self, hub, dataset_id) -> None:
        st.caption("Which modules can use this dataset right now.")
        rows = ""
        for c in hub.compatibility(dataset_id):
            badge = C.badge_html("READY" if c.ready else "NOT READY",
                                 "success" if c.ready else "danger",
                                 icon_name="check" if c.ready else "x")
            rows += (f'<div class="fap-compat-row"><span class="mod">{_html.escape(c.module)}</span>'
                     f'{badge}<span class="why">{_html.escape(c.reason)}</span></div>')
        st.markdown(f'<div class="fap-card">{rows}</div>', unsafe_allow_html=True)

    def _lineage(self, hub, dataset_id) -> None:
        events = hub.lineage(dataset_id)
        if not events:
            st.caption("No lineage recorded.")
            return
        rows = "".join(
            f'<div class="fap-activity-row">{C.badge_html(e.get("stage","").title(), "info")}'
            f'<span class="who">{_html.escape(e.get("detail",""))}</span>'
            f'<span class="ts">{_html.escape(e.get("at",""))}</span></div>' for e in events)
        st.markdown(f'<div class="fap-card fap-activity">{rows}</div>', unsafe_allow_html=True)

    def _versions(self, shell, hub, dataset_id) -> None:
        versions = hub.versions(dataset_id)
        if not versions:
            st.caption("No versions yet.")
            return
        for v in reversed(versions):
            cols = st.columns([4, 1], vertical_alignment="center")
            cols[0].markdown(f"**v{v.get('version')}** - {_html.escape(v.get('note',''))} "
                             f"<span style='color:var(--fap-text-subtle)'>{_html.escape(v.get('at',''))}</span>",
                             unsafe_allow_html=True)
            if cols[1].button("Restore", key=f"dh_restore_{dataset_id}_{v.get('version')}",
                              use_container_width=True):
                self._safe(lambda vv=v: hub.restore_version(shell.user, dataset_id, vv.get("version")))

    # ============================================================ helpers
    @staticmethod
    def _preview_table(pv) -> str:
        if not pv.columns:
            return "<div class='fap-card'>No rows to preview.</div>"
        head = "".join(f"<th>{_html.escape(str(c))}</th>" for c in pv.columns)
        body = ""
        for row, flag in zip(pv.rows, pv.flags):
            tds = ""
            for c in pv.columns:
                cls = flag.get(c, "")
                cell = _html.escape(str(row.get(c, "")))
                tds += f'<td class="cell-{cls}">{cell}</td>' if cls else f"<td>{cell}</td>"
            body += f"<tr>{tds}</tr>"
        return (f'<div class="fap-dh-scroll"><table class="fap-dh-table">'
                f'<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')

    @staticmethod
    def _safe(fn) -> None:
        try:
            fn()
            st.rerun()
        except AuthError as exc:
            st.warning(str(exc))
        except Exception as exc:
            st.error(str(exc))
