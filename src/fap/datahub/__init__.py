"""Universal Data Hub (Phase 12) — the central import + dataset-management module.

A first-class module (like players/scouting/setpieces) that becomes the single
entry point for every dataset. It REUSES the platform end to end and duplicates
nothing:

* import engine  -> fap.pipeline.ImportService (detect, map, normalize, clean,
                    validate, score)
* dataset store  -> fap.workspaces.WorkspaceManager (datasets table + storage +
                    active-dataset seam + presets + audit)
* validation / cleaning / mapping / quality / coordinates -> fap.pipeline.*
* providers      -> fap.providers.*
* permissions    -> enforced by the WorkspaceManager

The Data Hub ADDS: the save workflow, dataset health, per-module compatibility,
lineage, versioning, import profiles and a professional preview view-model.
Every module then simply calls ``choose`` (which sets the active dataset that all
modules already read) — no duplicated import logic anywhere.
"""
from fap.datahub.models import (
    CompatibilityResult, DatasetHealth, DatasetVersion, HealthAxis, ImportProfile,
    LineageEvent, SUPPORTED_SOURCES, SourceKind, TARGET_MODULES, LINEAGE_STAGES,
)
from fap.datahub.preview import PreviewRequest, PreviewResult, build_preview
from fap.datahub.service import DataHubService

__all__ = [
    "DataHubService", "SUPPORTED_SOURCES", "SourceKind", "TARGET_MODULES",
    "LINEAGE_STAGES", "LineageEvent", "DatasetVersion", "ImportProfile",
    "HealthAxis", "DatasetHealth", "CompatibilityResult",
    "PreviewRequest", "PreviewResult", "build_preview",
]
