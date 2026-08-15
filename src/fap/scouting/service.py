"""ScoutingService - the facade the scouting UI talks to.

Owns the player database and everything that hangs off a player (notes, videos,
media, attachments, watchlists, report links). It is service-driven: no business
logic lives in Streamlit. It REUSES the platform services and never duplicates
them - ImageStorage for images, the new FileStorage for videos/attachments,
ReportsManager for scouting reports (opened in the existing Report Studio),
PermissionService for capability checks and AuditService for the trail.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import pandas as pd

from fap.identity.capabilities import Capability
from fap.identity.models import User
from fap.scouting.models import (
    Player, PlayerAttachment, PlayerMedia, PlayerNote, PlayerVideo,
    ScoutingReportLink, Watchlist,
)
from fap.scouting.repository import (
    AttachmentRepository, MediaRepository, NoteRepository, PlayerRepository,
    ReportLinkRepository, VideoRepository, WatchlistRepository,
)

_ALLOWED_IMAGE = {"image/png", "image/jpeg", "image/jpg", "image/svg+xml", "image/webp"}

# media kind for charts the scout pinned to a player for their report (frozen PNGs)
CHART_MEDIA_KIND = "report_chart"


class ScoutingService:
    def __init__(self, db: Any, *, permissions: Any, audit: Any, reports: Any = None,
                 images: Any = None, videos: Any = None, attachments: Any = None,
                 workspaces: Any = None) -> None:
        self._db = db
        self.players = PlayerRepository(db)
        self.notes = NoteRepository(db)
        self.videos_repo = VideoRepository(db)
        self.media = MediaRepository(db)
        self.attachments_repo = AttachmentRepository(db)
        self.links = ReportLinkRepository(db)
        self.watchlists = WatchlistRepository(db)
        self.perms = permissions
        self.audit = audit
        self._reports = reports
        self._images = images
        self._video_storage = videos
        self._attach_storage = attachments
        self._wm = workspaces

    # ---------------------------------------------------------------- guards
    def _require(self, user: User, cap: Capability, scope: str | None = None) -> None:
        self.perms.require(user, str(cap), scope)

    def _uid(self) -> str:
        return str(uuid.uuid4())

    # ============================================================ active dataset (Phase 12.3)
    # Scouting owns PERSISTENT recruitment metadata (notes, ratings, tags, videos,
    # reports) in its own database. Match/event data is NOT stored here - it is read
    # from the platform's single source of truth (WorkspaceManager.active_frame) and
    # joined to the scouting record IN MEMORY, never duplicated.
    def has_active_dataset(self, user: User) -> bool:
        try:
            return self._wm is not None and self._wm.active_dataset(user) is not None
        except Exception:
            return False

    # ============================================================ scouting datasets (P0.5)
    # A player-scouting table (percentile/metric rows, one per player) imported via
    # the Data Hub is registered as a normal dataset flagged dataset_type=
    # 'player_scouting'. Scouting discovers those here through the SAME
    # WorkspaceManager the rest of the platform uses - no second store, no filename
    # knowledge. The persistent player DB is untouched and stays authoritative.
    def available_scouting_datasets(self, user: User, *,
                                    workspace_id: str | None = None) -> list[dict[str, Any]]:
        """Every registered player-scouting dataset, newest-agnostic. Returns light
        descriptors (id/name/schema summary) so the UI can offer a picker without
        loading any frames."""
        self._require(user, Capability.VIEW_SCOUTING)
        if self._wm is None:
            return []
        from fap.datahub.classification import PLAYER_SCOUTING
        out: list[dict[str, Any]] = []
        try:
            datasets = self._wm.list_datasets(workspace_id=workspace_id)
        except Exception:
            return []
        for ds in datasets:
            doc = ds.document if isinstance(ds.document, dict) else {}
            if doc.get("dataset_type") != PLAYER_SCOUTING:
                continue
            summary = doc.get("scouting_summary", {}) or {}
            out.append({
                "id": ds.id, "name": ds.name,
                "competition": ds.competition or summary.get("competition", ""),
                "players": summary.get("entity_count", ds.rows),
                "teams": summary.get("teams", 0),
                "metrics": summary.get("metric_count", 0),
                "grade": summary.get("grade", doc.get("quality_rating", "")),
            })
        return out

    def scouting_dataset_schema(self, user: User, dataset_id: str) -> dict[str, Any] | None:
        """The persisted semantic schema (id field, dimensions, metrics, units,
        value-scale) of a scouting dataset - what the Scouting analytics need to
        read the table without re-inferring column meaning."""
        self._require(user, Capability.VIEW_SCOUTING)
        if self._wm is None:
            return None
        ds = self._wm.get_dataset(dataset_id)
        if ds is None:
            return None
        doc = ds.document if isinstance(ds.document, dict) else {}
        from fap.datahub.classification import PLAYER_SCOUTING
        if doc.get("dataset_type") != PLAYER_SCOUTING:
            return None
        return doc.get("scouting_schema")

    def scouting_dataset_frame(self, user: User, dataset_id: str):
        """The raw player-scouting table (one row per player), read from the shared
        dataset storage. ``None`` if the dataset is missing or not a scouting table."""
        self._require(user, Capability.VIEW_SCOUTING)
        if self._wm is None or self.scouting_dataset_schema(user, dataset_id) is None:
            return None
        return self._wm.dataset_frame(dataset_id)

    # -- dataset CAPABILITY boundary -----------------------------------------
    # Player-scouting datasets (one row per player, metric columns) and event
    # datasets (one row per on-ball event) are DIFFERENT capabilities and must not
    # be confused: a player-scouting dataset has no events, so the event lookup is
    # never run against it (that produced the misleading "No events found").
    def active_dataset_kind(self, user: User) -> str:
        """The active dataset's capability: ``'player_scouting'``, ``'event'`` (an
        event/match dataset - the historical default, carries no type flag), or
        ``''`` when nothing is active."""
        if self._wm is None:
            return ""
        try:
            ds = self._wm.active_dataset(user)
        except Exception:
            return ""
        if ds is None:
            return ""
        from fap.datahub.classification import PLAYER_SCOUTING
        doc = ds.document if isinstance(ds.document, dict) else {}
        return "player_scouting" if doc.get("dataset_type") == PLAYER_SCOUTING else "event"

    def _player_names(self, p) -> set[str]:
        from fap.scouting import identity
        return identity.identity_keys(p)

    # ============================================================ identity (P4.1)
    # The persistent player_id is the identity anchor; a dataset row is only a data
    # source resolved back to a player by name/alias. All identity attributes the
    # players table has no column for (aliases/display_name/source) live in the
    # existing document JSON - no migration, no new table.
    def resolve_player(self, user: User, *, player_id: str | None = None,
                       name: str | None = None, workspace_id: str | None = None):
        """Resolve an identity to a persistent player. ``player_id`` wins; else an
        exact name/alias match, with ambiguity surfaced (never guessed). Returns an
        ``identity.Resolution``."""
        self._require(user, Capability.VIEW_SCOUTING)
        from fap.scouting import identity
        if player_id:
            p = self.players.get(player_id)
            return identity.Resolution(
                player=p, candidates=[p] if p else [],
                reason="matched by player_id" if p else "no player with that id")
        # Resolve in memory over the workspace pool: aliases/display_name live in the
        # document, which the SQL name filter cannot see, so we must not pre-filter
        # by the name query here.
        pool = self.players.search(query="", workspace_id=workspace_id, limit=500)
        return identity.resolve(pool, name=name)

    def find_players_by_name(self, user: User, name: str, *,
                             workspace_id: str | None = None) -> list[Player]:
        """Every persistent player that answers to ``name`` (name/alias/display),
        for disambiguation UIs. Exact identity match, not a fuzzy search."""
        self._require(user, Capability.VIEW_SCOUTING)
        from fap.scouting import identity
        pool = self.players.search(query="", workspace_id=workspace_id, limit=500)
        return [p for p in pool if identity.matches_name(p, name)]

    def _set_doc(self, user: User, player_id: str, action: str, **doc_updates: Any) -> Player:
        p = self._player_or_raise(player_id)
        doc = dict(p.document) if isinstance(p.document, dict) else {}
        doc.update(doc_updates)
        p.document = doc
        self.players.save(p)
        self.audit.record(user, action, target_type="player", target_id=player_id,
                          detail={"fields": sorted(doc_updates)})
        return p

    def add_alias(self, user: User, player_id: str, alias: str) -> Player:
        self._require(user, Capability.EDIT_SCOUTING)
        from fap.scouting import identity
        p = self._player_or_raise(player_id)
        aliases = identity.aliases_of(p)
        a = str(alias or "").strip()
        if a and a.lower() not in {x.lower() for x in aliases} and a.lower() != p.name.lower():
            aliases.append(a)
        return self._set_doc(user, player_id, "scouting.player.alias_add", aliases=aliases)

    def remove_alias(self, user: User, player_id: str, alias: str) -> Player:
        self._require(user, Capability.EDIT_SCOUTING)
        from fap.scouting import identity
        p = self._player_or_raise(player_id)
        a = str(alias or "").strip().lower()
        aliases = [x for x in identity.aliases_of(p) if x.lower() != a]
        return self._set_doc(user, player_id, "scouting.player.alias_remove", aliases=aliases)

    def set_aliases(self, user: User, player_id: str, aliases: list[str]) -> Player:
        """Replace the whole alias set (de-duplicated, excludes the primary name)."""
        self._require(user, Capability.EDIT_SCOUTING)
        p = self._player_or_raise(player_id)
        cleaned: list[str] = []
        for a in aliases or []:
            a = str(a).strip()
            if a and a.lower() not in {x.lower() for x in cleaned} and a.lower() != p.name.lower():
                cleaned.append(a)
        return self._set_doc(user, player_id, "scouting.player.aliases", aliases=cleaned)

    def set_display_name(self, user: User, player_id: str, display_name: str) -> Player:
        self._require(user, Capability.EDIT_SCOUTING)
        return self._set_doc(user, player_id, "scouting.player.display_name",
                             display_name=str(display_name or "").strip())

    def set_source(self, user: User, player_id: str, source: str) -> Player:
        self._require(user, Capability.EDIT_SCOUTING)
        return self._set_doc(user, player_id, "scouting.player.source",
                             source=str(source or "").strip())

    def set_recruitment_status(self, user: User, player_id: str, status: str) -> Player:
        """Set the canonical recruitment status (normalized). Status *history* is
        added in P4.2; this persists the current value only."""
        self._require(user, Capability.EDIT_SCOUTING)
        from fap.scouting import identity
        p = self._player_or_raise(player_id)
        p.status = identity.normalize_status(status)
        self.players.save(p)
        self.audit.record(user, "scouting.player.status", target_type="player",
                          target_id=player_id, detail={"status": p.status})
        return p

    def set_priority(self, user: User, player_id: str, priority: str) -> Player:
        self._require(user, Capability.EDIT_SCOUTING)
        from fap.scouting import identity
        p = self._player_or_raise(player_id)
        p.priority = identity.normalize_priority(priority)
        self.players.save(p)
        self.audit.record(user, "scouting.player.priority", target_type="player",
                          target_id=player_id, detail={"priority": p.priority})
        return p

    def player_event_frame(self, user: User, player_id: str):
        """The active dataset's events for this scouting player (canonical match/
        event source), joined in memory to the persistent record by name. ``None``
        when no dataset is active, the active dataset is player-scouting (not events),
        or the player has no events in it. Stores nothing."""

    def active_scouting_profile(self, user: User, player_id: str) -> dict[str, Any] | None:
        """When a PLAYER-SCOUTING dataset is active, resolve this scouting record by
        name against the dataset's player-identity column and return its metric
        profile (dimensions + per-metric value/unit + value scale). ``None`` when the
        active dataset is not player-scouting or the player is not in it. Reads the
        persisted schema; never runs an event lookup or fabricates events."""
        self._require(user, Capability.VIEW_SCOUTING)
        if self._wm is None:
            return None
        ds = self._wm.active_dataset(user)
        if ds is None:
            return None
        from fap.datahub.classification import PLAYER_SCOUTING
        doc = ds.document if isinstance(ds.document, dict) else {}
        if doc.get("dataset_type") != PLAYER_SCOUTING:
            return None
        schema = doc.get("scouting_schema") or {}
        id_field = schema.get("id_field")
        frame = self._wm.dataset_frame(ds.id)
        if not id_field or frame is None or getattr(frame, "empty", True) \
                or id_field not in frame.columns:
            return None
        p = self.get_player(player_id)
        if p is None:
            return None
        names = self._player_names(p)
        col = frame[id_field].astype(str).str.lower().str.strip()
        match = frame[col.isin(names)]
        if match.empty:
            return None
        row = match.iloc[0]
        metrics = []
        for m in schema.get("metrics", []):
            src = m.get("source")
            if src in frame.columns:
                val = row[src]
                metrics.append({"name": m.get("name", src), "source": src,
                                "unit": m.get("unit", ""),
                                "value": None if pd.isna(val) else val})
        dimensions = {k: (None if pd.isna(row[v]) else row[v])
                      for k, v in (schema.get("dimensions") or {}).items()
                      if v in frame.columns}
        return {"dataset": ds.name, "dataset_id": ds.id,
                "player": str(row[id_field]), "dimensions": dimensions,
                "metrics": metrics, "value_scale": schema.get("value_scale", "raw")}

    def active_scouting_dataset(self, user: User) -> dict[str, Any] | None:
        """The full active player-scouting dataset context for the visualization
        workspace: id, name, semantic schema, the frame (one row per player) and the
        list of player names. ``None`` when the active dataset is not player-scouting.
        Reads only scouting APIs - never the event pipeline."""
        self._require(user, Capability.VIEW_SCOUTING)
        if self._wm is None:
            return None
        ds = self._wm.active_dataset(user)
        if ds is None:
            return None
        from fap.datahub.classification import PLAYER_SCOUTING
        doc = ds.document if isinstance(ds.document, dict) else {}
        if doc.get("dataset_type") != PLAYER_SCOUTING:
            return None
        schema = doc.get("scouting_schema") or {}
        frame = self._wm.dataset_frame(ds.id)
        id_field = schema.get("id_field")
        players: list[str] = []
        if frame is not None and id_field in getattr(frame, "columns", []):
            players = [str(x) for x in frame[id_field].astype(str).str.strip().tolist()
                       if str(x).strip()]
        return {"id": ds.id, "name": ds.name, "schema": schema, "frame": frame,
                "players": players}

    # -- saved visualization/pizza selections (reuses WorkspaceManager presets) --
    _VIEW_PRESET_KIND = "scouting_pizza"

    def save_scouting_view_preset(self, user: User, name: str,
                                  config: dict[str, Any]) -> str | None:
        """Persist a named metric selection (pizza/radar) via the EXISTING preset
        store - no new persistence system. Returns the preset id, or None if
        presets are unavailable."""
        self._require(user, Capability.EDIT_SCOUTING)
        if self._wm is None:
            return None
        preset = self._wm.save_preset(user, kind=self._VIEW_PRESET_KIND,
                                      name=name, document=dict(config))
        return getattr(preset, "id", None)

    def list_scouting_view_presets(self, user: User) -> list[dict[str, Any]]:
        self._require(user, Capability.VIEW_SCOUTING)
        if self._wm is None:
            return []
        try:
            presets = self._wm.list_presets(user, kind=self._VIEW_PRESET_KIND)
        except Exception:
            return []
        return [{"id": p.id, "name": p.name, "config": p.document} for p in presets]

    def player_event_frame(self, user: User, player_id: str):
        """The active dataset's events for this scouting player (canonical match/
        event source), joined in memory to the persistent record by name. ``None``
        when no dataset is active, the active dataset is player-scouting (not events),
        or the player has no events in it. Stores nothing."""
        self._require(user, Capability.VIEW_SCOUTING)
        if self._wm is None:
            return None
        # Capability boundary: never run the event lookup on a player-scouting
        # dataset (it has no events) - that is what produced "No events found".
        if self.active_dataset_kind(user) == "player_scouting":
            return None
        p = self.get_player(player_id)
        if p is None:
            return None
        frame = self._wm.active_frame(user)
        if frame is None or getattr(frame, "empty", True) or "player" not in frame.columns:
            return None
        names = self._player_names(p)
        match = frame[frame["player"].astype(str).str.lower().str.strip().isin(names)]
        return match if not match.empty else None

    def active_player_stats(self, user: User, player_id: str) -> dict[str, Any]:
        """Event/match counts for this player in the active dataset (read-only)."""
        frame = self.player_event_frame(user, player_id)
        if frame is None:
            return {"events": 0, "matches": 0}
        matches = int(frame["match_id"].astype(str).str.strip().replace("", "0").nunique()) \
            if "match_id" in frame.columns else 0
        return {"events": int(len(frame)), "matches": matches}

    def available_visualizations(self, user: User) -> list[dict[str, str]]:
        """Every registered visualization, live from the shared registry (reused,
        not duplicated) - rendered by the existing engine over the player's frame."""
        self._require(user, Capability.VIEW_SCOUTING)
        from fap.visuals.base import load_builtin_visuals, visual_registry
        load_builtin_visuals()
        out = []
        for cls in visual_registry:
            try:
                info = cls.info
                out.append({"id": info.id, "name": info.name,
                            "category": getattr(info, "category", "") or "General"})
            except Exception:
                continue
        return sorted(out, key=lambda v: (v["category"], v["name"]))

    def render_player_chart(self, user: User, player_id: str, viz_id: str, *,
                            controls: dict[str, Any] | None = None,
                            theme_id: str = "opta_light", dpi: int = 150) -> bytes | None:
        """Render a visualization for the scouting player from the ACTIVE dataset
        through the EXISTING engine (ReportsManager.preview_chart). No new viz code."""
        self._require(user, Capability.VIEW_SCOUTING)
        frame = self.player_event_frame(user, player_id)
        if frame is None or self._reports is None:
            return None
        try:
            return self._reports.preview_chart(viz_id, frame, controls or {}, theme_id=theme_id, dpi=dpi)
        except TypeError:
            return self._reports.preview_chart(viz_id, frame, controls or {}, dpi=dpi)

    # ================================================================ players
    def create_player(self, user: User, name: str, **fields: Any) -> Player:
        self._require(user, Capability.EDIT_SCOUTING)
        p = Player(id=self._uid(), name=name.strip(), owner=user.email, created_by=user.email,
                   workspace_id=fields.pop("workspace_id", None))
        for k, v in fields.items():
            if hasattr(p, k):
                setattr(p, k, v)
        self.players.save(p)
        self.audit.record(user, "scouting.player.create", target_type="player", target_id=p.id,
                          detail={"name": p.name})
        return p

    def get_player(self, player_id: str) -> Player | None:
        return self.players.get(player_id)

    def view_player(self, user: User, player_id: str) -> Player | None:
        """Read + record 'recently viewed' (reuses WorkspaceManager user items)."""
        self._require(user, Capability.VIEW_SCOUTING)
        p = self.players.get(player_id)
        if p and self._wm is not None:
            try:
                self._wm.touch_recent(user, "player", player_id)
            except Exception:
                pass
        return p

    def update_player(self, user: User, player_id: str, **fields: Any) -> Player:
        self._require(user, Capability.EDIT_SCOUTING)
        p = self._player_or_raise(player_id)
        for k, v in fields.items():
            if hasattr(p, k):
                setattr(p, k, v)
        self.players.save(p)
        self.audit.record(user, "scouting.player.update", target_type="player", target_id=player_id,
                          detail={"fields": sorted(fields)})
        return p

    def archive_player(self, user: User, player_id: str, archived: bool = True) -> None:
        self._require(user, Capability.EDIT_SCOUTING)
        p = self._player_or_raise(player_id)
        p.archived = archived
        self.players.save(p)
        self.audit.record(user, "scouting.player.archive" if archived else "scouting.player.restore",
                          target_type="player", target_id=player_id)

    def restore_player(self, user: User, player_id: str) -> None:
        self.archive_player(user, player_id, archived=False)

    def delete_player(self, user: User, player_id: str) -> None:
        """Hard delete a player and all its owned assets (blobs + rows)."""
        self._require(user, Capability.EDIT_SCOUTING)
        self._player_or_raise(player_id)
        for v in self.videos_repo.list(player_id):
            if v.file_id and self._video_storage is not None:
                self._video_storage.delete(v.file_id)
        for a in self.attachments_repo.list(player_id):
            if a.file_id and self._attach_storage is not None:
                self._attach_storage.delete(a.file_id)
        for m in self.media.list(player_id):
            if m.image_id and self._images is not None:
                self._images.delete(m.image_id)
        self.players.delete(player_id)      # cascades notes/videos/media/attachments/links/members
        self.audit.record(user, "scouting.player.delete", target_type="player", target_id=player_id)

    def duplicate_player(self, user: User, player_id: str) -> Player:
        self._require(user, Capability.EDIT_SCOUTING)
        src = self._player_or_raise(player_id)
        copy = Player(id=self._uid(), name=f"{src.name} (copy)", nickname=src.nickname, club=src.club,
                      league=src.league, country=src.country, nationality=src.nationality, age=src.age,
                      dob=src.dob, position=src.position, secondary_positions=list(src.secondary_positions),
                      foot=src.foot, height=src.height, weight=src.weight, shirt_number=src.shirt_number,
                      contract_until=src.contract_until, market_value=src.market_value, agent=src.agent,
                      status=src.status, tags=list(src.tags), custom_fields=dict(src.custom_fields),
                      priority=src.priority, internal_rating=src.internal_rating,
                      workspace_id=src.workspace_id, owner=user.email, created_by=user.email)
        self.players.save(copy)
        self.audit.record(user, "scouting.player.duplicate", target_type="player", target_id=copy.id,
                          detail={"source": player_id})
        return copy

    def merge_players(self, user: User, primary_id: str, other_id: str) -> Player:
        """Move every asset from ``other`` onto ``primary`` and delete ``other`` -
        so the same footballer never exists as two records."""
        self._require(user, Capability.EDIT_SCOUTING)
        primary = self._player_or_raise(primary_id)
        self._player_or_raise(other_id)
        self._db.execute("UPDATE player_notes SET player_id=? WHERE player_id=?", (primary_id, other_id))
        self._db.execute("UPDATE player_videos SET player_id=? WHERE player_id=?", (primary_id, other_id))
        self._db.execute("UPDATE player_media SET player_id=? WHERE player_id=?", (primary_id, other_id))
        self._db.execute("UPDATE player_attachments SET player_id=? WHERE player_id=?", (primary_id, other_id))
        self._db.execute("UPDATE scouting_reports SET player_id=? WHERE player_id=?", (primary_id, other_id))
        self._db.execute(
            "UPDATE OR IGNORE watchlist_members SET player_id=? WHERE player_id=?", (primary_id, other_id))
        self.players.delete(other_id)
        self.audit.record(user, "scouting.player.merge", target_type="player", target_id=primary_id,
                          detail={"merged": other_id})
        return primary

    def set_favorite(self, user: User, player_id: str, on: bool = True) -> None:
        self._require(user, Capability.VIEW_SCOUTING)
        p = self._player_or_raise(player_id)
        p.favorite = on
        self.players.save(p)
        self.audit.record(user, "scouting.player.favorite", target_type="player", target_id=player_id,
                          detail={"on": on})

    def search(self, user: User, *, query: str = "", filters: dict[str, Any] | None = None,
               archived: bool = False, favorite: bool | None = None) -> list[Player]:
        self._require(user, Capability.VIEW_SCOUTING)
        return self.players.search(query=query, filters=filters, archived=archived, favorite=favorite)

    def bulk_archive(self, user: User, ids: list[str], archived: bool = True) -> int:
        self._require(user, Capability.EDIT_SCOUTING)
        n = 0
        for pid in ids:
            p = self.players.get(pid)
            if p:
                p.archived = archived; self.players.save(p); n += 1
        self.audit.record(user, "scouting.player.bulk_archive", target_type="player",
                          target_id=",".join(ids[:20]), detail={"count": n, "archived": archived})
        return n

    def bulk_delete(self, user: User, ids: list[str]) -> int:
        self._require(user, Capability.EDIT_SCOUTING)
        n = 0
        for pid in ids:
            if self.players.get(pid):
                self.delete_player(user, pid); n += 1
        return n

    # ================================================================ notes
    def add_note(self, user: User, player_id: str, body: str, *, kind: str = "note",
                 pinned: bool = False, private: bool = False) -> PlayerNote:
        self._require(user, Capability.EDIT_SCOUTING)
        n = PlayerNote(id=self._uid(), player_id=player_id, body=body, kind=kind, pinned=pinned,
                       private=private, author=user.email)
        self.notes.save(n)
        self.audit.record(user, "scouting.note.add", target_type="player", target_id=player_id)
        return n

    def update_note(self, user: User, note: PlayerNote) -> None:
        self._require(user, Capability.EDIT_SCOUTING)
        self.notes.save(note)
        self.audit.record(user, "scouting.note.update", target_type="note", target_id=note.id)

    def list_notes(self, player_id: str) -> list[PlayerNote]:
        return self.notes.list(player_id)

    def delete_note(self, user: User, note_id: str) -> None:
        self._require(user, Capability.EDIT_SCOUTING)
        self.notes.delete(note_id)
        self.audit.record(user, "scouting.note.delete", target_type="note", target_id=note_id)

    # ================================================================ images
    def add_image(self, user: User, player_id: str, data: bytes, mime: str, *,
                  kind: str = "scouting", caption: str = "") -> PlayerMedia:
        self._require(user, Capability.EDIT_SCOUTING)
        if self._images is None:
            raise ValueError("Image storage is not configured.")
        if mime.lower() not in _ALLOWED_IMAGE:
            raise ValueError(f"Unsupported image type {mime!r}.")
        image_id = self._uid()
        self._images.save(image_id, data, mime)
        m = PlayerMedia(id=self._uid(), player_id=player_id, image_id=image_id, kind=kind,
                        caption=caption, created_by=user.email)
        self.media.add(m)
        if kind == "profile":
            self.update_player(user, player_id, profile_image_id=image_id)
        self.audit.record(user, "scouting.image.add", target_type="player", target_id=player_id,
                          detail={"kind": kind})
        return m

    def list_media(self, player_id: str, *, kind: str | None = None) -> list[PlayerMedia]:
        return self.media.list(player_id, kind=kind)

    # ------------------------------------------------------------ assigned charts
    # A chart the scout rendered in the Visualization workspace and pinned to the
    # player. Stored as a FROZEN PNG (reusing ImageStorage via add_image, kind
    # 'report_chart') so it survives regardless of which dataset is active later,
    # then embedded into the player's report as an image block at generate time.
    def assign_chart(self, user: User, player_id: str, png: bytes, *,
                     title: str = "", viz_id: str = "") -> PlayerMedia:
        self._require(user, Capability.EDIT_SCOUTING)
        caption = (title or viz_id or "Chart").strip()
        m = self.add_image(user, player_id, png, "image/png",
                           kind=CHART_MEDIA_KIND, caption=caption)
        self.audit.record(user, "scouting.chart.assign", target_type="player",
                          target_id=player_id, detail={"viz_id": viz_id, "title": caption})
        return m

    def list_assigned_charts(self, player_id: str) -> list[PlayerMedia]:
        return self.media.list(player_id, kind=CHART_MEDIA_KIND)

    def unassign_chart(self, user: User, media_id: str) -> None:
        self.delete_media(user, media_id)

    def image_bytes(self, image_id: str) -> bytes | None:
        return self._images.load(image_id) if self._images else None

    def delete_media(self, user: User, media_id: str) -> None:
        self._require(user, Capability.EDIT_SCOUTING)
        m = self.media.get(media_id)
        if m and self._images is not None:
            self._images.delete(m.image_id)
        self.media.delete(media_id)
        self.audit.record(user, "scouting.image.delete", target_type="media", target_id=media_id)

    # ================================================================ videos
    def add_uploaded_video(self, user: User, player_id: str, data: bytes, filename: str,
                           mime: str = "", title: str = "") -> PlayerVideo:
        self._require(user, Capability.EDIT_SCOUTING)
        if self._video_storage is None:
            raise ValueError("Video storage is not configured.")
        file_id = self._uid()
        self._video_storage.save(file_id, data, filename=filename, mime=mime)
        v = PlayerVideo(id=self._uid(), player_id=player_id, kind="upload", provider="file",
                        file_id=file_id, filename=filename, mime=mime, size_bytes=len(data),
                        title=title or filename, created_by=user.email)
        self.videos_repo.add(v)
        self.audit.record(user, "scouting.video.upload", target_type="player", target_id=player_id,
                          detail={"filename": filename, "bytes": len(data)})
        return v

    def add_external_video(self, user: User, player_id: str, url: str, *, provider: str = "url",
                           title: str = "") -> PlayerVideo:
        self._require(user, Capability.EDIT_SCOUTING)
        v = PlayerVideo(id=self._uid(), player_id=player_id, kind="external",
                        provider=self._detect_provider(url, provider), url=url,
                        title=title or url, created_by=user.email)
        self.videos_repo.add(v)
        self.audit.record(user, "scouting.video.link", target_type="player", target_id=player_id,
                          detail={"provider": v.provider, "url": url})
        return v

    @staticmethod
    def _detect_provider(url: str, default: str) -> str:
        u = url.lower()
        for name in ("youtube", "youtu.be", "vimeo", "hudl", "wyscout", "skillcorner", "statsbomb"):
            if name in u:
                return "youtube" if "youtu" in name else name
        return default or "url"

    def list_videos(self, player_id: str) -> list[PlayerVideo]:
        return self.videos_repo.list(player_id)

    def video_bytes(self, video_id: str) -> bytes | None:
        v = self.videos_repo.get(video_id)
        return self._video_storage.load(v.file_id) if (v and v.file_id and self._video_storage) else None

    def delete_video(self, user: User, video_id: str) -> None:
        self._require(user, Capability.EDIT_SCOUTING)
        v = self.videos_repo.get(video_id)
        if v and v.file_id and self._video_storage is not None:
            self._video_storage.delete(v.file_id)
        self.videos_repo.delete(video_id)
        self.audit.record(user, "scouting.video.delete", target_type="video", target_id=video_id)

    def set_video_sync(self, user: User, video_id: str, match_id: str,
                       sync_offset_seconds: float | None) -> PlayerVideo | None:
        """Associate a video with a match and record its kickoff offset (the two
        Tier-1 sync fields). Both are plain metadata - no match/event data is copied
        or duplicated. Returns the updated record, or ``None`` if it doesn't exist."""
        self._require(user, Capability.EDIT_SCOUTING)
        if self.videos_repo.get(video_id) is None:
            return None
        offset = None if sync_offset_seconds is None else float(sync_offset_seconds)
        self.videos_repo.set_sync(video_id, str(match_id or ""), offset)
        self.audit.record(user, "scouting.video.sync", target_type="video", target_id=video_id,
                          detail={"match_id": match_id, "offset": offset})
        return self.videos_repo.get(video_id)

    # ================================================================ attachments
    def add_attachment(self, user: User, player_id: str, data: bytes, filename: str,
                       mime: str = "", kind: str = "document") -> PlayerAttachment:
        self._require(user, Capability.EDIT_SCOUTING)
        if self._attach_storage is None:
            raise ValueError("Attachment storage is not configured.")
        file_id = self._uid()
        self._attach_storage.save(file_id, data, filename=filename, mime=mime)
        a = PlayerAttachment(id=self._uid(), player_id=player_id, file_id=file_id, filename=filename,
                             mime=mime, size_bytes=len(data), kind=kind, created_by=user.email)
        self.attachments_repo.add(a)
        self.audit.record(user, "scouting.attachment.add", target_type="player", target_id=player_id,
                          detail={"filename": filename})
        return a

    def list_attachments(self, player_id: str) -> list[PlayerAttachment]:
        return self.attachments_repo.list(player_id)

    def attachment_bytes(self, attachment_id: str) -> bytes | None:
        a = self.attachments_repo.get(attachment_id)
        return self._attach_storage.load(a.file_id) if (a and self._attach_storage) else None

    def delete_attachment(self, user: User, attachment_id: str) -> None:
        self._require(user, Capability.EDIT_SCOUTING)
        a = self.attachments_repo.get(attachment_id)
        if a and self._attach_storage is not None:
            self._attach_storage.delete(a.file_id)
        self.attachments_repo.delete(attachment_id)
        self.audit.record(user, "scouting.attachment.delete", target_type="attachment",
                          target_id=attachment_id)

    # ================================================================ reports (reuse Studio)
    def create_report(self, user: User, player_id: str, *, title: str = "",
                      include_charts: bool = True) -> ScoutingReportLink:
        """Auto-generate a professional scouting report through ReportsManager and
        link it to the player. Assigned charts (pinned in the Visualization tab)
        are embedded as image blocks so a downloaded report already contains them.
        The report is then edited in the EXISTING Report Studio - no second editor."""
        self._require(user, Capability.CREATE_REPORT)
        if self._reports is None:
            raise ValueError("Reports engine is not configured.")
        p = self._player_or_raise(player_id)
        title = title or f"Scouting Report — {p.name}"
        cover = {"title": title, "subtitle": f"{p.position} · {p.club}".strip(" ·"),
                 "club": p.club, "competition": p.league, "opponent": "", "season": "",
                 "analyst": user.name or user.email, "match_date": ""}
        df = self._player_frame(p)
        record = self._auto_report(user, p, title, cover, df)
        if include_charts:
            try:
                self.add_charts_to_report(user, record.id, player_id)
            except Exception:
                pass                                   # a report without charts is still valid
        link = ScoutingReportLink(id=self._uid(), player_id=player_id, report_id=record.id,
                                  title=title, created_by=user.email)
        self.links.add(link)
        self.audit.record(user, "scouting.report.create", target_type="player", target_id=player_id,
                          detail={"report_id": record.id, "title": title})
        return link

    def add_charts_to_report(self, user: User, report_id: str, player_id: str) -> int:
        """Append every chart assigned to the player onto a report as image blocks.
        Reuses the reports engine's document mutation + shared ImageStorage; the
        exporter embeds the image at download. Returns how many were added."""
        self._require(user, Capability.CREATE_REPORT)
        if self._reports is None:
            return 0
        charts = self.list_assigned_charts(player_id)
        if not charts:
            return 0
        from fap.reports.blocks import add_block, image_block

        def mutate(doc):
            for m in charts:
                add_block(doc, image_block(m.image_id, caption=m.caption or "",
                                           title=m.caption or "Chart"))
        self._reports.update_blocks(user, report_id, mutate)
        self.audit.record(user, "scouting.report.charts", target_type="report",
                          target_id=report_id, detail={"count": len(charts), "player": player_id})
        return len(charts)

    def report_formats(self) -> list[str]:
        return self._reports.available_formats() if self._reports is not None else []

    def render_report(self, user: User, report_id: str, fmt: str = "pdf"):
        """Render a linked report to a downloadable file (PDF/HTML/DOCX/PPTX) via
        the existing reports engine - charts embedded. Returns a RenderedReport
        (``.content`` bytes, ``.filename``, ``.mime``)."""
        self._require(user, Capability.EXPORT_REPORT)
        if self._reports is None:
            raise ValueError("Reports engine is not configured.")
        return self._reports.render(user, report_id, fmt)

    def _auto_report(self, user: User, player: Player, title: str, cover: dict[str, Any],
                     df: pd.DataFrame):
        # Start blank (cover + empty body): the scout builds the report in the
        # Studio with Add Content. No sections are auto-inserted.
        templates = [t.info.id for t in self._reports.templates()]
        template = "blank" if "blank" in templates else (templates[0] if templates else "")
        try:
            return self._reports.create(user, template=template, df=df, title=title,
                                        workspace_id=player.workspace_id, cover=cover)
        except Exception:
            return self._reports.create(user, template=templates[0], df=df, title=title,
                                        workspace_id=player.workspace_id, cover=cover)

    @staticmethod
    def _player_frame(p: Player) -> pd.DataFrame:
        return pd.DataFrame([{
            "player": p.name, "club": p.club, "league": p.league, "position": p.position,
            "age": p.age or 0, "foot": p.foot, "height": p.height or 0,
            "rating": p.internal_rating or 0, "market_value": p.market_value or 0}])

    def list_reports(self, player_id: str) -> list[ScoutingReportLink]:
        return self.links.list(player_id)

    # ================================================================ watchlists
    def create_watchlist(self, user: User, name: str) -> Watchlist:
        self._require(user, Capability.EDIT_SCOUTING)
        w = Watchlist(id=self._uid(), name=name.strip(), owner=user.email)
        self.watchlists.save(w)
        self.audit.record(user, "scouting.watchlist.create", target_type="watchlist", target_id=w.id,
                          detail={"name": name})
        return w

    def list_watchlists(self) -> list[Watchlist]:
        return self.watchlists.list()

    def add_to_watchlist(self, user: User, watchlist_id: str, player_id: str) -> None:
        self._require(user, Capability.EDIT_SCOUTING)
        self.watchlists.add_member(watchlist_id, player_id, added_by=user.email)
        self.audit.record(user, "scouting.watchlist.add", target_type="watchlist",
                          target_id=watchlist_id, detail={"player": player_id})

    def remove_from_watchlist(self, user: User, watchlist_id: str, player_id: str) -> None:
        self._require(user, Capability.EDIT_SCOUTING)
        self.watchlists.remove_member(watchlist_id, player_id)
        self.audit.record(user, "scouting.watchlist.remove", target_type="watchlist",
                          target_id=watchlist_id, detail={"player": player_id})

    def watchlist_players(self, watchlist_id: str) -> list[Player]:
        return [p for pid in self.watchlists.members(watchlist_id)
                if (p := self.players.get(pid)) is not None]

    def watchlists_for_player(self, player_id: str) -> list[str]:
        return self.watchlists.watchlists_for_player(player_id)

    # ================================================================ dashboard
    def dashboard(self, user: User) -> dict[str, Any]:
        self._require(user, Capability.VIEW_SCOUTING)
        today = date.today().isoformat()
        soon = date(date.today().year + 1, date.today().month, 1).isoformat()
        recents = []
        if self._wm is not None:
            try:
                recents = [p for tt, tid in self._wm.recents(user, limit=8) if tt == "player"
                           and (p := self.players.get(tid)) is not None]
            except Exception:
                recents = []
        return {
            "counts": {"active": self.players.count(archived=False),
                       "archived": self.players.count(archived=True)},
            "recent": self.players.recent(limit=8),
            "recently_viewed": recents,
            "favorites": self.players.search(query="", favorite=True)[:8],
            "top_rated": self.players.top_rated(limit=8),
            "contracts_expiring": self.players.contracts_expiring(before=soon, limit=8),
            "latest_reports": self.links.recent(limit=8),
            "watchlists": self.watchlists.list(),
        }

    # ================================================================ admin / storage
    def storage_report(self, user: User) -> dict[str, Any]:
        self._require(user, Capability.VIEW_SCOUTING)
        return {
            "players_active": self.players.count(archived=False),
            "players_archived": self.players.count(archived=True),
            "videos_bytes": self._dir_size(getattr(self._video_storage, "_root", None)),
            "attachments_bytes": self._dir_size(getattr(self._attach_storage, "_root", None)),
        }

    def archived_players(self, user: User) -> list[Player]:
        self._require(user, Capability.VIEW_SCOUTING)
        return self.players.recent(limit=500, archived=True)

    # ---------------------------------------------------------------- helpers
    def _player_or_raise(self, player_id: str) -> Player:
        p = self.players.get(player_id)
        if p is None:
            raise ValueError(f"player {player_id!r} not found")
        return p

    @staticmethod
    def _dir_size(root: Any) -> int:
        if not root:
            return 0
        import os
        total = 0
        try:
            for dp, _d, files in os.walk(str(root)):
                for f in files:
                    try:
                        total += os.path.getsize(os.path.join(dp, f))
                    except OSError:
                        pass
        except Exception:
            return 0
        return total
