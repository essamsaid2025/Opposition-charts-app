"""Coordinate systems as plugins. Vendors disagree (0-100, 120x80, 105x68...);
each convention is one small class. The canonical internal space is 0-100."""
from __future__ import annotations

from abc import abstractmethod

import pandas as pd

from fap.core.plugin import Plugin, PluginInfo, PluginRegistry


class CoordinateSystem(Plugin):
    @abstractmethod
    def to_canonical(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return a copy with x/y/x2/y2 expressed in 0-100 canonical space."""


coord_registry: PluginRegistry[CoordinateSystem] = PluginRegistry("coordinate_system")


@coord_registry.register
class Canonical(CoordinateSystem):
    info = PluginInfo(id="0-100", name="0-100 (canonical)", category="coords")

    def to_canonical(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.copy()


@coord_registry.register
class StatsBombLike(CoordinateSystem):
    info = PluginInfo(id="120x80", name="120 x 80", category="coords")

    def to_canonical(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        for col, maxv in (("x", 120), ("x2", 120), ("y", 80), ("y2", 80)):
            if col in df.columns:
                df[col] = df[col] / maxv * 100
        return df


def load_builtin_coordinate_systems() -> None:
    """Registration happens at import; this exists for symmetric bootstrap calls."""
