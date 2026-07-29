"""Pure presentation helpers for the professional application shell (Phase 13.1).

Phase 13.1 replaced the earlier link-based rail (an anchor is a browser navigation,
which starts a NEW Streamlit session and restarts app.py - unacceptable for a
desktop app). The clickable navigation is now real ``st.button`` widgets (rendered
by ``fap.ui.app_shell``) that change ``st.session_state["_active_page"]`` IN-SESSION
via the existing ``ShellContext.goto`` semantics - no anchors, no query params, no
window scripting, no browser navigation.

This module therefore holds only PURE, non-interactive pieces (no Streamlit, no
routing): the rail's static HTML chrome (brand, group titles, footer, header
display) and the CSS that paints each button as a professional nav item (icon +
accent). The buttons themselves live in the shell because only Streamlit can make a
click run Python in the same session.
"""
from __future__ import annotations

import html as _html
import urllib.parse
from dataclasses import dataclass, field
from typing import Sequence

from fap.theme.icons import icon

# section slug -> a registry icon, used when a page declares no icon of its own
_SECTION_ICON = {
    "overview": "dashboard", "analysis": "analysis", "squad": "players",
    "workspace": "folder", "admin": "settings",
}


def _esc(text: str) -> str:
    return _html.escape(str(text or ""))


@dataclass(slots=True)
class NavItem:
    """One navigation entry: reuses the page registry's id/name/icon verbatim."""
    id: str
    name: str
    icon: str = ""
    active: bool = False
    favorite: bool = False


@dataclass(slots=True)
class NavGroup:
    title: str
    items: list[NavItem] = field(default_factory=list)
    icon: str = ""


@dataclass(slots=True)
class FooterInfo:
    dataset: str = "No active dataset"
    provider: str = ""
    rows: str = ""
    quality: str = ""
    user: str = ""
    theme: str = ""
    storage: str = "Local"
    connection: str = "online"
    workspace: str = ""
    version: str = ""


def section_icon(section: str) -> str:
    return _SECTION_ICON.get((section or "").strip().lower(), "grid")


# ---------------------------------------------------------------- static chrome (HTML)
def brand_html(logo_html: str, title: str, subtitle: str, collapsed: bool) -> str:
    """A premium brand block: logo (never stretched) · title + muted subtitle.
    Collapsed shows the logo alone, centred."""
    if collapsed:
        return f'<div class="fap-rail-brand collapsed">{logo_html}</div>'
    text = (f'<div class="brand-text">'
            f'<div class="brand-title">{_esc(title)}</div>'
            f'<div class="brand-sub">{_esc(subtitle)}</div></div>')
    return f'<div class="fap-rail-brand">{logo_html}{text}</div>'


def group_title_html(title: str, icon_name: str = "") -> str:
    """A small uppercase section label (plain text - desktop-nav style)."""
    return f'<div class="fap-nav-group-title">{_esc(title)}</div>'


def footer_html(f: FooterInfo, collapsed: bool = False) -> str:
    conn_ok = (f.connection or "").lower() in ("online", "connected", "ok")
    if collapsed:
        dot = "ok" if conn_ok else "off"
        return (f'<div class="fap-rail-footer collapsed">'
                f'<span class="ft-status-dot {dot}" title="{_esc(f.connection)}"></span></div>')
    prov = f'<span class="ft-badge">{_esc(f.provider)}</span>' if f.provider else ""
    rows = f'<span class="ft-rows">{_esc(f.rows)} rows</span>' if f.rows else ""
    status_cls = "ok" if conn_ok else "off"
    status_txt = "Online" if conn_ok else _esc(f.connection or "Offline")
    return (
        '<div class="fap-rail-footer">'
        '<div class="ft-ds">'
        '<div class="ft-title"><span class="ft-dot"></span>Current dataset</div>'
        f'<div class="ft-name" title="{_esc(f.dataset)}">{_esc(f.dataset)}</div>'
        + (f'<div class="ft-meta">{prov}{rows}</div>' if (prov or rows) else '')
        + '</div>'
        '<div class="ft-grid">'
        f'<span class="ft-k">Workspace</span><span class="ft-v">{_esc(f.workspace) or "—"}</span>'
        f'<span class="ft-k">Version</span><span class="ft-v">{_esc(f.version) or "—"}</span>'
        f'<span class="ft-k">Status</span>'
        f'<span class="ft-v"><span class="ft-status {status_cls}">'
        f'<span class="ft-status-dot {status_cls}"></span>{status_txt}</span></span>'
        '</div>'
        '</div>')


# ---------------------------------------------------------------- header display (HTML)
def header_titles_html(module_title: str, module_icon: str, breadcrumb_html: str) -> str:
    chip = f'<span class="mod-chip">{icon(module_icon, 20)}</span>' if module_icon else ""
    return (f'<div class="fap-hdr-titles">{chip}'
            f'<div class="titles"><b class="mod-title">{_esc(module_title)}</b>'
            f'<span class="crumbs">{breadcrumb_html}</span></div></div>')


def header_user_html(user_name: str, user_initials: str, role_badge_html: str,
                     notif_count: int) -> str:
    n = int(notif_count or 0)
    bell = (f'<span class="hbtn bell {"has" if n else ""}" title="Notifications">'
            f'{icon("bell", 18)}{f"<span class=chip-count>{n}</span>" if n else ""}</span>')
    return (f'<div class="fap-hdr-user">{bell}<span class="hsep"></span>'
            f'<span class="user"><span class="uava">{_esc(user_initials)}</span>'
            f'<span class="uinfo"><b>{_esc(user_name)}</b>{role_badge_html}</span></span></div>')


# ---------------------------------------------------------------- icon masks (CSS)
def _icon_data_uri(name: str) -> str:
    """A registry SVG as a URL-encoded data URI, for a CSS mask (so the icon takes
    the element's currentColor and tints with hover/active - our set, no emoji)."""
    svg = icon(name, 20) or icon("grid", 20)
    return "data:image/svg+xml," + urllib.parse.quote(svg)


def icon_css(specs: Sequence[tuple[str, str]]) -> str:
    """A ``<style>`` mapping each button's ``st-key-<key>`` wrapper to its icon mask.
    ``specs`` is a list of ``(widget_key, icon_name)``. Pure string; no Streamlit."""
    rules = []
    seen: set[str] = set()
    for key, name in specs:
        if key in seen:
            continue
        seen.add(key)
        uri = _icon_data_uri(name)
        rules.append(
            f'.st-key-{key} button::before{{-webkit-mask-image:url("{uri}");'
            f'mask-image:url("{uri}");}}')
    return "<style>" + "".join(rules) + "</style>"


def input_icon_css(key: str, icon_name: str) -> str:
    """A ``<style>`` that draws an icon inside a keyed st.text_input (the search box).
    The box/position rules live in the stylesheet; this only sets the mask shape."""
    uri = _icon_data_uri(icon_name)
    return (f'<style>.st-key-{key} [data-testid="stTextInputRootElement"]::before{{'
            f'-webkit-mask-image:url("{uri}");mask-image:url("{uri}");}}</style>')
