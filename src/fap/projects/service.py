"""ProjectService: application-layer save/load of an analysis session.
Captures everything needed to restore the screen: source ref, filters,
active visual plugin id, control values, theme."""
from __future__ import annotations

import uuid
from typing import Any

from fap.core.events import EventBus
from fap.db.models import DOCUMENT_SCHEMA_VERSION, Project
from fap.db.repositories import ProjectRepository
from fap.pipeline.filters import FilterSet


class ProjectService:
    def __init__(self, repo: ProjectRepository, events: EventBus) -> None:
        self._repo = repo
        self._events = events

    def save(self, *, project_id: str | None, workspace_id: str, name: str,
             source: dict[str, Any], filters: FilterSet, visual_id: str | None,
             controls: dict[str, Any], theme_id: str | None) -> Project:
        project = Project(
            id=project_id or str(uuid.uuid4()),
            workspace_id=workspace_id,
            name=name,
            document={
                "schema_version": DOCUMENT_SCHEMA_VERSION,
                "source": source,
                "filters": filters.to_dict(),
                "visual_id": visual_id,
                "controls": controls,
                "theme_id": theme_id,
            },
        )
        self._repo.save(project)
        self._events.publish("project.saved", {"project_id": project.id})
        return project

    def load(self, project_id: str) -> Project | None:
        return self._repo.get(project_id)

    def restore_filters(self, project: Project) -> FilterSet:
        return FilterSet.from_dict(project.document.get("filters", {}))

    def list_for_workspace(self, workspace_id: str) -> list[Project]:
        return self._repo.list_for_workspace(workspace_id)

    def delete(self, project_id: str) -> None:
        self._repo.delete(project_id)
        self._events.publish("project.deleted", {"project_id": project_id})
