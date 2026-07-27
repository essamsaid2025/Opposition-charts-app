"""Data Hub import facade over the platform ``ImportService``.

The whole import engine (provider detection, raw inspect, mapping, coordinate
normalization, cleaning, validation, quality) is the ImportService. This module
re-exports its result types and exposes the supported-format helpers the wizard
needs. It performs no importing itself — the service injects the ImportService.
"""
from __future__ import annotations

from fap.datahub.models import SUPPORTED_SOURCES
from fap.pipeline.importer import FilePreview, ImportResult, ImportService

# every extension the catalog can accept, for the uploader's ``type=`` filter
SUPPORTED_FORMATS: tuple[str, ...] = tuple(sorted({
    fmt for s in SUPPORTED_SOURCES if s.available for fmt in s.formats
}))


def filename_supported(filename: str) -> bool:
    name = (filename or "").lower()
    return any(name.endswith("." + ext) for ext in SUPPORTED_FORMATS)


__all__ = ["ImportService", "ImportResult", "FilePreview",
           "SUPPORTED_FORMATS", "filename_supported"]
