"""Professional Scouting Platform (Phase 8.0).

A first-class platform module built on the existing architecture: a persistent
player database plus notes, videos, images, attachments, watchlists and scouting
reports. It REUSES ReportsManager (reports open in the existing Report Studio),
the visualization registry (charts), ImageStorage (images), the new FileStorage
(videos/attachments), PermissionService (capability checks) and AuditService.

Service-driven: all logic lives in ``ScoutingService``; Streamlit pages only
render. Nothing lives in session_state - every object persists in the platform
Database and storage tiers, surviving logout, restart and cache expiry.
"""
from fap.scouting.models import (
    Player, PlayerAttachment, PlayerMedia, PlayerNote, PlayerVideo,
    ScoutingReportLink, Watchlist,
)
from fap.scouting.service import ScoutingService

__all__ = [
    "ScoutingService", "Player", "PlayerNote", "PlayerVideo", "PlayerMedia",
    "PlayerAttachment", "ScoutingReportLink", "Watchlist",
]
