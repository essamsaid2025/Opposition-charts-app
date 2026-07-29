"""Pure HTML builders for the professional application shell (Phase 13.0).

The shell is a fixed left navigation rail + a top header, rendered as custom
HTML/CSS (styled by ``fap.theme.css``) rather than Streamlit's native sidebar.
Everything here is a PURE string builder - no Streamlit, no I/O - so the whole
navigation surface is unit-testable and carries no page/routing logic of its own.

Navigation reuses the existing routing: each item is an ``<a href="?nav=ID">``
link; the shell reads that query param and drives the SAME active-page state and
``page_registry`` the app already uses. Collapse/pin are the same pattern
(``?shell=toggle`` / ``?fav=ID``). No second registry, no duplicated routing.
"""
from __future__ import annotations

import html as _html
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


# ---------------------------------------------------------------- nav rows
def _icon_for(item: NavItem, group_icon: str = "") -> str:
    name = item.icon or group_icon or "grid"
    return icon(name, 18)


def nav_row_html(item: NavItem, *, group_icon: str = "") -> str:
    """A navigation row: the page link (icon + label) plus a pin toggle. The pin
    is a SIBLING link (never nested in the page link - nested <a> is invalid)."""
    cls = "fap-nav-row" + (" active" if item.active else "")
    label = _esc(item.name)
    star = "star" if item.favorite else "star"
    pin_cls = "fap-nav-pin" + (" on" if item.favorite else "")
    # target="_self" keeps navigation INSIDE the current tab. Streamlit renders
    # markdown anchors so they open in a NEW tab by default; _self overrides that
    # so a click updates the query param in-app, exactly like the old sidebar.
    return (
        f'<div class="{cls}">'
        f'<a class="fap-nav-link" href="?nav={_esc(item.id)}" target="_self" aria-label="{label}" '
        f'title="{label}" data-tip="{label}">'
        f'<span class="ic">{_icon_for(item, group_icon)}</span>'
        f'<span class="label">{label}</span></a>'
        f'<a class="{pin_cls}" href="?fav={_esc(item.id)}" target="_self" tabindex="0" '
        f'title="{"Unpin" if item.favorite else "Pin to favorites"}" '
        f'aria-label="{"Unpin " if item.favorite else "Pin "}{label}">{icon(star, 13)}</a>'
        f'</div>')


def nav_group_html(group: NavGroup) -> str:
    if not group.items:
        return ""
    rows = "".join(nav_row_html(i, group_icon=group.icon) for i in group.items)
    head = (f'<div class="fap-nav-group-title">'
            f'<span class="gt-ic">{icon(group.icon, 14)}</span>'
            f'<span class="gt-label">{_esc(group.title)}</span></div>') if group.title else ""
    return f'<div class="fap-nav-group">{head}{rows}</div>'


def section_icon(section: str) -> str:
    return _SECTION_ICON.get((section or "").strip().lower(), "grid")


# ---------------------------------------------------------------- rail
def _quick_group(title: str, icon_name: str, items: Sequence[NavItem]) -> str:
    if not items:
        return ""
    rows = "".join(nav_row_html(i) for i in items)
    head = (f'<div class="fap-nav-group-title">'
            f'<span class="gt-ic">{icon(icon_name, 14)}</span>'
            f'<span class="gt-label">{_esc(title)}</span></div>')
    return f'<div class="fap-nav-group">{head}{rows}</div>'


def _footer_html(f: FooterInfo) -> str:
    conn_ok = (f.connection or "").lower() in ("online", "connected", "ok")
    conn_cls = "ok" if conn_ok else "off"
    prov = f'<span class="ft-badge">{_esc(f.provider)}</span>' if f.provider else ""
    rows = f'<span class="ft-k">Rows</span><span class="ft-v">{_esc(f.rows)}</span>' if f.rows else ""
    qual = (f'<span class="ft-k">Quality</span><span class="ft-v">{_esc(f.quality)}</span>'
            if f.quality else "")
    return (
        '<div class="fap-rail-footer">'
        '<div class="ft-ds">'
        f'<div class="ft-title"><span class="ft-dot"></span>Current dataset</div>'
        f'<div class="ft-name" title="{_esc(f.dataset)}">{_esc(f.dataset)}</div>'
        f'<div class="ft-meta">{prov}{rows}{qual}</div>'
        '</div>'
        '<div class="ft-grid">'
        f'<span class="ft-k">User</span><span class="ft-v">{_esc(f.user)}</span>'
        f'<span class="ft-k">Theme</span><span class="ft-v">{_esc(f.theme)}</span>'
        f'<span class="ft-k">Storage</span><span class="ft-v">{_esc(f.storage)}</span>'
        f'<span class="ft-k">Status</span>'
        f'<span class="ft-v conn {conn_cls}"><span class="cdot"></span>{_esc(f.connection)}</span>'
        '</div>'
        '</div>')


