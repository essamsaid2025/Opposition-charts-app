"""Professional UI components built from the theme tokens.

Each component has a pure ``*_html`` builder (returns a string, unit-testable
without Streamlit) and a thin ``render_*`` wrapper that injects it. Pages use
these instead of writing inline HTML/CSS, so the look stays centralized.
"""
from __future__ import annotations

from typing import Iterable, Sequence

from fap.theme.branding import logo_data_uri
from fap.theme.icons import icon

_BADGE_KINDS = {"success", "warning", "danger", "info", "neutral"}


def logo_html(path: str, *, height: int = 28, alt: str = "", cls: str = "fap-logo") -> str:
    """An inline <img> for a brand logo, embedded as a data URI. Raises loudly
    (FileNotFoundError) if the asset is missing - callers surface that visibly
    rather than silently rendering generic branding."""
    uri = logo_data_uri(path)
    alt_attr = alt or "logo"
    return (f'<img src="{uri}" alt="{alt_attr}" class="{cls}" '
            f'style="height:{height}px;width:auto;" />')


def kpi_card_html(label: str, value: str, *, delta: str | None = None,
                  direction: str = "", icon_name: str = "") -> str:
    glyph = f'<span class="fap-kpi-icon">{icon(icon_name)}</span>' if icon_name else ""
    delta_html = ""
    if delta:
        cls = "up" if direction == "up" else "down" if direction == "down" else ""
        delta_html = f'<div class="delta {cls}">{delta}</div>'
    return (f'<div class="fap-card fap-kpi">{glyph}'
            f'<div class="label">{label}</div>'
            f'<div class="value">{value}</div>{delta_html}</div>')


def badge_html(text: str, kind: str = "neutral", *, icon_name: str = "") -> str:
    kind = kind if kind in _BADGE_KINDS else "neutral"
    glyph = icon(icon_name, size=13) if icon_name else ""
    return f'<span class="fap-badge {kind}">{glyph}{text}</span>'


def breadcrumb_html(items: Sequence[str]) -> str:
    parts = [p for p in items if p]
    if not parts:
        return '<span class="fap-breadcrumb">—</span>'
    body = " › ".join(parts[:-1] + [f"<b>{parts[-1]}</b>"]) if len(parts) > 1 else f"<b>{parts[0]}</b>"
    return f'<span class="fap-breadcrumb">{body}</span>'


def nav_item_html(label: str, *, icon_name: str = "", active: bool = False) -> str:
    glyph = icon(icon_name) if icon_name else ""
    return (f'<div class="fap-nav-item{" active" if active else ""}">'
            f'{glyph}<span>{label}</span></div>')


def footer_html(items: Iterable[tuple[str, str]]) -> str:
    cells = "".join(f'<span><b>{k}:</b> {v}</span>' for k, v in items)
    return f'<div class="fap-footer">{cells}</div>'


def section_header_html(title: str, *, icon_name: str = "") -> str:
    glyph = icon(icon_name, size=20) if icon_name else ""
    return f'<h3 class="fap-section">{glyph} {title}</h3>'


def section_title_html(title: str, *, eyebrow: str = "", subtitle: str = "",
                       icon_name: str = "") -> str:
    """A page/section heading block: small uppercase eyebrow, title with an
    optional icon chip, and a muted subtitle. The professional alternative to a
    bare ``st.title`` — used at the top of every module screen."""
    chip = (f'<span class="fap-title-chip">{icon(icon_name, size=20)}</span>'
            if icon_name else "")
    eye = f'<div class="eyebrow">{eyebrow}</div>' if eyebrow else ""
    sub = f'<div class="subtitle">{subtitle}</div>' if subtitle else ""
    return (f'<div class="fap-page-head">{chip}<div class="text">{eye}'
            f'<h2 class="title">{title}</h2>{sub}</div></div>')


# ---------------------------------------------------------------- dashboard surfaces
def hero_html(greeting: str, subtitle: str = "", *, eyebrow: str = "",
              context: Sequence[tuple[str, str]] = ()) -> str:
    """The dashboard greeting hero: small eyebrow, a bold time-aware greeting, a
    muted subtitle and an optional context strip (label/value pairs)."""
    eye = f'<div class="eyebrow">{eyebrow}</div>' if eyebrow else ""
    sub = f'<div class="sub">{subtitle}</div>' if subtitle else ""
    ctx = ""
    if context:
        ctx = '<div class="ctx">' + "".join(
            f'<span><b>{lbl}</b> {val}</span>' for lbl, val in context if val) + "</div>"
    return (f'<div class="fap-hero">{eye}<div class="greet">{greeting}</div>{sub}{ctx}</div>')


