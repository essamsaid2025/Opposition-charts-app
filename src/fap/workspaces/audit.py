"""Audit trail. Every important action is recorded append-only with who did it,
their role, what they touched, and when."""
from __future__ import annotations

import uuid
from typing import Any

from fap.identity.models import User
from fap.workspaces.models import AuditEntry
from fap.workspaces.repositories import AuditRepository


class AuditService:
    def __init__(self, repo: AuditRepository) -> None:
        self._repo = repo

    def record(self, actor: User | None, action: str, *, target_type: str = "",
               target_id: str = "", detail: dict[str, Any] | None = None) -> AuditEntry:
        entry = AuditEntry(
            id=str(uuid.uuid4()), action=action,
            actor=actor.email if actor else "",
            actor_role=actor.role.slug if actor else "",
            target_type=target_type, target_id=target_id, detail=detail or {})
        self._repo.add(entry)
        return entry

    def recent(self, *, actor: str | None = None, action: str | None = None,
               limit: int = 200) -> list[AuditEntry]:
        return self._repo.recent(actor=actor, action=action, limit=limit)
