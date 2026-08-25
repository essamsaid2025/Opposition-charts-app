"""Report Studio v2 (Phase A) — Konva editor page, behind a feature flag.

This page is REGISTERED ONLY when ``FAP_REPORT_STUDIO_V2`` is enabled
(``editor_adapter.v2_enabled``). When the flag is off it does not exist in the
navigation and the classic "Report Studio" (``report_editor``) remains the sole,
unchanged default. Nothing here touches the classic studio, the xG model, or any
unrelated feature.

Phase A scope: mount the React+Konva editor as a Streamlit custom component,
initialize/round-trip an engine-independent document (``editor_adapter``), and
prove a basic save/load cycle. No templates/charts/data-binding/export/AI yet.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from fap.core.plugin import PluginInfo
from fap.identity.roles import Role
from fap.reports import editor_adapter as adapter
from fap.reports.models import ReportDocument
from fap.ui.page import Page, page_registry

_FRONTEND_DIR = Path(__file__).resolve().parent / "frontend" / "report_studio"

# session keys (Phase A persistence foundation lives in session_state)
_S_DOC = "rs2_doc"          # current engine-independent v2 document (dict)
_S_SAVED = "rs2_saved_rd"   # last persisted ReportDocument (dict) — the save target
_S_TS = "rs2_last_ts"       # last component action stamp (dedupe re-delivered values)

_component = None


def _get_component():
    """Lazy component declaration so importing this module never requires the
    component runtime (keeps plugin discovery light and headless-test safe)."""
    global _component
    if _component is None:
        import streamlit.components.v1 as components
        _component = components.declare_component("fap_report_studio", path=str(_FRONTEND_DIR))
    return _component


def _current_doc() -> dict[str, Any]:
    doc = st.session_state.get(_S_DOC)
    if not isinstance(doc, dict) or not doc.get("pages"):
        doc = adapter.new_document()
        st.session_state[_S_DOC] = doc
    return doc


class ReportStudioV2Page(Page):
    """The new Konva-based Report Studio (preview). Registered only when flagged."""
    info = PluginInfo(id="report_studio_v2", name="Report Studio (Preview)", category="page")
    section = "Workspace"
    icon = "reports"
    order = 32
    min_role = Role.READ_ONLY

    def render(self, shell) -> None:  # noqa: ANN001
        st.title("Report Studio (Preview)")
        st.caption("Phase A — architecture proof (Konva editor). The classic Report "
                   "Studio remains available and unchanged.")

        doc = _current_doc()

        # ---- mount the React+Konva editor and receive edits back -------------
        value = _get_component()(document=doc, key="report_studio_v2", default=None)
        if isinstance(value, dict) and isinstance(value.get("document"), dict):
            ts = value.get("ts")
            if ts != st.session_state.get(_S_TS):        # dedupe re-delivered values
                st.session_state[_S_TS] = ts
                st.session_state[_S_DOC] = adapter.normalize(value["document"])
                doc = st.session_state[_S_DOC]

        # ---- save / load foundation (via the engine-independent adapter) -----
        c1, c2, c3, c4 = st.columns(4)
        if c1.button("Save", key="rs2_save"):
            rd = adapter.to_report_document(doc, report_id=doc.get("id"), title=doc.get("title"))
            st.session_state[_S_SAVED] = rd.to_dict()
            _persist_if_possible(shell, rd)
            st.success("Saved.")
        if c2.button("Load last save", key="rs2_load", disabled=_S_SAVED not in st.session_state):
            saved = st.session_state.get(_S_SAVED)
            if saved:
                st.session_state[_S_DOC] = adapter.from_report_document(ReportDocument.from_dict(saved))
                st.rerun()
        if c3.button("New", key="rs2_new"):
            st.session_state[_S_DOC] = adapter.new_document()
            st.session_state.pop(_S_TS, None)
            st.rerun()
        c4.metric("Pages / Elements", f"{len(doc['pages'])} / "
                  f"{sum(len(p.get('elements', [])) for p in doc['pages'])}")

        with st.expander("Engine-independent document (JSON)"):
            st.json(doc)


def _persist_if_possible(shell, rd: ReportDocument) -> None:
    """Best-effort: if the reports engine is available and a report is open,
    persist through the UNCHANGED ReportsManager path. Otherwise the session-state
    save above is the Phase-A persistence foundation. Never raises."""
    try:
        reports = getattr(getattr(shell, "platform", None), "reports", None)
        open_id = st.session_state.get("open_report_id") if hasattr(st, "session_state") else None
        if reports is not None and open_id and reports.get(open_id) is not None:
            reports.save(open_id, rd.to_dict())          # unchanged manager API
    except Exception:
        pass


# Feature flag gate: register the page ONLY when v2 is enabled. When off, the
# class still exists (importable by tests) but never appears in navigation.
if adapter.v2_enabled():
    page_registry.register(ReportStudioV2Page)
