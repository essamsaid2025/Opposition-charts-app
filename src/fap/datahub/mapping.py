"""Data Hub column-mapping facade.

Re-exports the platform's alias-based column detection (``fap.pipeline.columns``)
and canonical rename (``fap.pipeline.schema.apply_mapping``). Mapping intelligence
is the platform's; the Data Hub only remembers a chosen mapping in an import
profile and lets the user override.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from fap.pipeline.columns import ColumnMapping, detect_columns
from fap.pipeline.schema import CANONICAL, apply_mapping


def suggestions(raw_frame: pd.DataFrame) -> dict[str, Any]:
    """Auto-detected mapping + per-field confidence for the mapping step UI."""
    detected = detect_columns(raw_frame)
    return {
        "mapping": dict(detected.mapping),
        "confidence": dict(detected.confidence),
        "unmapped_sources": list(detected.unmapped_sources),
        "overall_confidence": round(detected.overall_confidence, 3),
        "canonical_fields": list(CANONICAL),
    }


__all__ = ["ColumnMapping", "detect_columns", "apply_mapping", "CANONICAL", "suggestions"]
