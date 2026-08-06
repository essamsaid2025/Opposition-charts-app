"""Map the app's generic chart Theme onto the Tactical Board's colour roles.

The board palette (``render.DEFAULT_COLORS``) uses tactical-specific roles
(grass, home, away, cone, mannequin, …) while ``fap.themes.Theme`` carries the
generic chart roles (bg, pitch, stripe, accent, accent_2, warning, …). There is
no 1:1 match, so this is a deliberate mapping, not a rename. Every tactical key
is always produced; any theme key this mapping needs but the theme lacks falls
back to the corresponding ``DEFAULT_COLORS`` value, so an incomplete/malformed
theme degrades per key instead of crashing.

Reasoning for the mapping (see the table in the code):
* ``pitch`` is the grass; the alternating mowing stripe uses ``stripe`` when the
  theme actually differs there, otherwise a subtly shaded variant of the grass
  (lightened for dark pitches, darkened for light ones) so stripes stay visible.
* ``lines`` (fallback ``grid``) are the pitch markings and the goal frame.
* ``accent``/``accent_2`` are the two team colours (home/away) - the same two
  hues the rest of the app already uses for the primary/secondary series.
* ``warning`` (a caution hue) -> cones; ``grey`` -> mannequins; ``success`` ->
  zone highlights; ``text`` -> labels; ``accent`` -> the captain/accent marks.
* ``ball``/``ball_line`` stay fixed white/dark: a themed ball reads worse than a
  real football, and the theme has no better-suited role for it.
"""
from __future__ import annotations

from typing import Any

from fap.tactical.render import DEFAULT_COLORS


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = str(hex_color).lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _hex(r: int, g: int, b: int) -> str:
    clamp = lambda v: max(0, min(255, int(v)))
    return f"#{clamp(r):02x}{clamp(g):02x}{clamp(b):02x}"


def _stripe_variant(pitch_hex: str) -> str:
    """A subtly different shade of the grass for the alternating mowing stripe:
    lighten a dark pitch, darken a light one, so the stripe is always visible."""
    try:
        r, g, b = _rgb(pitch_hex)
    except (ValueError, IndexError):
        return DEFAULT_COLORS["grass_alt"]
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
    f = 1.12 if luminance < 0.5 else 0.90
    return _hex(r * f, g * f, b * f)


def _pick(theme_colors: dict[str, str], key: str, fallback: str) -> str:
    v = theme_colors.get(key)
    return v if isinstance(v, str) and v.strip() else fallback


def tactical_colors_from_theme(theme: Any) -> dict[str, str]:
    """Return a COMPLETE tactical colour dict from a ``fap.themes.Theme`` (or any
    object exposing ``.colors``). Missing theme keys fall back per key to
    ``DEFAULT_COLORS`` — this never raises on an incomplete theme."""
    d = DEFAULT_COLORS
    tc = dict(getattr(theme, "colors", None) or {})

    grass = _pick(tc, "pitch", d["grass"])
    stripe = tc.get("stripe")
    if isinstance(stripe, str) and stripe.strip() and stripe.lower() != grass.lower():
        grass_alt = stripe                           # theme actually distinguishes the stripe
    else:
        grass_alt = _stripe_variant(grass)           # derive a visible variant from the grass

    # theme role            -> tactical role
    return {
        "bg": _pick(tc, "bg", d["bg"]),              # bg        -> bg
        "grass": grass,                              # pitch     -> grass
        "grass_alt": grass_alt,                      # stripe    -> grass_alt (derived if absent)
        "line": _pick(tc, "lines", _pick(tc, "grid", d["line"])),   # lines/grid -> line
        "home": _pick(tc, "accent", d["home"]),      # accent    -> home team
        "away": _pick(tc, "accent_2", d["away"]),    # accent_2  -> away team
        "ball": d["ball"],                           # fixed white
        "ball_line": d["ball_line"],                 # fixed dark
        "cone": _pick(tc, "warning", d["cone"]),     # warning   -> cone
        "goal": _pick(tc, "lines", d["goal"]),       # lines     -> goal frame
        "text": _pick(tc, "text", d["text"]),        # text      -> labels
        "accent": _pick(tc, "accent", d["accent"]),  # accent    -> captain/accent marks
        "zone": _pick(tc, "success", d["zone"]),     # success   -> zone highlight
        "mannequin": _pick(tc, "grey", d["mannequin"]),  # grey  -> mannequin
    }
