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
