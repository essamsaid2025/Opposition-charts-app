"""Professional Set Piece Analysis Platform (Phase 9.0 - Foundation).

A first-class platform module built on the existing architecture: a persistent,
provider-agnostic set-piece event store (corners, free kicks, throw-ins,
penalties, kick-offs; offensive & defensive; own & opposition) plus the
per-delivery player positions (box occupancy), contact/second-ball events and
CSV/Excel/JSON import. It REUSES PermissionService (VIEW_SETPIECE / EDIT_SETPIECE,
already provisioned), AuditService, ReportsManager (reports open in the existing
Report Studio in a later phase), ImageStorage / FileStorage and WorkspaceManager.

Service-driven: all logic lives in ``SetPieceService``; Streamlit pages only
render. Nothing lives in session_state except navigation - every object persists
in the platform Database (migration 10) and storage tiers, surviving logout,
restart and cache expiry. Analytics, visualizations and report sections arrive in
Phases 9.1-9.5 and extend this foundation without touching other modules.
"""
from fap.setpieces.models import (
    ImportResult, SetPiece, SetPieceContact, SetPieceImport, SetPiecePosition,
)
from fap.setpieces.service import SetPieceService

__all__ = [
    "SetPieceService", "SetPiece", "SetPiecePosition", "SetPieceContact",
    "SetPieceImport", "ImportResult",
]
