"""Scouting persistence - the only place scouting SQL lives (repository pattern),
over the SAME platform Database (migration 9). Documents/lists are JSON columns."""
from __future__ import annotations

import json
from typing import Any

from fap.db.engine import Database
from fap.scouting.models import (
    Player, PlayerAttachment, PlayerMedia, PlayerNote, PlayerVideo,
    ScoutingReportLink, Watchlist,
)


class PlayerRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def save(self, p: Player) -> None:
        self._db.execute(
            """INSERT INTO players
                 (id, name, nickname, club, league, country, nationality, age, dob, position,
                  secondary_positions, foot, height, weight, shirt_number, contract_until,
                  market_value, agent, status, profile_image_id, club_logo_id, flag, tags,
                  custom_fields, availability, medical_notes, internal_rating, priority,
                  workspace_id, owner, favorite, archived, document)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name, nickname=excluded.nickname,
                 club=excluded.club, league=excluded.league, country=excluded.country,
                 nationality=excluded.nationality, age=excluded.age, dob=excluded.dob,
                 position=excluded.position, secondary_positions=excluded.secondary_positions,
                 foot=excluded.foot, height=excluded.height, weight=excluded.weight,
                 shirt_number=excluded.shirt_number, contract_until=excluded.contract_until,
                 market_value=excluded.market_value, agent=excluded.agent, status=excluded.status,
                 profile_image_id=excluded.profile_image_id, club_logo_id=excluded.club_logo_id,
                 flag=excluded.flag, tags=excluded.tags, custom_fields=excluded.custom_fields,
                 availability=excluded.availability, medical_notes=excluded.medical_notes,
                 internal_rating=excluded.internal_rating, priority=excluded.priority,
                 workspace_id=excluded.workspace_id, favorite=excluded.favorite,
                 archived=excluded.archived, document=excluded.document,
                 updated_at=datetime('now')""",
            (p.id, p.name, p.nickname, p.club, p.league, p.country, p.nationality, p.age, p.dob,
             p.position, json.dumps(p.secondary_positions), p.foot, p.height, p.weight,
             p.shirt_number, p.contract_until, p.market_value, p.agent, p.status,
             p.profile_image_id, p.club_logo_id, p.flag, json.dumps(p.tags),
             json.dumps(p.custom_fields), p.availability, p.medical_notes, p.internal_rating,
             p.priority, p.workspace_id, p.owner, int(p.favorite), int(p.archived),
             json.dumps(p.document)))

    def get(self, player_id: str) -> Player | None:
        rows = self._db.query("SELECT * FROM players WHERE id = ?", (player_id,))
        return self._row(rows[0]) if rows else None

    def delete(self, player_id: str) -> None:
        self._db.execute("DELETE FROM players WHERE id = ?", (player_id,))

    def search(self, *, query: str = "", filters: dict[str, Any] | None = None,
               archived: bool = False, favorite: bool | None = None,
               workspace_id: str | None = None, limit: int = 500) -> list[Player]:
        clauses, params = ["archived = ?"], [int(archived)]
        f = filters or {}
        if query.strip():
            q = f"%{query.strip().lower()}%"
            clauses.append("(lower(name) LIKE ? OR lower(nickname) LIKE ? OR lower(club) LIKE ? "
                           "OR lower(league) LIKE ? OR lower(country) LIKE ? OR lower(position) LIKE ?)")
            params += [q, q, q, q, q, q]
        for col in ("club", "league", "country", "nationality", "position", "foot", "status", "priority"):
            if f.get(col):
                clauses.append(f"lower({col}) = ?"); params.append(str(f[col]).lower())
        if f.get("min_age") is not None:
            clauses.append("age >= ?"); params.append(int(f["min_age"]))
        if f.get("max_age") is not None:
            clauses.append("age <= ?"); params.append(int(f["max_age"]))
        if f.get("min_rating") is not None:
            clauses.append("internal_rating >= ?"); params.append(float(f["min_rating"]))
        if f.get("contract_before"):
            clauses.append("contract_until <> '' AND contract_until <= ?")
            params.append(str(f["contract_before"]))
        if f.get("tag"):
            clauses.append("lower(tags) LIKE ?"); params.append(f"%\"{str(f['tag']).lower()}\"%")
        if favorite is not None:
            clauses.append("favorite = ?"); params.append(int(favorite))
        if workspace_id is not None:
            clauses.append("workspace_id = ?"); params.append(workspace_id)
        sql = "SELECT * FROM players WHERE " + " AND ".join(clauses) + " ORDER BY updated_at DESC LIMIT ?"
        params.append(int(limit))
        return [self._row(r) for r in self._db.query(sql, tuple(params))]

    def recent(self, limit: int = 10, archived: bool = False) -> list[Player]:
        rows = self._db.query(
            "SELECT * FROM players WHERE archived = ? ORDER BY updated_at DESC LIMIT ?",
            (int(archived), limit))
        return [self._row(r) for r in rows]

    def top_rated(self, limit: int = 10) -> list[Player]:
        rows = self._db.query(
            "SELECT * FROM players WHERE archived = 0 AND internal_rating IS NOT NULL "
            "ORDER BY internal_rating DESC LIMIT ?", (limit,))
        return [self._row(r) for r in rows]

    def contracts_expiring(self, before: str, limit: int = 20) -> list[Player]:
        rows = self._db.query(
            "SELECT * FROM players WHERE archived = 0 AND contract_until <> '' "
            "AND contract_until <= ? ORDER BY contract_until ASC LIMIT ?", (before, limit))
        return [self._row(r) for r in rows]

    def count(self, *, archived: bool | None = None) -> int:
        if archived is None:
            return self._db.query("SELECT COUNT(*) AS c FROM players")[0]["c"]
        return self._db.query("SELECT COUNT(*) AS c FROM players WHERE archived = ?",
                              (int(archived),))[0]["c"]

    @staticmethod
    def _row(r: Any) -> Player:
        return Player(
            id=r["id"], name=r["name"], nickname=r["nickname"], club=r["club"], league=r["league"],
            country=r["country"], nationality=r["nationality"], age=r["age"], dob=r["dob"],
            position=r["position"], secondary_positions=json.loads(r["secondary_positions"]),
            foot=r["foot"], height=r["height"], weight=r["weight"], shirt_number=r["shirt_number"],
            contract_until=r["contract_until"], market_value=r["market_value"], agent=r["agent"],
            status=r["status"], profile_image_id=r["profile_image_id"], club_logo_id=r["club_logo_id"],
            flag=r["flag"], tags=json.loads(r["tags"]), custom_fields=json.loads(r["custom_fields"]),
            availability=r["availability"], medical_notes=r["medical_notes"],
            internal_rating=r["internal_rating"], priority=r["priority"], workspace_id=r["workspace_id"],
            owner=r["owner"], favorite=bool(r["favorite"]), archived=bool(r["archived"]),
            document=json.loads(r["document"]), created_at=r["created_at"], updated_at=r["updated_at"],
            created_by=r["created_by"])


class NoteRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def save(self, n: PlayerNote) -> None:
        self._db.execute(
            """INSERT INTO player_notes (id, player_id, body, kind, pinned, private, author, document)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET body=excluded.body, kind=excluded.kind,
                 pinned=excluded.pinned, private=excluded.private, document=excluded.document,
                 updated_at=datetime('now')""",
            (n.id, n.player_id, n.body, n.kind, int(n.pinned), int(n.private), n.author,
             json.dumps(n.document)))

    def list(self, player_id: str) -> list[PlayerNote]:
        rows = self._db.query(
            "SELECT * FROM player_notes WHERE player_id = ? ORDER BY pinned DESC, updated_at DESC",
            (player_id,))
        return [self._row(r) for r in rows]

    def delete(self, note_id: str) -> None:
        self._db.execute("DELETE FROM player_notes WHERE id = ?", (note_id,))

    @staticmethod
    def _row(r: Any) -> PlayerNote:
        return PlayerNote(id=r["id"], player_id=r["player_id"], body=r["body"], kind=r["kind"],
                          pinned=bool(r["pinned"]), private=bool(r["private"]), author=r["author"],
                          document=json.loads(r["document"]), created_at=r["created_at"],
                          updated_at=r["updated_at"])


class VideoRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, v: PlayerVideo) -> None:
        self._db.execute(
            """INSERT INTO player_videos (id, player_id, kind, provider, url, file_id, filename,
                 mime, size_bytes, title, created_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (v.id, v.player_id, v.kind, v.provider, v.url, v.file_id, v.filename, v.mime,
             v.size_bytes, v.title, v.created_by))

    def list(self, player_id: str) -> list[PlayerVideo]:
        rows = self._db.query(
            "SELECT * FROM player_videos WHERE player_id = ? ORDER BY created_at DESC", (player_id,))
        return [self._row(r) for r in rows]

    def get(self, video_id: str) -> PlayerVideo | None:
        rows = self._db.query("SELECT * FROM player_videos WHERE id = ?", (video_id,))
        return self._row(rows[0]) if rows else None

    def delete(self, video_id: str) -> None:
        self._db.execute("DELETE FROM player_videos WHERE id = ?", (video_id,))

    @staticmethod
    def _row(r: Any) -> PlayerVideo:
        return PlayerVideo(id=r["id"], player_id=r["player_id"], kind=r["kind"],
                           provider=r["provider"], url=r["url"], file_id=r["file_id"],
                           filename=r["filename"], mime=r["mime"], size_bytes=r["size_bytes"],
                           title=r["title"], created_by=r["created_by"], created_at=r["created_at"])


class MediaRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, m: PlayerMedia) -> None:
        self._db.execute(
            """INSERT INTO player_media (id, player_id, image_id, kind, caption, created_by)
               VALUES (?,?,?,?,?,?)""",
            (m.id, m.player_id, m.image_id, m.kind, m.caption, m.created_by))

    def list(self, player_id: str, *, kind: str | None = None) -> list[PlayerMedia]:
        if kind:
            rows = self._db.query(
                "SELECT * FROM player_media WHERE player_id = ? AND kind = ? ORDER BY created_at DESC",
                (player_id, kind))
        else:
            rows = self._db.query(
                "SELECT * FROM player_media WHERE player_id = ? ORDER BY created_at DESC", (player_id,))
        return [self._row(r) for r in rows]

    def get(self, media_id: str) -> PlayerMedia | None:
        rows = self._db.query("SELECT * FROM player_media WHERE id = ?", (media_id,))
        return self._row(rows[0]) if rows else None

    def delete(self, media_id: str) -> None:
        self._db.execute("DELETE FROM player_media WHERE id = ?", (media_id,))

    @staticmethod
    def _row(r: Any) -> PlayerMedia:
        return PlayerMedia(id=r["id"], player_id=r["player_id"], image_id=r["image_id"],
                           kind=r["kind"], caption=r["caption"], created_by=r["created_by"],
                           created_at=r["created_at"])


class AttachmentRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, a: PlayerAttachment) -> None:
        self._db.execute(
            """INSERT INTO player_attachments (id, player_id, file_id, filename, mime, size_bytes,
                 kind, created_by) VALUES (?,?,?,?,?,?,?,?)""",
            (a.id, a.player_id, a.file_id, a.filename, a.mime, a.size_bytes, a.kind, a.created_by))

    def list(self, player_id: str) -> list[PlayerAttachment]:
        rows = self._db.query(
            "SELECT * FROM player_attachments WHERE player_id = ? ORDER BY created_at DESC",
            (player_id,))
        return [self._row(r) for r in rows]

    def get(self, attachment_id: str) -> PlayerAttachment | None:
        rows = self._db.query("SELECT * FROM player_attachments WHERE id = ?", (attachment_id,))
        return self._row(rows[0]) if rows else None

    def delete(self, attachment_id: str) -> None:
        self._db.execute("DELETE FROM player_attachments WHERE id = ?", (attachment_id,))

    @staticmethod
    def _row(r: Any) -> PlayerAttachment:
        return PlayerAttachment(id=r["id"], player_id=r["player_id"], file_id=r["file_id"],
                                filename=r["filename"], mime=r["mime"], size_bytes=r["size_bytes"],
                                kind=r["kind"], created_by=r["created_by"], created_at=r["created_at"])


class ReportLinkRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, link: ScoutingReportLink) -> None:
        self._db.execute(
            """INSERT INTO scouting_reports (id, player_id, report_id, title, created_by)
               VALUES (?,?,?,?,?)""",
            (link.id, link.player_id, link.report_id, link.title, link.created_by))

    def list(self, player_id: str) -> list[ScoutingReportLink]:
        rows = self._db.query(
            "SELECT * FROM scouting_reports WHERE player_id = ? ORDER BY created_at DESC", (player_id,))
        return [self._row(r) for r in rows]

    def recent(self, limit: int = 10) -> list[ScoutingReportLink]:
        rows = self._db.query("SELECT * FROM scouting_reports ORDER BY created_at DESC LIMIT ?", (limit,))
        return [self._row(r) for r in rows]

    def delete(self, link_id: str) -> None:
        self._db.execute("DELETE FROM scouting_reports WHERE id = ?", (link_id,))

    @staticmethod
    def _row(r: Any) -> ScoutingReportLink:
        return ScoutingReportLink(id=r["id"], player_id=r["player_id"], report_id=r["report_id"],
                                  title=r["title"], created_by=r["created_by"], created_at=r["created_at"])


class WatchlistRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def save(self, w: Watchlist) -> None:
        self._db.execute(
            """INSERT INTO watchlists (id, name, owner, workspace_id, document) VALUES (?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name, document=excluded.document""",
            (w.id, w.name, w.owner, w.workspace_id, json.dumps(w.document)))

    def list(self, *, workspace_id: str | None = None) -> list[Watchlist]:
        rows = self._db.query(
            "SELECT w.*, (SELECT COUNT(*) FROM watchlist_members m WHERE m.watchlist_id = w.id) AS mc "
            "FROM watchlists w ORDER BY created_at DESC")
        return [self._row(r) for r in rows]

    def get(self, watchlist_id: str) -> Watchlist | None:
        rows = self._db.query("SELECT * FROM watchlists WHERE id = ?", (watchlist_id,))
        return self._row(rows[0]) if rows else None

    def delete(self, watchlist_id: str) -> None:
        self._db.execute("DELETE FROM watchlists WHERE id = ?", (watchlist_id,))

    def add_member(self, watchlist_id: str, player_id: str, added_by: str = "") -> None:
        self._db.execute(
            "INSERT OR IGNORE INTO watchlist_members (watchlist_id, player_id, added_by) VALUES (?,?,?)",
            (watchlist_id, player_id, added_by))

    def remove_member(self, watchlist_id: str, player_id: str) -> None:
        self._db.execute(
            "DELETE FROM watchlist_members WHERE watchlist_id = ? AND player_id = ?",
            (watchlist_id, player_id))

    def members(self, watchlist_id: str) -> list[str]:
        rows = self._db.query(
            "SELECT player_id FROM watchlist_members WHERE watchlist_id = ?", (watchlist_id,))
        return [r["player_id"] for r in rows]

    def watchlists_for_player(self, player_id: str) -> list[str]:
        rows = self._db.query(
            "SELECT watchlist_id FROM watchlist_members WHERE player_id = ?", (player_id,))
        return [r["watchlist_id"] for r in rows]

    @staticmethod
    def _row(r: Any) -> Watchlist:
        return Watchlist(id=r["id"], name=r["name"], owner=r["owner"], workspace_id=r["workspace_id"],
                         document=json.loads(r["document"]), created_at=r["created_at"],
                         member_count=r["mc"] if "mc" in r.keys() else 0)
