"""DataHubService — the orchestrator for the Universal Data Hub.

It composes the platform's existing engine into the Data Hub workflow. It owns NO
import/validation/cleaning/mapping/quality logic (that is the ``ImportService`` +
pipeline), NO dataset table or storage (that is the ``WorkspaceManager``), and NO
permission logic (the manager enforces capabilities). It adds only the concepts
the Data Hub introduces: the save workflow, lineage, versioning, health,
per-module compatibility, and import profiles — all stored inside the dataset's
existing ``document`` JSON. Pure (no Streamlit).
"""
from __future__ import annotations

import datetime as _dt
from typing import Any

import pandas as pd

from fap.datahub import quality as dq
from fap.datahub import validation as dv
from fap.datahub.dataset_profiles import ProfileStore
from fap.datahub.models import (
    LINEAGE_STAGES, TARGET_MODULES, CompatibilityResult, DatasetHealth, HealthAxis,
    LineageEvent, SUPPORTED_SOURCES,
)
from fap.datahub.preview import PreviewRequest, PreviewResult, build_preview
from fap.datahub.repository import DataHubRepository
from fap.identity.models import User
from fap.pipeline.importer import FilePreview, ImportResult, ImportService
from fap.pipeline.validation import KNOWN_EVENTS


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _nonempty(frame: pd.DataFrame, col: str) -> float:
    if col not in frame.columns or frame.empty:
        return 0.0
    s = frame[col]
    filled = s.notna() if s.dtype.kind in "fiu" else s.astype(str).str.strip().ne("")
    return float(filled.mean())


