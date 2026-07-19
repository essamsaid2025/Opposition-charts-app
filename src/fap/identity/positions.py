"""Positions - the club job title a user holds.

A Position is INFORMATIONAL and is deliberately NOT a Role: permissions come
from roles/capabilities, positions describe what someone does in the club. They
are shown in the directory and can drive reporting, never authorization.
"""
from __future__ import annotations

# Ordered for display; extend freely - positions never gate access.
POSITIONS: tuple[str, ...] = (
    "Sporting Director",
    "Technical Director",
    "CEO",
    "Head Coach",
    "Assistant Coach",
    "Goalkeeping Coach",
    "Opponent Analyst",
    "Performance Analyst",
    "First Team Analyst",
    "Academy Analyst",
    "Scout",
    "Academy Scout",
    "Recruitment Analyst",
    "Medical Staff",
    "Read Only",
    "Guest",
)

DEFAULT_POSITION = "Guest"


def normalize_position(value: str | None) -> str:
    if not value:
        return DEFAULT_POSITION
    v = str(value).strip()
    for p in POSITIONS:
        if p.lower() == v.lower():
            return p
    return v            # allow custom position labels; still informational only
