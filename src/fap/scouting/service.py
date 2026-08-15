"""ScoutingService - the facade the scouting UI talks to.

Owns the player database and everything that hangs off a player (notes, videos,
media, attachments, watchlists, report links). It is service-driven: no business
logic lives in Streamlit. It REUSES the platform services and never duplicates
them - ImageStorage for images, the new FileStorage for videos/attachments,
ReportsManager for scouting reports (opened in the existing Report Studio),
PermissionService for capability checks and AuditService for the trail.
"""
from __future__ import annotations

import datetime as _dt
import uuid
from datetime import date
from typing import Any

import pandas as pd


def _dt_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")

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

    def set_recruitment_status(self, user: User, player_id: str, status: str,
                               note: str = "") -> Player:
        """Set the canonical recruitment status (normalized) and append an
        append-only status-history event to the player's document (+ audit trail).
        No-op history entry when the status is unchanged."""
        self._require(user, Capability.EDIT_SCOUTING)
        from fap.scouting import identity
        p = self._player_or_raise(player_id)
        old = identity.normalize_status(p.status)
        new = identity.normalize_status(status)
        p.status = new
        if new != old:
            history = identity.status_history_of(p)
            history.append({"from": old, "to": new, "at": _dt_now(), "by": user.email,
                            "note": str(note or "").strip()})
            doc = dict(p.document) if isinstance(p.document, dict) else {}
            doc["status_history"] = history
            p.document = doc
        self.players.save(p)
        self.audit.record(user, "scouting.player.status", target_type="player",
                          target_id=player_id, detail={"status": p.status, "from": old})
        return p

    # ============================================================ pathway / registry (P4.2)
    def _assign_operational_id(self, player_type: str) -> str:
        """A stable, club-wide operational id (CLB-/ACD-/TRI-000001). Backed by the
        WorkspaceManager's global monotonic counter, so ids are never reused after a
        player is deleted. The immutable player_id remains the true identity anchor."""
        from fap.scouting import identity
        pt = identity.normalize_player_type(player_type)
        prefix = identity.TYPE_PREFIX.get(pt, "CLB")
        seq = self._wm.next_counter(f"scouting_op_{prefix}") if self._wm is not None else 0
        return identity.format_operational_id(pt, seq)

    def set_player_type(self, user: User, player_id: str, player_type: str, *,
                        reassign_operational_id: bool = False, note: str = "") -> Player:
        """Change a player's pathway (academy/first_team/trialist) WITHOUT changing
        player_id. Records a pathway-history event; optionally issues a new
        operational id for the new pathway while keeping the old one in history."""
        self._require(user, Capability.EDIT_SCOUTING)
        from fap.scouting import identity
        p = self._player_or_raise(player_id)
        old_type = identity.player_type_of(p)
        new_type = identity.normalize_player_type(player_type)
        old_op = identity.operational_id_of(p)
        doc = dict(p.document) if isinstance(p.document, dict) else {}
        doc["player_type"] = new_type
        new_op = old_op
        if reassign_operational_id or not old_op:
            new_op = self._assign_operational_id(new_type)
            doc["operational_id"] = new_op
        history = list(doc.get("pathway_history", []) or [])
        history.append({"from": old_type, "to": new_type, "at": _dt_now(), "by": user.email,
                        "operational_id_before": old_op, "operational_id_after": new_op,
                        "note": str(note or "").strip()})
        doc["pathway_history"] = history
        p.document = doc
        self.players.save(p)
        self.audit.record(user, "scouting.player.pathway", target_type="player",
                          target_id=player_id,
                          detail={"from": old_type, "to": new_type, "operational_id": new_op})
        return p

    def promote_to_first_team(self, user: User, player_id: str, note: str = "") -> Player:
        """Promote an academy player to the first team - SAME player_id, all history
        and assets preserved, a new CLB operational id issued, pathway history logged."""
        return self.set_player_type(user, player_id, "first_team",
                                    reassign_operational_id=True, note=note)

    def set_recruitment_profile(self, user: User, player_id: str, profile_id: str) -> Player:
        self._require(user, Capability.EDIT_SCOUTING)
        return self._set_doc(user, player_id, "scouting.player.profile",
                             recruitment_profile=str(profile_id or "").strip())

    def set_age_group(self, user: User, player_id: str, age_group: str) -> Player:
        self._require(user, Capability.EDIT_SCOUTING)
        return self._set_doc(user, player_id, "scouting.player.age_group",
                             age_group=str(age_group or "").strip())

    def set_academy_profile(self, user: User, player_id: str, **fields: Any) -> Player:
        """Store academy-specific development fields (development stage, potential
        ratings, projection, …) in document['academy']. Only the given keys are set;
        empty values are dropped so nothing is fabricated."""
        self._require(user, Capability.EDIT_SCOUTING)
        from fap.scouting import identity
        p = self._player_or_raise(player_id)
        academy = identity.academy_profile_of(p)
        for k, v in fields.items():
            if v in (None, ""):
                academy.pop(k, None)
            else:
                academy[k] = v
        return self._set_doc(user, player_id, "scouting.player.academy", academy=academy)

    def set_trial_profile(self, user: User, player_id: str, **fields: Any) -> Player:
        """Store trialist-specific fields (trial period/source, evaluation status) in
        document['trial']. Empty values dropped - nothing fabricated."""
        self._require(user, Capability.EDIT_SCOUTING)
        p = self._player_or_raise(player_id)
        doc = dict(p.document) if isinstance(p.document, dict) else {}
        trial = dict(doc.get("trial") or {})
        for k, v in fields.items():
            if v in (None, ""):
                trial.pop(k, None)
            else:
                trial[k] = v
        return self._set_doc(user, player_id, "scouting.player.trial", trial=trial)

    # -- professional profile (P4.3) ----------------------------------------
    _PROFILE_COLUMNS = ("dob", "nationality", "country", "height", "weight", "foot",
                        "position", "secondary_positions", "club", "league",
                        "shirt_number", "contract_until", "agent", "market_value")

    def update_profile(self, user: User, player_id: str, **fields: Any) -> Player:
        """Edit structured profile metadata. Preserves player_id / operational_id /
        aliases / dataset links / videos / notes / history - only the given profile
        fields change. Foot is normalized to the controlled vocabulary; secondary
        nationalities are multi-valued in document. Audited."""
        self._require(user, Capability.EDIT_SCOUTING)
        from fap.scouting import player_profile
        secondary_nats = fields.pop("secondary_nationalities", None)
        if "foot" in fields and fields["foot"] is not None:
            fields["foot"] = player_profile.normalize_foot(fields["foot"])
        col_updates = {k: v for k, v in fields.items() if k in self._PROFILE_COLUMNS}
        if col_updates:
            self.update_player(user, player_id, **col_updates)
        if secondary_nats is not None:
            self.set_secondary_nationalities(user, player_id, secondary_nats)
        return self._player_or_raise(player_id)

    def set_secondary_nationalities(self, user: User, player_id: str,
                                    nationalities: list[str]) -> Player:
        self._require(user, Capability.EDIT_SCOUTING)
        p = self._player_or_raise(player_id)
        doc = dict(p.document) if isinstance(p.document, dict) else {}
        prof = dict(doc.get("profile") or {})
        cleaned: list[str] = []
        for n in nationalities or []:
            n = str(n).strip()
            if n and n not in cleaned:
                cleaned.append(n)
        prof["secondary_nationalities"] = cleaned
        doc["profile"] = prof
        return self._save_doc(user, player_id, doc, "scouting.player.profile")

    def _save_doc(self, user: User, player_id: str, doc: dict[str, Any], action: str) -> Player:
        p = self._player_or_raise(player_id)
        p.document = doc
        self.players.save(p)
        self.audit.record(user, action, target_type="player", target_id=player_id)
        return p

    # club logo (reuses ImageStorage; no new media store)
    def set_club_logo(self, user: User, player_id: str, data: bytes, mime: str) -> Player:
        self._require(user, Capability.EDIT_SCOUTING)
        self.add_image(user, player_id, data, mime, kind="logo", caption="club logo")
        return self._player_or_raise(player_id)

    def remove_club_logo(self, user: User, player_id: str) -> Player:
        self._require(user, Capability.EDIT_SCOUTING)
        p = self._player_or_raise(player_id)
        if p.club_logo_id and self._images is not None:
            self._images.delete(p.club_logo_id)
        return self.update_player(user, player_id, club_logo_id="")

    # external (non-video) links - stored in document, no new table/storage
    def add_link(self, user: User, player_id: str, url: str, *, title: str = "",
                 category: str = "reference", note: str = "") -> dict[str, Any]:
        self._require(user, Capability.EDIT_SCOUTING)
        p = self._player_or_raise(player_id)
        doc = dict(p.document) if isinstance(p.document, dict) else {}
        links = list(doc.get("links", []) or [])
        link = {"id": self._uid(), "url": str(url).strip(), "title": str(title).strip() or str(url).strip(),
                "category": category, "note": note, "created_by": user.email, "created_at": _dt_now()}
        links.append(link)
        doc["links"] = links
        self._save_doc(user, player_id, doc, "scouting.player.link_add")
        return link

    def list_links(self, player_id: str) -> list[dict[str, Any]]:
        p = self.get_player(player_id)
        from fap.scouting import player_profile
        return player_profile.links_of(p) if p else []

    def delete_link(self, user: User, player_id: str, link_id: str) -> None:
        self._require(user, Capability.EDIT_SCOUTING)
        p = self._player_or_raise(player_id)
        doc = dict(p.document) if isinstance(p.document, dict) else {}
        doc["links"] = [l for l in (doc.get("links") or []) if l.get("id") != link_id]
        self._save_doc(user, player_id, doc, "scouting.player.link_delete")

    def player_dashboard(self, user: User, player_id: str) -> dict[str, Any] | None:
        """Everything the premium player dashboard needs, aggregated from existing
        services: normalized snapshot, dataset-link state, transparent profile fit,
        top/bottom percentile strengths, and asset counts. Never fabricates."""
        self._require(user, Capability.VIEW_SCOUTING)
        from fap.scouting import identity, player_profile
        p = self.get_player(player_id)
        if p is None:
            return None
        snap = player_profile.player_snapshot(p)
        link = self.dataset_link_status(user, player_id)
        fit = None
        prof_id = snap.get("recruitment_profile")
        if prof_id:
            fit = self.profile_fit_for(user, player_id, prof_id)
        strengths, dev_areas = self._percentile_highlights(user, player_id)
        counts = {"notes": len(self.list_notes(player_id)),
                  "videos": len(self.list_videos(player_id)),
                  "links": len(self.list_links(player_id)),
                  "attachments": len(self.list_attachments(player_id)),
                  "reports": len(self.list_reports(player_id)),
                  "tags": len(snap.get("tags", []))}
        return {"snapshot": snap, "dataset": link, "fit": fit,
                "strengths": strengths, "dev_areas": dev_areas, "counts": counts,
                "academy": identity.academy_profile_of(p)}

    def _percentile_highlights(self, user: User, player_id: str, n: int = 5):
        """Top/bottom metrics by percentile from the linked scouting dataset - real
        observation, not interpretation. Empty when no dataset row is linked."""
        prof = self.active_scouting_profile(user, player_id)
        if prof is None:
            return [], []
        ctx = self.active_scouting_dataset(user)
        if ctx is None:
            return [], []
        from fap.scouting import viz
        primary, _ = self._resolve_dataset_key(self.get_player(player_id), ctx)
        if primary is None:
            return [], []
        view = viz.build_view(ctx["frame"], ctx["schema"], [primary],
                              dataset_id=ctx["id"], dataset_name=ctx["name"])
        ranked = [(m.name, m.percentile(primary)) for m in view.metrics
                  if m.percentile(primary) is not None]
        ranked.sort(key=lambda t: t[1], reverse=True)
        strengths = [{"name": nm, "percentile": round(pct)} for nm, pct in ranked[:n]]
        dev = [{"name": nm, "percentile": round(pct)} for nm, pct in ranked[-n:][::-1]] \
            if len(ranked) > n else []
        return strengths, dev

    def status_history(self, player_id: str):
        from fap.scouting import identity
        p = self.get_player(player_id)
        return identity.status_history_of(p) if p else []

    def pathway_history(self, player_id: str):
        from fap.scouting import identity
        p = self.get_player(player_id)
        return identity.pathway_history_of(p) if p else []

    # -- recruitment profiles + fit -----------------------------------------
    def available_profiles(self, position: str = "") -> list[dict[str, Any]]:
        from fap.scouting import profiles
        return [pr.to_dict() for pr in profiles.profiles_for_position(position)]

    # -- dataset identity mapping (P4.2.1) ----------------------------------
    # The player is the source of truth; the dataset is evidence. A confirmed
    # mapping (player_id -> dataset row) is persisted per dataset in the player's
    # document, so resolution is deterministic and survives reloads. The dataset's
    # spelling never becomes the player's identity.
    def _dataset_links(self, player) -> dict[str, Any]:
        doc = getattr(player, "document", None) or {}
        links = doc.get("dataset_links")
        return dict(links) if isinstance(links, dict) else {}

    def _resolve_dataset_key(self, player, ctx) -> tuple[str | None, Any]:
        """Resolve a player to a dataset row: a confirmed mapping wins; otherwise a
        single high-confidence match auto-resolves. Returns (entity_key|None, result)
        where result is the explainable MatchResult (or None). Never guesses."""
        from fap.scouting import matching
        entities = matching.dataset_entities(ctx["frame"], ctx["schema"])
        keys = {e.key for e in entities}
        link = self._dataset_links(player).get(ctx["id"])
        if link and link.get("entity_key") in keys:
            return link["entity_key"], None
        result = matching.match_player(player, entities)
        if result.status == "matched" and result.auto and result.candidate:
            return result.candidate.key, result
        return None, result

    def match_player_in_active_dataset(self, user: User, player_id: str) -> dict[str, Any] | None:
        """Explainable match of a player to the ACTIVE scouting dataset for the UI.
        ``None`` when no scouting dataset is active. Includes the confirmed link if
        any, the auto/proposed match, and ambiguous candidates."""
        self._require(user, Capability.VIEW_SCOUTING)
        from fap.scouting import matching
        ctx = self.active_scouting_dataset(user)
        if ctx is None or ctx.get("frame") is None:
            return None
        p = self.get_player(player_id)
        if p is None:
            return None
        link = self._dataset_links(p).get(ctx["id"])
        entities = matching.dataset_entities(ctx["frame"], ctx["schema"])
        result = matching.match_player(p, entities)
        out = {"dataset_id": ctx["id"], "dataset_name": ctx["name"],
               "linked": bool(link and link.get("entity_key") in {e.key for e in entities}),
               "link": link, "match": result.to_dict()}
        return out

    def link_dataset_identity(self, user: User, player_id: str, entity_key: str, *,
                              method: str = "manual", confidence: str = "confirmed",
                              add_alias: bool = False) -> Player:
        """Persist a confirmed player <-> dataset-row mapping for the ACTIVE dataset
        (in document['dataset_links'][dataset_id]). Optionally add the dataset name
        as an internal alias. Never changes the canonical name or the dataset."""
        self._require(user, Capability.EDIT_SCOUTING)
        ctx = self.active_scouting_dataset(user)
        if ctx is None:
            raise ValueError("no active player-scouting dataset")
        p = self._player_or_raise(player_id)
        links = self._dataset_links(p)
        links[ctx["id"]] = {"entity_key": str(entity_key), "dataset_display_name": str(entity_key),
                            "dataset_name": ctx["name"], "match_method": method,
                            "confidence": confidence, "confirmed_by": user.email,
                            "confirmed_at": _dt_now()}
        p = self._set_doc(user, player_id, "scouting.player.dataset_link", dataset_links=links)
        if add_alias:
            self.add_alias(user, player_id, str(entity_key))
            p = self.get_player(player_id)
        return p

    def unlink_dataset_identity(self, user: User, player_id: str,
                                dataset_id: str | None = None) -> Player:
        self._require(user, Capability.EDIT_SCOUTING)
        p = self._player_or_raise(player_id)
        links = self._dataset_links(p)
        if dataset_id is None:
            ctx = self.active_scouting_dataset(user)
            dataset_id = ctx["id"] if ctx else None
        if dataset_id:
            links.pop(dataset_id, None)
        return self._set_doc(user, player_id, "scouting.player.dataset_unlink", dataset_links=links)

    def dataset_link_status(self, user: User, player_id: str) -> dict[str, Any]:
        """The three independent states the UI needs: player exists / dataset linked /
        metrics available - so a profile never reads as 'the player doesn't exist'."""
        self._require(user, Capability.VIEW_SCOUTING)
        p = self.get_player(player_id)
        status = {"player_exists": p is not None, "dataset_active": False, "linked": False,
                  "auto": False, "entity_key": None, "method": "", "confidence": "",
                  "metrics_available": False, "metric_count": 0, "candidates": [],
                  "proposed": None, "dataset_name": ""}
        if p is None:
            return status
        ctx = self.active_scouting_dataset(user)
        if ctx is None or ctx.get("frame") is None:
            return status
        status["dataset_active"] = True
        status["dataset_name"] = ctx["name"]
        key, result = self._resolve_dataset_key(p, ctx)
        if key is not None:
            link = self._dataset_links(p).get(ctx["id"])
            status.update(linked=True, entity_key=key,
                          method=(link or {}).get("match_method") or (result.method if result else "auto"),
                          confidence=(link or {}).get("confidence") or (result.confidence if result else ""),
                          auto=bool(result.auto) if result else True)
            metrics = ctx.get("schema", {}).get("metrics", []) or []
            status["metrics_available"] = bool(metrics)
            status["metric_count"] = len(metrics)
        elif result is not None and result.status == "ambiguous":
            status["candidates"] = [c.to_dict() for c in result.candidates]
        elif result is not None and result.status == "matched" and result.candidate:
            # a single but lower-confidence match: propose it for explicit confirmation
            status["proposed"] = result.candidate.to_dict()
        return status

    def profile_fit_for(self, user: User, player_id: str, profile_id: str) -> dict[str, Any] | None:
        """Transparent profile-fit for a player against the ACTIVE player-scouting
        dataset. ``None`` when no scouting dataset is active or the player cannot be
        resolved to a row; ``available: False`` when the dataset lacks enough
        compatible metrics."""
        self._require(user, Capability.VIEW_SCOUTING)
        from fap.scouting import profiles, viz
        profile = profiles.get_profile(profile_id)
        if profile is None:
            return None
        ctx = self.active_scouting_dataset(user)
        if ctx is None or ctx.get("frame") is None:
            return None
        p = self.get_player(player_id)
        if p is None:
            return None
        primary, _ = self._resolve_dataset_key(p, ctx)
        if primary is None:
            return None
        view = viz.build_view(ctx["frame"], ctx["schema"], [primary],
                              dataset_id=ctx["id"], dataset_name=ctx["name"])
        result = profiles.profile_fit(view, profile, primary)
        result["profile"] = profile.name
        result["profile_id"] = profile.id
        return result

    @staticmethod
    def _matches_query(p, query: str) -> bool:
        """One professional search surface: name, display name, aliases, operational
        id, internal id, club, league, position, nationality, and any linked dataset
        display name. Case-insensitive substring."""
        from fap.scouting import identity
        doc = p.document if isinstance(p.document, dict) else {}
        parts = [p.name, identity.display_name_of(p), identity.operational_id_of(p), p.id,
                 p.club, p.league, p.position, p.nationality, p.country]
        parts += identity.aliases_of(p)
        for link in (doc.get("dataset_links") or {}).values():
            parts += [str(link.get("dataset_display_name", "")), str(link.get("dataset_name", ""))]
        hay = " ".join(str(x) for x in parts if x).lower()
        return all(tok in hay for tok in query.split())

    def player_registry(self, user: User, *, filters: dict[str, Any] | None = None,
                        workspace_id: str | None = None,
                        min_fit: float | None = None,
                        profile_id: str | None = None) -> list[dict[str, Any]]:
        """The recruitment registry: players (canonical records) with identity,
        pathway, status/priority and - when a compatible scouting dataset is active -
        an optional profile-fit score. Filters adapt to player_type. Never depends on
        a filename; identity is the anchor."""
        self._require(user, Capability.VIEW_SCOUTING)
        from fap.scouting import identity
        f = dict(filters or {})
        player_type = f.pop("player_type", None)
        query = str(f.get("query", "")).strip().lower()
        repo_filters = {k: v for k, v in f.items()
                        if k in ("club", "league", "country", "nationality", "position",
                                 "foot", "status", "priority", "min_age", "max_age") and v not in (None, "")}
        # Fetch the pool WITHOUT the name query so an in-memory search can also match
        # operational id / aliases / display name / linked dataset name (none of which
        # the SQL name filter can see).
        pool = self.players.search(query="", filters=repo_filters,
                                   workspace_id=workspace_id, limit=500)
        out: list[dict[str, Any]] = []
        for p in pool:
            pt = identity.player_type_of(p)
            if player_type and player_type != "all" and pt != player_type:
                continue
            if f.get("age_group") and identity.age_group_of(p) != f["age_group"]:
                continue
            if f.get("recruitment_profile") and identity.recruitment_profile_of(p) != f["recruitment_profile"]:
                continue
            if query and not self._matches_query(p, query):
                continue
            fit = None
            if profile_id:
                res = self.profile_fit_for(user, p.id, profile_id)
                fit = res.get("score") if res and res.get("available") else None
                if min_fit is not None and (fit is None or fit < min_fit):
                    continue
            out.append({
                "id": p.id, "operational_id": identity.operational_id_of(p),
                "name": p.name, "display_name": identity.display_name_of(p),
                "player_type": pt, "type_label": identity.type_label(pt),
                "position": p.position, "club": p.club, "league": p.league,
                "age": p.age, "age_group": identity.age_group_of(p),
                "nationality": p.nationality or p.country,
                "status": identity.normalize_status(p.status),
                "priority": identity.normalize_priority(p.priority),
                "recruitment_profile": identity.recruitment_profile_of(p),
                "profile_fit": fit, "profile_image_id": p.profile_image_id,
                "favorite": p.favorite,
            })
        return out

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
        # Resolve the dataset row through the deterministic matcher (confirmed
        # mapping -> exact/normalized/initial-variant), not a bare exact-name match.
        ctx = {"id": ds.id, "name": ds.name, "schema": schema, "frame": frame}
        key, _ = self._resolve_dataset_key(p, ctx)
        if key is None:
            return None
        col = frame[id_field].astype(str).str.strip()
        match = frame[col == key]
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
        """Create a canonical player. Assigns the immutable internal ``player_id``
        (uuid) and a stable operational id (CLB-/ACD-/TRI-000001) reflecting the
        pathway. player_type/operational_id are structured identity metadata in the
        document - no schema migration. The operational prefix never becomes the
        identity."""
        self._require(user, Capability.EDIT_SCOUTING)
        from fap.scouting import identity, player_profile
        player_type = identity.normalize_player_type(fields.pop("player_type", "first_team"))
        # document keys we manage on the identity/profile layer (not dataclass columns)
        doc_extra = {k: fields.pop(k) for k in
                     ("aliases", "display_name", "source", "age_group",
                      "recruitment_profile", "academy") if k in fields}
        secondary_nats = fields.pop("secondary_nationalities", None)
        if "foot" in fields:
            fields["foot"] = player_profile.normalize_foot(fields["foot"])
        p = Player(id=self._uid(), name=name.strip(), owner=user.email, created_by=user.email,
                   workspace_id=fields.pop("workspace_id", None))
        for k, v in fields.items():
            if hasattr(p, k):
                setattr(p, k, v)
        p.status = identity.normalize_status(p.status)
        p.priority = identity.normalize_priority(p.priority)
        doc = dict(p.document) if isinstance(p.document, dict) else {}
        doc.update(doc_extra)
        doc["player_type"] = player_type
        doc["operational_id"] = self._assign_operational_id(player_type)
        if secondary_nats:
            prof = dict(doc.get("profile") or {})
            prof["secondary_nationalities"] = [str(n).strip() for n in secondary_nats if str(n).strip()]
            doc["profile"] = prof
        p.document = doc
        self.players.save(p)
        self.audit.record(user, "scouting.player.create", target_type="player", target_id=p.id,
                          detail={"name": p.name, "player_type": player_type,
                                  "operational_id": doc["operational_id"]})
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
        # a duplicate is a NEW canonical identity: same pathway, fresh operational id,
        # no inherited history/aliases.
        from fap.scouting import identity
        pt = identity.player_type_of(src)
        copy.document = {"player_type": pt, "operational_id": self._assign_operational_id(pt)}
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
        elif kind == "logo":
            self.update_player(user, player_id, club_logo_id=image_id)
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
