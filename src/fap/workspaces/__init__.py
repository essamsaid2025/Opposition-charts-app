"""Workspaces & Data Management.

``WorkspaceService`` is the original thin workspace container. ``WorkspaceManager``
(Phase 3B) is the club-environment facade: hierarchy, data manager, presets,
version history, auto-save, pins/favorites, search and audit - all permission
checked against the identity Role and recorded in the audit log.
"""
from fap.workspaces.service import WorkspaceService
from fap.workspaces.manager import WorkspaceManager, SearchHit, VersionDiff
from fap.workspaces.permissions import Capability, can, require

__all__ = ["WorkspaceService", "WorkspaceManager", "SearchHit", "VersionDiff",
           "Capability", "can", "require"]