def action_card_html(title: str, description: str = "", *, icon_name: str = "") -> str:
    """A professional module-launcher card: icon chip, title, concise description and
    a hover-revealed arrow. Pair it with an invisible full-cover ``st.button`` inside a
    ``st.container(key="dash_action_<id>")`` so the whole card is the click target."""
    chip = f'<span class="chip">{icon(icon_name, 18)}</span>' if icon_name else ""
    desc = f'<div class="d">{description}</div>' if description else ""
    return (f'<div class="fap-action-card">{chip}'
            f'<div class="t">{title}</div>{desc}'
            f'<span class="go">{icon("arrow-right", 16)}</span></div>')


def recent_row_html(name: str, meta: str = "", *, icon_name: str = "clock") -> str:
    """One row of the recent-analysis list: a small icon, a title, a muted meta line
    and a chevron affordance. Pair with an overlay ``st.button`` for navigation."""
    glyph = icon(icon_name, 15) if icon_name else ""
    meta_html = f'<div class="mt">{meta}</div>' if meta else ""
    return (f'<div class="fap-recent-row"><span class="ic">{glyph}</span>'
            f'<div class="main"><div class="nm">{name}</div>{meta_html}</div>'
            f'<span class="go">{icon("chevron-right", 16)}</span></div>')


# ---------------------------------------------------------------- metric surfaces
def metric_card_html(label: str, value: str, *, delta: str | None = None,
                     direction: str = "", icon_name: str = "", hint: str = "",
                     accent: str = "") -> str:
    """A premium KPI card: icon chip, label, big tabular value, optional trend
    pill and a muted hint line. ``accent`` is a CSS colour var name suffix
    (primary|success|warning|danger|info) tinting the icon chip."""
    accent_cls = f" accent-{accent}" if accent else ""
    chip = (f'<span class="fap-metric-chip{accent_cls}">{icon(icon_name, size=18)}</span>'
            if icon_name else "")
    trend = ""
    if delta:
        d = "up" if direction == "up" else "down" if direction == "down" else "flat"
        arrow = icon("arrow-up", 13) if d == "up" else icon("arrow-down", 13) if d == "down" else ""
        trend = f'<span class="fap-trend {d}">{arrow}{delta}</span>'
    hint_html = f'<div class="hint">{hint}</div>' if hint else ""
    return (f'<div class="fap-card fap-metric">'
            f'<div class="top">{chip}<div class="label">{label}</div></div>'
            f'<div class="value">{value}</div>'
            f'<div class="foot">{trend}{hint_html}</div></div>')


def stat_tile_html(label: str, value: str, *, sub: str = "") -> str:
    """A compact stat tile for dense KPI strips (tabular numerals)."""
    sub_html = f'<span class="sub">{sub}</span>' if sub else ""
    return (f'<div class="fap-stat-tile"><span class="v">{value}{sub_html}</span>'
            f'<span class="l">{label}</span></div>')


# ---------------------------------------------------------------- status badges
# One vocabulary for player/squad status across the whole app. Each entry maps a
# canonical key to (display label, badge kind, icon). Aliases fold onto a key so
# callers can pass loose values ("fit", "unavailable", "on loan"...).
_STATUS: dict[str, tuple[str, str, str]] = {
    "healthy":     ("Healthy", "success", "heart"),
    "available":   ("Available", "success", "check"),
    "fit":         ("Fit", "success", "heart"),
    "injured":     ("Injured", "danger", "cross-medical"),
    "unavailable": ("Unavailable", "danger", "x"),
    "suspended":   ("Suspended", "danger", "x"),
    "doubtful":    ("Doubtful", "warning", "help"),
    "rehab":       ("Rehab", "warning", "pulse"),
    "expiring":    ("Contract expiring", "warning", "calendar"),
    "loan":        ("Loan", "info", "link"),
    "captain":     ("Captain", "captain", "star"),
    "vice":        ("Vice-captain", "info", "star"),
    "youth":       ("Youth", "info", "flag"),
    "homegrown":   ("Homegrown", "success", "shield"),
    "international":("International", "info", "flag"),
    "new":         ("New signing", "info", "plus"),
}
_STATUS_ALIASES = {
    "on loan": "loan", "loaned": "loan", "out on loan": "loan",
    "contract expiring": "expiring", "expiring soon": "expiring",
    "not available": "unavailable", "out": "injured", "injury": "injured",
    "questionable": "doubtful", "gk": "", "captain (c)": "captain",
}


