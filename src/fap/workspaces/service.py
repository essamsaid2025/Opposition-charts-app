from __future__ import annotations

import uuid

from fap.core.events import EventBus
from fap.db.models import Workspace
from fap.db.repositories import WorkspaceRepository


class WorkspaceService:
    def __init__(self, repo: WorkspaceRepository, events: EventBus) -> None:
        self._repo = repo
        self._events = events

    def create(self, name: str, owner_id: str | None = None) -> Workspace:
        ws = Workspace(id=str(uuid.uuid4()), name=name, owner_id=owner_id)
        self._repo.save(ws)
        self._events.publish("workspace.created", {"workspace_id": ws.id})
        return ws

    def rename(self, workspace_id: str, name: str) -> None:
        ws = self._repo.get(workspace_id)
        if ws:
            ws.name = name
            self._repo.save(ws)

    def get(self, workspace_id: str) -> Workspace | None:
        return self._repo.get(workspace_id)

    def list_all(self) -> list[Workspace]:
        return self._repo.list_all()

    def ensure_default(self) -> Workspace:
        existing = self._repo.list_all()
        return existing[0] if existing else self.create("Default Workspace")

    def delete(self, workspace_id: str) -> None:
        self._repo.delete(workspace_id)
        self._events.publish("workspace.deleted", {"workspace_id": workspace_id})
