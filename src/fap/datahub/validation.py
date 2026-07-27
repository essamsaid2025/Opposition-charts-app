"""Data Hub validation facade.

Re-exports the platform ``ValidationEngine`` / ``ValidationReport`` and adds only
*presentation* helpers (large validation badges). The validation logic is the
platform's — never re-implemented here. Nothing is silently fixed; every issue
the engine reports is surfaced.
"""
from __future__ import annotations

from typing import Any

from fap.pipeline.validation import Issue, ValidationEngine, ValidationReport


def badges(report: ValidationReport) -> list[dict[str, Any]]:
    """View-model for the wizard's validation step: one badge per issue, plus
    severity counts, so the UI renders large status badges without touching the
    report internals."""
    return [{
        "code": i.code, "severity": i.severity, "message": i.message,
        "count": i.count, "examples": list(i.examples),
    } for i in report.issues]


def summary(report: ValidationReport) -> dict[str, Any]:
    return {
        "rows_checked": report.rows_checked,
        "errors": len(report.errors),
        "warnings": len(report.warnings),
        "ok": report.ok,
    }


__all__ = ["ValidationEngine", "ValidationReport", "Issue", "badges", "summary"]
