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
from typing import Any

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
    def add_note(self, user: User, player_id: str, body: str, *, kind: str = "note",
                 pinned: bool = False, private: bool = False) -> PlayerNote:
        self._require(user, Capability.EDIT_PLAYERS)
        n = PlayerNote(id=self._uid(), player_id=player_id, body=body, kind=kind, pinned=pinned,
                       private=private, author=user.email)
        self.notes.add(n)
        return n

    def list_notes(self, player_id: str) -> list[PlayerNote]:
        return self.notes.list(player_id)

    # ================================================================ career
    def add_career(self, user: User, player_id: str, **fields: Any) -> PlayerCareer:
        self._require(user, Capability.EDIT_PLAYERS)
        c = PlayerCareer(id=self._uid(), player_id=player_id)
        for k, v in fields.items():
            if hasattr(c, k):
                setattr(c, k, v)
        self.career.add(c)
        return c

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

    # ================================================================ profile bundle
    def overview(self, user: User, player_id: str) -> dict[str, Any]:
        """Everything the Overview tab needs, assembled once."""
        self._require(user, Capability.VIEW_PLAYERS)
        p = self._player_or_raise(player_id)
        contracts = self.contracts.list(player_id)
        can_medical = self.perms.can(user, str(Capability.VIEW_MEDICAL))
        medical = self.medical.list(player_id) if can_medical else []
        return {
            "player": p, "age": A.age_from_dob(p.dob),
            "contract": A.current_contract(contracts),
            "contract_expiring": A.contract_expiring(contracts),
            "injury": A.current_injury(medical) if can_medical else None,
            "availability": A.availability_label(p.status, p.availability, medical),
            "workload": A.workload(self.training.list(player_id)),
            "career_totals": A.career_totals(self.career.list(player_id)),
            "matches": len(self.match_links.list(player_id)),
        }
