"""The professional application shell (Phase 3C).

Top header · left navigation · main content · status bar. The shell owns the
chrome and dispatches to the active Page; pages own their content. It wraps the
existing platform (identity, workspaces, importer) and never touches the
visualization engine - the Open Play screen is just another page whose renderer
app.py injects.

Only ``render_shell`` and the private ``_render_*`` helpers touch Streamlit; the
navigation model (fap.ui.page) is pure and unit-tested. This is a NEW shell,
separate from the legacy fap.ui.shell (which is left untouched).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import streamlit as st

from fap.core.version import platform_version
from fap.identity import logout, require_login
from fap.identity.models import User
from fap.ui.page import (
    default_page_id, get_page, load_builtin_pages, register_renderer,
    visible_by_section, visible_pages,
)

_ACTIVE = "_active_page"
_WORKSPACE = "_active_workspace"
_PROJECT = "_active_project"


@dataclass(slots=True)
class ShellContext:
    """What a page receives: the signed-in user, the platform, the workspace
    manager, and navigation helpers - so pages never reach for globals."""
    user: User
    platform: Any
    wm: Any
    active_page_id: str

    def goto(self, page_id: str) -> None:
        st.session_state[_ACTIVE] = page_id
        st.rerun()

    @property
    def workspace_id(self) -> str | None:
        return st.session_state.get(_WORKSPACE)

    @property
    def project_id(self) -> str | None:
        return st.session_state.get(_PROJECT)

    def search(self, query: str) -> list[Any]:
        try:
            return self.wm.search(query, workspace_id=self.workspace_id)
        except Exception:
            return []


# ---------------------------------------------------------------- entry point
def render_shell(open_play_renderer: Callable[[], None] | None = None) -> None:
    """Render the whole application: gate on identity, then header + nav +
    active page + status bar. ``open_play_renderer`` is app.py's run_app,
    injected as the Opponent Analysis page body (no circular import)."""
    if open_play_renderer is not None:
        register_renderer("opponent_analysis", open_play_renderer)

    user = require_login()
    st.session_state["_in_shell"] = True
    load_builtin_pages()

    platform, wm = _platform_and_wm()
    active = _resolve_active_page(user)
    ctx = ShellContext(user=user, platform=platform, wm=wm, active_page_id=active)

    _render_header(ctx)
    _render_sidebar(ctx)

    page = get_page(active)
    if page is not None:
        page.render(ctx)                 # only the active page initializes (lazy)
    else:
        st.info("Select a page from the navigation.")

    _render_status_bar(ctx)


# ---------------------------------------------------------------- helpers
def _platform_and_wm() -> tuple[Any, Any]:
    try:
        import app                       # app.py owns the cached platform accessor
        return app.platform(), app.workspace_manager()
    except Exception:
        return None, None


def _resolve_active_page(user: User) -> str:
    active = st.session_state.get(_ACTIVE) or default_page_id(user.role)
    allowed = {p.info.id for p in visible_pages(user.role)}
    if active not in allowed:            # role changed or stale selection -> default
        active = default_page_id(user.role)
    st.session_state[_ACTIVE] = active
    return active


def _org_context() -> dict[str, str]:
    ctx = st.session_state.get("_org_context")
    return ctx if isinstance(ctx, dict) else {}


def _render_header(ctx: ShellContext) -> None:
    org = _org_context()
    left, right = st.columns([3, 1])
    with left:
        crumbs = " › ".join(v for v in (
            org.get("club", ""), org.get("season", ""), org.get("competition", ""),
            org.get("opponent", "")) if v) or "No club selected"
        st.markdown(f"#### {crumbs}")
        project = st.session_state.get("_active_project_name", "")
        if project:
            st.caption(f"Project: {project}")
    with right:
        notifications = st.session_state.get("_notifications", [])
        st.markdown(f"🔔 {len(notifications)}  ·  **{ctx.user.name}**  \n{ctx.user.role_label}")
    st.divider()


def _render_sidebar(ctx: ShellContext) -> None:
    with st.sidebar:
        st.markdown("### ⚽ FAP Platform")
        if ctx.wm is not None:
            _workspace_and_project_selectors(ctx)

        query = st.text_input("🔎 Search", key="_global_search",
                              placeholder="players, teams, datasets, projects…")
        if query.strip():
            _render_search_results(ctx, query)

        st.divider()
        _render_navigation(ctx)
        st.divider()
        _render_profile(ctx)


def _workspace_and_project_selectors(ctx: ShellContext) -> None:
    try:
        workspaces = ctx.wm.list_workspaces()
        if not workspaces:
            ctx.wm.ensure_workspace(ctx.user)
            workspaces = ctx.wm.list_workspaces()
        names = {w.id: w.name for w in workspaces}
        ids = list(names)
        if not ids:
            return
        current = ctx.workspace_id if ctx.workspace_id in names else ids[0]
        chosen = st.selectbox("Workspace", ids, index=ids.index(current),
                              format_func=lambda i: names[i])
        st.session_state[_WORKSPACE] = chosen
        projects = ctx.wm.list_projects(chosen)
        if projects:
            pnames = {p.id: p.name for p in projects}
            pid = st.selectbox("Project", ["—", *pnames],
                               format_func=lambda i: "— none —" if i == "—" else pnames[i])
            if pid != "—":
                st.session_state[_PROJECT] = pid
                st.session_state["_active_project_name"] = pnames[pid]
                ctx.wm.touch_recent(ctx.user, "project", pid)
    except Exception:
        st.caption("Workspace unavailable.")


def _render_search_results(ctx: ShellContext, query: str) -> None:
    hits = ctx.search(query)
    if not hits:
        st.caption("No matches.")
        return
    st.caption(f"{len(hits)} result(s)")
    for hit in hits[:12]:
        st.write(f"• **{hit.name}** · _{hit.type}_" + (f" · {hit.context}" if hit.context else ""))


def _render_navigation(ctx: ShellContext) -> None:
    for section, pages in visible_by_section(ctx.user.role).items():
        st.caption(section.upper())
        for page in pages:
            if st.button(f"{page.icon}  {page.info.name}", key=f"nav_{page.info.id}",
                         use_container_width=True,
                         type="primary" if page.info.id == ctx.active_page_id else "secondary"):
                ctx.goto(page.info.id)


def _render_profile(ctx: ShellContext) -> None:
    with st.expander(f"👤 {ctx.user.name}", expanded=False):
        st.caption(f"{ctx.user.email}\n\n**{ctx.user.role_label}**"
                   + (f" · {ctx.user.organization}" if ctx.user.organization else ""))
        if st.button("Settings", key="profile_settings", use_container_width=True):
            ctx.goto("settings")
        if st.button("Sign out", key="profile_signout", use_container_width=True):
            logout()
            st.rerun()


def _render_status_bar(ctx: ShellContext) -> None:
    st.divider()
    provider = st.session_state.get("_status_provider", "—")
    dataset = st.session_state.get("_status_dataset", "—")
    ws_name = "—"
    try:
        if ctx.wm and ctx.workspace_id:
            ws_name = next((w.name for w in ctx.wm.list_workspaces()
                            if w.id == ctx.workspace_id), "—")
    except Exception:
        pass
    cols = st.columns(6)
    cols[0].caption(f"Provider: **{provider}**")
    cols[1].caption(f"Dataset: **{dataset}**")
    cols[2].caption(f"Workspace: **{ws_name}**")
    cols[3].caption(f"User: **{ctx.user.name}**")
    cols[4].caption(f"Version: **{_short_version()}**")
    cols[5].caption("Connection: **online** 🟢")


def _short_version() -> str:
    try:
        return platform_version().split("+")[0]
    except Exception:
        return "?"
