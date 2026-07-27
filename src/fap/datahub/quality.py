"""Data Hub quality facade.

Re-exports the platform quality scorer (``fap.pipeline.quality.score`` /
``QualityScore``, which already grades Excellent/Good/Fair/Poor) and adds a
readiness helper that combines the score with the validation result. No scoring
logic is duplicated.
"""
from __future__ import annotations

from typing import Any

from fap.pipeline.quality import QualityScore, score
from fap.pipeline.validation import ValidationReport


def rating(overall: float) -> str:
    """Excellent / Good / Fair / Poor — same thresholds as QualityScore.grade."""
    return ("Excellent" if overall >= 90 else "Good" if overall >= 75
            else "Fair" if overall >= 55 else "Poor")


def readiness(quality: QualityScore, validation: ValidationReport | None = None) -> dict[str, Any]:
    """A single readiness verdict for the quality step: the score, its rating,
    per-component breakdown, and whether hard validation errors block use."""
    blocked = bool(validation and validation.errors)
    return {
        "score": quality.overall,
        "rating": rating(quality.overall),
        "components": dict(quality.components),
        "blocked_by_errors": blocked,
        "ready": (quality.overall >= 55) and not blocked,
    }


__all__ = ["QualityScore", "score", "rating", "readiness"]
