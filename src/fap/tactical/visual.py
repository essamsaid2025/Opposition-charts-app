"""Centralized visual tokens for the Tactical Board object system (Phase 5C).

ONE source of truth for object SIZING + SELECTION styling + team/role COLOUR
resolution, shared by BOTH renderers so the live board, SVG export and PNG export
show the same marker:

  - ``fap.tactical.render``        (SVG — authoritative; also drives the live JS board)
  - ``fap.tactical.export_render`` (matplotlib — PNG/PDF, kept in lockstep)

Colour *values* stay in ``render.DEFAULT_COLORS`` (theme-overridable); this module
adds the sizing/geometry/selection spec plus the helpers that pick the right colour
role for a player. Pure values + functions — no Streamlit, no engine, no persistence.

Backward compatible by construction: every helper reads ``props`` defensively, so an
old object with missing visual props simply gets the safe default here — no migration.
"""
from __future__ import annotations

# --- object sizing (1050x680 authoring plane; 10px == 1 pitch unit) --------------
PLAYER_R = 17.0
BALL_R = 9.0

# --- selection ring (single = Python SVG; multi = JS overlay in index.html, kept
#     visually identical to these numbers) -------------------------------------
SELECT_HALO_R = 28.0
SELECT_RING_R = 24.0
SELECT_HALO_WIDTH = 6.0
SELECT_RING_WIDTH = 2.5
SELECT_HALO_OPACITY = 0.22

# --- label typography ------------------------------------------------------------
NUMBER_SCALE = 0.92     # font-size as a fraction of the marker radius
NAME_SIZE = 12.0


def is_goalkeeper(props) -> bool:
    return bool((props or {}).get("goalkeeper"))


def team_role(props) -> str:
    """Colour role for a player marker: ``"gk"`` | ``"away"`` | ``"home"``."""
    p = props or {}
    if p.get("goalkeeper"):
        return "gk"
    return "away" if p.get("team") == "away" else "home"


def player_fill(colors: dict, props) -> str:
    """Disc colour: an explicit ``props["color"]`` override wins, else the role colour
    (home / away / goalkeeper) from the resolved theme palette."""
    p = props or {}
    if p.get("color"):
        return p["color"]
    key = team_role(p)                      # "gk" | "away" | "home" — all live in colours
    return colors.get(key) or colors.get("home") or "#e07b2b"


def ink_for(hex_color: str) -> str:
    """A readable detail colour for text/number ON the given fill: dark ink on light
    fills, light ink on dark fills (relative-luminance threshold)."""
    try:
        h = str(hex_color).lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        return "#10131a" if lum > 150 else "#ffffff"
    except Exception:
        return "#ffffff"
