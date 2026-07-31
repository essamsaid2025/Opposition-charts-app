"""Pure presentation helpers for the professional application shell (Phase 13.2).

The navigation is a fixed desktop-style rail. Per the Phase 13.2 design, everything
the user SEES is custom HTML/CSS (built here); the Streamlit ``st.button`` widgets
that ``fap.ui.app_shell`` renders are INVISIBLE click overlays sitting on top of
each custom row - so the click still runs Python IN-SESSION via the existing
``ShellContext.goto`` semantics (no anchors, no query params, no window scripting,
no browser navigation), while the visible surface never looks like a Streamlit
button.

This module is pure (no Streamlit, no routing): the brand block, search field
chrome, section labels, the visible nav rows (inline registry SVG icons), the
footer status panel and the header display. Colours come only from theme tokens.
"""
from __future__ import annotations

import html as _html
import urllib.parse
from dataclasses import dataclass, field
from typing import Sequence

from fap.theme.icons import icon

_SECTION_ICON = {
    "overview": "dashboard", "analysis": "analysis", "squad": "players",
    "workspace": "folder", "admin": "settings",
}


def _esc(text: str) -> str:
    return _html.escape(str(text or ""))


@dataclass(slots=True)
class NavItem:
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


# ---------------------------------------------------------------- brand
def brand_html(club_logo_html: str, org_logo_html: str, title: str, subtitle: str,
               collapsed: bool) -> str:
    """FC Masar × Right To Dream, centred, equal size, with a soft divider; then a
    compact title + subtitle. Collapsed shows the club crest alone."""
    if collapsed:
        return f'<div class="nv-brand collapsed">{club_logo_html}</div>'
    logos = (f'<div class="nv-logos">{club_logo_html}'
             f'<span class="nv-logo-sep"></span>{org_logo_html}</div>')
    return (f'<div class="nv-brand">{logos}'
            f'<div class="nv-brand-title">{_esc(title)}</div>'
            f'<div class="nv-brand-sub">{_esc(subtitle)}</div></div>')


# ---------------------------------------------------------------- rows / groups
def group_title_html(title: str) -> str:
    return f'<div class="nv-sec">{_esc(title)}</div>'


def nav_row_html(name: str, icon_name: str, *, active: bool = False, favorite: bool = False,
                 recent: bool = False, collapsed: bool = False) -> str:
    """The VISIBLE nav row (an invisible st.button overlays it for the click)."""
    cls = "nv-row" + (" active" if active else "") + (" recent" if recent else "")
    glyph = icon(icon_name, 16 if recent else 20)
    if collapsed:
        return f'<div class="{cls} only-icon" title="{_esc(name)}"><span class="ic">{glyph}</span></div>'
    star = "" if recent else (f'<span class="star{" on" if favorite else ""}">'
                              f'{icon("star", 15)}</span>')
    return (f'<div class="{cls}"><span class="ic">{glyph}</span>'
            f'<span class="lbl">{_esc(name)}</span>{star}</div>')


# ---------------------------------------------------------------- footer status panel
def footer_html(f: FooterInfo, collapsed: bool = False) -> str:
    conn_ok = (f.connection or "").lower() in ("online", "connected", "ok")
    if collapsed:
        return (f'<div class="nv-footer collapsed">'
                f'<span class="nv-status-dot {"ok" if conn_ok else "off"}" '
                f'title="{_esc(f.connection)}"></span></div>')
    prov = f'<span class="nv-badge">{_esc(f.provider)}</span>' if f.provider else ""
    rows = f'<span class="nv-rows">{_esc(f.rows)} events</span>' if f.rows else ""
    scls = "ok" if conn_ok else "off"
    stext = "Online" if conn_ok else _esc(f.connection or "Offline")
    return (
        '<div class="nv-footer"><div class="nv-card">'
        '<div class="nv-card-title">Current Dataset</div>'
        f'<div class="nv-card-ds" title="{_esc(f.dataset)}">{_esc(f.dataset)}</div>'
        + (f'<div class="nv-card-meta">{prov}{rows}</div>' if (prov or rows) else '')
        + '<div class="nv-card-grid">'
        f'<span class="k">Workspace</span><span class="v">{_esc(f.workspace) or "—"}</span>'
        f'<span class="k">Version</span><span class="v">{_esc(f.version) or "—"}</span>'
        '</div>'
        f'<div class="nv-status {scls}"><span class="nv-status-dot {scls}"></span>{stext}</div>'
        '</div></div>')


# ---------------------------------------------------------------- header display
def header_titles_html(module_title: str, module_icon: str, breadcrumb_html: str) -> str:
    chip = f'<span class="mod-chip">{icon(module_icon, 20)}</span>' if module_icon else ""
    return (f'<div class="fap-hdr-titles">{chip}'
            f'<div class="titles"><span class="crumbs">{breadcrumb_html}</span>'
            f'<b class="mod-title">{_esc(module_title)}</b></div></div>')


def header_user_html(user_name: str, user_initials: str, role_badge_html: str,
                     notif_count: int) -> str:
    n = int(notif_count or 0)
    bell = (f'<span class="hbtn bell {"has" if n else ""}" title="Notifications">'
            f'{icon("bell", 18)}{f"<span class=chip-count>{n}</span>" if n else ""}</span>')
    return (f'<div class="fap-hdr-user">{bell}<span class="hsep"></span>'
            f'<span class="user"><span class="uava">{_esc(user_initials)}</span>'
            f'<span class="uinfo"><b>{_esc(user_name)}</b>{role_badge_html}</span></span></div>')


# ---------------------------------------------------------------- icon masks (header buttons + search)
def _icon_data_uri(name: str) -> str:
    svg = icon(name, 20) or icon("grid", 20)
    return "data:image/svg+xml," + urllib.parse.quote(svg)


def icon_css(specs: Sequence[tuple[str, str]]) -> str:
    """Per-widget ``st-key-<key>`` icon masks - used for the header's collapse/theme
    icon buttons (their glyph is a mask so it takes the button's currentColor)."""
    rules, seen = [], set()
    for key, name in specs:
        if key in seen:
            continue
        seen.add(key)
        uri = _icon_data_uri(name)
        rules.append(f'.st-key-{key} button::before{{-webkit-mask-image:url("{uri}");'
                     f'mask-image:url("{uri}");}}')
    return "<style>" + "".join(rules) + "</style>"


def input_icon_css(key: str, icon_name: str) -> str:
    """Draw a search glyph inside the keyed st.text_input (the search pill)."""
    uri = _icon_data_uri(icon_name)
    return (f'<style>.st-key-{key} [data-testid="stTextInputRootElement"]::before{{'
            f'-webkit-mask-image:url("{uri}");mask-image:url("{uri}");}}</style>')
