"""First Team Players persistence - the only place players SQL lives (repository
pattern), over the SAME platform Database (migration 11). Lists/documents are JSON
columns. No business logic here."""
from __future__ import annotations

import json
from typing import Any

from fap.db.engine import Database
from fap.players.models import (
    Player, PlayerCareer, PlayerContract, PlayerDocument, PlayerImage,
    PlayerMatchLink, PlayerMedical, PlayerNote, PlayerTraining, PlayerVideo,
)


def _b(v: Any) -> bool:
    return bool(v)


def _load(s: str | None, default: Any) -> Any:
    if not s:
        return default
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return default


class PlayerRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    _COLS = ("id, first_name, last_name, display_name, shirt_number, dob, nationality, foot, "
             "primary_position, secondary_positions, height, weight, join_date, captain, "
             "vice_captain, status, availability, profile_image_id, club_logo_id, flag, "
             "source_scout_player_id, tags, custom_fields, workspace_id, owner, favorite, "
             "archived, document")

    def save(self, p: Player) -> None:
        self._db.execute(
            f"""INSERT INTO first_team_players ({self._COLS})
                VALUES ({','.join(['?'] * 28)})
                ON CONFLICT(id) DO UPDATE SET
                  first_name=excluded.first_name, last_name=excluded.last_name,
                  display_name=excluded.display_name, shirt_number=excluded.shirt_number,
                  dob=excluded.dob, nationality=excluded.nationality, foot=excluded.foot,
                  primary_position=excluded.primary_position,
                  secondary_positions=excluded.secondary_positions, height=excluded.height,
                  weight=excluded.weight, join_date=excluded.join_date, captain=excluded.captain,
                  vice_captain=excluded.vice_captain, status=excluded.status,
                  availability=excluded.availability, profile_image_id=excluded.profile_image_id,
                  club_logo_id=excluded.club_logo_id, flag=excluded.flag,
                  source_scout_player_id=excluded.source_scout_player_id, tags=excluded.tags,
                  custom_fields=excluded.custom_fields, workspace_id=excluded.workspace_id,
                  favorite=excluded.favorite, archived=excluded.archived, document=excluded.document,
                  updated_at=datetime('now')""",
            (p.id, p.first_name, p.last_name, p.display_name, p.shirt_number, p.dob, p.nationality,
             p.foot, p.primary_position, json.dumps(p.secondary_positions), p.height, p.weight,
             p.join_date, int(p.captain), int(p.vice_captain), p.status, p.availability,
             p.profile_image_id, p.club_logo_id, p.flag, p.source_scout_player_id,
             json.dumps(p.tags), json.dumps(p.custom_fields), p.workspace_id, p.owner,
             int(p.favorite), int(p.archived), json.dumps(p.document)))

    def get(self, player_id: str) -> Player | None:
        rows = self._db.query("SELECT * FROM first_team_players WHERE id = ?", (player_id,))
        return self._row(rows[0]) if rows else None

    def delete(self, player_id: str) -> None:
        self._db.execute("DELETE FROM first_team_players WHERE id = ?", (player_id,))

    def count(self, *, archived: bool = False) -> int:
        rows = self._db.query("SELECT COUNT(*) AS n FROM first_team_players WHERE archived = ?",
                              (int(archived),))
        return int(rows[0]["n"]) if rows else 0

    def recent(self, *, limit: int = 500, archived: bool = False) -> list[Player]:
        rows = self._db.query(
            "SELECT * FROM first_team_players WHERE archived = ? ORDER BY updated_at DESC LIMIT ?",
            (int(archived), limit))
        return [self._row(r) for r in rows]

    def search(self, *, query: str = "", filters: dict[str, Any] | None = None,
               archived: bool = False, favorite: bool | None = None,
               workspace_id: str | None = None, limit: int = 500) -> list[Player]:
        clauses, params = ["archived = ?"], [int(archived)]
        f = filters or {}
        if workspace_id:
            clauses.append("workspace_id = ?"); params.append(workspace_id)
        if query.strip():
            q = f"%{query.strip().lower()}%"
            clauses.append("(lower(display_name) LIKE ? OR lower(first_name) LIKE ? "
                           "OR lower(last_name) LIKE ? OR lower(nationality) LIKE ? "
                           "OR lower(primary_position) LIKE ? OR CAST(shirt_number AS TEXT) LIKE ?)")
            params += [q, q, q, q, q, q.strip("%")]
        for col in ("primary_position", "nationality", "foot", "status", "availability"):
            if f.get(col):
                clauses.append(f"lower({col}) = ?"); params.append(str(f[col]).lower())
        if f.get("min_age") is not None or f.get("max_age") is not None:
            # dob is 'YYYY-MM-DD'; approximate age filter by birth-year window
            import datetime as _dt
            year = _dt.date.today().year
            if f.get("min_age") is not None:
                clauses.append("(dob = '' OR CAST(substr(dob,1,4) AS INTEGER) <= ?)")
                params.append(year - int(f["min_age"]))
            if f.get("max_age") is not None:
                clauses.append("(dob = '' OR CAST(substr(dob,1,4) AS INTEGER) >= ?)")
                params.append(year - int(f["max_age"]))
        if f.get("contract_expiring_before"):
            clauses.append("id IN (SELECT player_id FROM player_contracts WHERE contract_end <> '' "
                           "AND contract_end <= ?)")
            params.append(str(f["contract_expiring_before"]))
        if f.get("captain"):
            clauses.append("captain = 1")
        if f.get("vice_captain"):
            clauses.append("vice_captain = 1")
        if favorite is not None:
            clauses.append("favorite = ?"); params.append(int(favorite))
        sql = (f"SELECT * FROM first_team_players WHERE {' AND '.join(clauses)} "
               "ORDER BY shirt_number IS NULL, shirt_number, display_name LIMIT ?")
        params.append(int(limit))
        return [self._row(r) for r in self._db.query(sql, tuple(params))]

    # -- batched card aggregates (keeps the squad grid O(1) queries) ------
    def contract_ends(self, ids: list[str]) -> dict[str, str]:
        if not ids:
            return {}
        marks = ",".join(["?"] * len(ids))
        rows = self._db.query(
            f"SELECT player_id, MAX(contract_end) AS e FROM player_contracts "
            f"WHERE player_id IN ({marks}) GROUP BY player_id", tuple(ids))
        return {r["player_id"]: (r["e"] or "") for r in rows}

    def open_injury_ids(self, ids: list[str]) -> set[str]:
        if not ids:
            return set()
        marks = ",".join(["?"] * len(ids))
        rows = self._db.query(
            f"SELECT DISTINCT player_id FROM player_medical WHERE player_id IN ({marks}) "
            f"AND status IN ('open','recovering')", tuple(ids))
        return {r["player_id"] for r in rows}

    def career_minutes(self, ids: list[str]) -> dict[str, int]:
        if not ids:
            return {}
        marks = ",".join(["?"] * len(ids))
        rows = self._db.query(
            f"SELECT player_id, COALESCE(SUM(minutes),0) AS m FROM player_career "
            f"WHERE player_id IN ({marks}) GROUP BY player_id", tuple(ids))
        return {r["player_id"]: int(r["m"]) for r in rows}

    def dataset_meta(self, ids: list[str]) -> dict[str, dict[str, str]]:
        """Read match metadata (opponent/competition/date/season) for linked
        datasets from the EXISTING datasets table (migration 5) - presentation
        only, no analytics. Unknown ids simply return nothing."""
        ids = [i for i in ids if i]
        if not ids:
            return {}
        try:
            marks = ",".join(["?"] * len(ids))
            rows = self._db.query(
                f"SELECT id, opponent, competition, match_date, season FROM datasets "
                f"WHERE id IN ({marks})", tuple(ids))
        except Exception:
            return {}
        return {r["id"]: {"opponent": r["opponent"], "competition": r["competition"],
                          "match_date": r["match_date"], "season": r["season"]} for r in rows}

    def distinct_values(self, column: str) -> list[str]:
        if column not in ("primary_position", "nationality", "foot", "status", "availability"):
            return []
        rows = self._db.query(
            f"SELECT DISTINCT {column} AS v FROM first_team_players WHERE {column} <> '' "
            f"ORDER BY {column}")
        return [str(r["v"]) for r in rows if r["v"]]

    @staticmethod
    def _row(r: Any) -> Player:
        d = dict(r)
        return Player(
            id=d["id"], first_name=d["first_name"], last_name=d["last_name"],
            display_name=d["display_name"], shirt_number=d["shirt_number"], dob=d["dob"],
            nationality=d["nationality"], foot=d["foot"], primary_position=d["primary_position"],
            secondary_positions=_load(d["secondary_positions"], []), height=d["height"],
            weight=d["weight"], join_date=d["join_date"], captain=_b(d["captain"]),
            vice_captain=_b(d["vice_captain"]), status=d["status"], availability=d["availability"],
            profile_image_id=d["profile_image_id"], club_logo_id=d["club_logo_id"], flag=d["flag"],
            source_scout_player_id=d["source_scout_player_id"], tags=_load(d["tags"], []),
            custom_fields=_load(d["custom_fields"], {}), workspace_id=d["workspace_id"],
            owner=d["owner"], favorite=_b(d["favorite"]), archived=_b(d["archived"]),
            document=_load(d["document"], {}), created_at=d["created_at"],
            updated_at=d["updated_at"], created_by=d["created_by"])


