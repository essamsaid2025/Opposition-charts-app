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
    # -- domain & status icons (football / squad / medical / calendar) --------
    "whistle": '<path d="M14 8a5 5 0 1 0 0 8h5a2 2 0 0 0 2-2v-4a2 2 0 0 0-2-2z"/><path d="M14 3v3M10 3v3M18 3v3"/>',
    "heart": '<path d="M12 20s-7-4.4-9.2-8.4A4.6 4.6 0 0 1 12 6a4.6 4.6 0 0 1 9.2 5.6C19 15.6 12 20 12 20z"/>',
    "pulse": '<path d="M3 12h4l2-6 4 12 2-6h6"/>',
    "cross-medical": '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M12 8v8M8 12h8"/>',
    "calendar": '<rect x="3" y="4" width="18" height="17" rx="2"/><path d="M3 9h18M8 2v4M16 2v4"/>',
    "jersey": '<path d="M8 3l-5 3 2 4 2-1v11h10V9l2 1 2-4-5-3a3 3 0 0 1-6 0z"/>',
    "flag": '<path d="M5 3v18"/><path d="M5 4h11l-2 3 2 3H5"/>',
    "trophy": '<path d="M7 4h10v4a5 5 0 0 1-10 0z"/><path d="M7 6H4v2a3 3 0 0 0 3 3M17 6h3v2a3 3 0 0 1-3 3M9 20h6M10 15h4v5h-4z"/>',
    "video": '<rect x="3" y="6" width="13" height="12" rx="2"/><path d="M16 10l5-3v10l-5-3z"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "edit": '<path d="M4 20h4l10-10-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>',
    "trash": '<path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13"/>',
    "eye": '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/>',
    "arrow-up": '<path d="M12 19V5M6 11l6-6 6 6"/>',
    "arrow-down": '<path d="M12 5v14M6 13l6 6 6-6"/>',
    "arrow-right": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "grid": '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    "list": '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "moon": '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
    "sliders": '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>',
    "layers": '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
    "target": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
    "shield": '<path d="M12 3l8 3v6c0 5-3.4 8-8 9-4.6-1-8-4-8-9V6z"/>',
    "flame": '<path d="M12 3c1 3-2 4-2 7a2 2 0 0 0 4 0c2 2 3 3.5 3 6a5 5 0 0 1-10 0c0-4 3-6 5-13z"/>',
    "link": '<path d="M9 15l6-6M8 12l-2 2a3 3 0 0 0 4 4l2-2M16 12l2-2a3 3 0 0 0-4-4l-2 2"/>',
    "external": '<path d="M14 4h6v6M20 4l-8 8M18 13v6a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h6"/>',
    "more": '<circle cx="5" cy="12" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="19" cy="12" r="1.4"/>',
    "sort": '<path d="M8 4v16M8 4L4 8M8 4l4 4M16 20V4M16 20l-4-4M16 20l4-4"/>',
    "x": '<path d="M6 6l12 12M18 6L6 18"/>',
    "refresh": '<path d="M4 12a8 8 0 0 1 14-5l2 2M20 12a8 8 0 0 1-14 5l-2-2M18 3v6h-6M6 21v-6h6"/>',
    "spinner": '<path d="M12 3a9 9 0 1 0 9 9" opacity="0.9"/>',
    "lightning": '<path d="M13 3L4 14h6l-1 7 9-11h-6z"/>',
    "map-pin": '<path d="M12 21s7-5.6 7-11a7 7 0 0 0-14 0c0 5.4 7 11 7 11z"/><circle cx="12" cy="10" r="2.5"/>',
    "book": '<path d="M4 5a2 2 0 0 1 2-2h12v18H6a2 2 0 0 1-2-2z"/><path d="M8 3v18"/>',
    "inbox": '<path d="M3 12h5l2 3h4l2-3h5"/><path d="M5 5h14l2 7v6a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-6z"/>',
    # -- tactical-board object glyphs (purpose-built for the Object Library rail) --------
    "ball": '<circle cx="12" cy="12" r="8.5"/><path d="M12 12V7M12 12l4.3 2.5M12 12l-4.3 2.5"/>',
    "cone": '<path d="M12 5l3.5 12h-7z"/><path d="M6.5 20h11"/><path d="M10 13h4"/>',
    "goal": '<path d="M4 6v13M20 6v13M4 6h16"/><path d="M4 12h16M9 6v13M15 6v13" opacity="0.4"/>',
    "mannequin": '<circle cx="12" cy="5.5" r="2.5"/><rect x="9" y="9" width="6" height="9" rx="2"/><ellipse cx="12" cy="20" rx="5" ry="1.5"/>',
    "line-straight": '<path d="M5 19L19 5"/><circle cx="5" cy="19" r="1.4"/><circle cx="19" cy="5" r="1.4"/>',
    "arrow-curved": '<path d="M4 19C4 11 9 5 19 5"/><path d="M15.5 2.5L19 5l-3.5 2.5"/>',
    "arrow-dashed": '<path d="M3 12h13" stroke-dasharray="3 3"/><path d="M13 7l5 5-5 5"/>',
    "zone-marker": '<rect x="3.5" y="6.5" width="17" height="11" rx="2" fill="currentColor" fill-opacity="0.2"/><path d="M12 6.5v11" opacity="0.5"/>',
    "shapes": '<circle cx="7" cy="8" r="3.4"/><path d="M15.5 4l4 7h-8z"/><rect x="12" y="13" width="8" height="8" rx="1.5"/>',
    "arrow-straight": '<path d="M4 20L20 4"/><path d="M12 4h8v8"/>',
    "circle": '<circle cx="12" cy="12" r="8.5"/>',
    # subtle fill (like zone-marker) so this reads clearly when rendered as a small CSS
    # mask-image in the tactical rail — a pure 2px outline nearly vanishes at ~20px. Used only
    # in the Tactical Board rail (Shapes category + shape tool), so the light fill is consistent.
    "square": '<rect x="4.5" y="4.5" width="15" height="15" rx="2" '
              'fill="currentColor" fill-opacity="0.18"/>',
    "text": '<path d="M5 5h14"/><path d="M12 5v14"/><path d="M9 19h6"/>',
}


def icon_names() -> list[str]:
    return sorted(_PATHS)


def has_icon(name: str) -> bool:
    return name in _PATHS


def icon(name: str, size: int = 18, stroke: float = 2.0,
         color: str = "currentColor") -> str:
    # 2.0 stroke + round caps/joins on a 24px grid == the Lucide house style,
    # so the whole registry reads as one consistent modern icon set.
    """Inline SVG for ``name`` (empty string for unknown names, so a missing
    icon never breaks a layout)."""
    inner = _PATHS.get(name)
    if inner is None:
        return ""
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
            f'stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" '
            f'stroke-linejoin="round" class="fap-icon fap-icon-{name}">{inner}</svg>')
