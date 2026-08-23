"""Tagging persistence service.

Reuses the WorkspaceManager: the live session is kept in an *autosave* scope (so a
Streamlit rerun / control change / accidental navigation never loses tags), and
named tagging projects are stored as WorkspaceManager *presets* (kind
``tagging_project``) carrying the full session + history + UI state. No new
persistence layer is introduced.
"""
from __future__ import annotations

from typing import Any

from fap.tagging.export import project_from_dict, session_to_csv, to_project_dict
from fap.tagging.models import TaggingSession
from fap.tagging.validation import validate_session

AUTOSAVE_SCOPE = "tagging_session"
KIND_PROJECT = "tagging_project"


class TaggingService:
    def __init__(self, workspaces: Any = None, datahub: Any = None) -> None:
        self._wm = workspaces
        self._datahub = datahub

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

    # -- one-click bridge into the Data Hub / Open Play -----------------------
    def send_to_datahub(self, user: Any, session: TaggingSession, *, name: str,
                        workspace_id: str | None = None, activate: bool = True):
        """Import the session straight into the Data Hub as an event dataset (no manual
        CSV round-trip) and optionally activate it, so it renders on the Open Play maps.

        Reuses the exact same canonical CSV the Export button produces, fed through the
        standard ``analyze`` -> ``save_dataset`` -> ``choose`` datahub path. Returns the
        saved ``Dataset``. Raises ``ValueError`` on validation problems or misconfig."""
        if self._datahub is None:
            raise ValueError("The Data Hub is not available in this session.")
        problems = validate_session(session)
        if problems:
            raise ValueError(f"{len(problems)} validation issue(s) — fix before importing.")
        if not session.events:
            raise ValueError("Nothing to import — tag some events first.")
        data = session_to_csv(session).encode("utf-8")
        filename = (name or "Tagging session").strip().replace(" ", "_") + ".csv"
        result = self._datahub.analyze(data, filename)
        if getattr(result, "import_result", None) is None:
            raise ValueError("The tagged data was not recognised as an event dataset.")
        ds = self._datahub.save_dataset(
            user, result.import_result, name=name or "Tagging session",
            workspace_id=workspace_id,
            metadata={"competition": session.competition, "match_date": session.match_date,
                      "opponent": session.opponent, "tags": ["tagging"],
                      "description": "Imported from the Tagging Studio."})
        if activate:
            self._datahub.choose(user, ds.id)
        return ds
