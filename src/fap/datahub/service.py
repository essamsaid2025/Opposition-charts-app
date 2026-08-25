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
from dataclasses import dataclass
from typing import Any

import pandas as pd

from fap.datahub import quality as dq
from fap.datahub import validation as dv
from fap.datahub.classification import (
    DatasetClassification, PLAYER_SCOUTING, TEAM_MATCH_STATS, classify_frame,
)
from fap.datahub.dataset_profiles import ProfileStore
from fap.datahub.models import (
    LINEAGE_STAGES, TARGET_MODULES, CompatibilityResult, DatasetHealth, HealthAxis,
    LineageEvent, SUPPORTED_SOURCES,
)
from fap.datahub.preview import PreviewRequest, PreviewResult, build_preview
from fap.datahub.repository import DataHubRepository
from fap.datahub.scouting_schema import ScoutingAnalysis, analyze_player_scouting
from fap.datahub.team_stats_schema import TeamStatsAnalysis, analyze_team_stats
from fap.identity.models import User
from fap.pipeline.importer import FilePreview, ImportResult, ImportService
from fap.pipeline.validation import KNOWN_EVENTS

# document key that flags a dataset's kind for every downstream consumer
DATASET_TYPE_KEY = "dataset_type"
ENTITY_TYPE_KEY = "entity_type"
# grade -> a 0-100 quality number so scouting datasets render on the same library
# card + quality badge as event datasets (no separate visual language).
_GRADE_SCORE = {"Good": 85.0, "Fair": 65.0, "Poor": 40.0}


