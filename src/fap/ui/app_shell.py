"""The professional application shell (Phase 3C, Phase 5.1 integration).

Top header · left navigation · main content · status bar. The shell owns the
chrome and the professional theme (fap.theme); it dispatches to the active Page
and never touches the visualization engine - the Open Play screen is just
another page whose renderer app.py injects.

The platform accessors are injected by app.py (no ``import app`` here, which
would be circular because Streamlit runs app.py as ``__main__``). Only
``render_shell`` and the ``_render_*`` helpers touch Streamlit; the navigation
model (fap.ui.page) and the theme (fap.theme) are pure and unit-tested. This is
a NEW shell, separate from the legacy fap.ui.shell (left untouched).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import streamlit as st

from fap import theme
from fap.core.version import platform_version
from fap.identity import logout, require_login
from fap.identity.models import User
from fap.theme import components as C
from fap.theme import icon
from fap.ui.page import (
    default_page_id, get_page, load_builtin_pages, register_renderer,
    visible_by_section, visible_pages,
)

_ACTIVE = "_active_page"
_WORKSPACE = "_active_workspace"
_PROJECT = "_active_project"

# injected by app.py so the shell never imports app (circular)
_platform_getter: "Callable[[], Any] | None" = None
_wm_getter: "Callable[[], Any] | None" = None


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
def render_shell(open_play_renderer: Callable[[], None] | None = None, *,
                 platform_getter: "Callable[[], Any] | None" = None,
                 wm_getter: "Callable[[], Any] | None" = None) -> None:
    """Render the whole application: apply the theme, gate on identity, then
    header + nav + active page + status bar. ``open_play_renderer`` is app.py's
    run_app, injected as the Opponent Analysis page body; the platform/wm
    getters are injected so the shell never imports app."""
    global _platform_getter, _wm_getter
    if open_play_renderer is not None:
        register_renderer("opponent_analysis", open_play_renderer)
    if platform_getter is not None:
        _platform_getter = platform_getter
    if wm_getter is not None:
        _wm_getter = wm_getter

    brand = _branding()
    theme.apply(brand, theme.resolve_mode(st.session_state.get("_theme_mode"), brand))

    # Login page: not signed in -> show both brand logos centered above the
    # sign-in controls (dev mode short-circuits current_user, so this is skipped).
    from fap.identity import current_user
    if current_user() is None:
        _render_login_branding(brand)
    user = require_login()
    st.session_state["_in_shell"] = True
    load_builtin_pages()

    platform, wm = _resolve_services()
    active = _resolve_active_page(user)
    ctx = ShellContext(user=user, platform=platform, wm=wm, active_page_id=active)

    _render_header(ctx, brand)
    _render_sidebar(ctx, brand)

    page = get_page(active)
    if page is not None:
        page.render(ctx)                 # only the active page initializes (lazy)
    else:
        st.info("Select a page from the navigation.")

    _render_status_bar(ctx)


# ---------------------------------------------------------------- helpers
def _branding() -> theme.Branding:
    # Reading secrets is soft: with no secrets.toml Streamlit raises
    # StreamlitSecretNotFoundError (a FileNotFoundError subclass), which must NOT
    # be treated as a missing-asset failure - fall back to the default brand.
    # Missing *asset* files still fail loudly, but that happens at render time
    # (logo_html), surfaced there as a visible error.
    try:
        cfg = dict(st.secrets.get("branding", {}) or {})
    except Exception:
        cfg = {}
    return theme.load_branding(cfg)


def _logo_pair_html(brand: theme.Branding, height: int) -> str:
    """FC Masar × Right To Dream, side by side. Raises loudly on a missing asset
    (never silently falls back to generic branding)."""
    club = C.logo_html(brand.primary_logo, height=height, alt=brand.club_name)
    org = C.logo_html(brand.secondary_logo, height=height, alt=brand.organization_name)
    return f'<span class="fap-logos">{club}<span class="sep">·</span>{org}</span>'


def _render_login_branding(brand: theme.Branding) -> None:
    try:
        logos = _logo_pair_html(brand, height=76)
    except FileNotFoundError as exc:
        st.error(f"Branding asset missing: {exc}")
        return
    st.markdown(
        f'<div class="fap-login">{logos}'
        f'<h2>{brand.platform_name}</h2>'
        f'<div class="powered">{brand.tagline}</div></div>',
        unsafe_allow_html=True)


def _resolve_services() -> tuple[Any, Any]:
    platform = _platform_getter() if _platform_getter else None
    wm = _wm_getter() if _wm_getter else None
    return platform, wm


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


def _active_page_meta(page_id: str):
    return get_page(page_id)


def _render_header(ctx: ShellContext, brand: theme.Branding) -> None:
    org = _org_context()
    page = _active_page_meta(ctx.active_page_id)
    crumbs = [brand.club_name if org.get("club") else "", org.get("season", ""),
              org.get("competition", ""), org.get("opponent", "")]
    crumbs = [c for c in crumbs if c] or [brand.organization_name]
    if page is not None:
        crumbs.append(page.info.name)

    notifications = st.session_state.get("_notifications", [])
    try:
        logos = _logo_pair_html(brand, height=34)
    except FileNotFoundError as exc:
        st.error(f"Branding asset missing: {exc}")
        logos = ""
    page_glyph = icon(page.icon, 18) if page and page.icon else ""
    # One sticky flex header owns the top and stays put on scroll: logos +
    # breadcrumb on the left, notifications + user badge on the right.
    st.markdown(
        f'<header class="fap-shell-header">'
        f'  <div class="left">{logos}'
        f'    <div class="titles"><b>{brand.platform_name}</b>'
        f'      <span class="crumbs">{page_glyph} {C.breadcrumb_html(crumbs)}</span>'
        f'    </div>'
        f'  </div>'
        f'  <div class="right">{icon("bell", 16)} {len(notifications)}'
        f'    <span class="sep">·</span> {icon("user", 16)} <b>{ctx.user.name}</b>'
        f'    {C.badge_html(ctx.user.role_label, "info")}</div>'
        f'</header>',
        unsafe_allow_html=True)


def _render_sidebar(ctx: ShellContext, brand: theme.Branding) -> None:
    with st.sidebar:
        try:
            logos = _logo_pair_html(brand, height=40)
        except FileNotFoundError as exc:
            st.error(f"Branding asset missing: {exc}")
            logos = ""
        st.markdown(f'<div class="fap-brandbar">{logos}</div>'
                    f'<div class="fap-brand"><b>{brand.platform_name}</b></div>',
                    unsafe_allow_html=True)

        if ctx.wm is not None:
            _workspace_and_project_selectors(ctx)

        query = st.text_input("Search", key="_global_search",
                              placeholder="players, teams, datasets, projects…",
                              label_visibility="collapsed")
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
        st.write(f"**{hit.name}** · _{hit.type}_" + (f" · {hit.context}" if hit.context else ""))


def _render_navigation(ctx: ShellContext) -> None:
    for section, pages in visible_by_section(ctx.user.role).items():
        st.markdown(f'<div class="fap-nav-section">{section}</div>', unsafe_allow_html=True)
        for page in pages:
            active = page.info.id == ctx.active_page_id
            # Streamlit buttons render text only; the active page is highlighted
            # via the primary style and the registry icon appears in the header.
            if st.button(page.info.name, key=f"nav_{page.info.id}",
                         use_container_width=True,
                         type="primary" if active else "secondary"):
                ctx.goto(page.info.id)


def _render_profile(ctx: ShellContext) -> None:
    with st.expander("Account", expanded=False):
        st.markdown(
            f'{icon("user", 16)} **{ctx.user.name}**  \n{ctx.user.email}  \n'
            f'{C.badge_html(ctx.user.role_label, "info")}'
            + (f' · {ctx.user.organization}' if ctx.user.organization else ''),
            unsafe_allow_html=True)
        if st.button("Settings", key="profile_settings", use_container_width=True):
            ctx.goto("settings")
        if st.button("Sign out", key="profile_signout", use_container_width=True):
            logout()
            st.rerun()


def _render_status_bar(ctx: ShellContext) -> None:
    provider = st.session_state.get("_status_provider", "—")
    dataset = st.session_state.get("_status_dataset", "—")
    ws_name = "—"
    try:
        if ctx.wm and ctx.workspace_id:
            ws_name = next((w.name for w in ctx.wm.list_workspaces()
                            if w.id == ctx.workspace_id), "—")
    except Exception:
        pass
    connection = C.badge_html("online", "success", icon_name="check")
    st.markdown(
        C.footer_html([
            ("Provider", provider), ("Dataset", dataset), ("Workspace", ws_name),
            ("User", ctx.user.name), ("Version", _short_version()),
        ]).replace("</div>", f"<span>{connection}</span></div>"),
        unsafe_allow_html=True)


def _short_version() -> str:
    try:
        return platform_version().split("+")[0]
    except Exception:
        return "?"