def rail_html(*, brand_html: str, platform_name: str, groups: Sequence[NavGroup],
              favorites: Sequence[NavItem], recents: Sequence[NavItem],
              footer: FooterInfo, collapsed: bool) -> str:
    """The whole fixed navigation rail as one HTML string (rendered once)."""
    nav = "".join(nav_group_html(g) for g in groups)
    fav = _quick_group("Favorites", "star", favorites)
    rec = _quick_group("Recent", "clock", recents)
    search = (
        '<div class="fap-rail-search">'
        f'<span class="s-ic">{icon("search", 15)}</span>'
        '<input class="fap-nav-search" type="text" autocomplete="off" spellcheck="false" '
        'placeholder="Search modules…" aria-label="Search modules" />'
        '</div>')
    cls = "fap-navrail" + (" collapsed" if collapsed else "")
    return (
        f'<nav class="{cls}" aria-label="Primary" role="navigation">'
        f'<div class="fap-rail-brand">{brand_html}'
        f'<span class="fap-rail-brandname">{_esc(platform_name)}</span></div>'
        f'{search}'
        f'<div class="fap-rail-scroll">{fav}{rec}{nav}</div>'
        f'{_footer_html(footer)}'
        f'</nav>')


# ---------------------------------------------------------------- header
def header_html(*, module_title: str, module_icon: str, breadcrumb_html: str,
                notif_count: int, user_name: str, user_initials: str,
                role_badge_html: str, collapsed: bool, theme_mode: str) -> str:
    """The top bar: collapse button, module title + breadcrumb, search hint,
    theme switch, notifications, user. Collapse/theme are query-param links so
    they reuse the shell's single-rerun state flow."""
    n = int(notif_count or 0)
    bell_cls = "has" if n else ""
    theme_icon = "sun" if (theme_mode or "").lower() == "dark" else "moon"
    toggle_icon = "chevron-right" if collapsed else "chevron-left"
    return (
        '<header class="fap-shell-header">'
        '  <div class="left">'
        f'    <a class="hbtn collapse" href="?shell=toggle" target="_self" role="button" '
        f'       aria-label="{"Expand" if collapsed else "Collapse"} navigation" '
        f'       title="{"Expand" if collapsed else "Collapse"} navigation">{icon(toggle_icon, 18)}</a>'
        f'    <span class="mod-chip">{icon(module_icon, 20) if module_icon else ""}</span>'
        f'    <div class="titles"><b class="mod-title">{_esc(module_title)}</b>'
        f'      <span class="crumbs">{breadcrumb_html}</span></div>'
        '  </div>'
        '  <div class="right">'
        f'    <a class="hbtn" href="?shell=theme" target="_self" role="button" aria-label="Toggle theme" '
        f'       title="Toggle light / dark">{icon(theme_icon, 17)}</a>'
        f'    <span class="hbtn bell {bell_cls}" title="Notifications" aria-label="Notifications">'
        f'      {icon("bell", 17)}{f"<span class=chip-count>{n}</span>" if n else ""}</span>'
        '    <span class="hsep"></span>'
        f'    <span class="user"><span class="uava">{_esc(user_initials)}</span>'
        f'      <span class="uinfo"><b>{_esc(user_name)}</b>{role_badge_html}</span></span>'
        '  </div>'
        '</header>')


# ---------------------------------------------------------------- search JS (enhancement)
# Progressive enhancement ONLY: live-filters the rail's nav rows as the user types.
# Runs from a components iframe against the parent document; if blocked, every page
# stays visible (nothing is lost) and navigation still works via the links.
SEARCH_JS = """
<script>
(function () {
  try {
    var doc = window.parent.document;
    function wire() {
      var input = doc.querySelector('.fap-nav-search');
      if (!input || input.dataset.wired) return;
      input.dataset.wired = '1';
      input.addEventListener('input', function () {
        var q = (input.value || '').trim().toLowerCase();
        doc.querySelectorAll('.fap-navrail .fap-nav-row').forEach(function (row) {
          var link = row.querySelector('.fap-nav-link');
          var name = (link && (link.getAttribute('data-tip') || link.textContent) || '').toLowerCase();
          row.style.display = (!q || name.indexOf(q) !== -1) ? '' : 'none';
        });
        doc.querySelectorAll('.fap-navrail .fap-nav-group').forEach(function (g) {
          var any = Array.prototype.some.call(g.querySelectorAll('.fap-nav-row'),
            function (r) { return r.style.display !== 'none'; });
          g.style.display = any ? '' : 'none';
        });
      });
    }
    wire();
    new MutationObserver(wire).observe(doc.body, {childList: true, subtree: true});
  } catch (e) { /* sandboxed: navigation still works via links */ }
})();
</script>
"""