@dataclass(slots=True)
class AnalyzeResult:
    """Discriminated result of ``analyze`` — the Data Hub's single entry point
    that classifies a file *first*, then routes it to the right analyzer. ``kind``
    tells the UI which report to render; exactly one payload is populated."""
    kind: str                                   # "event" | "player_scouting" | "team_match_stats"
    classification: DatasetClassification
    filename: str = ""
    import_result: ImportResult | None = None   # kind == "event"
    scouting: ScoutingAnalysis | None = None    # kind == "player_scouting"
    team_stats: TeamStatsAnalysis | None = None  # kind == "team_match_stats"


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

    # ------------------------------------------------------- classification/routing
    def classify(self, data: bytes, filename: str, *,
                 provider_id: str | None = None) -> DatasetClassification:
        """What does this file represent? Loads the raw provider frame (reusing the
        ImportService's one provider-resolution path) and classifies its schema/
        content — event, tracking, player-scouting, roster, set-piece or unknown —
        without running the event pipeline. Row-count agnostic; never uses the
        filename as evidence."""
        preview = self._imp.inspect(data, filename, provider_id=provider_id)
        return classify_frame(preview.frame)

    def analyze(self, data: bytes, filename: str, *, provider_id: str | None = None,
                use_cache: bool = True) -> AnalyzeResult:
        """Classify first, then route to the correct analyzer. A player-scouting
        table is read by the scouting analyzer (never the event pipeline, which is
        why it no longer fails with 'No objects to concatenate'); anything else
        continues through the existing event import unchanged."""
        preview = self._imp.inspect(data, filename, provider_id=provider_id)
        cls = classify_frame(preview.frame)
        if cls.is_player_scouting:
            analysis = analyze_player_scouting(preview.frame, cls)
            return AnalyzeResult(kind=PLAYER_SCOUTING, classification=cls,
                                 filename=filename, scouting=analysis)
        if cls.dataset_type == TEAM_MATCH_STATS:
            ts = analyze_team_stats(preview.frame, cls)
            return AnalyzeResult(kind=TEAM_MATCH_STATS, classification=cls,
                                 filename=filename, team_stats=ts)
        result = self.run_import(data, filename, provider_id=provider_id,
                                 use_cache=use_cache)
        return AnalyzeResult(kind="event", classification=cls, filename=filename,
                             import_result=result)

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

    def save_scouting_dataset(self, user: User, analysis: ScoutingAnalysis, *, name: str,
                              workspace_id: str | None = None,
                              metadata: dict[str, Any] | None = None):
        """Persist a player-scouting table as a first-class dataset through the SAME
        WorkspaceManager register/store paths every dataset uses (no second store).
        The semantic schema (dimensions/metrics/units/value-scale) and a
        ``dataset_type`` flag are stored in the dataset's existing ``document`` JSON,
        so the Scouting module can discover and read it without re-inferring."""
        meta = dict(metadata or {})
        summary = analysis.summary()
        frame = analysis.frame if analysis.frame is not None else pd.DataFrame()
        grade = analysis.quality.grade
        document = {
            DATASET_TYPE_KEY: analysis.dataset_type,
            ENTITY_TYPE_KEY: analysis.schema.entity_type,
            "scouting_schema": analysis.schema.to_dict(),
            "scouting_summary": summary,
            "classification": analysis.classification.to_dict(),
            "quality": _GRADE_SCORE.get(grade, 60.0),
            "quality_rating": grade,
            "provider": "player_scouting",
            "coord_system": "",
            "pitch": meta.get("pitch", ""),
            "units": meta.get("units", ""),
            "tags": list(meta.get("tags", [])),
            "visibility": meta.get("visibility", "workspace"),
            "description": meta.get("description", ""),
        }
        ds = self.repo.register(
            user, name=name, provider_id="player_scouting", coord_system="",
            rows=int(len(frame)), content_hash="", workspace_id=workspace_id,
            season=meta.get("season", ""),
            competition=meta.get("competition") or analysis.competition,
            opponent=meta.get("opponent", ""), match_date=meta.get("match_date", ""),
            document=document)
        self.repo.store_frame(ds.id, frame)
        lineage = [LineageEvent(s, _now(), user.email,
                                "scouting analyzer").to_dict() for s in LINEAGE_STAGES[:5]]
        lineage.append(LineageEvent("saved", _now(), user.email, name).to_dict())
        self.repo.save_hub_doc(ds.id, {"lineage": lineage, "versions": []})
        self._snapshot(ds.id, user, note="initial import")
        return self.repo.get(ds.id)

    def save_team_stats_dataset(self, user: User, analysis: TeamStatsAnalysis, *, name: str,
                                workspace_id: str | None = None,
                                metadata: dict[str, Any] | None = None):
        """Persist a team-comparison stat table as a first-class dataset through the
        SAME WorkspaceManager register/store paths every dataset uses. The semantic
        schema (teams/categories/statistics/units) and a ``dataset_type`` flag live
        in the dataset's existing ``document`` JSON, so Open Play can discover it and
        draw dedicated comparison charts without re-inferring anything."""
        meta = dict(metadata or {})
        summary = analysis.summary()
        frame = analysis.frame if analysis.frame is not None else pd.DataFrame()
        grade = analysis.quality.grade
        document = {
            DATASET_TYPE_KEY: analysis.dataset_type,
            ENTITY_TYPE_KEY: analysis.schema.entity_type,
            "team_stats_schema": analysis.schema.to_dict(),
            "team_stats_summary": summary,
            "classification": analysis.classification.to_dict(),
            "quality": _GRADE_SCORE.get(grade, 60.0),
            "quality_rating": grade,
            "provider": "team_match_stats",
            "coord_system": "",
            "pitch": meta.get("pitch", ""),
            "units": meta.get("units", ""),
            "tags": list(meta.get("tags", [])),
            "visibility": meta.get("visibility", "workspace"),
            "description": meta.get("description", ""),
        }
        ds = self.repo.register(
            user, name=name, provider_id="team_match_stats", coord_system="",
            rows=int(len(frame)), content_hash="", workspace_id=workspace_id,
            season=meta.get("season", ""),
            competition=meta.get("competition") or analysis.competition,
            opponent=meta.get("opponent", ""), match_date=meta.get("match_date", ""),
            document=document)
        self.repo.store_frame(ds.id, frame)
        lineage = [LineageEvent(s, _now(), user.email,
                                "team-stats analyzer").to_dict() for s in LINEAGE_STAGES[:5]]
        lineage.append(LineageEvent("saved", _now(), user.email, name).to_dict())
        self.repo.save_hub_doc(ds.id, {"lineage": lineage, "versions": []})
        self._snapshot(ds.id, user, note="initial import")
        return self.repo.get(ds.id)

    # ------------------------------------------------------------ scouting discovery
    def list_scouting_datasets(self, *, workspace_id: str | None = None,
                               include_archived: bool = False) -> list[Any]:
        """Every registered player-scouting dataset — the query the Scouting module
        uses to find datasets by kind, without knowing any filename."""
        out = []
        for ds in self.repo.list(workspace_id=workspace_id,
                                 include_archived=include_archived):
            doc = ds.document if isinstance(ds.document, dict) else {}
            if doc.get(DATASET_TYPE_KEY) == PLAYER_SCOUTING:
                out.append(ds)
        return out

    def list_team_stats_datasets(self, *, workspace_id: str | None = None,
                                 include_archived: bool = False) -> list[Any]:
        """Every registered team-match-stats dataset — the query Open Play uses to
        find comparison tables by kind, without knowing any filename."""
        out = []
        for ds in self.repo.list(workspace_id=workspace_id,
                                 include_archived=include_archived):
            doc = ds.document if isinstance(ds.document, dict) else {}
            if doc.get(DATASET_TYPE_KEY) == TEAM_MATCH_STATS:
                out.append(ds)
        return out

    @staticmethod
    def dataset_type(ds: Any) -> str:
        doc = getattr(ds, "document", None)
        return doc.get(DATASET_TYPE_KEY, "") if isinstance(doc, dict) else ""

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
        if doc.get(DATASET_TYPE_KEY) == PLAYER_SCOUTING:
            return self._scouting_health(frame, doc)
        if doc.get(DATASET_TYPE_KEY) == TEAM_MATCH_STATS:
            return self._team_stats_health(doc)
        return self._health(frame, doc)

    def _team_stats_health(self, doc: dict[str, Any]) -> DatasetHealth:
        """Team-comparison tables are graded on team/statistic/category coverage
        and value completeness — not on event coordinates/event-types, which they
        legitimately lack. Reads the persisted semantic schema; never re-infers."""
        schema = doc.get("team_stats_schema", {}) if isinstance(doc, dict) else {}
        teams = schema.get("teams", []) or []
        stats = schema.get("stats", []) or []
        cats = schema.get("categories", []) or []
        n_teams = len(teams)
        incomplete = sum(1 for s in stats
                         if len({k for k, v in (s.get("values") or {}).items()
                                 if v is not None}) < n_teams)
        axes = [
            HealthAxis("teams", "Teams", "green" if n_teams >= 2 else "red",
                       1.0 if n_teams >= 2 else 0.0, f"{n_teams} team(s) compared"),
            HealthAxis("statistics", "Statistics",
                       "green" if len(stats) >= 5 else "yellow" if stats else "red",
                       1.0 if stats else 0.0, f"{len(stats)} statistic(s)"),
            HealthAxis("categories", "Categories",
                       "green" if cats else "yellow", 1.0 if cats else 0.0,
                       f"{len(cats)} category group(s)" if cats else "no category grouping"),
            HealthAxis("completeness", "Completeness",
                       "yellow" if incomplete else "green",
                       1.0 - (incomplete / len(stats) if stats else 0.0),
                       f"{incomplete} statistic(s) missing a team value" if incomplete
                       else "every statistic has a value for each team"),
        ]
        return DatasetHealth(axes=axes)

    def _scouting_health(self, frame: pd.DataFrame | None,
                         doc: dict[str, Any]) -> DatasetHealth:
        """Player-scouting datasets are graded on identity/metric/dimension
        coverage — not on event coordinates/event-types, which they legitimately
        lack. Reads the persisted semantic schema so it never re-infers."""
        schema = doc.get("scouting_schema", {}) if isinstance(doc, dict) else {}
        summary = doc.get("scouting_summary", {}) if isinstance(doc, dict) else {}
        metrics = schema.get("metrics", []) or []
        dims = schema.get("dimensions", {}) or {}
        rows = int(len(frame)) if frame is not None else int(summary.get("entity_count", 0))
        missing = [m for m in metrics if float(m.get("missing_pct", 0)) > 0]
        id_ok = bool(schema.get("id_field"))
        axes = [
            HealthAxis("identity", "Player Identity", "green" if id_ok else "red",
                       1.0 if id_ok else 0.0,
                       "player column present" if id_ok else "no player column"),
            HealthAxis("metrics", "Scouting Metrics",
                       "green" if len(metrics) >= 3 else "yellow" if metrics else "red",
                       1.0 if metrics else 0.0, f"{len(metrics)} metric(s)"),
            HealthAxis("dimensions", "Dimensions",
                       "green" if len(dims) >= 2 else "yellow" if dims else "red",
                       min(len(dims) / 6.0, 1.0), f"{len(dims)} identity/dimension field(s)"),
            HealthAxis("completeness", "Completeness",
                       "yellow" if missing else "green",
                       1.0 - (len(missing) / len(metrics) if metrics else 0.0),
                       f"{len(missing)} metric(s) with missing values" if missing
                       else "no missing metric values"),
            HealthAxis("players", "Players", "green" if rows else "red",
                       1.0 if rows else 0.0, f"{rows} player row(s)"),
        ]
        return DatasetHealth(axes=axes)

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
        ds = self.repo.get(dataset_id)
        doc = (ds.document if ds else {}) or {}
        if doc.get(DATASET_TYPE_KEY) == PLAYER_SCOUTING:
            schema = doc.get("scouting_schema", {}) if isinstance(doc, dict) else {}
            has_players = bool(schema.get("id_field"))
            has_metrics = bool(schema.get("metrics"))
            ready = has_players and has_metrics
            return [
                CompatibilityResult("Scouting", ready,
                                    "" if ready else "no player identity/metrics"),
                CompatibilityResult("Players", has_players,
                                    "" if has_players else "no player identity"),
                CompatibilityResult("Reports", bool(has_players),
                                    "" if has_players else "no rows to report on"),
                CompatibilityResult("Open Play", False, "player-level data, not events"),
                CompatibilityResult("Set Pieces", False, "player-level data, not events"),
                CompatibilityResult("Tracking", False, "player-level data, not tracking"),
            ]
        if doc.get(DATASET_TYPE_KEY) == TEAM_MATCH_STATS:
            schema = doc.get("team_stats_schema", {}) if isinstance(doc, dict) else {}
            has_teams = len(schema.get("teams", []) or []) >= 2
            has_stats = bool(schema.get("stats"))
            ready = has_teams and has_stats
            return [
                CompatibilityResult("Open Play", ready,
                                    "" if ready else "no team columns / statistics to compare"),
                CompatibilityResult("Reports", has_stats,
                                    "" if has_stats else "no statistics to report on"),
                CompatibilityResult("Set Pieces", False, "team-level stats, not events"),
                CompatibilityResult("Players", False, "team-level stats, no player identities"),
                CompatibilityResult("Scouting", False, "team-level stats, no player identities"),
                CompatibilityResult("Tracking", False, "team-level stats, not tracking"),
            ]
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
