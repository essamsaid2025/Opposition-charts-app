"""Tagging persistence service.

Reuses the WorkspaceManager: the live session is kept in an *autosave* scope (so a
Streamlit rerun / control change / accidental navigation never loses tags), and
named tagging projects are stored as WorkspaceManager *presets* (kind
``tagging_project``) carrying the full session + history + UI state. No new
persistence layer is introduced.
"""
from __future__ import annotations

from typing import Any

from fap.tagging.export import project_from_dict, to_project_dict
from fap.tagging.models import TaggingSession

AUTOSAVE_SCOPE = "tagging_session"
KIND_PROJECT = "tagging_project"


class TaggingService:
    def __init__(self, workspaces: Any = None) -> None:
        self._wm = workspaces

    # -- autosave (session safety across reruns) ------------------------------
    def autosave(self, user: Any, session: TaggingSession,
                 ui_state: dict[str, Any] | None = None) -> None:
        if self._wm is None:
            return
        try:
            self._wm.autosave(user, to_project_dict(session, ui_state=ui_state),
                              scope=AUTOSAVE_SCOPE)
        except Exception:
            pass

    def load_autosave(self, user: Any) -> tuple[TaggingSession, dict[str, Any]]:
        if self._wm is None:
            return TaggingSession(), {}
        try:
            doc = self._wm.load_autosave(user, scope=AUTOSAVE_SCOPE)
        except Exception:
            doc = {}
        if not doc:
            return TaggingSession(), {}
        return project_from_dict(doc)

    # -- named projects (presets) ---------------------------------------------
    def save_project(self, user: Any, session: TaggingSession, *, name: str,
                     ui_state: dict[str, Any] | None = None,
                     preset_id: str | None = None) -> Any:
        if self._wm is None:
            raise ValueError("Workspace manager is not available.")
        return self._wm.save_preset(
            user, kind=KIND_PROJECT, name=name or "Tagging project",
            document=to_project_dict(session, ui_state=ui_state, name=name),
            preset_id=preset_id)

    def list_projects(self, user: Any) -> list:
        if self._wm is None:
            return []
        try:
            return self._wm.list_presets(user, kind=KIND_PROJECT)
        except Exception:
            return []

    def load_project(self, user: Any, preset_id: str
                     ) -> tuple[TaggingSession, dict[str, Any]] | None:
        for p in self.list_projects(user):
            if getattr(p, "id", None) == preset_id:
                return project_from_dict(getattr(p, "document", None) or {})
        return None

    def delete_project(self, user: Any, preset_id: str) -> None:
        if self._wm is not None:
            try:
                self._wm.delete_preset(user, preset_id)
            except Exception:
                pass
