"""Data Hub repository facade.

The Data Hub does NOT own a dataset table or dataset storage — those belong to the
``WorkspaceManager`` (datasets table + DatasetStorage), which it reuses unchanged.
This facade wraps that manager and reads/writes the Data-Hub metadata that lives
inside each dataset's existing ``document`` JSON (namespace ``document['datahub']``:
lineage, versions, health cache, provenance). No SQL, no new table, no duplicated
repository — a small, cohesive surface the service talks to.
"""
from __future__ import annotations

from typing import Any

from fap.identity.models import User
from fap.workspaces.models import Dataset

NS = "datahub"


class DataHubRepository:
    def __init__(self, workspaces: Any) -> None:
        self._wm = workspaces

    # -- dataset lifecycle (delegated verbatim to the WorkspaceManager) --
    def register(self, user: User, **kwargs: Any) -> Dataset:
        return self._wm.register_dataset(user, **kwargs)

    def get(self, dataset_id: str) -> Dataset | None:
        return self._wm.get_dataset(dataset_id)

    def list(self, *, workspace_id: str | None = None,
             include_archived: bool = False) -> list[Dataset]:
        return self._wm.list_datasets(workspace_id=workspace_id,
                                      include_archived=include_archived)

    def rename(self, user: User, dataset_id: str, name: str) -> None:
        self._wm.rename_dataset(user, dataset_id, name)

    def archive(self, user: User, dataset_id: str, archived: bool = True) -> None:
        self._wm.archive_dataset(user, dataset_id, archived=archived)

    def duplicate(self, user: User, dataset_id: str, name: str | None = None) -> Dataset:
        return self._wm.duplicate_dataset(user, dataset_id, name=name)

    def delete(self, user: User, dataset_id: str) -> None:
        self._wm.delete_dataset(user, dataset_id)

    def store_frame(self, dataset_id: str, frame: Any) -> None:
        self._wm.store_dataset_frame(dataset_id, frame)

    def frame(self, dataset_id: str) -> Any:
        return self._wm.dataset_frame(dataset_id)

    def set_active(self, user: User, dataset_id: str) -> None:
        self._wm.set_active_dataset(user, dataset_id)

    # -- datahub document namespace (persisted inside dataset.document) --
    def hub_doc(self, dataset_id: str) -> dict[str, Any]:
        ds = self._wm.get_dataset(dataset_id)
        if ds is None:
            return {}
        return dict(ds.document.get(NS, {})) if isinstance(ds.document, dict) else {}

    def save_hub_doc(self, dataset_id: str, hub: dict[str, Any]) -> None:
        """Persist the datahub namespace back into the dataset document via the
        WorkspaceManager (which owns the datasets table). We update the in-memory
        Dataset and re-save it through the manager's repository path."""
        ds = self._wm.get_dataset(dataset_id)
        if ds is None:
            return
        doc = dict(ds.document) if isinstance(ds.document, dict) else {}
        doc[NS] = hub
        ds.document = doc
        # reuse the manager's dataset repository (no direct SQL here)
        self._wm._datasets.save(ds)      # single write path already used by the manager

    def update_dataset_row(self, dataset_id: str, **fields: Any) -> None:
        """Update first-class metadata columns (name/season/competition/etc.) and
        merge document keys, through the manager's dataset repository."""
        ds = self._wm.get_dataset(dataset_id)
        if ds is None:
            return
        doc_updates = fields.pop("document", None)
        for k, v in fields.items():
            if hasattr(ds, k):
                setattr(ds, k, v)
        if isinstance(doc_updates, dict):
            merged = dict(ds.document) if isinstance(ds.document, dict) else {}
            merged.update(doc_updates)
            ds.document = merged
        self._wm._datasets.save(ds)


__all__ = ["DataHubRepository", "NS"]
