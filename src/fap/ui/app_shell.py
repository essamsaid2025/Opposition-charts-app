"""The professional application shell (Phase 3C · Phase 5.1 · Phase 13.0).

A fixed custom navigation rail + a top header + main content + a slim status bar.
Phase 13.0 REPLACES Streamlit's native sidebar with a pure-HTML fixed rail
(``fap.ui.nav``, styled by ``fap.theme.css``): the native sidebar and its collapse
control are hidden, and the shell owns width/collapse/state. Navigation REUSES the
existing routing verbatim - each rail item is an ``<a href="?nav=ID">`` link the
shell maps to the SAME active-page state and ``page_registry``; there is no second
registry and no duplicated routing. Collapse (``?shell=toggle``) and pin
(``?fav=ID``) use the same pattern, and their state persists per-user through the
existing ``WorkspaceManager`` autosave/recents - never browser storage.

The platform accessors are injected by app.py (no ``import app`` here, which would
be circular). Only ``render_shell`` and the ``_render_*`` helpers touch Streamlit;
the navigation model (fap.ui.page), the HTML builders (fap.ui.nav) and the theme
(fap.theme) are pure and unit-tested.
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
    theme.apply(brand, theme.resolve_mode(st.session_state.get("_theme_mode"), brand))

    from fap.identity import current_user
    if current_user() is None:
        _render_login_branding(brand)
    user = require_login()
    st.session_state["_in_shell"] = True
    load_builtin_pages()

    platform, wm = _resolve_services()
    ctx = ShellContext(user=user, platform=platform, wm=wm, active_page_id="")

    # 1) apply query-param actions (nav / collapse / theme / pin) BEFORE rendering
    _process_shell_actions(ctx)

    active = _resolve_active_page(user)
    ctx.active_page_id = active

    collapsed = _is_collapsed(ctx)
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
    _inject_search_enhancement()


# ---------------------------------------------------------------- query-param actions
def _process_shell_actions(ctx: "ShellContext") -> None:
    """Map the rail's ``<a href="?...">`` links onto existing state. ``nav`` is
    idempotent (left in the URL); toggles (collapse/theme/pin) are cleared so a
    refresh does not re-fire them. Each is the single rerun the user approved."""
    qp = st.query_params
    role = ctx.user.role
    allowed = {p.info.id for p in visible_pages(role)}

    nav_id = qp.get("nav")
    if nav_id and nav_id in allowed:
        st.session_state[_ACTIVE] = nav_id
        _record_recent(ctx, nav_id)

    toggled = False
    shell_action = qp.get("shell")
    if shell_action == "toggle":
        _set_collapsed(ctx, not _is_collapsed(ctx))
        toggled = True
    elif shell_action == "theme":
        current = theme.resolve_mode(st.session_state.get("_theme_mode"),
                                     theme.branding_for(
                                         st.session_state.get("_theme_preset")
                                         or theme.DEFAULT_PRESET_ID, _branding()))
        st.session_state["_theme_mode"] = "light" if current == "dark" else "dark"
        toggled = True

    fav_id = qp.get("fav")
    if fav_id and fav_id in allowed:
        _toggle_favorite(ctx, fav_id)
        toggled = True

    if toggled:
        st.query_params.clear()
        st.rerun()


# ---------------------------------------------------------------- persisted state
def _is_collapsed(ctx: "ShellContext") -> bool:
    doc = _load_scope(ctx, _SHELL_SCOPE)
    if "collapsed" in doc:
        return bool(doc["collapsed"])
    return bool(st.session_state.get("_rail_collapsed", False))


def _set_collapsed(ctx: "ShellContext", value: bool) -> None:
    st.session_state["_rail_collapsed"] = bool(value)
    _save_scope(ctx, _SHELL_SCOPE, {"collapsed": bool(value)})


def _favorites(ctx: "ShellContext") -> list[str]:
    doc = _load_scope(ctx, _FAV_SCOPE)
    return [str(x) for x in (doc.get("pages") or [])]


def _toggle_favorite(ctx: "ShellContext", page_id: str) -> None:
    favs = _favorites(ctx)
    favs.remove(page_id) if page_id in favs else favs.append(page_id)
    _save_scope(ctx, _FAV_SCOPE, {"pages": favs})


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
    fav_ids = [i for i in _favorites(ctx) if i in by_id]
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
    preset = theme.get_preset(st.session_state.get("_theme_preset") or theme.DEFAULT_PRESET_ID)
    mode = theme.resolve_mode(st.session_state.get("_theme_mode"), brand)
    theme_label = f"{preset.name} · {mode.title()}"
    storage = "Local"
    try:
        storage = getattr(getattr(ctx.platform, "cache", None), "backend_name", "Local").title()
    except Exception:
        pass
    return nav.FooterInfo(dataset=dataset, provider=provider, rows=rows, quality=quality,
                          user=ctx.user.name, theme=theme_label, storage=storage,
                          connection="online")


# ---------------------------------------------------------------- rail + header
def _render_rail(ctx: "ShellContext", brand: theme.Branding, collapsed: bool) -> None:
    try:
        brand_logos = _logo_pair_html(brand, height=28)
    except FileNotFoundError as exc:
        st.error(f"Branding asset missing: {exc}")
        brand_logos = ""
    groups, favorites, recents = _nav_model(ctx)
    footer = _footer_info(ctx, brand)
    st.markdown(
        nav.rail_html(brand_html=brand_logos, platform_name=brand.platform_name,
                      groups=groups, favorites=favorites, recents=recents,
                      footer=footer, collapsed=collapsed),
        unsafe_allow_html=True)


def _render_header(ctx: "ShellContext", brand: theme.Branding, collapsed: bool) -> None:
    org = _org_context()
    page = get_page(ctx.active_page_id)
    crumbs = [brand.club_name if org.get("club") else "", org.get("season", ""),
              org.get("competition", ""), org.get("opponent", "")]
    crumbs = [c for c in crumbs if c] or [brand.organization_name]
    if page is not None:
        crumbs.append(page.info.name)

    notifications = st.session_state.get("_notifications", [])
    module_title = page.info.name if page else brand.platform_name
    module_icon = page.icon if page and page.icon else ""
    initials = "".join(p[0] for p in ctx.user.name.split()[:2]).upper() or "?"
    mode = theme.resolve_mode(st.session_state.get("_theme_mode"), brand)
    st.markdown(
        nav.header_html(
            module_title=module_title, module_icon=module_icon,
            breadcrumb_html=C.breadcrumb_html(crumbs),
            notif_count=len(notifications), user_name=ctx.user.name,
            user_initials=initials, role_badge_html=C.badge_html(ctx.user.role_label, "info"),
            collapsed=collapsed, theme_mode=mode),
        unsafe_allow_html=True)


def _render_controls_bar(ctx: "ShellContext", brand: theme.Branding) -> None:
    """The interactive controls Streamlit cannot express as static HTML: workspace
    and project selectors, appearance and account. A slim toolbar under the header;
    navigation itself stays in the HTML rail."""
    if ctx.wm is None:
        return
    cols = st.columns([3, 3, 6, 2, 2], vertical_alignment="center")
    with cols[0]:
        _workspace_selector(ctx)
    with cols[1]:
        _project_selector(ctx)
    with cols[3]:
        _appearance_popover()
    with cols[4]:
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


def _inject_search_enhancement() -> None:
    """Progressive enhancement: live-filter the rail's modules as the user types.
    Isolated in a 0-height component; if the browser sandboxes it, navigation still
    works via the links and every module stays visible."""
    try:
        import streamlit.components.v1 as components
        components.html(nav.SEARCH_JS, height=0)
    except Exception:
        pass


def _short_version() -> str:
    try:
        return platform_version().split("+")[0]
    except Exception:
        return "?"
