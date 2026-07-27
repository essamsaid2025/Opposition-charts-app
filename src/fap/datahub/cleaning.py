"""Data Hub cleaning facade.

Re-exports the platform cleaning pipeline (``fap.pipeline.cleaning.clean``) and a
tiny helper to present the change log. The cleaning logic is the platform's; the
Data Hub only shows exactly what changed (it never silently fixes without the log).
"""
from __future__ import annotations

from typing import Any

from fap.pipeline.cleaning import clean


def change_log(cleaning_log: list[str]) -> list[dict[str, Any]]:
    """View-model for the cleaning step: each recorded change as a row."""
    return [{"change": entry} for entry in (cleaning_log or [])]


__all__ = ["clean", "change_log"]
