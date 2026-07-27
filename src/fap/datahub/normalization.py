"""Data Hub coordinate-normalization facade.

Re-exports the platform coordinate engine (``fap.pipeline.coordinates``): the
detector and the registry of systems (0-1, 0-100, 120x80, 105x68 meters,
StatsBomb, Opta, WyScout, SkillCorner, Metrica, Second Spectrum, Tracab). The
actual normalization happens inside ``ImportService.import_file`` via the
DataPipeline — the Data Hub only *detects for display* and lists the systems.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from fap.pipeline.coordinates import (
    coord_registry, detect_coordinate_system, load_builtin_coordinate_systems,
)


def coordinate_systems() -> list[str]:
    load_builtin_coordinate_systems()
    return sorted(coord_registry.ids())


def detect(frame: pd.DataFrame) -> dict[str, Any]:
    """Detected system + confidence, for the coordinate step's before/after view."""
    system, confidence = detect_coordinate_system(frame)
    return {"system": system, "confidence": round(float(confidence), 3)}


__all__ = ["coord_registry", "detect_coordinate_system", "load_builtin_coordinate_systems",
           "coordinate_systems", "detect"]
