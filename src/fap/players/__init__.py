"""First Team Players platform module (Phase 10).

Our own squad — a first-class module completely separate from scouting. A
persistent roster plus contracts, medical, training/GPS, documents, images,
videos, notes, career history and LINK-ONLY match references (match statistics
stay in the event datasets). It REUSES the platform services and never
duplicates them: ImageStorage, FileStorage, ReportsManager (Report Studio),
the visualization Renderer, PermissionService (VIEW/EDIT/DELETE_PLAYERS,
VIEW/EDIT_MEDICAL), AuditService, WorkspaceManager and CacheManager.

Service-driven: all logic in ``PlayersService``; Streamlit pages only render.
Nothing lives in session_state except navigation. Independent of the scouting
module; the only bridge is the optional, read-only ``promote_from_scouting``.
"""
from fap.players.models import (
    Player, PlayerCareer, PlayerContract, PlayerDocument, PlayerImage,
    PlayerMatchLink, PlayerMedical, PlayerNote, PlayerTraining, PlayerVideo,
)
from fap.players.service import PlayersService

__all__ = [
    "PlayersService", "Player", "PlayerContract", "PlayerMedical", "PlayerTraining",
    "PlayerDocument", "PlayerImage", "PlayerVideo", "PlayerNote", "PlayerCareer",
    "PlayerMatchLink",
]
