"""Dashboard — the football intelligence command center.

A landing overview built entirely from REAL workspace data (datasets, projects,
reports, recent activity). It reuses the theme component library (hero, metric
cards, action cards, recent rows) — no page-local CSS, no fabricated metrics.
Navigation stays in-session via ``shell.goto`` (the existing routing).
"""
from __future__ import annotations

import datetime as _dt
import html as _html

import streamlit as st

from fap.core.plugin import PluginInfo
from fap.identity.roles import Role
from fap.theme import components as C
from fap.ui.page import HIDDEN_PAGE_IDS, Page, get_page, page_registry, visible_pages

# Modules offered as "Start analysis" launchers — shown only when the page exists
# and the user's role can see it (no invented modules).
_ACTIONS = [
    ("scouting", "Scouting", "Player identification, evaluation and recruitment analysis.", "scouting"),
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

        datasets, _projects, recents, audit, reports_n, ws_name, ds_name = _gather(shell)

        # ---- greeting hero with live context ----
        C.render_hero(
            f"{_greeting()}, {first}", "Your football intelligence workspace.", eyebrow="Overview",
            context=[("Workspace", ws_name), ("Active dataset", ds_name),
                     ("Today", _dt.date.today().strftime("%A %d %B %Y"))])

        # ---- intelligence snapshot (real figures only) ----
        st.markdown('<div class="fap-dash-h">Intelligence snapshot</div>', unsafe_allow_html=True)
        metrics = [
            C.metric_card_html("Datasets", f"{len(datasets)}", icon_name="datasets",
                               accent="primary", hint="in this workspace"),
        ]
        if reports_n is not None:
            metrics.append(C.metric_card_html("Reports", f"{reports_n}", icon_name="reports",
                                              accent="success", hint="created"))
        scouted = _scouted_count(shell)
        if scouted is not None:
            metrics.append(C.metric_card_html("Scouted players", f"{scouted}", icon_name="scouting",
                                              accent="warning", hint="in the registry"))
        C.render_metric_row(metrics)

        # ---- primary workflows: professional entry points into the analysis modules ----
        actions = [(pid, t, d, ic) for pid, t, d, ic in _ACTIONS if _can_open(shell, pid)]
        if actions:
            st.markdown('<div class="fap-dash-h">Primary workflows</div>', unsafe_allow_html=True)
            per_row = 3
            for start in range(0, len(actions), per_row):
                chunk = actions[start:start + per_row]
                cols = st.columns(per_row, gap="small")
                for col, (pid, title, desc, ic) in zip(cols, chunk):
                    with col:
                        _action_card(shell, pid, title, desc, ic)

        # ---- current workspace: the active dataset in context (no recent-activity feed) ----
        st.markdown('<div class="fap-dash-h">Current workspace</div>', unsafe_allow_html=True)
        self._current_workspace(shell)


    def _current_workspace(self, shell) -> None:
        """The active dataset in context — a clean detail list, not a wall of cards.
        Only real fields are shown; nothing is fabricated. Polished empty state when
        no dataset is active."""
        ds = None
        try:
            ds = shell.wm.active_dataset(shell.user) if shell.wm is not None else None
        except Exception:
            ds = None
        if ds is None:
            if C.render_empty_state(
                    "No active dataset", "Import and activate a dataset in the Data Hub to begin — "
                    "its type, competition, players and data quality will appear here.",
                    icon_name="datasets", action_label="Open Data Hub", key="dash_ws_empty"):
                shell.goto("data_hub")
            return
        doc = ds.document if isinstance(getattr(ds, "document", None), dict) else {}
        summary = doc.get("scouting_summary") if isinstance(doc.get("scouting_summary"), dict) else {}
        dtype = doc.get("dataset_type") or ("player scouting" if summary else "event")
        rows: list[tuple[str, str]] = [("Dataset", ds.name),
                                       ("Type", str(dtype).replace("_", " ").title())]
        comp = ds.competition or summary.get("competition") or ""
        if comp:
            rows.append(("Competition", comp))
        if summary:                                         # player-scouting dataset
            if summary.get("entity_count"):
                rows.append(("Players", f"{summary['entity_count']:,}"))
            if summary.get("teams"):
                rows.append(("Teams", f"{summary['teams']:,}"))
            if summary.get("metric_count"):
                rows.append(("Metrics", f"{summary['metric_count']:,}"))
        elif isinstance(getattr(ds, "rows", None), int) and ds.rows:
            rows.append(("Rows", f"{ds.rows:,}"))
        q = doc.get("quality")
        rating = doc.get("quality_rating") or summary.get("grade") or ""
        if isinstance(q, (int, float)):
            rows.append(("Data quality", f"{q:.0f}/100" + (f" · {rating}" if rating else "")))
        elif rating:
            rows.append(("Data quality", str(rating)))
        detail = "".join(
            f'<div class="fap-kv"><span class="fap-kv-k">{_html.escape(str(k))}</span>'
            f'<span class="fap-kv-v">{_html.escape(str(v))}</span></div>' for k, v in rows)
        st.markdown(f'<div class="fap-card fap-ws-detail">{detail}</div>', unsafe_allow_html=True)
        if st.button("Open in Data Hub", key="dash_ws_open"):
            shell.goto("data_hub")


# ---------------------------------------------------------------- helpers
def _scouted_count(shell):
    """Real scouted-player count, or None when the scouting service is unavailable."""
    svc = getattr(getattr(shell, "platform", None), "scouting", None)
    if svc is None:
        return None
    try:
        return svc.players.count(archived=False)
    except Exception:
        return None


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
            if tid == "dashboard" or tid in HIDDEN_PAGE_IDS:
                continue
            p = get_page(tid)
            if p is not None:
                out.append((p.info.name, "Module", p.icon or "analysis", tid))
        elif ttype == "dataset":
            out.append((ds_names.get(tid) or "Dataset", "Dataset", "datasets", "data_hub"))
        elif ttype == "project":
            continue
        if len(out) >= 6:
            break
    return out
