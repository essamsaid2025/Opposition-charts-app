"""Coordinate systems as plugins + automatic detection.

Canonical internal space: x 0-100 (attack left->right), y 0-100 (0 = right
touchline from the attacking view, matching the previous app convention).
Every vendor convention normalizes INTO this space exactly once; nothing
downstream ever sees a vendor coordinate again.
"""
from __future__ import annotations

from abc import abstractmethod

import pandas as pd

from fap.core.plugin import Plugin, PluginInfo, PluginRegistry

_COORD_COLS = (("x", "y"), ("end_x", "end_y"), ("x2", "y2"))


class CoordinateSystem(Plugin):
    @abstractmethod
    def to_canonical(self, df: pd.DataFrame) -> pd.DataFrame:
        """Convert x/y/end_x/end_y (and legacy x2/y2) into 0-100 space in place."""


coord_registry: PluginRegistry[CoordinateSystem] = PluginRegistry("coordinate_system")


def _scale(df: pd.DataFrame, fx, fy) -> pd.DataFrame:
    for xcol, ycol in _COORD_COLS:
        if xcol in df.columns:
            df[xcol] = fx(pd.to_numeric(df[xcol], errors="coerce"))
        if ycol in df.columns:
            df[ycol] = fy(pd.to_numeric(df[ycol], errors="coerce"))
    return df


@coord_registry.register
class Canonical(CoordinateSystem):
    info = PluginInfo(id="0-100", name="0-100 (canonical)", category="coords")

    def to_canonical(self, df: pd.DataFrame) -> pd.DataFrame:
        return df


@coord_registry.register
class StatsBomb(CoordinateSystem):
    """120 x 80, y measured top-down -> invert y."""
    info = PluginInfo(id="statsbomb", name="StatsBomb (120 x 80)", category="coords")

    def to_canonical(self, df: pd.DataFrame) -> pd.DataFrame:
        return _scale(df, lambda x: x / 120 * 100, lambda y: (80 - y) / 80 * 100)


@coord_registry.register
class Generic120x80(CoordinateSystem):
    info = PluginInfo(id="120x80", name="120 x 80", category="coords")

    def to_canonical(self, df: pd.DataFrame) -> pd.DataFrame:
        return _scale(df, lambda x: x / 120 * 100, lambda y: y / 80 * 100)


@coord_registry.register
class Opta(CoordinateSystem):
    """Opta already uses 0-100 on both axes."""
    info = PluginInfo(id="opta", name="Opta (0-100)", category="coords")

    def to_canonical(self, df: pd.DataFrame) -> pd.DataFrame:
        return df


@coord_registry.register
class Wyscout(CoordinateSystem):
    """0-100 percentages, y measured top-down -> invert y."""
    info = PluginInfo(id="wyscout", name="Wyscout (0-100, y inverted)", category="coords")

    def to_canonical(self, df: pd.DataFrame) -> pd.DataFrame:
        return _scale(df, lambda x: x, lambda y: 100 - y)


@coord_registry.register
class Metrica(CoordinateSystem):
    """Metrica Sports: 0-1 normalized, y top-down."""
    info = PluginInfo(id="metrica", name="Metrica (0-1)", category="coords")

    def to_canonical(self, df: pd.DataFrame) -> pd.DataFrame:
        return _scale(df, lambda x: x * 100, lambda y: (1 - y) * 100)


@coord_registry.register
class Meters105x68(CoordinateSystem):
    """Absolute meters, origin at a corner (105 x 68)."""
    info = PluginInfo(id="105x68", name="105 x 68 meters", category="coords")

    def to_canonical(self, df: pd.DataFrame) -> pd.DataFrame:
        return _scale(df, lambda x: x / 105 * 100, lambda y: y / 68 * 100)


class _CenteredMeters(CoordinateSystem):
    """Meters with origin at the center spot (±52.5, ±34)."""

    def to_canonical(self, df: pd.DataFrame) -> pd.DataFrame:
        return _scale(df, lambda x: (x + 52.5) / 105 * 100, lambda y: (y + 34) / 68 * 100)


@coord_registry.register
class SkillCorner(_CenteredMeters):
    info = PluginInfo(id="skillcorner", name="SkillCorner (centered meters)", category="coords")


@coord_registry.register
class SecondSpectrum(_CenteredMeters):
    info = PluginInfo(id="second_spectrum", name="Second Spectrum (centered meters)", category="coords")


@coord_registry.register
class Tracab(CoordinateSystem):
    """Centimeters with origin at the center spot (Tracab/ChyronHego)."""
    info = PluginInfo(id="tracab", name="Tracab (centered centimeters)", category="coords")

    def to_canonical(self, df: pd.DataFrame) -> pd.DataFrame:
        return _scale(df, lambda x: (x / 100 + 52.5) / 105 * 100, lambda y: (y / 100 + 34) / 68 * 100)


# ------------------------------------------------------------------ detection
def detect_coordinate_system(df: pd.DataFrame) -> tuple[str, float]:
    """Heuristic detection from value ranges. Returns (system_id, confidence)."""
    xs = pd.concat([pd.to_numeric(df.get(c), errors="coerce")
                    for c in ("x", "end_x", "x2") if c in df.columns]).dropna()
    ys = pd.concat([pd.to_numeric(df.get(c), errors="coerce")
                    for c in ("y", "end_y", "y2") if c in df.columns]).dropna()
    if xs.empty or ys.empty:
        return "0-100", 0.0
    xmin, xmax, ymin, ymax = xs.min(), xs.max(), ys.min(), ys.max()

    if xmin >= 0 and xmax <= 1.05 and ymax <= 1.05:
        return "metrica", 0.95
    if xmin < -200 or xmax > 200:                       # centimeter magnitudes
        return "tracab", 0.9
    if xmin < -1 or ymin < -1:                          # centered meters
        return "skillcorner", 0.8
    if xmax > 105 and xmax <= 121 and ymax <= 81:
        return "statsbomb", 0.85
    if xmax > 100 and xmax <= 106 and ymax <= 69:
        return "105x68", 0.85
    if xmax <= 100 and ymax <= 100:
        return "0-100", 0.9 if xmax > 68 or ymax > 68 else 0.6
    return "0-100", 0.3


def load_builtin_coordinate_systems() -> None:
    """Registration happens at import; this exists for symmetric bootstrap calls."""
