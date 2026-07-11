"""LayerContext - everything a rendering layer receives.

Layers never touch Streamlit, never load themes, never compute coordinates
themselves: they read data + styling from here and draw on ctx.ax.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from fap.visuals.legend import LegendEngine
from fap.visuals.pitch import DISPLAY_WIDTH, PitchSpec
from fap.visuals.tokens import StyleTokens


@dataclass(slots=True)
class LayerContext:
    fig: Figure
    ax: Axes
    df: pd.DataFrame
    theme: Any
    tokens: StyleTokens
    controls: dict[str, Any]
    pitch_spec: PitchSpec
    view: str = "full"
    vertical: bool = False
    legend: LegendEngine = field(default_factory=LegendEngine)
    _memo: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------ styling
    def style(self, key: str, default: Any = None) -> Any:
        """Resolution chain: control value > theme token > framework default."""
        value = self.controls.get(key)
        if value is not None:
            return value
        return self.tokens.get(key, default)

    def color(self, key: str, fallback: str = "accent") -> str:
        return self.controls.get(key) or self.theme.colors.get(key) \
            or self.theme.colors[fallback]

    # ------------------------------------------------------------ coordinates
    def to_display(self, x: Any, y: Any) -> tuple[np.ndarray, np.ndarray]:
        """Canonical (0-100, 0-100) -> display coords, honoring orientation."""
        dx = np.asarray(pd.to_numeric(pd.Series(x), errors="coerce"), dtype=float)
        dy = np.asarray(pd.to_numeric(pd.Series(y), errors="coerce"), dtype=float) \
            * DISPLAY_WIDTH / 100.0
        return (dy, dx) if self.vertical else (dx, dy)

    # ------------------------------------------------------------ performance
    def memo(self, key: str, compute: Callable[[], Any]) -> Any:
        """Per-render memo so expensive layer computations (histograms, hulls,
        voronoi) run once even when several layers share them."""
        if key not in self._memo:
            self._memo[key] = compute()
        return self._memo[key]
