"""Data Hub provider facade.

Re-exports the existing provider registry + intelligence (``fap.providers``) and
the source catalog. NO provider logic lives here — detection and loading are done
by the platform's ``ImportService`` / ``ProviderIntelligence``; this module only
gives the Data Hub a stable name to import and the display catalog.
"""
from __future__ import annotations

from fap.datahub.models import SUPPORTED_SOURCES, SourceKind
from fap.providers.base import provider_registry
from fap.providers.intelligence import DetectionReport, ProviderIntelligence


def load_providers() -> None:
    from fap.providers.base import load_builtin_providers
    load_builtin_providers()


def registered_provider_ids() -> list[str]:
    load_providers()
    return sorted(provider_registry.ids())


def source_catalog() -> tuple[SourceKind, ...]:
    return SUPPORTED_SOURCES


__all__ = ["provider_registry", "ProviderIntelligence", "DetectionReport",
           "load_providers", "registered_provider_ids", "source_catalog",
           "SUPPORTED_SOURCES", "SourceKind"]
