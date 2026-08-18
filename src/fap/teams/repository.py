"""Relational persistence for teams + team members (mirrors the scouting repositories)."""
from __future__ import annotations

from typing import Any

from fap.db.engine import Database
from fap.teams.models import Team, TeamMatch, TeamMedia, TeamMember


class TeamRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    # ---- teams ----
    def add(self, t: Team) -> None:
        self._db.execute(
            """INSERT INTO teams (id, name, kind, age_group, competition, season,
                 crest_image_id, info, created_by)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (t.id, t.name, t.kind, t.age_group, t.competition, t.season,
             t.crest_image_id, t.info, t.created_by))

    def list(self) -> list[Team]:
        rows = self._db.query("SELECT * FROM teams ORDER BY kind, age_group, name")
        return [self._team(r) for r in rows]

    def get(self, team_id: str) -> Team | None:
        rows = self._db.query("SELECT * FROM teams WHERE id = ?", (team_id,))
        return self._team(rows[0]) if rows else None

    def update(self, team_id: str, **fields: Any) -> None:
        allowed = ("name", "kind", "age_group", "competition", "season", "crest_image_id", "info")
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        cols = ", ".join(f"{k} = ?" for k in sets)
        self._db.execute(f"UPDATE teams SET {cols} WHERE id = ?", (*sets.values(), team_id))

    def delete(self, team_id: str) -> None:
        self._db.execute("DELETE FROM team_members WHERE team_id = ?", (team_id,))
        self._db.execute("DELETE FROM team_matches WHERE team_id = ?", (team_id,))
        self._db.execute("DELETE FROM team_media WHERE team_id = ?", (team_id,))
        self._db.execute("DELETE FROM teams WHERE id = ?", (team_id,))

    # ---- media (notes / videos / clips / charts) ----
    def add_media(self, m: TeamMedia) -> None:
        self._db.execute(
            """INSERT INTO team_media (id, team_id, match_id, kind, member_id, title, body, url,
                 file_id, image_id, created_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (m.id, m.team_id, m.match_id, m.kind, m.member_id, m.title, m.body, m.url, m.file_id,
             m.image_id, m.created_by))

    def list_media(self, team_id: str, *, match_id: str | None = None,
                   kind: str | None = None, member_id: str | None = None) -> list[TeamMedia]:
        sql = "SELECT * FROM team_media WHERE team_id = ?"
        args: list[Any] = [team_id]
        if match_id is not None:
            sql += " AND match_id = ?"; args.append(match_id)
        if kind is not None:
            sql += " AND kind = ?"; args.append(kind)
        if member_id is not None:
            sql += " AND member_id = ?"; args.append(member_id)
        sql += " ORDER BY created_at DESC"
        return [self._media(r) for r in self._db.query(sql, tuple(args))]

    def get_media(self, media_id: str) -> TeamMedia | None:
        rows = self._db.query("SELECT * FROM team_media WHERE id = ?", (media_id,))
        return self._media(rows[0]) if rows else None

    def delete_media(self, media_id: str) -> None:
        self._db.execute("DELETE FROM team_media WHERE id = ?", (media_id,))

    # ---- matches ----
    def add_match(self, m: TeamMatch) -> None:
        self._db.execute(
            """INSERT INTO team_matches (id, team_id, opponent, match_date, competition, venue,
                 our_score, opp_score, formation, notes, dataset_id, match_id, created_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (m.id, m.team_id, m.opponent, m.match_date, m.competition, m.venue,
             m.our_score, m.opp_score, m.formation, m.notes, m.dataset_id, m.match_id, m.created_by))

    def list_matches(self, team_id: str) -> list[TeamMatch]:
        rows = self._db.query(
            "SELECT * FROM team_matches WHERE team_id = ? ORDER BY match_date DESC, created_at DESC",
            (team_id,))
        return [self._match(r) for r in rows]

    def get_match(self, match_row_id: str) -> TeamMatch | None:
        rows = self._db.query("SELECT * FROM team_matches WHERE id = ?", (match_row_id,))
        return self._match(rows[0]) if rows else None

    def update_match(self, match_row_id: str, **fields: Any) -> None:
        allowed = ("opponent", "match_date", "competition", "venue", "our_score", "opp_score",
                   "formation", "notes", "dataset_id", "match_id")
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        cols = ", ".join(f"{k} = ?" for k in sets)
        self._db.execute(f"UPDATE team_matches SET {cols} WHERE id = ?", (*sets.values(), match_row_id))

    def delete_match(self, match_row_id: str) -> None:
        self._db.execute("DELETE FROM team_matches WHERE id = ?", (match_row_id,))

    def match_count(self, team_id: str) -> int:
        rows = self._db.query("SELECT COUNT(*) AS n FROM team_matches WHERE team_id = ?", (team_id,))
        return int(rows[0]["n"]) if rows else 0

    # ---- members ----
    def add_member(self, m: TeamMember) -> None:
        self._db.execute(
            """INSERT INTO team_members (id, team_id, player_id, operational_id, player_name,
                 source, shirt_number, role)
               VALUES (?,?,?,?,?,?,?,?)""",
            (m.id, m.team_id, m.player_id, m.operational_id, m.player_name,
             m.source, m.shirt_number, m.role))

    def list_members(self, team_id: str) -> list[TeamMember]:
        rows = self._db.query(
            "SELECT * FROM team_members WHERE team_id = ? ORDER BY created_at", (team_id,))
        return [self._member(r) for r in rows]

    def remove_member(self, member_id: str) -> None:
        self._db.execute("DELETE FROM team_members WHERE id = ?", (member_id,))

    def member_count(self, team_id: str) -> int:
        rows = self._db.query("SELECT COUNT(*) AS n FROM team_members WHERE team_id = ?", (team_id,))
        return int(rows[0]["n"]) if rows else 0

    # ---- row mappers ----
    @staticmethod
    def _team(r: Any) -> Team:
        return Team(id=r["id"], name=r["name"], kind=r["kind"], age_group=r["age_group"],
                    competition=r["competition"], season=r["season"],
                    crest_image_id=r["crest_image_id"], info=r["info"],
                    created_by=r["created_by"], created_at=r["created_at"])

    @staticmethod
    def _media(r: Any) -> TeamMedia:
        keys = r.keys()
        return TeamMedia(id=r["id"], team_id=r["team_id"], match_id=r["match_id"], kind=r["kind"],
                         member_id=(r["member_id"] if "member_id" in keys else ""),
                         title=r["title"], body=r["body"], url=r["url"], file_id=r["file_id"],
                         image_id=r["image_id"], created_by=r["created_by"], created_at=r["created_at"])

    @staticmethod
    def _match(r: Any) -> TeamMatch:
        return TeamMatch(id=r["id"], team_id=r["team_id"], opponent=r["opponent"],
                         match_date=r["match_date"], competition=r["competition"], venue=r["venue"],
                         our_score=r["our_score"], opp_score=r["opp_score"], formation=r["formation"],
                         notes=r["notes"], dataset_id=r["dataset_id"], match_id=r["match_id"],
                         created_by=r["created_by"], created_at=r["created_at"])

    @staticmethod
    def _member(r: Any) -> TeamMember:
        return TeamMember(id=r["id"], team_id=r["team_id"], player_id=r["player_id"],
                          operational_id=r["operational_id"], player_name=r["player_name"],
                          source=r["source"], shirt_number=r["shirt_number"], role=r["role"],
                          created_at=r["created_at"])
