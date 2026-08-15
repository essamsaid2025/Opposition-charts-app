"""The professional application shell (Phase 3C · Phase 5.1 · Phase 13.1).

A fixed navigation rail + a top header + main content + a slim status bar. Phase
13.1 replaces Streamlit's native sidebar with a fixed rail whose clickable items
are REAL ``st.button`` widgets (styled by ``fap.theme.css`` to look like a desktop
rail). Navigation is fully IN-SESSION: a button click runs a Python ``on_click``
callback that sets ``st.session_state["_active_page"]`` and lets Streamlit rerun in
the same session - it uses NO browser navigation, NO URL/query-param change, and NO
window scripting, so the session (workspace, active dataset, players, reports) is
never recreated. Routing reuses the existing ``page_registry`` and the
``ShellContext.goto`` semantics; there is no second registry. Collapse, theme and
pin are the same in-session button pattern, persisted per-user through the existing
``WorkspaceManager`` autosave/recents - never browser storage.

The platform accessors are injected by app.py (no ``import app`` here, which would
be circular). Only ``render_shell`` and the ``_render_*`` helpers touch Streamlit;
the navigation model (fap.ui.page), the presentation builders (fap.ui.nav) and the
theme (fap.theme) are pure and unit-tested.
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
from fap.ui import nav
from fap.ui.page import (
    default_page_id, get_page, load_builtin_pages, register_renderer,
    visible_by_section, visible_pages,
)

_ACTIVE = "_active_page"
_WORKSPACE = "_active_workspace"
_PROJECT = "_active_project"

# per-user persisted shell state (WorkspaceManager autosave scopes - never localStorage)
_SHELL_SCOPE = "shell_ui"          # {"collapsed": bool}
_FAV_SCOPE = "nav_favorites"       # {"pages": [page_id, ...]}

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
        _record_recent(self, page_id)
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
    """Render the whole application: theme, identity gate, then a fixed nav rail +
    header + active page + status bar. ``open_play_renderer`` is app.py's run_app,
    injected as the Opponent Analysis page body; platform/wm getters are injected
    so the shell never imports app."""
    global _platform_getter, _wm_getter
    if open_play_renderer is not None:
        register_renderer("opponent_analysis", open_play_renderer)
    if platform_getter is not None:
        _platform_getter = platform_getter
    if wm_getter is not None:
        _wm_getter = wm_getter

    from fap.identity import enterprise
    enterprise.bind(lambda: _platform_getter() if _platform_getter else None)

    base_brand = _branding()
    preset_id = st.session_state.get("_theme_preset") or theme.DEFAULT_PRESET_ID
    brand = theme.branding_for(preset_id, base_brand)
    # ONE fixed application identity: an always-light workspace (the dark navigation
    # rail is skinned independently in fap.theme.css). No application light/dark
    # switching — chart visualization themes are separate and untouched.
    theme.apply(brand, "light")

    from fap.identity import current_user
    if current_user() is None:
        _render_login_branding(brand)
    user = require_login()
    st.session_state["_in_shell"] = True
    load_builtin_pages()

    platform, wm = _resolve_services()
    ctx = ShellContext(user=user, platform=platform, wm=wm, active_page_id="")

    # Load persisted shell state (collapse + favorites) ONCE per session into
    # session_state, which is then the in-session source of truth. All navigation
    # below is IN-SESSION only: st.button widgets mutate session_state and trigger
    # the normal Streamlit rerun - no href, no query params, no browser navigation,
    # so the session (workspace, dataset, players, reports) is never recreated.
    _ensure_shell_loaded(ctx)

    active = _resolve_active_page(user)
    ctx.active_page_id = active
    # record 'recent' when the active page actually changed (the button callback set it)
    if st.session_state.get("_last_recorded_active") != active:
        _record_recent(ctx, active)
        st.session_state["_last_recorded_active"] = active

    collapsed = _is_collapsed()
    # per-run width variable -> the collapse animates via the CSS width transition
    st.markdown(f'<style>:root{{--fap-rail-width:'
                f'{"var(--fap-rail-collapsed)" if collapsed else "var(--fap-rail-expanded)"}}}</style>',
                unsafe_allow_html=True)

    _render_rail(ctx, brand, collapsed)
    _render_header(ctx, brand, collapsed)
    _render_controls_bar(ctx, brand)

    page = get_page(active)
    if page is not None:
        page.render(ctx)                 # only the active page initializes (lazy)
    else:
        C.render_alert("Select a page from the navigation.", "info")

    _render_status_bar(ctx)
    # durably mirror the in-session shell state to the WorkspaceManager (only writes
    # when it changed) so a genuine reopen restores it - never browser storage.
    _persist_shell_state(ctx)


# ---------------------------------------------------------------- in-session state + callbacks
def _ensure_shell_loaded(ctx: "ShellContext") -> None:
    """Load persisted collapse + favorites into session_state once per session."""
    if st.session_state.get("_shell_loaded"):
        return
    st.session_state.setdefault(
        "_rail_collapsed", bool(_load_scope(ctx, _SHELL_SCOPE).get("collapsed", False)))
    st.session_state.setdefault(
        "_favorites", [str(x) for x in (_load_scope(ctx, _FAV_SCOPE).get("pages") or [])])
    st.session_state["_shell_loaded"] = True


def _is_collapsed() -> bool:
    return bool(st.session_state.get("_rail_collapsed", False))


def _favorites() -> list[str]:
    return [str(x) for x in st.session_state.get("_favorites", [])]


def _persist_shell_state(ctx: "ShellContext") -> None:
    """Write shell state to the WorkspaceManager ONLY when it changed this session
    (avoids redundant writes). Session-only fallback handled by _save_scope."""
    want = {"collapsed": _is_collapsed(), "pages": _favorites()}
    if st.session_state.get("_shell_persisted") == want:
        return
    _save_scope(ctx, _SHELL_SCOPE, {"collapsed": want["collapsed"]})
    _save_scope(ctx, _FAV_SCOPE, {"pages": want["pages"]})
    st.session_state["_shell_persisted"] = want


# button callbacks: mutate session_state IN-SESSION; Streamlit reruns automatically.
# No st.rerun() needed (the widget triggers one), no navigation of any kind.
def _cb_set_active(page_id: str) -> None:
    st.session_state[_ACTIVE] = page_id


def _cb_toggle_collapse() -> None:
    st.session_state["_rail_collapsed"] = not bool(st.session_state.get("_rail_collapsed", False))


def _cb_toggle_theme() -> None:
    st.session_state["_theme_mode"] = "light" if st.session_state.get("_theme_mode") == "dark" else "dark"


def _cb_toggle_fav(page_id: str) -> None:
    favs = _favorites()
    favs.remove(page_id) if page_id in favs else favs.append(page_id)
    st.session_state["_favorites"] = favs


def _record_recent(ctx: "ShellContext", page_id: str) -> None:
    if ctx.wm is None:
        recents = [x for x in st.session_state.get("_recent_pages", []) if x != page_id]
        st.session_state["_recent_pages"] = [page_id, *recents][:10]
        return
    try:
        ctx.wm.touch_recent(ctx.user, "page", page_id)
    except Exception:
        pass


def _recent_page_ids(ctx: "ShellContext") -> list[str]:
    if ctx.wm is None:
        return list(st.session_state.get("_recent_pages", []))
    try:
        return [tid for (ttype, tid) in ctx.wm.recents(ctx.user, limit=30) if ttype == "page"]
    except Exception:
        return []


def _load_scope(ctx: "ShellContext", scope: str) -> dict:
    if ctx.wm is None:
        return dict(st.session_state.get(f"_scope_{scope}", {}))
    try:
        return ctx.wm.load_autosave(ctx.user, scope=scope) or {}
    except Exception:
        return {}


def _save_scope(ctx: "ShellContext", scope: str, doc: dict) -> None:
    st.session_state[f"_scope_{scope}"] = dict(doc)   # session mirror (instant restore)
    if ctx.wm is None:
        return
    try:
        ctx.wm.autosave(ctx.user, doc, scope=scope)
    except Exception:
        pass


# ---------------------------------------------------------------- helpers
def _branding() -> theme.Branding:
    try:
        cfg = dict(st.secrets.get("branding", {}) or {})
    except Exception:
        cfg = {}
    return theme.load_branding(cfg)


def _logo_pair_html(brand: theme.Branding, height: int) -> str:
    """FC Masar × Right To Dream, side by side. Raises loudly on a missing asset."""
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


# ---------------------------------------------------------------- navigation model
def _nav_model(ctx: "ShellContext") -> tuple[list[nav.NavGroup], list[nav.NavItem], list[nav.NavItem]]:
    """Build the rail's model from the EXISTING registry (role-filtered, grouped,
    ordered). Reuses ids/names/icons verbatim - no second registry."""
    role = ctx.user.role
    pages = visible_pages(role)
    by_id = {p.info.id: p for p in pages}
    fav_ids = [i for i in _favorites() if i in by_id]
    fav_set = set(fav_ids)

    def item(p) -> nav.NavItem:
        return nav.NavItem(id=p.info.id, name=p.info.name, icon=p.icon,
                           active=p.info.id == ctx.active_page_id,
                           favorite=p.info.id in fav_set)

    groups = [nav.NavGroup(title=section, icon=nav.section_icon(section),
                           items=[item(p) for p in section_pages])
              for section, section_pages in visible_by_section(role).items()]
    favorites = [item(by_id[i]) for i in fav_ids][:8]
    recent_ids = [i for i in _recent_page_ids(ctx) if i in by_id and i != ctx.active_page_id]
    recents = [item(by_id[i]) for i in recent_ids][:5]
    return groups, favorites, recents


def _footer_info(ctx: "ShellContext", brand: theme.Branding) -> nav.FooterInfo:
    dataset, provider, rows, quality = "No active dataset", "", "", ""
    try:
        ds = ctx.wm.active_dataset(ctx.user) if ctx.wm is not None else None
    except Exception:
        ds = None
    if ds is not None:
        dataset = ds.name
        provider = ds.provider_id or ""
        rows = f"{ds.rows:,}" if isinstance(getattr(ds, "rows", None), int) else ""
        doc = ds.document if isinstance(getattr(ds, "document", None), dict) else {}
        q = doc.get("quality")
        quality = f"{q:.0f}" if isinstance(q, (int, float)) else ""
    # single fixed application appearance — no light/dark label to surface
    theme_label = "Professional"
    storage = "Local"
    try:
        storage = getattr(getattr(ctx.platform, "cache", None), "backend_name", "Local").title()
    except Exception:
        pass
    workspace = ""
    try:
        if ctx.wm is not None and ctx.workspace_id:
            workspace = next((w.name for w in ctx.wm.list_workspaces()
                              if w.id == ctx.workspace_id), "")
    except Exception:
        pass
    return nav.FooterInfo(dataset=dataset, provider=provider, rows=rows, quality=quality,
                          user=ctx.user.name, theme=theme_label, storage=storage,
                          connection="online", workspace=workspace, version=_short_version())


# ---------------------------------------------------------------- rail + header
def _render_rail(ctx: "ShellContext", brand: theme.Branding, collapsed: bool) -> None:
    """The fixed desktop navigation rail. Each row is CUSTOM HTML (the visible
    surface); an INVISIBLE st.button is overlaid on top for the click, so routing
    stays fully in-session (no href/query params) while nothing looks like a
    Streamlit button."""
    try:
        club = C.logo_html(brand.primary_logo, height=30, alt=brand.club_name, cls="nv-logo")
        org = C.logo_html(brand.secondary_logo, height=30, alt=brand.organization_name, cls="nv-logo")
    except FileNotFoundError as exc:
        st.error(f"Branding asset missing: {exc}")
        club = org = ""
    groups, favorites, recents = _nav_model(ctx)
    footer = _footer_info(ctx, brand)
    icon_specs: list[tuple[str, str]] = []

    with st.container(key="fap_rail"):
        st.markdown(nav.brand_html(club, org, brand.platform_name,
                                   "Professional Football Intelligence", collapsed),
                    unsafe_allow_html=True)
        query = ""
        if not collapsed:
            query = (st.text_input("Search modules", key="_nav_search",
                                   placeholder="Search modules...",
                                   label_visibility="collapsed") or "").strip().lower()
            st.markdown(nav.input_icon_css("_nav_search", "search"), unsafe_allow_html=True)
        with st.container(key="fap_rail_nav"):
            _render_nav_group(ctx, "Favorites", favorites, "fav", collapsed, query, icon_specs)
            _render_nav_group(ctx, "Recent", recents, "rec", collapsed, query, icon_specs)
            for g in groups:
                _render_nav_group(ctx, g.title, g.items, "nav", collapsed, query, icon_specs,
                                  collapsible=True)
        with st.container(key="fap_rail_footer"):
            st.markdown(nav.footer_html(footer, collapsed), unsafe_allow_html=True)

    # per-row icon glyphs (a CSS mask on each button, keyed by st-key)
    st.markdown(nav.icon_css(icon_specs), unsafe_allow_html=True)
    if collapsed:  # icon-only rows when the rail is narrow
        st.markdown(
            '<style>.st-key-fap_rail .stButton>button{justify-content:center;padding:0;}'
            '.st-key-fap_rail .stButton>button::before{margin-right:0;}</style>',
            unsafe_allow_html=True)


def _render_nav_group(ctx: "ShellContext", title: str, items: list[nav.NavItem],
                      prefix: str, collapsed: bool, query: str,
                      icon_specs: list[tuple[str, str]], collapsible: bool = False) -> None:
    """Each nav row is a REAL st.button (native, always clickable in Streamlit),
    styled by CSS to look like a desktop nav item. ``collapsible`` sections get a
    clickable dropdown header (also a real button) that toggles the group open in
    session - no HTML overlay, no positioning tricks."""
    visible = [it for it in items if not query or query in it.name.lower()]
    if not visible:
        return
    recent = prefix == "rec"
    show_items = True
    if collapsible and not collapsed and not query:
        slug = _slug(title)
        open_ = _group_open(slug, visible)
        hdr_key = f"grp_{slug}"
        icon_specs.append((hdr_key, "chevron-down" if open_ else "chevron-right"))
        st.button(title, key=hdr_key, on_click=_cb_toggle_group, args=(slug,),
                  use_container_width=True)
        show_items = open_
    elif not collapsed:
        st.markdown(nav.group_title_html(title), unsafe_allow_html=True)
    if not show_items:
        return
    for it in visible:
        key = f"{prefix}_{it.id}"
        icon_specs.append((key, "clock" if recent else (it.icon or nav.section_icon(title))))
        st.button(it.name if not collapsed else "", key=key, on_click=_cb_set_active,
                  args=(it.id,), type="primary" if it.active else "secondary",
                  use_container_width=True, help=it.name if collapsed else None)


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in str(text).lower())


def _group_open(slug: str, items: list[nav.NavItem]) -> bool:
    """A section dropdown's open state (session-only presentation flag). The section
    containing the ACTIVE page is always open so the user sees where they are."""
    if any(getattr(it, "active", False) for it in items):
        return True
    return bool(st.session_state.get(f"_grpopen_{slug}", True))


def _cb_toggle_group(slug: str) -> None:
    key = f"_grpopen_{slug}"
    st.session_state[key] = not st.session_state.get(key, True)


def _render_header(ctx: "ShellContext", brand: theme.Branding, collapsed: bool) -> None:
    """Top bar. Collapse + theme are REAL st.button widgets (in-session, no href);
    title/breadcrumb/user are static HTML."""
    org = _org_context()
    page = get_page(ctx.active_page_id)
    crumbs = [brand.club_name if org.get("club") else "", org.get("season", ""),
              org.get("competition", ""), org.get("opponent", "")]
    crumbs = [c for c in crumbs if c] or [brand.organization_name]
    if page is not None:
        crumbs.append(page.info.name)
    module_title = page.info.name if page else brand.platform_name
    module_icon = page.icon if page and page.icon else ""
    initials = "".join(p[0] for p in ctx.user.name.split()[:2]).upper() or "?"
    notifications = st.session_state.get("_notifications", [])

    with st.container(key="fap_header"):
        c = st.columns([0.6, 8, 3], vertical_alignment="center")
        with c[0]:
            st.button("", key="hdr_collapse", on_click=_cb_toggle_collapse,
                      help="Expand navigation" if collapsed else "Collapse navigation",
                      use_container_width=True)
        with c[1]:
            st.markdown(nav.header_titles_html(module_title, module_icon,
                                               C.breadcrumb_html(crumbs)),
                        unsafe_allow_html=True)
        with c[2]:
            st.markdown(nav.header_user_html(
                ctx.user.name, initials, C.badge_html(ctx.user.role_label, "info"),
                len(notifications)), unsafe_allow_html=True)
    # header button glyph (collapse chevron). The application has a single fixed
    # appearance, so there is no light/dark theme control.
    st.markdown(nav.icon_css([
        ("hdr_collapse", "chevron-right" if collapsed else "chevron-left"),
    ]), unsafe_allow_html=True)


def _render_controls_bar(ctx: "ShellContext", brand: theme.Branding) -> None:
    """The interactive controls Streamlit cannot express as static HTML: workspace
    and project selectors, appearance and account. A slim toolbar under the header;
    navigation itself stays in the HTML rail."""
    if ctx.wm is None:
        return
    # The application has ONE fixed appearance, so there is no theme/appearance
    # control here (chart visualization themes remain selectable inside the chart
    # tools, unchanged).
    cols = st.columns([3, 3, 8, 2], vertical_alignment="center")
    with cols[0]:
        _workspace_selector(ctx)
    with cols[1]:
        _project_selector(ctx)
    with cols[3]:
        _account_popover(ctx)


def _workspace_selector(ctx: "ShellContext") -> None:
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
                              format_func=lambda i: names[i], key="_ws_select")
        st.session_state[_WORKSPACE] = chosen
    except Exception:
        st.caption("Workspace unavailable.")


def _project_selector(ctx: "ShellContext") -> None:
    try:
        chosen = st.session_state.get(_WORKSPACE)
        if not chosen:
            return
        projects = ctx.wm.list_projects(chosen)
        if not projects:
            st.selectbox("Project", ["— none —"], disabled=True, key="_pj_none")
            return
        pnames = {p.id: p.name for p in projects}
        pid = st.selectbox("Project", ["—", *pnames], key="_pj_select",
                           format_func=lambda i: "— none —" if i == "—" else pnames[i])
        if pid != "—":
            st.session_state[_PROJECT] = pid
            st.session_state["_active_project_name"] = pnames[pid]
            ctx.wm.touch_recent(ctx.user, "project", pid)
    except Exception:
        pass


def _appearance_popover() -> None:
    """Theme preset + light/dark/auto - the header's quick toggle handles mode; this
    exposes the full preset set (Professional Dark/Light, Club, Opta, Hudl)."""
    with st.popover("Theme", use_container_width=True):
        ids = theme.preset_ids()
        labels = {pid: lbl for pid, lbl in theme.preset_choices()}
        current = st.session_state.get("_theme_preset") or theme.DEFAULT_PRESET_ID
        if current not in ids:
            current = theme.DEFAULT_PRESET_ID
        chosen = st.selectbox("Preset", ids, index=ids.index(current),
                              format_func=lambda i: labels.get(i, i), key="_theme_preset_select")
        if chosen != st.session_state.get("_theme_preset"):
            st.session_state["_theme_preset"] = chosen
            st.session_state.pop("_theme_mode", None)
            st.rerun()
        st.caption(theme.get_preset(chosen).description)
        modes = ["auto", "light", "dark"]
        labels_m = {"auto": "Auto", "light": "Light", "dark": "Dark"}
        cur_mode = st.session_state.get("_theme_mode") or theme.get_preset(chosen).mode
        cur_mode = cur_mode if cur_mode in modes else "auto"
        picked = st.radio("Mode", modes, index=modes.index(cur_mode), horizontal=True,
                          format_func=lambda m: labels_m[m], key="_theme_mode_radio")
        if picked != (st.session_state.get("_theme_mode") or theme.get_preset(chosen).mode):
            st.session_state["_theme_mode"] = picked
            st.rerun()


def _account_popover(ctx: "ShellContext") -> None:
    with st.popover("Account", use_container_width=True):
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


def _render_status_bar(ctx: "ShellContext") -> None:
    """A slim desktop-style status strip at the very bottom (version · workspace ·
    connection) - complements the rail footer's dataset panel."""
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
            ("Workspace", ws_name), ("User", ctx.user.name), ("Version", _short_version()),
        ]).replace("</div>", f"<span>{connection}</span></div>"),
        unsafe_allow_html=True)


def _short_version() -> str:
    try:
        return platform_version().split("+")[0]
    except Exception:
        return "?"
