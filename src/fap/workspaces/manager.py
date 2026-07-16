"""WorkspaceManager - the club-environment facade.

One object the app talks to for the whole Workspace & Data Management layer:
the club hierarchy, the data manager, presets, project version history,
auto-save, pins/favorites/recents, global search - each call permission-checked
against the caller's identity Role and recorded in the audit log.

It wraps the existing platform (ProjectRepository/WorkspaceRepository, the same
Database); it does not replace or modify any of it.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from fap.db.engine import Database
from fap.db.models import Project, Workspace
from fap.db.repositories import ProjectRepository, WorkspaceRepository
from fap.identity.models import User
from fap.workspaces.audit import AuditService
from fap.workspaces.models import (
    ORG_KINDS, AuditEntry, Dataset, OrgNode, Preset, ProjectVersion,
)
from fap.workspaces.permissions import Capability, can, require
from fap.workspaces.repositories import (
    AuditRepository, DatasetRepository, OrgRepository, PresetRepository,
    UserStateRepository, VersionRepository,
)


@dataclass(frozen=True, slots=True)
class SearchHit:
    type: str
    id: str
    name: str
    context: str = ""


@dataclass(frozen=True, slots=True)
class VersionDiff:
    added: list[str]
    removed: list[str]
    changed: list[str]


class WorkspaceManager:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._org = OrgRepository(db)
        self._datasets = DatasetRepository(db)
        self._presets = PresetRepository(db)
        self._versions = VersionRepository(db)
        self._projects = ProjectRepository(db)
        self._workspaces = WorkspaceRepository(db)
        self._state = UserStateRepository(db)
        self.audit = AuditService(AuditRepository(db))

    # ---------------------------------------------------------------- workspaces & projects
    def list_workspaces(self) -> list[Workspace]:
        return self._workspaces.list_all()

    def ensure_workspace(self, actor: User) -> Workspace:
        existing = self._workspaces.list_all()
        if existing:
            return existing[0]
        require(actor.role, Capability.EDIT)
        ws = Workspace(id=str(uuid.uuid4()), name="My Workspace", owner_id=actor.email)
        self._workspaces.save(ws)
        self.audit.record(actor, "workspace.create", target_type="workspace", target_id=ws.id,
                          detail={"name": ws.name})
        return ws

    def create_workspace(self, actor: User, name: str) -> Workspace:
        require(actor.role, Capability.MANAGE_CLUB)
        ws = Workspace(id=str(uuid.uuid4()), name=name, owner_id=actor.email)
        self._workspaces.save(ws)
        self.audit.record(actor, "workspace.create", target_type="workspace", target_id=ws.id,
                          detail={"name": name})
        return ws

    def list_projects(self, workspace_id: str) -> list[Project]:
        return self._projects.list_for_workspace(workspace_id)

    def get_project(self, project_id: str) -> Project | None:
        return self._projects.get(project_id)

    # ---------------------------------------------------------------- club hierarchy
    def create_club(self, actor: User, name: str) -> OrgNode:
        require(actor.role, Capability.MANAGE_CLUB)
        return self._new_node(actor, "club", name, parent_id=None)

    def add_child(self, actor: User, parent_id: str, kind: str, name: str) -> OrgNode:
        require(actor.role, Capability.MANAGE_CLUB)
        if kind not in ORG_KINDS:
            raise ValueError(f"unknown org kind {kind!r}")
        return self._new_node(actor, kind, name, parent_id=parent_id)

    def _new_node(self, actor: User, kind: str, name: str, parent_id: str | None) -> OrgNode:
        node = OrgNode(id=str(uuid.uuid4()), kind=kind, name=name, parent_id=parent_id,
                       created_by=actor.email)
        self._org.save(node)
        self.audit.record(actor, "org.create", target_type=kind, target_id=node.id,
                          detail={"name": name, "parent_id": parent_id})
        return node

    def rename_node(self, actor: User, node_id: str, name: str) -> None:
        require(actor.role, Capability.MANAGE_CLUB)
        node = self._org.get(node_id)
        if node is None:
            raise ValueError("node not found")
        node.name = name
        self._org.save(node)
        self.audit.record(actor, "org.rename", target_type=node.kind, target_id=node_id,
                          detail={"name": name})

    def move_node(self, actor: User, node_id: str, new_parent_id: str | None) -> None:
        require(actor.role, Capability.MANAGE_CLUB)
        node = self._org.get(node_id)
        if node is None:
            raise ValueError("node not found")
        node.parent_id = new_parent_id
        self._org.save(node)
        self.audit.record(actor, "org.move", target_type=node.kind, target_id=node_id,
                          detail={"new_parent_id": new_parent_id})

    def delete_node(self, actor: User, node_id: str) -> None:
        node = self._org.get(node_id)
        if node is None:
            return
        # deleting a whole club (a workspace) is Super-Admin only; branches are Club-Admin
        require(actor.role, Capability.DELETE_WORKSPACE if node.kind == "club"
                else Capability.MANAGE_CLUB)
        self._org.delete(node_id)   # cascades to descendants
        self.audit.record(actor, "org.delete", target_type=node.kind, target_id=node_id)

    def children(self, parent_id: str | None) -> list[OrgNode]:
        return self._org.children(parent_id)

    def nodes_of_kind(self, kind: str) -> list[OrgNode]:
        return self._org.by_kind(kind)

    # ---------------------------------------------------------------- data manager
    def register_dataset(self, actor: User, *, name: str, provider_id: str = "",
                         coord_system: str = "", rows: int = 0, size_bytes: int = 0,
                         content_hash: str = "", workspace_id: str | None = None,
                         project_id: str | None = None, node_id: str | None = None,
                         season: str = "", competition: str = "", opponent: str = "",
                         match_date: str = "", document: dict[str, Any] | None = None) -> Dataset:
        require(actor.role, Capability.EDIT)
        ds = Dataset(id=str(uuid.uuid4()), name=name, provider_id=provider_id,
                     coord_system=coord_system, rows=rows, size_bytes=size_bytes,
                     content_hash=content_hash, workspace_id=workspace_id, project_id=project_id,
                     node_id=node_id, season=season, competition=competition, opponent=opponent,
                     match_date=match_date, document=document or {}, created_by=actor.email)
        self._datasets.save(ds)
        self.audit.record(actor, "dataset.import", target_type="dataset", target_id=ds.id,
                          detail={"name": name, "provider": provider_id, "rows": rows})
        return ds

    def get_dataset(self, dataset_id: str) -> Dataset | None:
        return self._datasets.get(dataset_id)

    def list_datasets(self, *, workspace_id: str | None = None,
                      include_archived: bool = False) -> list[Dataset]:
        status = None if include_archived else "active"
        return self._datasets.list(workspace_id=workspace_id, status=status)

    def rename_dataset(self, actor: User, dataset_id: str, name: str) -> None:
        require(actor.role, Capability.EDIT)
        ds = self._require_dataset(dataset_id)
        ds.name = name
        self._datasets.save(ds)
        self.audit.record(actor, "dataset.rename", target_type="dataset", target_id=dataset_id,
                          detail={"name": name})

    def archive_dataset(self, actor: User, dataset_id: str, archived: bool = True) -> None:
        require(actor.role, Capability.EDIT)
        ds = self._require_dataset(dataset_id)
        ds.status = "archived" if archived else "active"
        self._datasets.save(ds)
        self.audit.record(actor, "dataset.archive" if archived else "dataset.unarchive",
                          target_type="dataset", target_id=dataset_id)

    def duplicate_dataset(self, actor: User, dataset_id: str, name: str | None = None) -> Dataset:
        require(actor.role, Capability.EDIT)
        src = self._require_dataset(dataset_id)
        copy = Dataset(id=str(uuid.uuid4()), name=name or f"{src.name} (copy)",
                       workspace_id=src.workspace_id, project_id=src.project_id, node_id=src.node_id,
                       provider_id=src.provider_id, coord_system=src.coord_system, rows=src.rows,
                       size_bytes=src.size_bytes, content_hash=src.content_hash, season=src.season,
                       competition=src.competition, opponent=src.opponent, match_date=src.match_date,
                       document=dict(src.document), status="active", created_by=actor.email)
        self._datasets.save(copy)
        self.audit.record(actor, "dataset.duplicate", target_type="dataset", target_id=copy.id,
                          detail={"source": dataset_id})
        return copy

    def move_dataset(self, actor: User, dataset_id: str, *, workspace_id: str | None = None,
                     node_id: str | None = None) -> None:
        require(actor.role, Capability.EDIT)
        ds = self._require_dataset(dataset_id)
        if workspace_id is not None:
            ds.workspace_id = workspace_id
        if node_id is not None:
            ds.node_id = node_id
        self._datasets.save(ds)
        self.audit.record(actor, "dataset.move", target_type="dataset", target_id=dataset_id,
                          detail={"workspace_id": workspace_id, "node_id": node_id})

    def delete_dataset(self, actor: User, dataset_id: str) -> None:
        require(actor.role, Capability.EDIT)
        self._require_dataset(dataset_id)
        self._datasets.delete(dataset_id)
        self.audit.record(actor, "dataset.delete", target_type="dataset", target_id=dataset_id)

    def export_dataset(self, actor: User, dataset_id: str) -> dict[str, Any]:
        """The dataset's metadata document for export; byte export is the app's job."""
        ds = self._require_dataset(dataset_id)
        self.audit.record(actor, "dataset.export", target_type="dataset", target_id=dataset_id)
        return {"id": ds.id, "name": ds.name, "provider": ds.provider_id, "rows": ds.rows,
                "season": ds.season, "competition": ds.competition, "opponent": ds.opponent,
                "match_date": ds.match_date, **ds.document}

    def _require_dataset(self, dataset_id: str) -> Dataset:
        ds = self._datasets.get(dataset_id)
        if ds is None:
            raise ValueError(f"dataset {dataset_id!r} not found")
        return ds

    # ---------------------------------------------------------------- presets / templates
    def save_preset(self, actor: User, *, kind: str, name: str, document: dict[str, Any],
                    scope: str = "user", preset_id: str | None = None) -> Preset:
        require(actor.role, Capability.EDIT)
        preset = Preset(id=preset_id or str(uuid.uuid4()), kind=kind, name=name,
                        owner_id=actor.email, scope=scope, document=document)
        self._presets.save(preset)
        self.audit.record(actor, "template.save", target_type=f"preset:{kind}", target_id=preset.id,
                          detail={"name": name, "scope": scope})
        return preset

    def list_presets(self, actor: User, *, kind: str | None = None) -> list[Preset]:
        return self._presets.list(kind=kind, owner_id=actor.email)

    def delete_preset(self, actor: User, preset_id: str) -> None:
        require(actor.role, Capability.EDIT)
        self._presets.delete(preset_id)
        self.audit.record(actor, "template.delete", target_type="preset", target_id=preset_id)

    # ---------------------------------------------------------------- version history
    def snapshot_project(self, actor: User, project_id: str, note: str = "") -> ProjectVersion:
        require(actor.role, Capability.EDIT)
        project = self._projects.get(project_id)
        if project is None:
            raise ValueError("project not found")
        version = ProjectVersion(id=str(uuid.uuid4()), project_id=project_id,
                                 version=self._versions.next_version(project_id),
                                 document=dict(project.document), note=note,
                                 created_by=actor.email)
        self._versions.add(version)
        self.audit.record(actor, "project.snapshot", target_type="project", target_id=project_id,
                          detail={"version": version.version, "note": note})
        return version

    def list_versions(self, project_id: str) -> list[ProjectVersion]:
        return self._versions.list(project_id)

    def restore_version(self, actor: User, project_id: str, version: int) -> Project:
        require(actor.role, Capability.EDIT)
        snap = self._versions.get(project_id, version)
        project = self._projects.get(project_id)
        if snap is None or project is None:
            raise ValueError("version or project not found")
        # snapshot the current state first, so a restore is itself reversible
        self.snapshot_project(actor, project_id, note=f"auto before restore of v{version}")
        project.document = dict(snap.document)
        self._projects.save(project)
        self.audit.record(actor, "project.restore", target_type="project", target_id=project_id,
                          detail={"version": version})
        return project

    def compare_versions(self, project_id: str, a: int, b: int) -> VersionDiff:
        va, vb = self._versions.get(project_id, a), self._versions.get(project_id, b)
        if va is None or vb is None:
            raise ValueError("version not found")
        ka, kb = set(va.document), set(vb.document)
        changed = [k for k in ka & kb if va.document[k] != vb.document[k]]
        return VersionDiff(added=sorted(kb - ka), removed=sorted(ka - kb), changed=sorted(changed))

    # ---------------------------------------------------------------- auto-save
    def autosave(self, user: User, document: dict[str, Any], scope: str = "session") -> None:
        """Persist session state (filters, provider, mapping, charts, theme,
        workspace, page, last project) with no Save button. Personal state, so
        any signed-in user may write their own."""
        self._state.save_state(user.email, scope, document)

    def load_autosave(self, user: User, scope: str = "session") -> dict[str, Any]:
        return self._state.load_state(user.email, scope)

    # ---------------------------------------------------------------- pins / favorites / recents
    def pin(self, user: User, target_type: str, target_id: str) -> None:
        self._state.add_item(user.email, "pin", target_type, target_id)

    def unpin(self, user: User, target_type: str, target_id: str) -> None:
        self._state.remove_item(user.email, "pin", target_type, target_id)

    def favorite(self, user: User, target_type: str, target_id: str) -> None:
        self._state.add_item(user.email, "favorite", target_type, target_id)

    def touch_recent(self, user: User, target_type: str, target_id: str) -> None:
        self._state.add_item(user.email, "recent", target_type, target_id)

    def pinned(self, user: User) -> list[tuple[str, str]]:
        return self._state.items(user.email, "pin")

    def favorites(self, user: User) -> list[tuple[str, str]]:
        return self._state.items(user.email, "favorite")

    def recents(self, user: User, limit: int = 10) -> list[tuple[str, str]]:
        return self._state.items(user.email, "recent", limit=limit)

    # ---------------------------------------------------------------- global search
    def search(self, query: str, *, workspace_id: str | None = None) -> list[SearchHit]:
        """Search datasets, org nodes (teams/opponents), projects and presets by
        name/metadata/tags. Case-insensitive substring match."""
        q = query.strip().lower()
        if not q:
            return []
        hits: list[SearchHit] = []

        for ds in self._datasets.list(workspace_id=workspace_id):
            haystack = " ".join([ds.name, ds.opponent, ds.competition, ds.season,
                                 " ".join(str(p) for p in ds.document.get("players", []))]).lower()
            if q in haystack:
                hits.append(SearchHit("dataset", ds.id, ds.name,
                                      context=f"{ds.opponent} {ds.competition}".strip()))
        for kind in ("team", "opponent", "competition", "season", "club"):
            for node in self._org.by_kind(kind):
                if q in node.name.lower():
                    hits.append(SearchHit(kind, node.id, node.name))
        for ws in self._workspaces.list_all():
            for project in self._projects.list_for_workspace(ws.id):
                tags = " ".join(project.document.get("tags", [])) if isinstance(
                    project.document, dict) else ""
                if q in project.name.lower() or q in tags.lower():
                    hits.append(SearchHit("project", project.id, project.name, context=ws.name))
        for preset in self._presets.list():
            if q in preset.name.lower():
                hits.append(SearchHit(f"preset:{preset.kind}", preset.id, preset.name))
        return hits

    # ---------------------------------------------------------------- audit access
    def audit_trail(self, *, actor: str | None = None, action: str | None = None,
                    limit: int = 200) -> list[AuditEntry]:
        return self.audit.recent(actor=actor, action=action, limit=limit)
