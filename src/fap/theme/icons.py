"""Centralized icon registry - inline SVG, no emoji, no duplicates.

One name -> one 24x24 stroke icon. Components ask for icons by name so the set
stays consistent and swappable. ``icon(name)`` returns an inline ``<svg>`` that
inherits ``currentColor``, so it takes the surrounding text colour.
"""
from __future__ import annotations

# Each value is the inner markup of a 24x24, stroke-based icon (viewBox 0 0 24 24).
_PATHS: dict[str, str] = {
    "dashboard": '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
    "analysis": '<path d="M3 3v18h18"/><path d="M7 14l3-4 3 3 4-6"/>',
    "match": '<circle cx="12" cy="12" r="9"/><path d="M12 3v18M3 12h18"/>',
    "setpiece": '<circle cx="12" cy="12" r="9"/><path d="M8 12h8M12 8v8"/>',
    "scouting": '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',
    "players": '<circle cx="12" cy="8" r="3.2"/><path d="M5 20c0-3.5 3.1-5.5 7-5.5s7 2 7 5.5"/>',
    "teams": '<circle cx="8" cy="9" r="2.6"/><circle cx="16" cy="9" r="2.6"/><path d="M3 19c0-2.6 2.2-4 5-4M21 19c0-2.6-2.2-4-5-4"/>',
    "projects": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "datasets": '<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
    "reports": '<path d="M6 3h9l5 5v13a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/><path d="M15 3v5h5M9 13h6M9 17h6"/>',
    "templates": '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M4 9h16M9 9v11"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/>',
    "admin": '<path d="M12 3l8 3v6c0 5-3.4 8-8 9-4.6-1-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',
    "bell": '<path d="M6 9a6 6 0 0 1 12 0c0 5 2 6 2 6H4s2-1 2-6z"/><path d="M10 19a2 2 0 0 0 4 0"/>',
    "user": '<circle cx="12" cy="8" r="3.5"/><path d="M5 20c0-3.5 3.1-5.5 7-5.5s7 2 7 5.5"/>',
    "logout": '<path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3"/><path d="M10 12H3M6 8l-3 4 3 4"/>',
    "chevron-left": '<path d="M15 6l-6 6 6 6"/>',
    "chevron-right": '<path d="M9 6l6 6-6 6"/>',
    "chevron-down": '<path d="M6 9l6 6 6-6"/>',
    "menu": '<path d="M4 7h16M4 12h16M4 17h16"/>',
    "upload": '<path d="M12 16V4M8 8l4-4 4 4"/><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/>',
    "download": '<path d="M12 4v12M8 12l4 4 4-4"/><path d="M4 18v1a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-1"/>',
    "filter": '<path d="M3 5h18l-7 8v6l-4-2v-4z"/>',
    "pin": '<path d="M9 3h6l-1 6 3 3v2H7v-2l3-3z"/><path d="M12 14v7"/>',
    "star": '<path d="M12 3l2.9 5.9 6.1.9-4.4 4.3 1 6.1L12 17.8 6.4 20.2l1-6.1L3 9.8l6.1-.9z"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "home": '<path d="M4 11l8-7 8 7"/><path d="M6 10v9a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1v-9"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.8.4-1 .9-1 1.7"/><path d="M12 17h.01"/>',
    "check": '<path d="M5 12l5 5 9-11"/>',
    "warning": '<path d="M12 3l9 16H3z"/><path d="M12 10v4M12 17h.01"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
}


def icon_names() -> list[str]:
    return sorted(_PATHS)


def has_icon(name: str) -> bool:
    return name in _PATHS


def icon(name: str, size: int = 18, stroke: float = 1.8,
         color: str = "currentColor") -> str:
    """Inline SVG for ``name`` (empty string for unknown names, so a missing
    icon never breaks a layout)."""
    inner = _PATHS.get(name)
    if inner is None:
        return ""
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
            f'stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" '
            f'stroke-linejoin="round" class="fap-icon fap-icon-{name}">{inner}</svg>')