# ---------------------------------------------------------------- child repositories
class _ChildRepo:
    table = ""
    order = "created_at"

    def __init__(self, db: Database) -> None:
        self._db = db

    def list(self, player_id: str) -> list[Any]:
        rows = self._db.query(
            f"SELECT * FROM {self.table} WHERE player_id = ? ORDER BY {self.order}", (player_id,))
        return [self._row(r) for r in rows]

    def get(self, row_id: str) -> Any | None:
        rows = self._db.query(f"SELECT * FROM {self.table} WHERE id = ?", (row_id,))
        return self._row(rows[0]) if rows else None

    def delete(self, row_id: str) -> None:
        self._db.execute(f"DELETE FROM {self.table} WHERE id = ?", (row_id,))

    @staticmethod
    def _row(r: Any) -> Any:
        raise NotImplementedError


class ContractRepository(_ChildRepo):
    table = "player_contracts"
    order = "contract_end DESC"

    def add(self, c: PlayerContract) -> None:
        self._db.execute(
            """INSERT INTO player_contracts (id, player_id, contract_start, contract_end, salary,
                 market_value, agent, loan, loan_club, release_clause, status, document, created_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (c.id, c.player_id, c.contract_start, c.contract_end, c.salary, c.market_value, c.agent,
             int(c.loan), c.loan_club, c.release_clause, c.status, json.dumps(c.document), c.created_by))

    @staticmethod
    def _row(r: Any) -> PlayerContract:
        d = dict(r)
        return PlayerContract(id=d["id"], player_id=d["player_id"], contract_start=d["contract_start"],
                              contract_end=d["contract_end"], salary=d["salary"],
                              market_value=d["market_value"], agent=d["agent"], loan=_b(d["loan"]),
                              loan_club=d["loan_club"], release_clause=d["release_clause"],
                              status=d["status"], document=_load(d["document"], {}),
                              created_by=d["created_by"], created_at=d["created_at"])


class MedicalRepository(_ChildRepo):
    table = "player_medical"
    order = "date DESC"

    def add(self, m: PlayerMedical) -> None:
        self._db.execute(
            """INSERT INTO player_medical (id, player_id, injury, injury_type, date, expected_return,
                 status, availability, severity, medical_notes, document, created_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (m.id, m.player_id, m.injury, m.injury_type, m.date, m.expected_return, m.status,
             m.availability, m.severity, m.medical_notes, json.dumps(m.document), m.created_by))

    @staticmethod
    def _row(r: Any) -> PlayerMedical:
        d = dict(r)
        return PlayerMedical(id=d["id"], player_id=d["player_id"], injury=d["injury"],
                             injury_type=d["injury_type"], date=d["date"],
                             expected_return=d["expected_return"], status=d["status"],
                             availability=d["availability"], severity=d["severity"],
                             medical_notes=d["medical_notes"], document=_load(d["document"], {}),
                             created_by=d["created_by"], created_at=d["created_at"])


class TrainingRepository(_ChildRepo):
    table = "player_training"
    order = "date DESC"

    def add(self, t: PlayerTraining) -> None:
        self._db.execute(
            """INSERT INTO player_training (id, player_id, date, attendance, sprint_distance, hsr,
                 accelerations, decelerations, load, rpe, wellness, coach_notes, document)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (t.id, t.player_id, t.date, t.attendance, t.sprint_distance, t.hsr, t.accelerations,
             t.decelerations, t.load, t.rpe, t.wellness, t.coach_notes, json.dumps(t.document)))

    @staticmethod
    def _row(r: Any) -> PlayerTraining:
        d = dict(r)
        return PlayerTraining(id=d["id"], player_id=d["player_id"], date=d["date"],
                              attendance=d["attendance"], sprint_distance=d["sprint_distance"],
                              hsr=d["hsr"], accelerations=d["accelerations"],
                              decelerations=d["decelerations"], load=d["load"], rpe=d["rpe"],
                              wellness=d["wellness"], coach_notes=d["coach_notes"],
                              document=_load(d["document"], {}), created_at=d["created_at"])


class DocumentRepository(_ChildRepo):
    table = "player_documents"

    def add(self, x: PlayerDocument) -> None:
        self._db.execute(
            """INSERT INTO player_documents (id, player_id, file_id, filename, mime, size_bytes,
                 kind, created_by) VALUES (?,?,?,?,?,?,?,?)""",
            (x.id, x.player_id, x.file_id, x.filename, x.mime, x.size_bytes, x.kind, x.created_by))

    @staticmethod
    def _row(r: Any) -> PlayerDocument:
        d = dict(r)
        return PlayerDocument(id=d["id"], player_id=d["player_id"], file_id=d["file_id"],
                              filename=d["filename"], mime=d["mime"], size_bytes=d["size_bytes"],
                              kind=d["kind"], created_by=d["created_by"], created_at=d["created_at"])


class ImageRepository(_ChildRepo):
    table = "player_images"

    def add(self, x: PlayerImage) -> None:
        self._db.execute(
            """INSERT INTO player_images (id, player_id, image_id, kind, caption, created_by)
               VALUES (?,?,?,?,?,?)""",
            (x.id, x.player_id, x.image_id, x.kind, x.caption, x.created_by))

    @staticmethod
    def _row(r: Any) -> PlayerImage:
        d = dict(r)
        return PlayerImage(id=d["id"], player_id=d["player_id"], image_id=d["image_id"],
                           kind=d["kind"], caption=d["caption"], created_by=d["created_by"],
                           created_at=d["created_at"])


class VideoRepository(_ChildRepo):
    table = "ft_player_videos"        # ft_ prefix: avoids the scouting player_videos table

    def add(self, x: PlayerVideo) -> None:
        self._db.execute(
            """INSERT INTO ft_player_videos (id, player_id, kind, provider, url, file_id, filename,
                 mime, size_bytes, title, created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (x.id, x.player_id, x.kind, x.provider, x.url, x.file_id, x.filename, x.mime,
             x.size_bytes, x.title, x.created_by))

    @staticmethod
    def _row(r: Any) -> PlayerVideo:
        d = dict(r)
        return PlayerVideo(id=d["id"], player_id=d["player_id"], kind=d["kind"], provider=d["provider"],
                           url=d["url"], file_id=d["file_id"], filename=d["filename"], mime=d["mime"],
                           size_bytes=d["size_bytes"], title=d["title"], created_by=d["created_by"],
                           created_at=d["created_at"])


class NoteRepository(_ChildRepo):
    table = "ft_player_notes"          # ft_ prefix: avoids the scouting player_notes table
    order = "pinned DESC, created_at DESC"

    def add(self, n: PlayerNote) -> None:
        self._db.execute(
            """INSERT INTO ft_player_notes (id, player_id, body, kind, pinned, private, author, document)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET body=excluded.body, kind=excluded.kind,
                 pinned=excluded.pinned, private=excluded.private, updated_at=datetime('now')""",
            (n.id, n.player_id, n.body, n.kind, int(n.pinned), int(n.private), n.author,
             json.dumps(n.document)))

    @staticmethod
    def _row(r: Any) -> PlayerNote:
        d = dict(r)
        return PlayerNote(id=d["id"], player_id=d["player_id"], body=d["body"], kind=d["kind"],
                          pinned=_b(d["pinned"]), private=_b(d["private"]), author=d["author"],
                          document=_load(d["document"], {}), created_at=d["created_at"],
                          updated_at=d["updated_at"])


class CareerRepository(_ChildRepo):
    table = "player_career"
    order = "season DESC"

    def add(self, c: PlayerCareer) -> None:
        self._db.execute(
            """INSERT INTO player_career (id, player_id, season, club, competition, appearances,
                 goals, assists, minutes, yellow, red, document) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (c.id, c.player_id, c.season, c.club, c.competition, c.appearances, c.goals, c.assists,
             c.minutes, c.yellow, c.red, json.dumps(c.document)))

    @staticmethod
    def _row(r: Any) -> PlayerCareer:
        d = dict(r)
        return PlayerCareer(id=d["id"], player_id=d["player_id"], season=d["season"], club=d["club"],
                            competition=d["competition"], appearances=d["appearances"], goals=d["goals"],
                            assists=d["assists"], minutes=d["minutes"], yellow=d["yellow"],
                            red=d["red"], document=_load(d["document"], {}), created_at=d["created_at"])


class MatchLinkRepository(_ChildRepo):
    table = "player_match_links"
    order = "created_at DESC"

    def add(self, x: PlayerMatchLink) -> None:
        self._db.execute(
            """INSERT INTO player_match_links (id, player_id, match_id, dataset_id, minutes, role,
                 availability) VALUES (?,?,?,?,?,?,?)""",
            (x.id, x.player_id, x.match_id, x.dataset_id, x.minutes, x.role, x.availability))

    @staticmethod
    def _row(r: Any) -> PlayerMatchLink:
        d = dict(r)
        return PlayerMatchLink(id=d["id"], player_id=d["player_id"], match_id=d["match_id"],
                               dataset_id=d["dataset_id"], minutes=d["minutes"], role=d["role"],
                               availability=d["availability"], created_at=d["created_at"])
