"""Legend Engine: automatic (layers register entries while drawing), manual
entries, grouping, custom ordering and hide/show - one consistent legend for
every visualization."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from matplotlib.axes import Axes
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from fap.visuals.tokens import StyleTokens

POSITIONS: dict[str, dict[str, Any]] = {
    "bottom": {"loc": "lower center", "bbox_to_anchor": (0.5, -0.09)},
    "top": {"loc": "upper center", "bbox_to_anchor": (0.5, 1.06)},
    "left": {"loc": "center left", "bbox_to_anchor": (-0.05, 0.5)},
    "right": {"loc": "center right", "bbox_to_anchor": (1.05, 0.5)},
    "inside": {"loc": "best"},
}


@dataclass(slots=True)
class LegendEntry:
    label: str
    kind: str = "marker"             # marker | line | patch
    color: str = "#888888"
    marker: str = "o"
    linestyle: str = "-"
    group: str = ""
    order: int = 100
    visible: bool = True


class LegendEngine:
    def __init__(self) -> None:
        self._entries: dict[str, LegendEntry] = {}

    # ------------------------------------------------------------ collection
    def add(self, label: str, *, kind: str = "marker", color: str = "#888888",
            marker: str = "o", linestyle: str = "-", group: str = "",
            order: int = 100, visible: bool = True) -> None:
        if label and label not in self._entries:
            self._entries[label] = LegendEntry(label, kind, color, marker,
                                               linestyle, group, order, visible)

    def add_manual(self, entries: list[dict[str, Any]]) -> None:
        for e in entries:
            self.add(**e)

    def hide(self, *labels: str) -> None:
        for label in labels:
            if label in self._entries:
                self._entries[label].visible = False

    def reorder(self, ordering: list[str]) -> None:
        for i, label in enumerate(ordering):
            if label in self._entries:
                self._entries[label].order = i

    @property
    def entries(self) -> list[LegendEntry]:
        return sorted((e for e in self._entries.values() if e.visible),
                      key=lambda e: (e.group, e.order, e.label))

    # ------------------------------------------------------------ rendering
    def build(self, ax: Axes, theme: Any, tokens: StyleTokens, *,
              position: str = "bottom", ncol: int | None = None,
              title: str | None = None) -> None:
        entries = self.entries
        if not entries:
            return
        handles = [self._handle(e) for e in entries]
        kwargs = dict(POSITIONS.get(position, POSITIONS["bottom"]))
        legend = ax.legend(
            handles=handles, ncol=ncol or min(int(tokens.get("legend_ncol")), len(entries)),
            fontsize=tokens.get("legend_size"), facecolor=theme.colors["panel"],
            edgecolor=theme.colors["grid"], labelcolor=theme.colors["text"],
            framealpha=tokens.get("legend_frame_alpha"), title=title, **kwargs,
        )
        if title:
            legend.get_title().set_color(theme.colors["text"])

    @staticmethod
    def _handle(e: LegendEntry) -> Any:
        if e.kind == "patch":
            return Patch(facecolor=e.color, label=e.label)
        if e.kind == "line":
            return Line2D([0], [0], color=e.color, linestyle=e.linestyle, lw=2, label=e.label)
        return Line2D([0], [0], marker=e.marker, linestyle="", markerfacecolor=e.color,
                      markeredgecolor=e.color, label=e.label)
