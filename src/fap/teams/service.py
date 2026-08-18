"""Team service — create/list/edit teams and manage rosters. Reuses the shared relational
engine, ImageStorage (crest) and audit; adds no duplicate persistence. Permission gating is
done in the UI (role-based, like the other pages); the service records created_by/audit."""
from __future__ import annotations

import uuid
from typing import Any

from fap.db.engine import Database
from fap.teams.models import Team, TeamMember
from fap.teams.repository import TeamRepository


class TeamService:
    def __init__(self, db: Database, *, images: Any = None, audit: Any = None) -> None:
        self.repo = TeamRepository(db)
        self._images = images
        self._audit = audit

    @staticmethod
    def _uid() -> str:
        return uuid.uuid4().hex

    def _record(self, user: Any, action: str, **detail: Any) -> None:
        if self._audit is not None:
            try:
                self._audit.record(user, action, detail=detail)
            except Exception:
                pass

    # ---- teams ----
    def create_team(self, user: Any, name: str, *, kind: str = "club", age_group: str = "",
                    competition: str = "", season: str = "", info: str = "") -> Team:
        name = str(name or "").strip()
        if not name:
            raise ValueError("Team name is required.")
        t = Team(id=self._uid(), name=name, kind=(kind if kind in ("club", "academy") else "club"),
                 age_group=str(age_group or "").strip(), competition=str(competition or "").strip(),
                 season=str(season or "").strip(), info=str(info or "").strip(),
                 created_by=getattr(user, "email", "") or "")
        self.repo.add(t)
        self._record(user, "teams.create", team_id=t.id, name=name)
        return t

    def list_teams(self) -> list[Team]:
        return self.repo.list()

    def get_team(self, team_id: str) -> Team | None:
        return self.repo.get(team_id)

    def update_team(self, user: Any, team_id: str, **fields: Any) -> Team | None:
        self.repo.update(team_id, **fields)
        self._record(user, "teams.update", team_id=team_id)
        return self.repo.get(team_id)

    def delete_team(self, user: Any, team_id: str) -> None:
        t = self.repo.get(team_id)
        if t is not None and t.crest_image_id and self._images is not None:
            try:
                self._images.delete(t.crest_image_id)
            except Exception:
                pass
        self.repo.delete(team_id)
        self._record(user, "teams.delete", team_id=team_id)

    def set_crest(self, user: Any, team_id: str, data: bytes, mime: str) -> Team | None:
        """Store a club/team crest, reusing ImageStorage (no new media store)."""
        if self._images is None:
            raise ValueError("Image storage is not configured.")
        t = self.repo.get(team_id)
        if t is None:
            return None
        if t.crest_image_id:
            try:
                self._images.delete(t.crest_image_id)
            except Exception:
                pass
        image_id = self._uid()
        self._images.save(image_id, data, mime=mime)
        self.repo.update(team_id, crest_image_id=image_id)
        self._record(user, "teams.crest", team_id=team_id)
        return self.repo.get(team_id)

    def crest_bytes(self, team_id: str) -> bytes | None:
        t = self.repo.get(team_id)
        if t is None or not t.crest_image_id or self._images is None:
            return None
        try:
            return self._images.load(t.crest_image_id)
        except Exception:
            return None

    # ---- roster ----
    def add_member(self, user: Any, team_id: str, *, player_name: str, operational_id: str = "",
                   player_id: str = "", source: str = "scouting", shirt_number: str = "",
                   role: str = "") -> TeamMember:
        name = str(player_name or "").strip()
        if not name and not operational_id:
            raise ValueError("A player name or operational id is required.")
        m = TeamMember(id=self._uid(), team_id=team_id, player_id=str(player_id or ""),
                       operational_id=str(operational_id or "").strip(), player_name=name,
                       source=(source if source in ("scouting", "first_team") else "scouting"),
                       shirt_number=str(shirt_number or "").strip(), role=str(role or "").strip())
        self.repo.add_member(m)
        self._record(user, "teams.member.add", team_id=team_id, name=name)
        return m

    def list_members(self, team_id: str) -> list[TeamMember]:
        return self.repo.list_members(team_id)

    def remove_member(self, user: Any, member_id: str) -> None:
        self.repo.remove_member(member_id)
        self._record(user, "teams.member.remove", member_id=member_id)

    def team_summaries(self) -> list[dict[str, Any]]:
        """Teams with roster counts — the T1 aggregate the Teams page lists (team-level
        aggregates/comparisons across rosters build on this in later phases)."""
        out: list[dict[str, Any]] = []
        for t in self.repo.list():
            out.append({"id": t.id, "name": t.name, "kind": t.kind, "age_group": t.age_group,
                        "competition": t.competition, "season": t.season,
                        "members": self.repo.member_count(t.id), "crest": bool(t.crest_image_id)})
        return out