def status_badge_html(status: str, *, label: str | None = None) -> str:
    """A unified squad-status badge. ``status`` is a canonical key or a loose
    alias; ``label`` overrides the display text. Unknown status -> neutral."""
    key = (status or "").strip().lower()
    key = _STATUS_ALIASES.get(key, key)
    disp, kind, glyph = _STATUS.get(key, (label or status or "—", "neutral", ""))
    text = label if label is not None else disp
    icon_html = icon(glyph, size=13) if glyph else ""
    return f'<span class="fap-badge {kind}">{icon_html}{text}</span>'


def status_keys() -> list[str]:
    return sorted(_STATUS)


# ---------------------------------------------------------------- alerts
_ALERT_ICONS = {"info": "info", "success": "check", "warning": "warning", "danger": "warning"}


def alert_html(message: str, kind: str = "info", *, title: str = "") -> str:
    """A professional inline alert/banner (info|success|warning|danger)."""
    kind = kind if kind in _ALERT_ICONS else "info"
    glyph = icon(_ALERT_ICONS[kind], size=18)
    title_html = f'<div class="title">{title}</div>' if title else ""
    return (f'<div class="fap-alert {kind}"><span class="ico">{glyph}</span>'
            f'<div class="body">{title_html}<div class="msg">{message}</div></div></div>')


# ---------------------------------------------------------------- empty & loading
def empty_state_html(title: str, description: str = "", *, icon_name: str = "inbox",
                     action: str = "") -> str:
    """A friendly empty state: icon, title, explanation and an optional action
    hint. Pages pair this with a real ``st.button`` for the action itself."""
    desc = f'<div class="desc">{description}</div>' if description else ""
    cta = f'<div class="cta-hint">{action}</div>' if action else ""
    return (f'<div class="fap-empty"><div class="art">{icon(icon_name, size=30)}</div>'
            f'<div class="title">{title}</div>{desc}{cta}</div>')


