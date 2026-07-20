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
    def create_report(self, user: User, player_id: str, *, title: str = "") -> ScoutingReportLink:
        """Auto-generate a professional scouting report through ReportsManager and
        link it to the player. The report is then edited in the EXISTING Report
        Studio (open by its report_id) - no second editor is built here."""
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
        link = ScoutingReportLink(id=self._uid(), player_id=player_id, report_id=record.id,
                                  title=title, created_by=user.email)
        self.links.add(link)
        self.audit.record(user, "scouting.report.create", target_type="player", target_id=player_id,
                          detail={"report_id": record.id, "title": title})
        return link

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
