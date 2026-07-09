"""Shared domain types. Keeping these in one module prevents circular imports
and gives every layer the same vocabulary."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

import pandas as pd


class Orientation(str, Enum):
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"


@dataclass(frozen=True, slots=True)
class PitchDims:
    """Canonical internal pitch. Providers normalize INTO this space once;
    every visual/metric downstream assumes it. x: 0-100, y: 0-100 logical,
    plotted on a length x width metric pitch."""
    length: float = 100.0
    width: float = 68.0
    final_third_x: float = 66.67
    box_x: float = 83.0
    box_y_min: float = 21.0
    box_y_max: float = 79.0


ControlKind = Literal["color", "slider", "int_slider", "checkbox", "select", "multiselect", "text"]


@dataclass(frozen=True, slots=True)
class Control:
    """Declarative UI control. Visual/metric plugins DECLARE controls; the UI
    layer renders them generically. New plugins therefore require zero UI code."""
    key: str
    label: str
    kind: ControlKind
    default: Any = None
    options: tuple[Any, ...] = ()
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None
    help: str = ""


@dataclass(slots=True)
class RenderContext:
    """Everything a visualization needs, injected by the application layer."""
    df: pd.DataFrame
    theme: "Any"                       # fap.themes.Theme (kept loose to avoid cycle)
    controls: dict[str, Any]
    pitch: PitchDims = field(default_factory=PitchDims)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MetricResult:
    id: str
    label: str
    value: float | int | str
    formatted: str
    unit: str = ""
    context: dict[str, Any] = field(default_factory=dict)