def skeleton_html(*, lines: int = 3, card: bool = True) -> str:
    """An animated shimmer placeholder. ``lines`` bars; ``card`` wraps them in a
    card surface. Use while data loads instead of a blank screen."""
    bars = "".join(
        f'<div class="sk-line" style="width:{w}%"></div>'
        for w in ([92, 76, 60] * ((lines // 3) + 1))[:max(1, lines)])
    inner = f'<div class="fap-skeleton">{bars}</div>'
    return f'<div class="fap-card">{inner}</div>' if card else inner


def skeleton_cards_html(count: int = 3) -> str:
    """A responsive grid of shimmer cards (for card grids that are loading)."""
    one = ('<div class="fap-card fap-sk-card"><div class="sk-avatar"></div>'
           '<div class="sk-line" style="width:70%"></div>'
           '<div class="sk-line" style="width:45%"></div></div>')
    return f'<div class="fap-card-grid">{one * max(1, count)}</div>'


# ---------------------------------------------------------------- avatar & player
def avatar_html(*, photo_uri: str = "", initials: str = "", size: int = 44,
                ring: str = "") -> str:
    """A circular avatar: photo if given, else initials. ``ring`` adds a colour
    ring (e.g. availability)."""
    ring_cls = f" ring-{ring}" if ring else ""
    if photo_uri:
        inner = f'<img src="{photo_uri}" alt="" />'
    else:
        inner = f'<span class="ini">{(initials or "?")[:2].upper()}</span>'
    return (f'<span class="fap-avatar{ring_cls}" '
            f'style="width:{size}px;height:{size}px;">{inner}</span>')


def player_card_html(name: str, *, number: str | int | None = None,
                     position: str = "", nationality: str = "", age: str = "",
                     contract: str = "", minutes: str = "", photo_uri: str = "",
                     status: str = "", captain: bool = False,
                     extra_badges: Sequence[str] = ()) -> str:
    """A professional squad player card: large photo/number, name, position,
    nationality, age, contract and minutes, availability + role badges. Pure
    HTML — the whole grid is styled by the theme stylesheet."""
    num = f'<span class="num">{number}</span>' if number not in (None, "") else ""
    if photo_uri:
        media = f'<div class="photo"><img src="{photo_uri}" alt="" />{num}</div>'
    else:
        initials = "".join(p[0] for p in name.split()[:2]).upper() or "?"
        media = f'<div class="photo empty"><span class="ini">{initials}</span>{num}</div>'
    badges = []
    if captain:
        badges.append(status_badge_html("captain"))
    if status:
        badges.append(status_badge_html(status))
    badges.extend(extra_badges)
    badge_row = f'<div class="badges">{"".join(badges)}</div>' if badges else ""

    def meta(icon_name: str, val: str) -> str:
        return f'<span class="m">{icon(icon_name, 13)}{val}</span>' if val else ""

    meta_row = "".join((
        meta("map-pin", position), meta("flag", nationality),
        meta("user", age), meta("calendar", contract), meta("clock", minutes),
    ))
    return (f'<div class="fap-card fap-player-card">{media}'
            f'<div class="body"><div class="name">{name}</div>'
            f'{badge_row}<div class="meta">{meta_row}</div></div></div>')


# ---------------------------------------------------------------- scouting dossier
def player_hero_html(name: str, *, position_line: str = "", photo_uri: str = "",
                     initials: str = "?", logo_uri: str = "", badges_html: str = "",
                     operational_id: str = "", profile_name: str = "",
                     context: Sequence[tuple[str, str]] = ()) -> str:
    """The Scouting player hero: prominent photo (or initials), name + position,
    a recruitment badge strip (pathway/status/priority + profile), the operational
    id, a football-context line and an optional club crest. Pure HTML — layout and
    theming live in the ``_scouting_dossier`` stylesheet."""
    if photo_uri:
        media = f'<img src="{photo_uri}" alt="" />'
    else:
        media = f'<span class="ini">{(initials or "?")[:3].upper()}</span>'
    prof = f'<span class="prof">{profile_name}</span>' if profile_name else ""
    badges = f'<div class="badges">{badges_html}{prof}</div>' if (badges_html or prof) else ""
    idrow = f'<div class="idrow">{operational_id}</div>' if operational_id else ""
    ctx = ""
    if context:
        ctx = '<div class="ctx">' + "".join(
            f'<span><b>{lbl}</b> {val}</span>' for lbl, val in context if val) + "</div>"
    pos = f'<div class="pos">{position_line}</div>' if position_line else ""
    logo = f'<div class="club"><img src="{logo_uri}" alt="" /></div>' if logo_uri else ""
    return (f'<div class="fap-player-hero"><div class="ph">{media}</div>'
            f'<div class="hero-main"><div class="nm">{name}</div>{pos}'
            f'{badges}{idrow}{ctx}</div>{logo}</div>')


def dossier_stat_html(label: str, value: str, *, sub: str = "", icon: str = "") -> str:
    """One compact snapshot cell (icon over label over value) — a dossier field, not
    a KPI card. ``sub`` renders a muted unit/qualifier; ``icon`` is icon HTML (SVG)."""
    sub_html = f' <small>{sub}</small>' if sub else ""
    ic = f'<span class="ic">{icon}</span>' if icon else ""
    return (f'<div class="fap-dstat">{ic}<div class="l">{label}</div>'
            f'<div class="v">{value}{sub_html}</div></div>')


def dossier_grid_html(tiles: Sequence[str]) -> str:
    """A seamless compact grid of snapshot cells (thin 1px dividers)."""
    return f'<div class="fap-dossier-grid">{"".join(tiles)}</div>'


def intel_strip_html(items: Sequence[tuple]) -> str:
    """The recruitment-intelligence strip. Each item is a tuple:
    ``(label, value, kind[, icon_html[, bar_pct]])`` — kind ∈ {'', 'good', 'warn',
    'muted', 'fit'} tints/emphasizes the cell; ``icon_html`` is optional icon SVG;
    ``bar_pct`` (0..100) renders an orange progress bar (used for Profile Fit)."""
    cells = []
    for it in items:
        label, value, kind = it[0], it[1], it[2]
        icon_html = it[3] if len(it) > 3 else ""
        bar = it[4] if len(it) > 4 else None
        k = f" {kind}" if kind in ("good", "warn", "muted", "fit") else ""
        ic = f'<span class="ic">{icon_html}</span>' if icon_html else ""
        bar_html = ""
        if bar is not None:
            w = max(0.0, min(100.0, float(bar)))
            bar_html = f'<div class="bar"><span style="width:{w:.0f}%"></span></div>'
        cells.append(f'<div class="fap-intel{k}">{ic}<div class="l">{label}</div>'
                     f'<div class="v">{value}</div>{bar_html}</div>')
    return f'<div class="fap-intel-strip">{"".join(cells)}</div>'


def snapshot_counts_html(items: Sequence[tuple[str, str, str]]) -> str:
    """The intelligence-snapshot counts row. ``items`` are (icon_html, value, label)
    — real persisted totals (data sources / matches / videos / visuals / reports)."""
    cells = [f'<div class="fap-snap-count"><span class="ic">{ic}</span>'
             f'<span class="v">{v}</span><span class="l">{lbl}</span></div>'
             for ic, v, lbl in items]
    return f'<div class="fap-snap-counts">{"".join(cells)}</div>'


def evidence_card_html(title: str, meta: str = "", *, icon: str = "") -> str:
    """A compact read-only evidence preview card (video/match) for the dossier."""
    ic = f'<span class="ic">{icon}</span>' if icon else ""
    m = f'<div class="m">{meta}</div>' if meta else ""
    return (f'<div class="fap-ev-card">{ic}<div class="bd"><div class="t">{title}</div>{m}</div></div>')


def dossier_label_html(text: str, *, icon: str = "") -> str:
    """A thin uppercase section label used between dossier blocks (optional icon)."""
    ic = f'<span class="ic">{icon}</span>' if icon else ""
    return f'<div class="fap-dossier-label">{ic}{text}</div>'


# ---------------------------------------------------------------- misc chrome
def chip_html(text: str, *, icon_name: str = "", active: bool = False) -> str:
    glyph = icon(icon_name, 13) if icon_name else ""
    return f'<span class="fap-chip{" active" if active else ""}">{glyph}{text}</span>'


def progress_html(pct: float, *, kind: str = "primary", label: str = "") -> str:
    pct = max(0.0, min(100.0, float(pct)))
    lab = f'<span class="pl">{label}</span>' if label else ""
    return (f'<div class="fap-progress {kind}">{lab}'
            f'<div class="track"><div class="fill" style="width:{pct:.0f}%"></div></div></div>')


# ---------------------------------------------------------------- render wrappers
def _write(html: str) -> None:
    import streamlit as st
    st.markdown(html, unsafe_allow_html=True)


def render_kpi_card(label: str, value: str, **kwargs) -> None:
    _write(kpi_card_html(label, value, **kwargs))


def render_badge(text: str, kind: str = "neutral", **kwargs) -> None:
    _write(badge_html(text, kind, **kwargs))


def render_breadcrumb(items: Sequence[str]) -> None:
    _write(breadcrumb_html(items))


def render_footer(items: Iterable[tuple[str, str]]) -> None:
    _write(footer_html(items))


def render_section_title(title: str, **kwargs) -> None:
    _write(section_title_html(title, **kwargs))


def render_hero(greeting: str, subtitle: str = "", **kwargs) -> None:
    _write(hero_html(greeting, subtitle, **kwargs))


def render_metric_card(label: str, value: str, **kwargs) -> None:
    _write(metric_card_html(label, value, **kwargs))


def render_metric_row(cards: Sequence[str]) -> None:
    """Render a responsive equal-width grid of pre-built metric-card HTML."""
    _write(f'<div class="fap-metric-grid">{"".join(cards)}</div>')


def render_status_badge(status: str, **kwargs) -> None:
    _write(status_badge_html(status, **kwargs))


def render_alert(message: str, kind: str = "info", **kwargs) -> None:
    _write(alert_html(message, kind, **kwargs))


def render_skeleton(*, lines: int = 3, card: bool = True) -> None:
    _write(skeleton_html(lines=lines, card=card))


def render_skeleton_cards(count: int = 3) -> None:
    _write(skeleton_cards_html(count))


def render_player_card(name: str, **kwargs) -> None:
    _write(player_card_html(name, **kwargs))


def render_player_hero(name: str, **kwargs) -> None:
    _write(player_hero_html(name, **kwargs))


def render_dossier_grid(tiles: Sequence[str]) -> None:
    _write(dossier_grid_html(tiles))


def render_intel_strip(items: Sequence[tuple]) -> None:
    _write(intel_strip_html(items))


def render_snapshot_counts(items: Sequence[tuple[str, str, str]]) -> None:
    _write(snapshot_counts_html(items))


def render_dossier_label(text: str, *, icon: str = "") -> None:
    _write(dossier_label_html(text, icon=icon))


def render_empty_state(title: str, description: str = "", *, icon_name: str = "inbox",
                       action_label: str = "", key: str | None = None) -> bool:
    """Render a centered empty state. If ``action_label`` is given, a real
    Streamlit button is rendered under it and this returns True when clicked —
    so "never a blank screen" also means "always a way forward"."""
    import streamlit as st
    _write(empty_state_html(title, description, icon_name=icon_name))
    if action_label:
        cols = st.columns([1, 1, 1])
        with cols[1]:
            return st.button(action_label, key=key, use_container_width=True,
                             type="primary")
    return False
