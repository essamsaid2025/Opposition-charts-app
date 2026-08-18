"""Relational persistence for teams + team members (mirrors the scouting repositories)."""
from __future__ import annotations

from typing import Any

from fap.db.engine import Database
from fap.teams.models import Team, TeamMember


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
        self._db.execute("DELETE FROM teams WHERE id = ?", (team_id,))

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
    def _member(r: Any) -> TeamMember:
        return TeamMember(id=r["id"], team_id=r["team_id"], player_id=r["player_id"],
                          operational_id=r["operational_id"], player_name=r["player_name"],
                          source=r["source"], shirt_number=r["shirt_number"], role=r["role"],
                          created_at=r["created_at"])
