"""Dashboard — the football intelligence command center.

A landing overview built entirely from REAL workspace data (datasets, projects,
reports, recent activity). It reuses the theme component library (hero, metric
cards, action cards, recent rows) — no page-local CSS, no fabricated metrics.
Navigation stays in-session via ``shell.goto`` (the existing routing).
"""
from __future__ import annotations

import datetime as _dt

import streamlit as st

from fap.core.plugin import PluginInfo
from fap.identity.roles import Role
from fap.theme import components as C
from fap.ui.page import Page, get_page, page_registry, visible_pages

# Modules offered as "Start analysis" launchers — shown only when the page exists
# and the user's role can see it (no invented modules).
_ACTIONS = [
    ("opponent_analysis", "Scouting", "Build an evidence-backed opposition profile.", "target"),
    ("open_play_studio", "Open Play Studio", "Explore open-play behaviour and tactical patterns.", "analysis"),
    ("set_piece_analysis", "Set Piece Analysis", "Analyse attacking and defensive set pieces.", "flag"),
    ("tactical_board", "Tactical Board", "Build and review tactical scenarios.", "teams"),
]


@page_registry.register
class DashboardPage(Page):
    info = PluginInfo(id="dashboard", name="Dashboard", category="page")
    section = "Overview"
    icon = "dashboard"
    order = 0
    min_role = Role.READ_ONLY

    def render(self, shell) -> None:
        first = shell.user.name.split()[0] if shell.user.name else "there"

        if shell.wm is None:
            C.render_hero(f"{_greeting()}, {first}", "Your football intelligence workspace.",
                          eyebrow="Overview")
            C.render_alert("Platform services are unavailable in this session.", "warning",
                           title="Limited mode")
            return

        datasets, projects, recents, audit, reports_n, ws_name, ds_name = _gather(shell)

        # ---- greeting hero with live context ----
        C.render_hero(
            f"{_greeting()}, {first}", "Your football intelligence workspace.", eyebrow="Overview",
            context=[("Workspace", ws_name), ("Active dataset", ds_name),
                     ("Today", _dt.date.today().strftime("%A %d %B %Y"))])

        # ---- primary analysis: the module entry points come first (analyst-led) ----
        actions = [(pid, t, d, ic) for pid, t, d, ic in _ACTIONS if _can_open(shell, pid)]
        if actions:
            st.markdown('<div class="fap-dash-h">Primary analysis</div>', unsafe_allow_html=True)
            cols = st.columns(len(actions), gap="small")
            for col, (pid, title, desc, ic) in zip(cols, actions):
                with col:
                    _action_card(shell, pid, title, desc, ic)

        # ---- workspace snapshot (real figures) ----
        st.markdown('<div class="fap-dash-h">Workspace snapshot</div>', unsafe_allow_html=True)
        metrics = [
            C.metric_card_html("Datasets", f"{len(datasets)}", icon_name="datasets",
                               accent="primary", hint="in this workspace"),
            C.metric_card_html("Projects", f"{len(projects)}", icon_name="projects",
                               accent="info", hint="in this workspace"),
        ]
        if reports_n is not None:
            metrics.append(C.metric_card_html("Reports", f"{reports_n}", icon_name="reports",
                                              accent="success", hint="created"))
        metrics.append(C.metric_card_html("Recent items", f"{len(recents)}", icon_name="clock",
                                          accent="warning", hint="you touched lately"))
        C.render_metric_row(metrics)

        # ---- recent analysis + activity ----
        left, right = st.columns([3, 2], gap="medium")
        with left:
            st.markdown('<div class="fap-dash-h">Recent analysis</div>', unsafe_allow_html=True)
            items = _recent_items(shell, datasets)
            if not items:
                C.render_empty_state("No recent analysis yet", "Modules and datasets you open will "
                                     "appear here for quick access.", icon_name="clock")
            else:
                for i, (name, meta, ic, target) in enumerate(items):
                    with st.container(key=f"dash_recent_{i}"):
                        st.markdown(C.recent_row_html(name, meta, icon_name=ic), unsafe_allow_html=True)
                        if st.button(name, key=f"dashrec_{i}", use_container_width=True):
                            shell.goto(target)
        with right:
            st.markdown('<div class="fap-dash-h">Recent activity</div>', unsafe_allow_html=True)
            if not audit:
                C.render_empty_state("No activity yet", "Actions across the platform are logged here.",
                                     icon_name="list")
            else:
                rows = "".join(
                    f'<div class="fap-activity-row"><code>{e.action}</code>'
                    f'<span class="who">{e.actor or "system"}</span>'
                    f'<span class="ts">{e.ts}</span></div>'
                    for e in audit)
                st.markdown(f'<div class="fap-card fap-activity">{rows}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------- helpers
def _greeting() -> str:
    h = _dt.datetime.now().hour
    return "Good morning" if h < 12 else "Good afternoon" if h < 18 else "Good evening"


def _gather(shell):
    """Collect the real workspace figures once, each guarded independently."""
    def safe(fn, default):
        try:
            return fn()
        except Exception:
            return default

    datasets = safe(lambda: shell.wm.list_datasets(workspace_id=shell.workspace_id), [])
    projects = safe(lambda: shell.wm.list_projects(shell.workspace_id), []) if shell.workspace_id else []
    recents = safe(lambda: shell.wm.recents(shell.user), [])
    audit = safe(lambda: shell.wm.audit_trail(limit=6), [])
    reports_svc = getattr(getattr(shell, "platform", None), "reports", None)
    reports_n = None
    if reports_svc is not None:
        reports_n = len(safe(lambda: reports_svc.list(shell.user, workspace_id=shell.workspace_id), []))
    # active dataset + workspace names for the hero context
    ds = safe(lambda: shell.wm.active_dataset(shell.user), None)
    ds_name = ds.name if ds is not None else "None selected"
    ws_name = "—"
    if shell.workspace_id:
        ws_name = safe(lambda: next((w.name for w in shell.wm.list_workspaces()
                                     if w.id == shell.workspace_id), "—"), "—")
    return datasets, projects, recents, audit, reports_n, ws_name, ds_name


def _can_open(shell, page_id: str) -> bool:
    if get_page(page_id) is None:
        return False
    try:
        return page_id in {p.info.id for p in visible_pages(shell.user.role)}
    except Exception:
        return True


def _action_card(shell, page_id: str, title: str, desc: str, icon_name: str) -> None:
    """A full-card click target: the visible action card + an invisible full-cover
    button (styled by the theme) so the whole surface navigates in-session."""
    with st.container(key=f"dash_action_{page_id}"):
        st.markdown(C.action_card_html(title, desc, icon_name=icon_name), unsafe_allow_html=True)
        # the button's element container (st-key-dashbtn_*) is absolutely positioned over
        # the card by the theme CSS, so the whole card is the click target with no visible
        # native button surface (see css._dashboard).
        if st.button(title, key=f"dashbtn_{page_id}", use_container_width=True):
            shell.goto(page_id)


def _recent_items(shell, datasets) -> list[tuple[str, str, str, str]]:
    """Map the workspace's recent touches to clickable rows (name, meta, icon, target
    page). Skips the dashboard itself and anything that no longer resolves."""
    try:
        recents = shell.wm.recents(shell.user, limit=16)
    except Exception:
        recents = []
    ds_names = {getattr(d, "id", ""): getattr(d, "name", "") for d in (datasets or [])}
    out: list[tuple[str, str, str, str]] = []
    for ttype, tid in recents:
        if ttype == "page":
            if tid == "dashboard":
                continue
            p = get_page(tid)
            if p is not None:
                out.append((p.info.name, "Module", p.icon or "analysis", tid))
        elif ttype == "dataset":
            out.append((ds_names.get(tid) or "Dataset", "Dataset", "datasets", "data_hub"))
        elif ttype == "project":
            out.append(("Project", "Project", "projects", "projects"))
        if len(out) >= 6:
            break
    return out
