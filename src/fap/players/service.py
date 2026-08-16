"""PlayersService - the façade the First Team Players UI talks to (Phase 10).

Owns the first-team roster and everything hanging off a player (contracts,
medical, training, media, notes, career, match links). Service-driven: no
business logic in Streamlit. It REUSES the platform services and never
duplicates them - ImageStorage for photos, FileStorage for documents/videos,
ReportsManager for reports (opened in the existing Report Studio in a later
milestone), PermissionService for capability checks, AuditService for the trail
and WorkspaceManager for scoping. Completely independent of the scouting module;
the only bridge is the optional, read-only ``promote_from_scouting``.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

from fap.identity.capabilities import Capability
from fap.identity.models import User
from fap.players import analysis as A
from fap.players.models import (
    Player, PlayerCareer, PlayerContract, PlayerDocument, PlayerImage,
    PlayerMatchLink, PlayerMedical, PlayerNote, PlayerTraining, PlayerVideo,
)
from fap.players.repository import (
    CareerRepository, ContractRepository, DocumentRepository, ImageRepository,
    MatchLinkRepository, MedicalRepository, NoteRepository, PlayerRepository,
    TrainingRepository, VideoRepository,
)

_ALLOWED_IMAGE = {"image/png", "image/jpeg", "image/jpg", "image/webp"}


def _player_report_sections(p: Player, ov: dict[str, Any]) -> list[Any]:
    """Auto-generated player report sections, reusing the report models (no new
    reporting engine). Kept module-level so it never imports at service import."""
    from fap.reports.models import KPI, Section, Table
    ct = ov["career_totals"]
    profile = Section(
        id="pl_profile", title=f"{p.name}",
        subtitle=f"{p.primary_position or '—'} · {ov['age'] or '—'} yrs · {p.nationality or '—'}",
        kpis=[KPI("Availability", ov["availability"]),
              KPI("Career apps", str(ct["appearances"])), KPI("Goals", str(ct["goals"])),
              KPI("Assists", str(ct["assists"])), KPI("Minutes", str(ct["minutes"]))])
    wl = ov["workload"]
    workload = Section(
        id="pl_workload", title="Workload",
        kpis=[KPI("Load 7d", str(wl["load_7d"])), KPI("Load 28d", str(wl["load_28d"])),
              KPI("Sessions 7d", str(wl["sessions_7d"])), KPI("Sprint 7d", str(wl["sprint_7d"]))])
    return [profile, workload]


class PlayersService:
    def __init__(self, db: Any, *, permissions: Any, audit: Any, reports: Any = None,
                 images: Any = None, files: Any = None, workspaces: Any = None,
                 scouting: Any = None, cache: Any = None) -> None:
        self._db = db
        self.players = PlayerRepository(db)
        self.contracts = ContractRepository(db)
        self.medical = MedicalRepository(db)
        self.training = TrainingRepository(db)
        self.documents = DocumentRepository(db)
        self.images = ImageRepository(db)
        self.videos = VideoRepository(db)
        self.notes = NoteRepository(db)
        self.career = CareerRepository(db)
        self.match_links = MatchLinkRepository(db)
        self.perms = permissions
        self.audit = audit
        self._reports = reports
        self._image_storage = images
        self._file_storage = files
        self._wm = workspaces
        self._scouting = scouting
        self._cache = cache

    # ---------------------------------------------------------------- guards
    def _require(self, user: User, cap: Capability, scope: str | None = None) -> None:
        self.perms.require(user, str(cap), scope)

    def _uid(self) -> str:
        return str(uuid.uuid4())

    def _player_or_raise(self, player_id: str) -> Player:
        p = self.players.get(player_id)
        if p is None:
            raise ValueError(f"player {player_id!r} not found")
        return p

    # ================================================================ players
    def create_player(self, user: User, **fields: Any) -> Player:
        self._require(user, Capability.EDIT_PLAYERS)
        p = Player(id=self._uid(), owner=user.email, created_by=user.email,
                   workspace_id=fields.pop("workspace_id", None))
        for k, v in fields.items():
            if hasattr(p, k):
                setattr(p, k, v)
        if not p.display_name:
            p.display_name = f"{p.first_name} {p.last_name}".strip()
        self.players.save(p)
        self.audit.record(user, "players.create", target_type="player", target_id=p.id,
                          detail={"name": p.name})
        return p

    def get_player(self, player_id: str) -> Player | None:
        return self.players.get(player_id)

    def view_player(self, user: User, player_id: str) -> Player | None:
        self._require(user, Capability.VIEW_PLAYERS)
        p = self.players.get(player_id)
        if p and self._wm is not None:
            try:
                self._wm.touch_recent(user, "first_team_player", player_id)
            except Exception:
                pass
        return p

    def update_player(self, user: User, player_id: str, **fields: Any) -> Player:
        self._require(user, Capability.EDIT_PLAYERS)
        p = self._player_or_raise(player_id)
        for k, v in fields.items():
            if hasattr(p, k) and k not in ("id", "created_by", "created_at"):
                setattr(p, k, v)
        self.players.save(p)
        self.audit.record(user, "players.update", target_type="player", target_id=player_id,
                          detail={"fields": sorted(fields)})
        return p

    def archive_player(self, user: User, player_id: str, archived: bool = True) -> None:
        self._require(user, Capability.EDIT_PLAYERS)
        p = self._player_or_raise(player_id)
        p.archived = archived
        p.status = "archived" if archived else "active"
        self.players.save(p)
        self.audit.record(user, "players.archive" if archived else "players.restore",
                          target_type="player", target_id=player_id)

    def restore_player(self, user: User, player_id: str) -> None:
        self.archive_player(user, player_id, archived=False)

    def delete_player(self, user: User, player_id: str) -> None:
        """Hard delete a player and every asset (blobs + cascaded rows)."""
        self._require(user, Capability.DELETE_PLAYERS)
        self._player_or_raise(player_id)
        for d in self.documents.list(player_id):
            if d.file_id and self._file_storage is not None:
                self._file_storage.delete(d.file_id)
        for v in self.videos.list(player_id):
            if v.file_id and self._file_storage is not None:
                self._file_storage.delete(v.file_id)
        for im in self.images.list(player_id):
            if im.image_id and self._image_storage is not None:
                self._image_storage.delete(im.image_id)
        self.players.delete(player_id)     # cascades child rows
        self.audit.record(user, "players.delete", target_type="player", target_id=player_id)

    def set_favorite(self, user: User, player_id: str, on: bool = True) -> None:
        self._require(user, Capability.VIEW_PLAYERS)
        p = self._player_or_raise(player_id)
        p.favorite = on
        self.players.save(p)

    def search(self, user: User, *, query: str = "", filters: dict[str, Any] | None = None,
               archived: bool = False, favorite: bool | None = None,
               workspace_id: str | None = None) -> list[Player]:
        self._require(user, Capability.VIEW_PLAYERS)
        return self.players.search(query=query, filters=filters, archived=archived,
                                   favorite=favorite, workspace_id=workspace_id)

    def filter_options(self, user: User) -> dict[str, list[str]]:
        self._require(user, Capability.VIEW_PLAYERS)
        return {c: self.players.distinct_values(c)
                for c in ("primary_position", "nationality", "foot", "status", "availability")}

    def card_index(self, user: User, players: list[Player]) -> dict[str, dict[str, Any]]:
        """Batched per-card aggregates (contract end, injured flag, career
        minutes) for a list of players in a handful of queries - not per card."""
        self._require(user, Capability.VIEW_PLAYERS)
        ids = [p.id for p in players]
        ends = self.players.contract_ends(ids)
        injured = self.players.open_injury_ids(ids)
        minutes = self.players.career_minutes(ids)
        return {pid: {"contract_end": ends.get(pid, ""), "injured": pid in injured,
                      "minutes": minutes.get(pid, 0)} for pid in ids}

    def squad_summary(self, user: User) -> dict[str, Any]:
        self._require(user, Capability.VIEW_PLAYERS)
        players = self.players.recent(limit=1000)
        injured = self.players.open_injury_ids([p.id for p in players])
        n_injured = sum(1 for p in players if p.status == "injured" or p.id in injured)
        return {"total": self.players.count(archived=False),
                "archived": self.players.count(archived=True), "injured": n_injured}

    # ================================================================ contracts
    def add_contract(self, user: User, player_id: str, **fields: Any) -> PlayerContract:
        self._require(user, Capability.EDIT_PLAYERS)
        c = PlayerContract(id=self._uid(), player_id=player_id, created_by=user.email)
        for k, v in fields.items():
            if hasattr(c, k):
                setattr(c, k, v)
        self.contracts.add(c)
        self.audit.record(user, "players.contract.add", target_type="player", target_id=player_id)
        return c

    def list_contracts(self, player_id: str) -> list[PlayerContract]:
        return self.contracts.list(player_id)

    def current_contract(self, player_id: str) -> PlayerContract | None:
        return A.current_contract(self.contracts.list(player_id))

    # ================================================================ medical (gated)
    def add_medical(self, user: User, player_id: str, **fields: Any) -> PlayerMedical:
        self._require(user, Capability.EDIT_MEDICAL)
        m = PlayerMedical(id=self._uid(), player_id=player_id, created_by=user.email)
        for k, v in fields.items():
            if hasattr(m, k):
                setattr(m, k, v)
        self.medical.add(m)
        # keep the player's availability in sync with an open injury
        if m.status in ("open", "recovering"):
            self.update_player(user, player_id, status="injured", availability="injured")
        self.audit.record(user, "players.medical.add", target_type="player", target_id=player_id)
        return m

    def list_medical(self, user: User, player_id: str) -> list[PlayerMedical]:
        self._require(user, Capability.VIEW_MEDICAL)
        return self.medical.list(player_id)

    def current_injury(self, user: User, player_id: str) -> PlayerMedical | None:
        self._require(user, Capability.VIEW_MEDICAL)
        return A.current_injury(self.medical.list(player_id))

    # ================================================================ training
    def add_training(self, user: User, player_id: str, **fields: Any) -> PlayerTraining:
        self._require(user, Capability.EDIT_PLAYERS)
        t = PlayerTraining(id=self._uid(), player_id=player_id)
        for k, v in fields.items():
            if hasattr(t, k):
                setattr(t, k, v)
        self.training.add(t)
        return t

    def list_training(self, player_id: str) -> list[PlayerTraining]:
        return self.training.list(player_id)

    def workload(self, player_id: str) -> dict[str, Any]:
        return A.workload(self.training.list(player_id))

    # ================================================================ images
    def add_image(self, user: User, player_id: str, data: bytes, mime: str, *,
                  kind: str = "profile", caption: str = "") -> PlayerImage:
        self._require(user, Capability.EDIT_PLAYERS)
        if self._image_storage is None:
            raise ValueError("Image storage is not configured.")
        if mime.lower() not in _ALLOWED_IMAGE:
            raise ValueError(f"Unsupported image type {mime!r}.")
        image_id = self._uid()
        self._image_storage.save(image_id, data, mime)
        im = PlayerImage(id=self._uid(), player_id=player_id, image_id=image_id, kind=kind,
                         caption=caption, created_by=user.email)
        self.images.add(im)
        if kind == "profile":
            self.update_player(user, player_id, profile_image_id=image_id)
        self.audit.record(user, "players.image.add", target_type="player", target_id=player_id)
        return im

    def list_images(self, player_id: str) -> list[PlayerImage]:
        return self.images.list(player_id)

    def image_bytes(self, image_id: str) -> bytes | None:
        return self._image_storage.load(image_id) if self._image_storage else None

    # ================================================================ documents
    def add_document(self, user: User, player_id: str, data: bytes, filename: str,
                     mime: str = "", kind: str = "document") -> PlayerDocument:
        self._require(user, Capability.EDIT_PLAYERS)
        if self._file_storage is None:
            raise ValueError("File storage is not configured.")
        file_id = self._uid()
        self._file_storage.save(file_id, data, filename=filename, mime=mime)
        x = PlayerDocument(id=self._uid(), player_id=player_id, file_id=file_id, filename=filename,
                           mime=mime, size_bytes=len(data), kind=kind, created_by=user.email)
        self.documents.add(x)
        self.audit.record(user, "players.document.add", target_type="player", target_id=player_id,
                          detail={"filename": filename, "kind": kind})
        return x

    def list_documents(self, player_id: str) -> list[PlayerDocument]:
        return self.documents.list(player_id)

    def document_bytes(self, doc_id: str) -> bytes | None:
        x = self.documents.get(doc_id)
        return self._file_storage.load(x.file_id) if (x and self._file_storage) else None

    # ================================================================ videos
    def add_video(self, user: User, player_id: str, *, url: str = "", data: bytes | None = None,
                  filename: str = "", mime: str = "", kind: str = "external", provider: str = "",
                  title: str = "") -> PlayerVideo:
        self._require(user, Capability.EDIT_PLAYERS)
        file_id = ""
        size = 0
        if data is not None:
            if self._file_storage is None:
                raise ValueError("File storage is not configured.")
            file_id = self._uid()
            self._file_storage.save(file_id, data, filename=filename, mime=mime)
            size = len(data)
            kind = kind if kind != "external" else "match"
        v = PlayerVideo(id=self._uid(), player_id=player_id, kind=kind,
                        provider=provider or self._detect_provider(url), url=url, file_id=file_id,
                        filename=filename, mime=mime, size_bytes=size, title=title or (filename or url),
                        created_by=user.email)
        self.videos.add(v)
        self.audit.record(user, "players.video.add", target_type="player", target_id=player_id)
        return v

    @staticmethod
    def _detect_provider(url: str) -> str:
        u = (url or "").lower()
        for name in ("youtube", "youtu.be", "vimeo", "hudl", "wyscout", "veo", "skillcorner"):
            if name in u:
                return "youtube" if "youtu" in name else name
        return "url" if url else ""

    def list_videos(self, player_id: str) -> list[PlayerVideo]:
        return self.videos.list(player_id)

    def video_bytes(self, video_id: str) -> bytes | None:
        v = self.videos.get(video_id)
        return self._file_storage.load(v.file_id) if (v and v.file_id and self._file_storage) else None

    # ================================================================ notes
    # note kinds distinguish the analyst's observation surfaces (FT-P6)
    NOTE_KINDS = ("player", "match", "video", "event")

    def add_note(self, user: User, player_id: str, body: str, *, kind: str = "player",
                 title: str = "", category: str = "", match_id: str = "", video_id: str = "",
                 tags: list[str] | None = None, pinned: bool = False,
                 private: bool = False) -> PlayerNote:
        """Add a typed analyst note (player / match / video / event). Extra metadata
        (title, category, match_id, video_id, tags) is stored in the note's own
        ``document`` JSON — no schema change. The note is anchored to ``player_id``."""
        self._require(user, Capability.EDIT_PLAYERS)
        doc = {k: v.strip() for k, v in (("title", title), ("category", category),
                                         ("match_id", match_id), ("video_id", video_id)) if v.strip()}
        clean_tags = [str(t).strip() for t in (tags or []) if str(t).strip()]
        if clean_tags:
            doc["tags"] = clean_tags
        n = PlayerNote(id=self._uid(), player_id=player_id, body=body,
                       kind=(kind or "player"), pinned=pinned, private=private,
                       author=user.email, document=doc)
        self.notes.add(n)
        self.audit.record(user, "players.note.add", target_type="player", target_id=player_id,
                          detail={"kind": n.kind})
        return n

    def update_note(self, user: User, note_id: str, *, body: str | None = None,
                    kind: str | None = None, title: str | None = None,
                    category: str | None = None, match_id: str | None = None,
                    video_id: str | None = None, tags: list[str] | None = None,
                    pinned: bool | None = None) -> PlayerNote:
        self._require(user, Capability.EDIT_PLAYERS)
        n = self.notes.get(note_id)
        if n is None:
            raise ValueError(f"note {note_id!r} not found")
        if body is not None:
            n.body = body
        if kind is not None:
            n.kind = kind or "player"
        if pinned is not None:
            n.pinned = bool(pinned)
        doc = dict(n.document or {})
        for key, val in (("title", title), ("category", category), ("match_id", match_id),
                         ("video_id", video_id)):
            if val is not None:
                if str(val).strip():
                    doc[key] = str(val).strip()
                else:
                    doc.pop(key, None)
        if tags is not None:
            clean = [str(t).strip() for t in tags if str(t).strip()]
            doc["tags"] = clean if clean else None
            if not doc["tags"]:
                doc.pop("tags", None)
        n.document = doc
        self.notes.add(n)                                 # UPSERT (document included)
        self.audit.record(user, "players.note.edit", target_type="player",
                          target_id=n.player_id, detail={"note_id": note_id})
        return n

    def delete_note(self, user: User, note_id: str) -> None:
        self._require(user, Capability.EDIT_PLAYERS)
        n = self.notes.get(note_id)
        self.notes.delete(note_id)
        self.audit.record(user, "players.note.delete", target_type="player",
                          target_id=(n.player_id if n else ""), detail={"note_id": note_id})

    def list_notes(self, player_id: str, *, kind: str = "") -> list[PlayerNote]:
        notes = self.notes.list(player_id)
        return [n for n in notes if n.kind == kind] if kind else notes

    # ---- attachments: delete (add_document/list_documents/document_bytes exist) ----
    def delete_document(self, user: User, doc_id: str) -> None:
        """Remove a player attachment: delete the FileStorage blob and the row. The
        binary always lived in FileStorage, never in Player.document."""
        self._require(user, Capability.EDIT_PLAYERS)
        d = self.documents.get(doc_id)
        if d is not None and getattr(d, "file_id", "") and self._file_storage is not None:
            try:
                self._file_storage.delete(d.file_id)
            except Exception:
                pass
        self.documents.delete(doc_id)
        self.audit.record(user, "players.document.delete", target_type="player",
                          target_id=(d.player_id if d else ""), detail={"doc_id": doc_id})

    # ---- media: delete image + set club logo (add_image/image_bytes exist) ----
    def delete_image(self, user: User, image_row_id: str) -> None:
        self._require(user, Capability.EDIT_PLAYERS)
        im = self.images.get(image_row_id)
        if im is not None and getattr(im, "image_id", "") and self._image_storage is not None:
            try:
                self._image_storage.delete(im.image_id)
            except Exception:
                pass
        self.images.delete(image_row_id)
        if im is not None:
            p = self.get_player(im.player_id)
            if p is not None and p.profile_image_id == im.image_id:
                self.update_player(user, im.player_id, profile_image_id="")
        self.audit.record(user, "players.image.delete", target_type="player",
                          target_id=(im.player_id if im else ""), detail={"image_row_id": image_row_id})

    def set_club_logo(self, user: User, player_id: str, data: bytes, mime: str) -> Player:
        self._require(user, Capability.EDIT_PLAYERS)
        if self._image_storage is None:
            raise ValueError("Image storage is not configured.")
        image_id = self._uid()
        self._image_storage.save(image_id, data, mime)
        self.audit.record(user, "players.logo.set", target_type="player", target_id=player_id)
        return self.update_player(user, player_id, club_logo_id=image_id)

    # ---- external links (player-owned, in document['links']; active-independent) ----
    @staticmethod
    def _safe_url(url: str) -> str:
        """A validated http(s) URL, or "" when unsafe/empty. Rejects javascript:/data:/
        vbscript:/file: schemes; a scheme-less host defaults to https://."""
        u = str(url or "").strip()
        if not u:
            return ""
        low = u.lower()
        if low.startswith(("javascript:", "data:", "vbscript:", "file:", "about:")):
            return ""
        if not low.startswith(("http://", "https://")):
            u = "https://" + u
        return u

    def _links(self, player) -> list[dict[str, Any]]:
        doc = getattr(player, "document", None) or {}
        return list(doc.get("links") or [])

    def list_links(self, player_id: str) -> list[dict[str, Any]]:
        p = self.get_player(player_id)
        return self._links(p) if p else []

    def add_link(self, user: User, player_id: str, url: str, *, title: str = "",
                 category: str = "") -> dict[str, Any]:
        self._require(user, Capability.EDIT_PLAYERS)
        safe = self._safe_url(url)
        if not safe:
            raise ValueError("invalid or unsafe URL")
        p = self._player_or_raise(player_id)
        links = self._links(p)
        link = {"id": self._uid(), "url": safe, "title": (title.strip() or safe),
                "category": category.strip(), "created_at": _now(), "created_by": user.email}
        links.append(link)
        self._set_doc(user, player_id, "players.link.add", links=links)
        return link

    def delete_link(self, user: User, player_id: str, link_id: str) -> None:
        self._require(user, Capability.EDIT_PLAYERS)
        p = self._player_or_raise(player_id)
        links = [l for l in self._links(p) if l.get("id") != link_id]
        self._set_doc(user, player_id, "players.link.delete", links=links)

    # ============================================================ intelligence dashboard (FT-P7)
    # A performance dossier aggregator over the existing FT-P2..P6 data. The A-F rating
    # here is a first-team PERFORMANCE rating (document['performance_rating']) — a
    # distinct concept from scouting's recruitment rating; it reuses only the neutral
    # A-F vocabulary. Nothing here depends on the active dataset.
    def performance_rating_of(self, player) -> str:
        from fap.scouting import identity
        doc = getattr(player, "document", None) or {}
        return identity.normalize_rating(doc.get("performance_rating"))

    def set_performance_rating(self, user: User, player_id: str, rating: str) -> Player:
        """The analyst's A-F PERFORMANCE rating (not a recruitment fit). '' clears it;
        any non-A-F value is rejected. Audited."""
        self._require(user, Capability.EDIT_PLAYERS)
        from fap.scouting import identity
        raw = str(rating or "").strip().upper()
        if raw and raw not in identity.ANALYST_RATINGS:
            raise ValueError(f"invalid performance rating {rating!r}; expected A-F or empty")
        return self._set_doc(user, player_id, "players.performance_rating",
                             performance_rating=raw)

    def player_percentile_highlights(self, user: User, player_id: str, dataset_id: str,
                                     n: int = 5) -> tuple[list[dict], list[dict]]:
        """(strengths, areas-to-monitor) as top/bottom metric percentiles for the
        player in a SPECIFIC linked dataset (by id, active-independent). Observation
        only — empty when the player row can't be resolved."""
        self._require(user, Capability.VIEW_PLAYERS)
        ctx = self.player_viz_context(user, player_id, dataset_id)
        if ctx is None:
            return [], []
        from fap.scouting import viz
        view = viz.build_view(ctx["frame"], ctx["schema"], [ctx["primary"]],
                              dataset_id=ctx["id"], dataset_name=ctx["name"])
        key = ctx["primary"]
        ranked = [(m.name, m.percentile(key)) for m in view.metrics if m.percentile(key) is not None]
        ranked.sort(key=lambda t: t[1], reverse=True)
        strengths = [{"name": nm, "percentile": round(pct)} for nm, pct in ranked[:n]]
        dev = [{"name": nm, "percentile": round(pct)} for nm, pct in ranked[-n:][::-1]] \
            if len(ranked) > n else []
        return strengths, dev

    def _recent_activity(self, player, videos, visuals, notes) -> list[dict[str, Any]]:
        """Recent player activity from REAL persisted timestamps only (never fabricated).
        Merges note/visual/video created_at + dataset-link confirmed_at, newest first."""
        acts: list[dict[str, Any]] = []
        for n in notes:
            acts.append({"kind": "note", "label": "Note added",
                         "detail": n.kind, "at": n.created_at or ""})
        for a in visuals:
            acts.append({"kind": "visual", "label": "Visualization saved",
                         "detail": a.get("title", ""), "at": a.get("created_at", "")})
        for v in videos:
            acts.append({"kind": "video", "label": "Video added",
                         "detail": v.title or "", "at": v.created_at or ""})
        for _ds, link in (self._dataset_links(player) or {}).items():
            acts.append({"kind": "dataset", "label": "Dataset linked",
                         "detail": (link or {}).get("dataset_name", ""),
                         "at": (link or {}).get("confirmed_at", "")})
        acts = [a for a in acts if a["at"]]
        acts.sort(key=lambda t: t["at"], reverse=True)
        return acts[:8]

    def player_intelligence(self, user: User, player_id: str) -> dict[str, Any]:
        """Everything the premium first-team dashboard needs, aggregated from the
        existing FT services (counts + rating + linked datasets + recent notes/activity).
        Active-dataset independent; never fabricates."""
        self._require(user, Capability.VIEW_PLAYERS)
        p = self.get_player(player_id)
        if p is None:
            return {}
        datasets = self.linked_player_scouting_datasets(user, player_id)
        matches = self.player_matches(user, player_id)
        videos = self.list_videos(player_id)
        visuals = self.list_player_visualizations(player_id)
        notes = self.list_notes(player_id)
        docs = self.list_documents(player_id)
        links = self.list_links(player_id)
        try:
            reports = self.player_reports(user, player_id).get("reports", [])
        except Exception:
            reports = []
        return {
            "rating": self.performance_rating_of(p),
            "counts": {"data_sources": len(datasets), "matches": len(matches),
                       "videos": len(videos), "visuals": len(visuals), "notes": len(notes),
                       "attachments": len(docs), "links": len(links), "reports": len(reports)},
            "datasets": datasets, "matches": matches, "videos": videos, "visuals": visuals,
            "notes": notes, "activity": self._recent_activity(p, videos, visuals, notes)}

    # ================================================================ career
    def add_career(self, user: User, player_id: str, **fields: Any) -> PlayerCareer:
        self._require(user, Capability.EDIT_PLAYERS)
        c = PlayerCareer(id=self._uid(), player_id=player_id)
        if "starts" in fields:                       # no column; store in document
            c.document["starts"] = int(fields.pop("starts") or 0)
        for k, v in fields.items():
            if hasattr(c, k):
                setattr(c, k, v)
        self.career.add(c)
        return c

    # ================================================================ analysis hub / matches (presentation)
    def analysis_hub(self, user: User, player_id: str) -> list[dict[str, Any]]:
        """Per-module dashboard cards (name, last analysis, last update, datasets,
        reports, page). Presentation over EXISTING data - reuses match links and
        the player's linked reports; recomputes nothing."""
        self._require(user, Capability.VIEW_PLAYERS)
        p = self._player_or_raise(player_id)
        links = self.match_links.list(player_id)
        datasets = len({l.dataset_id for l in links if l.dataset_id})
        n_reports = len(p.document.get("report_ids") or [])
        last_analysis = (links[0].created_at[:10] if links and links[0].created_at else "—")
        upd = (p.updated_at or "")[:10] or "—"
        return [
            {"name": "Open Play", "page_id": "opponent_analysis", "datasets": datasets,
             "reports": n_reports, "last_analysis": last_analysis, "last_update": upd,
             "desc": "Match event maps for this player."},
            {"name": "Set Pieces", "page_id": "set_piece_analysis", "datasets": "—",
             "reports": "—", "last_analysis": "—", "last_update": upd,
             "desc": "Set-piece involvement & routines."},
            {"name": "Opponent Analysis", "page_id": "opponent_analysis", "datasets": datasets,
             "reports": n_reports, "last_analysis": last_analysis, "last_update": upd,
             "desc": "Opponent breakdowns."},
        ]

    def match_rows(self, user: User, player_id: str) -> list[dict[str, Any]]:
        """Rich match rows for the Matches tab: opponent / competition / date /
        result resolved from the LINKED dataset metadata (existing datasets table);
        no match statistics are stored or recomputed here."""
        self._require(user, Capability.VIEW_PLAYERS)
        links = self.match_links.list(player_id)
        meta = self.players.dataset_meta([l.dataset_id for l in links])
        rows = []
        for l in links:
            m = meta.get(l.dataset_id, {})
            rows.append({
                "opponent": m.get("opponent") or "—", "competition": m.get("competition") or "—",
                "date": m.get("match_date") or "—", "season": m.get("season") or "",
                "minutes": l.minutes, "role": l.role, "availability": l.availability,
                "result": (l.availability if l.availability in ("W", "D", "L") else "—"),
                "dataset_id": l.dataset_id, "match_id": l.match_id})
        return rows

    def list_career(self, player_id: str) -> list[PlayerCareer]:
        return self.career.list(player_id)

    def career_totals(self, player_id: str) -> dict[str, int]:
        return A.career_totals(self.career.list(player_id))

    # ================================================================ match links
    def link_match(self, user: User, player_id: str, *, dataset_id: str = "", match_id: str = "",
                   minutes: int | None = None, role: str = "", availability: str = "") -> PlayerMatchLink:
        """Link a player to an existing match/dataset. Stores NO match statistics."""
        self._require(user, Capability.EDIT_PLAYERS)
        x = PlayerMatchLink(id=self._uid(), player_id=player_id, dataset_id=dataset_id,
                            match_id=match_id, minutes=minutes, role=role, availability=availability)
        self.match_links.add(x)
        self.audit.record(user, "players.match.link", target_type="player", target_id=player_id,
                          detail={"dataset_id": dataset_id})
        return x

    def list_match_links(self, player_id: str) -> list[PlayerMatchLink]:
        return self.match_links.list(player_id)

    # ============================================================ player↔dataset intelligence (FT-P2/P3)
    # Active-INDEPENDENT first-team player data, mirroring the mature scouting
    # architecture: a matcher-resolved dataset IDENTITY link lives additively in
    # Player.document['dataset_links'][dataset_id]; metrics/visualizations read a
    # dataset BY ID via WorkspaceManager, NEVER the active dataset. Reuses the shared,
    # domain-neutral matcher (fap.scouting.matching) and the player-scouting schema.
    # No new table, no migration, no scouting behaviour changed.
    def _set_doc(self, user: User, player_id: str, action: str, **fields: Any) -> Player:
        p = self._player_or_raise(player_id)
        doc = dict(p.document) if isinstance(p.document, dict) else {}
        doc.update(fields)
        p.document = doc
        self.players.save(p)
        self.audit.record(user, action, target_type="player", target_id=player_id)
        return self._player_or_raise(player_id)

    def _dataset_links(self, player) -> dict[str, Any]:
        doc = getattr(player, "document", None) or {}
        links = doc.get("dataset_links")
        return dict(links) if isinstance(links, dict) else {}

    def _player_scouting_ctx(self, dataset_id: str) -> dict[str, Any] | None:
        """(id, name, schema, frame, players, id_field) for a player-scouting dataset
        read BY ID, or None when the dataset is missing / not player-scouting."""
        if self._wm is None or not dataset_id:
            return None
        ds = self._wm.get_dataset(dataset_id)
        if ds is None:
            return None
        from fap.datahub.classification import PLAYER_SCOUTING
        doc = ds.document if isinstance(ds.document, dict) else {}
        if doc.get("dataset_type") != PLAYER_SCOUTING:
            return None
        schema = doc.get("scouting_schema") or {}
        id_field = schema.get("id_field")
        frame = self._wm.dataset_frame(dataset_id)
        if not id_field or frame is None or getattr(frame, "empty", True) \
                or id_field not in getattr(frame, "columns", []):
            return None
        players = [str(x) for x in frame[id_field].astype(str).str.strip().tolist() if str(x).strip()]
        return {"id": ds.id, "name": ds.name, "schema": schema, "frame": frame,
                "players": players, "id_field": id_field}

    def _resolve_dataset_key(self, player, ctx) -> tuple[str | None, Any]:
        """Resolve a player to a dataset row: a CONFIRMED link wins; otherwise a single
        high-confidence match auto-resolves. Never guesses (ambiguity → None)."""
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

    def dataset_identity_status(self, user: User, player_id: str, dataset_id: str) -> dict[str, Any]:
        """Explainable match state of a player against a player-scouting dataset:
        linked / proposed (auto) / ambiguous (candidates) / none — for the UI."""
        self._require(user, Capability.VIEW_PLAYERS)
        out: dict[str, Any] = {"dataset_id": dataset_id, "dataset_name": "", "linked": False,
                               "entity_key": None, "method": "", "proposed": None,
                               "candidates": [], "players": []}
        ctx = self._player_scouting_ctx(dataset_id)
        if ctx is None:
            return out
        out["dataset_name"] = ctx["name"]
        out["players"] = ctx["players"]
        p = self.get_player(player_id)
        if p is None:
            return out
        link = self._dataset_links(p).get(dataset_id)
        from fap.scouting import matching
        entities = matching.dataset_entities(ctx["frame"], ctx["schema"])
        keys = {e.key for e in entities}
        if link and link.get("entity_key") in keys:
            out.update(linked=True, entity_key=link["entity_key"], method=link.get("match_method", ""))
            return out
        result = matching.match_player(p, entities)
        if result.status == "matched" and result.candidate:
            out["proposed"] = {"key": result.candidate.key, "method": result.candidate.method,
                               "confidence": result.candidate.confidence, "auto": result.auto}
        elif result.status == "ambiguous":
            out["candidates"] = [{"key": c.key, "method": c.method, "dims": dict(c.dims)}
                                 for c in result.candidates]
        return out

    def link_dataset_identity(self, user: User, player_id: str, entity_key: str, *,
                              dataset_id: str, method: str = "manual",
                              confidence: str = "confirmed") -> Player:
        """Persist a confirmed player↔dataset-row mapping for a SPECIFIC dataset in
        document['dataset_links'][dataset_id]. Active-independent; never changes the
        canonical identity or the dataset."""
        self._require(user, Capability.EDIT_PLAYERS)
        ctx = self._player_scouting_ctx(dataset_id)
        if ctx is None:
            raise ValueError(f"dataset {dataset_id!r} is not an available player-scouting dataset")
        p = self._player_or_raise(player_id)
        links = self._dataset_links(p)
        links[dataset_id] = {"entity_key": str(entity_key), "dataset_name": ctx["name"],
                             "match_method": method, "confidence": confidence,
                             "confirmed_by": user.email, "confirmed_at": _now()}
        return self._set_doc(user, player_id, "players.dataset_link", dataset_links=links)

    def unlink_dataset_identity(self, user: User, player_id: str, dataset_id: str) -> Player:
        self._require(user, Capability.EDIT_PLAYERS)
        p = self._player_or_raise(player_id)
        links = self._dataset_links(p)
        links.pop(dataset_id, None)
        return self._set_doc(user, player_id, "players.dataset_unlink", dataset_links=links)

    def player_dataset_profile(self, user: User, player_id: str,
                               dataset_id: str) -> dict[str, Any]:
        """The player's metric profile from a SPECIFIC player-scouting dataset, read BY
        ID and independent of the active dataset. Honest status; never fabricates."""
        self._require(user, Capability.VIEW_PLAYERS)
        out = {"dataset_id": dataset_id, "dataset_name": "", "status": "unavailable",
               "entity_key": None, "metrics": [], "dimensions": {}, "value_scale": "raw",
               "metric_count": 0}
        if self._wm is None:
            return out
        ds = self._wm.get_dataset(dataset_id)
        if ds is None:
            return out                                    # linked dataset was deleted
        out["dataset_name"] = ds.name
        ctx = self._player_scouting_ctx(dataset_id)
        if ctx is None:
            from fap.datahub.classification import PLAYER_SCOUTING
            doc = ds.document if isinstance(ds.document, dict) else {}
            out["status"] = "not_scouting" if doc.get("dataset_type") != PLAYER_SCOUTING else "unavailable"
            return out
        p = self.get_player(player_id)
        out["value_scale"] = ctx["schema"].get("value_scale", "raw")
        out["metric_count"] = len(ctx["schema"].get("metrics", []) or [])
        key = None
        if p is not None:
            key, _ = self._resolve_dataset_key(p, ctx)
        if key is None:
            out["status"] = "linked_no_row" if (p and dataset_id in self._dataset_links(p)) else "unavailable"
            return out
        from fap.scouting import viz
        view = viz.build_view(ctx["frame"], ctx["schema"], [key],
                              dataset_id=ctx["id"], dataset_name=ctx["name"])
        out["entity_key"] = key
        out["dimensions"] = view.dimensions.get(view.primary, {})
        out["metrics"] = [{"name": m.name, "unit": m.unit, "value": m.value(key)}
                          for m in view.metrics]
        out["status"] = "metrics_available" if view.metrics else "linked_no_row"
        return out

    def player_viz_context(self, user: User, player_id: str,
                           dataset_id: str) -> dict[str, Any] | None:
        """A player-scoped visualization context for a SPECIFIC player-scouting dataset
        (by id, NEVER the active dataset), matcher-resolved so the workspace receives
        ONLY that player as ``primary`` (+ the population for optional comparison)."""
        self._require(user, Capability.VIEW_PLAYERS)
        ctx = self._player_scouting_ctx(dataset_id)
        if ctx is None:
            return None
        p = self.get_player(player_id)
        if p is None:
            return None
        key, _ = self._resolve_dataset_key(p, ctx)
        if key is None:
            return None
        schema = ctx["schema"]
        return {"id": ctx["id"], "name": ctx["name"], "schema": schema, "frame": ctx["frame"],
                "players": ctx["players"], "primary": key,
                "value_scale": schema.get("value_scale", "raw"),
                "metric_count": len(schema.get("metrics", []) or []),
                "linked": dataset_id in self._dataset_links(p)}

    def linked_player_scouting_datasets(self, user: User, player_id: str) -> list[dict[str, Any]]:
        """Player-scouting datasets available for THIS player's analysis: every confirmed
        link (active-independent) + the active dataset if the player resolves in it but
        it is not yet linked (so a freshly-activated dataset is usable and linkable)."""
        self._require(user, Capability.VIEW_PLAYERS)
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        p = self.get_player(player_id)
        if p is None:
            return out
        for ds_id in self._dataset_links(p):
            prof = self.player_dataset_profile(user, player_id, ds_id)
            out.append({"dataset_id": ds_id, "name": prof["dataset_name"] or ds_id,
                        "status": prof["status"], "metric_count": prof["metric_count"],
                        "linked": True})
            seen.add(ds_id)
        try:
            ad = self._wm.active_dataset(user) if self._wm else None
        except Exception:
            ad = None
        if ad is not None and ad.id not in seen:
            c = self.player_viz_context(user, player_id, ad.id)
            if c is not None:
                out.append({"dataset_id": ad.id, "name": c["name"], "status": "active_unlinked",
                            "metric_count": c["metric_count"], "linked": False})
        return out

    # ============================================================ saved visual evidence (FT-P4)
    # Immutable PNG assets scoped to a SINGLE first-team player + a SPECIFIC dataset.
    # The PNG lives in ImageStorage; only metadata lives in Player.document
    # ['visual_assets'] (never a DataFrame/Figure). Mirrors scouting P4.6 exactly and
    # reuses the shared viz workspace's domain-neutral ``save_player_visualization``
    # contract, so a saved chart survives active-dataset changes, reload and even the
    # source dataset later disappearing.
    def save_player_visualization(self, user: User, player_id: str, png: bytes, *,
                                  dataset_id: str = "", title: str = "", viz_id: str = "",
                                  scope: dict[str, Any] | None = None,
                                  config: dict[str, Any] | None = None,
                                  source_name: str = "") -> dict[str, Any]:
        """Persist a rendered visualization as an immutable player asset. Scope is the
        SINGLE resolved player (never the whole dataset). Returns the asset metadata."""
        self._require(user, Capability.EDIT_PLAYERS)
        if self._image_storage is None:
            raise ValueError("Image storage is not configured.")
        p = self._player_or_raise(player_id)
        if (not dataset_id or scope is None or not source_name) and self._wm is not None:
            # derive missing context from the active player-scouting dataset, resolving
            # THIS player's single row (never the whole population)
            try:
                ad = self._wm.active_dataset(user)
            except Exception:
                ad = None
            if ad is not None:
                ctx = self.player_viz_context(user, player_id, ad.id)
                if ctx is not None:
                    dataset_id = dataset_id or ctx["id"]
                    source_name = source_name or ctx["name"]
                    if scope is None:
                        scope = {"player": [ctx["primary"]]}
        image_id = self._uid()
        self._image_storage.save(image_id, png, "image/png")
        asset = {"id": self._uid(), "image_id": image_id, "player_id": player_id,
                 "asset_type": "visualization", "dataset_id": dataset_id or "",
                 "source_dataset_name": source_name or "", "viz_id": viz_id,
                 "chart_type": viz_id, "title": (title or viz_id or "Visualization").strip(),
                 "scope": scope or {}, "config": config or {},
                 "created_by": user.email, "created_at": _now()}
        doc = dict(p.document) if isinstance(p.document, dict) else {}
        assets = list(doc.get("visual_assets", []) or [])
        assets.append(asset)
        doc["visual_assets"] = assets
        p.document = doc
        self.players.save(p)
        self.audit.record(user, "players.visualization.save", target_type="player",
                          target_id=player_id,
                          detail={"viz_id": viz_id, "dataset_id": dataset_id, "title": asset["title"]})
        return asset

    def list_player_visualizations(self, player_id: str) -> list[dict[str, Any]]:
        p = self.get_player(player_id)
        if p is None:
            return []
        doc = p.document if isinstance(p.document, dict) else {}
        return list(doc.get("visual_assets", []) or [])

    def player_visualization_bytes(self, player_id: str, asset_id: str) -> bytes | None:
        """The immutable PNG for a saved asset (from ImageStorage). ``None`` if the
        asset or its blob is missing — the metadata is never silently regenerated."""
        for a in self.list_player_visualizations(player_id):
            if a.get("id") == asset_id:
                img = a.get("image_id")
                return self._image_storage.load(img) if (img and self._image_storage) else None
        return None

    def delete_player_visualization(self, user: User, player_id: str, asset_id: str) -> None:
        self._require(user, Capability.EDIT_PLAYERS)
        p = self._player_or_raise(player_id)
        doc = dict(p.document) if isinstance(p.document, dict) else {}
        keep, removed = [], None
        for a in (doc.get("visual_assets") or []):
            if a.get("id") == asset_id:
                removed = a
            else:
                keep.append(a)
        if removed and removed.get("image_id") and self._image_storage is not None:
            self._image_storage.delete(removed["image_id"])
        doc["visual_assets"] = keep
        p.document = doc
        self.players.save(p)
        self.audit.record(user, "players.visualization.delete", target_type="player",
                          target_id=player_id, detail={"asset_id": asset_id})

    # ============================================================ video evidence + timeline (FT-P5)
    # PLAYER → VIDEO → DATASET_ID → MATCH_ID → EVENTS → VIDEO TIMESTAMP. The video's
    # (dataset_id, match_id, sync_offset_seconds, team, note) are stored additively in
    # Player.document['video_sync'][video_id] (ft_player_videos has no sync columns —
    # document is the established FT boundary, no migration). Event actions ALWAYS come
    # from the video's PERSISTED dataset_id via WorkspaceManager.dataset_frame — the
    # active dataset has ZERO influence. Reuses the domain-neutral evidence.event_rows +
    # identity.identity_keys + the shared video_sync component (no second video engine).
    def _video_sync(self, player) -> dict[str, Any]:
        doc = getattr(player, "document", None) or {}
        vs = doc.get("video_sync")
        return dict(vs) if isinstance(vs, dict) else {}

    def video_sync_of(self, player_id: str, video_id: str) -> dict[str, Any]:
        """The persisted (dataset_id, match_id, sync_offset_seconds, team, note) for a
        video, or {} for a legacy/unlinked video (NEVER the active dataset)."""
        p = self.get_player(player_id)
        return dict(self._video_sync(p).get(video_id) or {}) if p else {}

    def _write_video_sync(self, user: User, player_id: str, video_id: str,
                          patch: dict[str, Any], action: str) -> dict[str, Any]:
        vs = self._video_sync(self._player_or_raise(player_id))
        cur = dict(vs.get(video_id) or {})
        cur.update(patch)
        cur["updated_at"] = _now()
        vs[video_id] = cur
        self._set_doc(user, player_id, action, video_sync=vs)
        return cur

    def link_video_to_match(self, user: User, player_id: str, video_id: str, *,
                            dataset_id: str, match_id: str = "", team: str = "") -> dict[str, Any]:
        """Persist a video's evidence source (dataset_id, match_id[, team]). The action
        list then ALWAYS comes from this dataset by id; the active dataset never
        influences it. Kickoff offset is left for calibration."""
        self._require(user, Capability.EDIT_PLAYERS)
        return self._write_video_sync(user, player_id, video_id,
                                      {"dataset_id": str(dataset_id or ""),
                                       "match_id": str(match_id or ""), "team": str(team or "")},
                                      "players.video.link")

    def set_video_sync(self, user: User, player_id: str, video_id: str, match_id: str,
                       sync_offset_seconds: float | None) -> dict[str, Any]:
        """Record the video's match association + kickoff offset (calibration). Clearing
        the match (empty match_id) also drops the persisted dataset link (mirrors the
        scouting semantics)."""
        self._require(user, Capability.EDIT_PLAYERS)
        patch: dict[str, Any] = {"match_id": str(match_id or ""),
                                 "sync_offset_seconds": None if sync_offset_seconds is None
                                 else float(sync_offset_seconds)}
        if not str(match_id or "").strip():
            patch["dataset_id"] = ""
        return self._write_video_sync(user, player_id, video_id, patch, "players.video.sync")

    def unlink_video(self, user: User, player_id: str, video_id: str) -> None:
        self._require(user, Capability.EDIT_PLAYERS)
        self._write_video_sync(user, player_id, video_id,
                               {"dataset_id": "", "match_id": "", "sync_offset_seconds": None},
                               "players.video.unlink")

    def set_video_note(self, user: User, player_id: str, video_id: str, note: str) -> dict[str, Any]:
        """A match/video-level note — kept distinct from global player notes and event
        evidence (stored on the video's sync record)."""
        self._require(user, Capability.EDIT_PLAYERS)
        return self._write_video_sync(user, player_id, video_id, {"note": str(note or "")},
                                      "players.video.note")

    def delete_video(self, user: User, player_id: str, video_id: str) -> None:
        self._require(user, Capability.EDIT_PLAYERS)
        v = self.videos.get(video_id)
        if v is not None and getattr(v, "file_id", "") and self._file_storage is not None:
            try:
                self._file_storage.delete(v.file_id)
            except Exception:
                pass
        self.videos.delete(video_id)
        p = self._player_or_raise(player_id)
        vs = self._video_sync(p)
        if video_id in vs:
            vs.pop(video_id, None)
            self._set_doc(user, player_id, "players.video.delete", video_sync=vs)
        else:
            self.audit.record(user, "players.video.delete", target_type="player",
                              target_id=player_id, detail={"video_id": video_id})

    def _event_frame_for(self, dataset_id: str):
        """A frame for an EVENT dataset read BY ID (never active), or None when the
        dataset is missing or is a player-scouting (metric) dataset."""
        if self._wm is None or not dataset_id:
            return None
        ds = self._wm.get_dataset(dataset_id)
        if ds is None:
            return None
        from fap.datahub.classification import PLAYER_SCOUTING
        doc = ds.document if isinstance(ds.document, dict) else {}
        if doc.get("dataset_type") == PLAYER_SCOUTING:
            return None
        try:
            return self._wm.dataset_frame(dataset_id)
        except Exception:
            return None

    def video_events(self, user: User, player_id: str, video) -> "pd.DataFrame | None":
        """The event/action rows for a LINKED video, read from the video's PERSISTED
        ``dataset_id`` (via WorkspaceManager.dataset_frame), NEVER the active dataset.
        Scoped by player identity (name+aliases) + the video's match_id via the
        domain-neutral ``evidence.event_rows``. ``None`` when the video is unlinked
        (legacy) or the dataset is missing/not event data — the caller shows an honest
        state and an explicit linking action; it never falls back to the active dataset."""
        self._require(user, Capability.VIEW_PLAYERS)
        vid_id = getattr(video, "id", None) or str(video)
        sync = self.video_sync_of(player_id, vid_id)
        ds_id = sync.get("dataset_id") or ""
        if not ds_id:
            return None
        frame = self._event_frame_for(ds_id)
        if frame is None:
            return None
        from fap.scouting import evidence, identity
        p = self.get_player(player_id)
        if p is None:
            return None
        keys = identity.identity_keys(p)
        return evidence.event_rows(frame, keys, team=sync.get("team", "") or "",
                                   match_id=sync.get("match_id", "") or "")

    def player_matches(self, user: User, player_id: str) -> list[dict[str, Any]]:
        """Match history for the player, aggregated across linked videos + explicit
        match links, deduped by (dataset_id, match_id). Event counts are read by
        dataset_id (active-independent); a missing dataset is reported, never dropped."""
        self._require(user, Capability.VIEW_PLAYERS)
        p = self.get_player(player_id)
        if p is None:
            return []
        from fap.scouting import evidence, identity
        keys = identity.identity_keys(p)
        seen: dict[tuple, dict[str, Any]] = {}

        def _entry(ds_id: str, match_id: str, team: str) -> dict[str, Any]:
            k = (ds_id, match_id or "")
            e = seen.get(k)
            if e is None:
                ds = self._wm.get_dataset(ds_id) if self._wm else None
                frame = self._event_frame_for(ds_id)
                ec = 0
                if frame is not None:
                    rows = evidence.event_rows(frame, keys, team=team or "", match_id=match_id or "")
                    ec = 0 if rows is None else int(len(rows))
                e = {"dataset_id": ds_id, "dataset_name": ds.name if ds else "",
                     "match_id": match_id or "", "team": team or "", "event_count": ec,
                     "exists": ds is not None, "videos": 0, "synced": False}
                seen[k] = e
            return e
        for _vid, sync in self._video_sync(p).items():
            ds_id = sync.get("dataset_id") or ""
            if not ds_id:
                continue
            e = _entry(ds_id, sync.get("match_id") or "", sync.get("team") or "")
            e["videos"] += 1
            if sync.get("sync_offset_seconds") is not None:
                e["synced"] = True
        for l in self.match_links.list(player_id):
            if l.dataset_id:
                _entry(l.dataset_id, l.match_id or "", "")
        return list(seen.values())

    # ================================================================ promote (read-only bridge)
    def promote_from_scouting(self, user: User, scout_player_id: str) -> Player:
        """Create a first-team player FROM a scouting record without duplicating
        data or modifying the scouting module. The scouting player is read only;
        the new player keeps a ``source_scout_player_id`` link and reuses the same
        stored image id (no image copy)."""
        self._require(user, Capability.EDIT_PLAYERS)
        if self._scouting is None:
            raise ValueError("Scouting module is not available.")
        sp = self._scouting.get_player(scout_player_id)
        if sp is None:
            raise ValueError(f"scouting player {scout_player_id!r} not found")
        player = self.create_player(
            user, display_name=getattr(sp, "name", ""), nationality=getattr(sp, "nationality", ""),
            primary_position=getattr(sp, "position", ""), foot=getattr(sp, "foot", ""),
            dob=getattr(sp, "dob", ""), height=getattr(sp, "height", None),
            weight=getattr(sp, "weight", None),
            profile_image_id=getattr(sp, "profile_image_id", ""),
            source_scout_player_id=scout_player_id,
            workspace_id=getattr(sp, "workspace_id", None))
        self.audit.record(user, "players.promote_from_scouting", target_type="player",
                          target_id=player.id, detail={"scout_player_id": scout_player_id})
        return player

    # ================================================================ flags (Academy/Homegrown/…)
    def set_flags(self, user: User, player_id: str, **flags: Any) -> None:
        """Set boolean player flags (academy_graduate, homegrown, …) in the
        player document without a schema change - future-proof for Academy/U21/
        Women modules that read the same flags."""
        self._require(user, Capability.EDIT_PLAYERS)
        p = self._player_or_raise(player_id)
        doc = dict(p.document)
        doc.update({k: bool(v) for k, v in flags.items()})
        p.document = doc
        self.players.save(p)

    # ================================================================ profile bundle
    def overview(self, user: User, player_id: str) -> dict[str, Any]:
        """A live Overview dashboard bundle, assembled once."""
        self._require(user, Capability.VIEW_PLAYERS)
        p = self._player_or_raise(player_id)
        contracts = self.contracts.list(player_id)
        training = self.training.list(player_id)
        links = self.match_links.list(player_id)
        can_medical = self.perms.can(user, str(Capability.VIEW_MEDICAL))
        medical = self.medical.list(player_id) if can_medical else []
        injury = A.current_injury(medical) if can_medical else None
        wl = A.workload(training)
        return {
            "player": p, "age": A.age_from_dob(p.dob),
            "contract": A.current_contract(contracts),
            "contract_expiring": A.contract_expiring(contracts),
            "injury": injury, "medical_status": ("Injured" if injury else "Fit"),
            "availability": A.availability_label(p.status, p.availability, medical),
            "workload": wl,
            "training_status": ("In training" if wl["sessions_7d"] else "No recent session data"),
            "recent_form": [{"minutes": l.minutes, "availability": l.availability, "role": l.role}
                            for l in links[:5]],
            "last_match": (links[0] if links else None),
            "next_match": None,     # fixtures feed not wired; shown as "—"
            "career_totals": A.career_totals(self.career.list(player_id)),
            "matches": len(links),
        }

    # ================================================================ timeline
    def timeline(self, user: User, player_id: str) -> list[dict[str, Any]]:
        """A chronological player timeline: signing, contracts, loans, injuries,
        recoveries, matches, reports, videos and awards - assembled from the data
        already stored (no new tables)."""
        self._require(user, Capability.VIEW_PLAYERS)
        p = self._player_or_raise(player_id)
        events: list[dict[str, Any]] = []
        if p.join_date:
            events.append({"date": p.join_date, "type": "signing", "label": "Signed for the club"})
        for c in self.contracts.list(player_id):
            if c.contract_start:
                events.append({"date": c.contract_start, "type": "contract", "label": "Contract start"})
            if c.contract_end:
                events.append({"date": c.contract_end, "type": "contract", "label": "Contract end"})
            if c.loan:
                events.append({"date": c.contract_start, "type": "loan",
                               "label": f"Loan{' — ' + c.loan_club if c.loan_club else ''}"})
        if self.perms.can(user, str(Capability.VIEW_MEDICAL)):
            for m in self.medical.list(player_id):
                if m.date:
                    events.append({"date": m.date, "type": "injury", "label": f"Injury: {m.injury}"})
                if m.status == "returned" and m.expected_return:
                    events.append({"date": m.expected_return, "type": "recovery", "label": "Returned to play"})
        for l in self.match_links.list(player_id):
            events.append({"date": (l.created_at or "")[:10], "type": "match",
                           "label": f"Match ({l.minutes or 0} min{', ' + l.role if l.role else ''})"})
        for v in self.videos.list(player_id):
            events.append({"date": (v.created_at or "")[:10], "type": "video",
                           "label": f"Video: {v.title}"})
        for a in (p.document.get("awards") or []):
            events.append({"date": a.get("date", ""), "type": "award",
                           "label": f"Award: {a.get('label', '')}"})
        if self._reports is not None:
            for rid in (p.document.get("report_ids") or []):
                rec = self._reports.get(rid)
                if rec:
                    events.append({"date": (rec.created_at or "")[:10], "type": "report",
                                   "label": f"Report: {rec.title}"})
        return sorted(events, key=lambda e: e["date"] or "", reverse=True)

    # ================================================================ charts (dynamic, reused engine)
    def available_visualizations(self, user: User) -> list[dict[str, str]]:
        """Every registered visualization, pulled LIVE from the visual registry
        (never a hardcoded list). Grouped for the picker; rendered by the existing
        engine over the player's event frame."""
        self._require(user, Capability.VIEW_PLAYERS)
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

    def _resolve_frame(self, user: User, dataset_id: str):
        """A dataset frame through the platform's single source of truth (the
        WorkspaceManager storage), falling back to the reports provider. No new
        data access, no duplicated state - the frame is owned by the WM."""
        if self._wm is not None:
            try:
                f = self._wm.dataset_frame(dataset_id)
                if f is not None:
                    return f
            except Exception:
                pass
        return self._reports.dataset_frame(dataset_id) if self._reports is not None else None

    def player_event_frame(self, user: User, player_id: str):
        """Canonical match/event frame for the player (Phase 12.3). The ACTIVE
        dataset (``WorkspaceManager.active_frame`` - the platform's single source of
        truth) is the primary source; any explicit per-player dataset links are
        unioned in for backward compatibility. Each dataset is resolved once (no
        duplicated dataframe state) and joined IN MEMORY to the player's identity
        (the persistent record) by name. The persistent player DB is untouched."""
        self._require(user, Capability.VIEW_PLAYERS)
        import pandas as pd
        p = self._player_or_raise(player_id)
        dataset_ids: list[str] = []
        active_id = self._wm.active_dataset_id(user) if self._wm is not None else None
        if active_id:
            dataset_ids.append(active_id)
        for l in self.match_links.list(player_id):
            if l.dataset_id and l.dataset_id not in dataset_ids:
                dataset_ids.append(l.dataset_id)
        frames = [f for did in dataset_ids
                  if (f := self._resolve_frame(user, did)) is not None and not f.empty]
        if not frames:
            return None
        frame = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]
        if "player" in frame.columns:
            names = {p.name.lower(), p.last_name.lower(), p.display_name.lower()} - {""}
            match = frame[frame["player"].astype(str).str.lower().isin(names)]
            if not match.empty:
                return match
        return frame

    def player_data_source(self, user: User, player_id: str) -> dict[str, Any]:
        """Where the player's match data comes from, for the UI caption (active
        dataset and/or explicit links). Read-only; joins nothing, stores nothing."""
        active = bool(self._wm is not None and self._wm.active_dataset_id(user))
        active_name = ""
        if active:
            try:
                ds = self._wm.active_dataset(user)
                active_name = ds.name if ds else ""
            except Exception:
                active_name = ""
        linked = sum(1 for l in self.match_links.list(player_id) if l.dataset_id)
        return {"active": active, "active_name": active_name, "linked": linked}

    def render_player_chart(self, user: User, player_id: str, viz_id: str, *,
                            controls: dict[str, Any] | None = None, theme_id: str = "opta_light",
                            dpi: int = 150) -> bytes | None:
        """Render one registered visualization for the player through the EXISTING
        engine (ReportsManager.preview_chart). Returns None when there is no
        linked event data to render."""
        self._require(user, Capability.VIEW_PLAYERS)
        frame = self.player_event_frame(user, player_id)
        if frame is None or self._reports is None:
            return None
        try:
            return self._reports.preview_chart(viz_id, frame, controls or {}, theme_id=theme_id, dpi=dpi)
        except TypeError:
            return self._reports.preview_chart(viz_id, frame, controls or {}, dpi=dpi)

    # ================================================================ reports (Studio, document-linked)
    def player_reports(self, user: User, player_id: str) -> dict[str, Any]:
        self._require(user, Capability.VIEW_PLAYERS)
        p = self._player_or_raise(player_id)
        pinned = set(p.document.get("pinned_reports") or [])
        out = []
        if self._reports is not None:
            for rid in (p.document.get("report_ids") or []):
                rec = self._reports.get(rid)
                if rec:
                    out.append({"id": rid, "title": rec.title, "pinned": rid in pinned,
                                "created_at": rec.created_at})
        out.sort(key=lambda r: (not r["pinned"], r["created_at"]), reverse=False)
        return {"reports": out, "pinned": [r for r in out if r["pinned"]]}

    def create_player_report(self, user: User, player_id: str, *, generate: bool = False,
                             title: str = ""):
        """Create (or auto-generate) a player report through the EXISTING
        ReportsManager and link it to the player via the player document. No
        second report engine, no player_reports table needed."""
        self._require(user, Capability.CREATE_REPORT)
        if self._reports is None:
            raise ValueError("Reports engine is not configured.")
        import pandas as pd
        p = self._player_or_raise(player_id)
        ov = self.overview(user, player_id)
        title = title or f"{p.name} — {'Performance Report' if generate else 'Report'}"
        cover = {"title": title, "subtitle": p.primary_position, "club": "",
                 "analyst": user.name or user.email}
        templates = [t.info.id for t in self._reports.templates()]
        template = "blank" if "blank" in templates else (templates[0] if templates else "")
        df = pd.DataFrame([{"player": p.name}])
        record = self._reports.create(user, template=template, df=df, title=title,
                                      workspace_id=p.workspace_id, cover=cover)
        if generate:
            sections = _player_report_sections(p, ov)
            self._reports.update_blocks(user, record.id, lambda doc: (
                doc.sections.extend(sections), doc.meta.update({"source": "players"})))
        doc = dict(p.document)
        doc.setdefault("report_ids", []).append(record.id)
        p.document = doc
        self.players.save(p)
        self.audit.record(user, "players.report.create", target_type="player", target_id=player_id,
                          detail={"report_id": record.id, "generated": generate})
        return record

    def pin_report(self, user: User, player_id: str, report_id: str, on: bool = True) -> None:
        self._require(user, Capability.EDIT_PLAYERS)
        p = self._player_or_raise(player_id)
        doc = dict(p.document)
        pinned = set(doc.get("pinned_reports") or [])
        pinned.add(report_id) if on else pinned.discard(report_id)
        doc["pinned_reports"] = sorted(pinned)
        p.document = doc
        self.players.save(p)