class DataHubService:
    def __init__(self, *, importer: ImportService, workspaces: Any, permissions: Any = None,
                 audit: Any = None) -> None:
        self._imp = importer
        self._wm = workspaces
        self._perms = permissions
        self._audit = audit
        self.repo = DataHubRepository(workspaces)
        self.profiles = ProfileStore(workspaces)

    # ------------------------------------------------------------ catalog
    def sources(self) -> tuple:
        return SUPPORTED_SOURCES

    # ------------------------------------------------------------ steps 1-2: inspect/detect
    def inspect(self, data: bytes, filename: str, *, provider_id: str | None = None,
                options: dict[str, Any] | None = None) -> FilePreview:
        return self._imp.inspect(data, filename, provider_id=provider_id, options=options)

    def detect_provider(self, data: bytes, filename: str):
        return self._imp.detect_provider(data, filename)

    # ------------------------------------------------------------ steps 3-7: full import
    def run_import(self, data: bytes, filename: str, *, provider_id: str | None = None,
                   mapping: dict[str, str] | None = None, coord_system: str | None = None,
                   flip_direction: bool = False, options: dict[str, Any] | None = None,
                   constants: dict[str, str] | None = None,
                   use_cache: bool = True) -> ImportResult:
        return self._imp.import_file(
            data, filename, provider_id=provider_id, mapping=mapping,
            coord_system=coord_system, flip_direction=flip_direction,
            options=options, constants=constants, use_cache=use_cache)

    def save_mapping_template(self, name: str, provider_id: str, raw_columns: list[str],
                              mapping: dict[str, str]) -> None:
        self._imp.save_template(name, provider_id, raw_columns, mapping)

    # ------------------------------------------------------------ step 9: save dataset
    def save_dataset(self, user: User, result: ImportResult, *, name: str,
                     workspace_id: str | None = None, metadata: dict[str, Any] | None = None):
        """Persist a fully-processed import as a first-class dataset (row +
        frame), seed its lineage (imported→…→saved) and version v1. Reuses the
        WorkspaceManager's register/store paths and permission checks verbatim."""
        meta = dict(metadata or {})
        summary = result.summary or {}
        document = {
            "provider": result.provider_id,
            "coord_system": result.coord_system,
            "mapping": dict(result.mapping),
            "quality": result.quality.overall,
            "quality_components": dict(result.quality.components),
            "quality_rating": dq.rating(result.quality.overall),
            "validation": dv.summary(result.validation),
            "summary": summary,
            "pitch": meta.get("pitch", ""),
            "units": meta.get("units", ""),
            "frame_rate": meta.get("frame_rate", ""),
            "tracking": bool(meta.get("tracking", False)),
            "gps": bool(meta.get("gps", False)),
            "tags": list(meta.get("tags", [])),
            "visibility": meta.get("visibility", "workspace"),
            "description": meta.get("description", ""),
        }
        ds = self.repo.register(
            user, name=name, provider_id=result.provider_id,
            coord_system=result.coord_system, rows=int(len(result.frame)),
            content_hash=summary.get("content_hash", ""), workspace_id=workspace_id,
            season=meta.get("season", ""), competition=meta.get("competition", ""),
            opponent=meta.get("opponent", ""), match_date=meta.get("match_date", ""),
            document=document)
        self.repo.store_frame(ds.id, result.frame)
        # seed lineage: the import already performed these stages in one call
        lineage = [LineageEvent(s, _now(), user.email,
                                "import pipeline").to_dict() for s in LINEAGE_STAGES[:5]]
        lineage.append(LineageEvent("saved", _now(), user.email, name).to_dict())
        hub = {"lineage": lineage, "versions": []}
        self.repo.save_hub_doc(ds.id, hub)
        self._snapshot(ds.id, user, note="initial import")
        return self.repo.get(ds.id)

    # ------------------------------------------------------------ step 8: preview
    def preview(self, dataset_id: str, request: PreviewRequest | None = None) -> PreviewResult:
        return build_preview(self.repo.frame(dataset_id), request)

    def preview_frame(self, frame: pd.DataFrame, request: PreviewRequest | None = None) -> PreviewResult:
        return build_preview(frame, request)

    # ------------------------------------------------------------ step 10: library
    def list_datasets(self, *, workspace_id: str | None = None,
                      include_archived: bool = False):
        return self.repo.list(workspace_id=workspace_id, include_archived=include_archived)

    def get(self, dataset_id: str):
        return self.repo.get(dataset_id)

    def rename(self, user: User, dataset_id: str, name: str) -> None:
        self.repo.rename(user, dataset_id, name)
        self._lineage_add(dataset_id, user, "edited", f"renamed to {name}")

    def update_metadata(self, user: User, dataset_id: str, **fields: Any) -> None:
        self.repo.update_dataset_row(dataset_id, **fields)
        self._lineage_add(dataset_id, user, "edited", "metadata updated")
        self._snapshot(dataset_id, user, note="metadata edit")

    def duplicate(self, user: User, dataset_id: str, name: str | None = None):
        return self.repo.duplicate(user, dataset_id, name=name)

    def archive(self, user: User, dataset_id: str, archived: bool = True) -> None:
        self.repo.archive(user, dataset_id, archived=archived)

    def delete(self, user: User, dataset_id: str) -> None:
        self.repo.delete(user, dataset_id)

    def choose(self, user: User, dataset_id: str) -> None:
        """Make a dataset the active dataset — the single seam every module reads
        (``WorkspaceManager.active_frame``). This is the whole 'Choose Dataset'
        integration: no module needs its own import."""
        self.repo.set_active(user, dataset_id)
        self._lineage_add(dataset_id, user, "used_by", "activated")

    # ------------------------------------------------------------ lineage
    def lineage(self, dataset_id: str) -> list[dict[str, Any]]:
        return list(self.repo.hub_doc(dataset_id).get("lineage", []))

    def _lineage_add(self, dataset_id: str, user: User, stage: str, detail: str = "") -> None:
        hub = self.repo.hub_doc(dataset_id)
        events = list(hub.get("lineage", []))
        events.append(LineageEvent(stage, _now(), user.email, detail).to_dict())
        hub["lineage"] = events
        self.repo.save_hub_doc(dataset_id, hub)

    # ------------------------------------------------------------ versioning
    def versions(self, dataset_id: str) -> list[dict[str, Any]]:
        return list(self.repo.hub_doc(dataset_id).get("versions", []))

    def _snapshot(self, dataset_id: str, user: User, note: str = "") -> None:
        ds = self.repo.get(dataset_id)
        if ds is None:
            return
        hub = self.repo.hub_doc(dataset_id)
        versions = list(hub.get("versions", []))
        doc = {k: v for k, v in (ds.document or {}).items() if k != "datahub"}
        snap = {
            "version": len(versions) + 1, "at": _now(), "by": user.email, "note": note,
            "metadata": {"name": ds.name, "season": ds.season, "competition": ds.competition,
                         "opponent": ds.opponent, "match_date": ds.match_date, "document": doc},
        }
        versions.append(snap)
        hub["versions"] = versions
        self.repo.save_hub_doc(dataset_id, hub)

    def snapshot(self, dataset_id: str, user: User, note: str = "") -> None:
        self._snapshot(dataset_id, user, note=note)

    def restore_version(self, user: User, dataset_id: str, version: int) -> None:
        versions = self.versions(dataset_id)
        target = next((v for v in versions if v.get("version") == version), None)
        if target is None:
            raise ValueError(f"version {version} not found")
        self._snapshot(dataset_id, user, note=f"auto before restore of v{version}")
        m = target.get("metadata", {})
        self.repo.update_dataset_row(
            dataset_id, name=m.get("name"), season=m.get("season", ""),
            competition=m.get("competition", ""), opponent=m.get("opponent", ""),
            match_date=m.get("match_date", ""), document=m.get("document", {}))
        self._lineage_add(dataset_id, user, "edited", f"restored v{version}")

    # ------------------------------------------------------------ health
    def health(self, dataset_id: str) -> DatasetHealth:
        frame = self.repo.frame(dataset_id)
        doc = (self.repo.get(dataset_id).document if self.repo.get(dataset_id) else {}) or {}
        return self._health(frame, doc)

    def _health(self, frame: pd.DataFrame | None, doc: dict[str, Any]) -> DatasetHealth:
        if frame is None or frame.empty:
            axes = [HealthAxis(k, lbl, "red", 0.0, "no data")
                    for k, lbl in (("coordinates", "Coordinates"), ("players", "Players"),
                                   ("teams", "Teams"), ("matches", "Matches"),
                                   ("events", "Events"))]
            return DatasetHealth(axes=axes)

        def band(cov: float) -> str:
            return "green" if cov >= 0.9 else "yellow" if cov >= 0.5 else "red"

        coords = float(((frame["x"].between(0, 100)) & (frame["y"].between(0, 100))).mean()) \
            if {"x", "y"} <= set(frame.columns) else 0.0
        players = _nonempty(frame, "player")
        teams = _nonempty(frame, "team")
        matches_present = frame["match_id"].astype(str).str.strip().ne("").any() \
            if "match_id" in frame.columns else False
        events_known = float(frame["event_type"].astype(str).str.lower().isin(KNOWN_EVENTS).mean()) \
            if "event_type" in frame.columns else 0.0
        setpiece_cov = _nonempty(frame, "set_piece")
        penalty = 0.0
        if "set_piece" in frame.columns:
            penalty = float(frame["set_piece"].astype(str).str.lower().str.contains("pen").mean())
        tracking = bool(doc.get("tracking"))
        gps = bool(doc.get("gps"))

        axes = [
            HealthAxis("coordinates", "Coordinates", band(coords), coords,
                       f"{coords:.0%} in range"),
            HealthAxis("players", "Players", band(players), players, f"{players:.0%} named"),
            HealthAxis("teams", "Teams", band(teams), teams, f"{teams:.0%} labelled"),
            HealthAxis("matches", "Matches", "green" if matches_present else "yellow",
                       1.0 if matches_present else 0.0,
                       "match ids present" if matches_present else "single/no match id"),
            HealthAxis("events", "Events", band(events_known), events_known,
                       f"{events_known:.0%} known types"),
            HealthAxis("setpiece", "Set Piece Data", band(setpiece_cov), setpiece_cov,
                       f"{setpiece_cov:.0%} tagged" if setpiece_cov else "no set-piece tags"),
            HealthAxis("penalty", "Penalty Data", "green" if penalty > 0 else "red", penalty,
                       "present" if penalty > 0 else "none tagged"),
            HealthAxis("tracking", "Tracking", "green" if tracking else "red",
                       1.0 if tracking else 0.0, "declared" if tracking else "not present"),
            HealthAxis("gps", "GPS", "green" if gps else "red", 1.0 if gps else 0.0,
                       "declared" if gps else "not present"),
        ]
        return DatasetHealth(axes=axes)

    # ------------------------------------------------------------ compatibility
    def compatibility(self, dataset_id: str) -> list[CompatibilityResult]:
        frame = self.repo.frame(dataset_id)
        health = self.health(dataset_id)
        return self._compatibility(frame, health)

    def _compatibility(self, frame: pd.DataFrame | None,
                       health: DatasetHealth) -> list[CompatibilityResult]:
        axis = {a.key: a for a in health.axes}
        has_rows = frame is not None and not frame.empty
        # Open Play needs broad coordinate + event validity (not just presence);
        # players/set-pieces are presence-gated (any identities / any tagging),
        # since those modules run their own deeper validation downstream.
        coords_ok = bool(axis.get("coordinates") and axis["coordinates"].status != "red")
        events_ok = bool(axis.get("events") and axis["events"].status != "red")
        players_present = bool(axis.get("players") and axis["players"].coverage > 0)
        setpiece_present = bool(axis.get("setpiece") and axis["setpiece"].coverage > 0)
        tracking = axis.get("tracking")

        results: list[CompatibilityResult] = []

        def add(module: str, ready: bool, reason: str = "") -> None:
            results.append(CompatibilityResult(module, ready, "" if ready else reason))

        add("Open Play", bool(has_rows and coords_ok and events_ok),
            "needs event rows with valid x/y coordinates")
        add("Set Pieces", setpiece_present,
            "no set-piece tagging (set_piece column empty)")
        add("Players", players_present, "no player identities in the data")
        add("Scouting", players_present, "no player identities to attach observations to")
        add("Reports", bool(has_rows), "no rows to report on")
        add("Tracking", bool(tracking and tracking.status == "green"),
            "missing tracking coordinates / player positions / GPS")
        return results

    # ------------------------------------------------------------ modules-supported summary
    def modules_supported(self, dataset_id: str) -> list[str]:
        return [c.module for c in self.compatibility(dataset_id) if c.ready]

    def target_modules(self) -> tuple:
        return TARGET_MODULES
