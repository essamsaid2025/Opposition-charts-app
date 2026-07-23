"""Set Piece persistence - the only place set-piece SQL lives (repository
pattern), over the SAME platform Database (migration 10). Lists/documents are
JSON columns; every read reconstructs a typed model. No business logic here."""
from __future__ import annotations

import json
from typing import Any

from fap.db.engine import Database
from fap.setpieces.models import (
    SetPiece, SetPieceContact, SetPieceImport, SetPiecePosition,
)


def _b(v: Any) -> bool:
    return bool(v)


def _load(s: str | None) -> Any:
    if not s:
        return None
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return None


class SetPieceRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    _COLS = (
        "id, workspace_id, match_id, match_label, season, competition, team, opponent, "
        "match_date, venue, perspective, phase, type, subtype, side, taker, taker_id, foot, "
        "minute, period, start_x, start_y, end_x, end_y, delivery_type, delivery_height, "
        "delivery_length, delivery_speed, players_in_box, first_contact_team, first_contact_x, "
        "first_contact_y, outcome, shot, goal, xg, second_ball_team, retained, "
        "time_to_first_contact, time_to_shot, routine, marking, video_url, source, import_id, "
        "owner, archived, tags, document"
    )

    def save(self, sp: SetPiece) -> None:
        self._db.execute(
            f"""INSERT INTO set_pieces ({self._COLS})
                VALUES ({','.join(['?'] * 49)})
                ON CONFLICT(id) DO UPDATE SET
                  workspace_id=excluded.workspace_id, match_id=excluded.match_id,
                  match_label=excluded.match_label, season=excluded.season,
                  competition=excluded.competition, team=excluded.team, opponent=excluded.opponent,
                  match_date=excluded.match_date, venue=excluded.venue,
                  perspective=excluded.perspective, phase=excluded.phase, type=excluded.type,
                  subtype=excluded.subtype, side=excluded.side, taker=excluded.taker,
                  taker_id=excluded.taker_id, foot=excluded.foot, minute=excluded.minute,
                  period=excluded.period, start_x=excluded.start_x, start_y=excluded.start_y,
                  end_x=excluded.end_x, end_y=excluded.end_y, delivery_type=excluded.delivery_type,
                  delivery_height=excluded.delivery_height, delivery_length=excluded.delivery_length,
                  delivery_speed=excluded.delivery_speed, players_in_box=excluded.players_in_box,
                  first_contact_team=excluded.first_contact_team,
                  first_contact_x=excluded.first_contact_x, first_contact_y=excluded.first_contact_y,
                  outcome=excluded.outcome, shot=excluded.shot, goal=excluded.goal, xg=excluded.xg,
                  second_ball_team=excluded.second_ball_team, retained=excluded.retained,
                  time_to_first_contact=excluded.time_to_first_contact,
                  time_to_shot=excluded.time_to_shot, routine=excluded.routine,
                  marking=excluded.marking, video_url=excluded.video_url, source=excluded.source,
                  import_id=excluded.import_id, owner=excluded.owner, archived=excluded.archived,
                  tags=excluded.tags, document=excluded.document, updated_at=datetime('now')""",
            (sp.id, sp.workspace_id, sp.match_id, sp.match_label, sp.season, sp.competition,
             sp.team, sp.opponent, sp.match_date, sp.venue, sp.perspective, sp.phase, sp.type,
             sp.subtype, sp.side, sp.taker, sp.taker_id, sp.foot, sp.minute, sp.period,
             sp.start_x, sp.start_y, sp.end_x, sp.end_y, sp.delivery_type, sp.delivery_height,
             sp.delivery_length, sp.delivery_speed, sp.players_in_box, sp.first_contact_team,
             sp.first_contact_x, sp.first_contact_y, sp.outcome, int(sp.shot), int(sp.goal),
             sp.xg, sp.second_ball_team, int(sp.retained), sp.time_to_first_contact,
             sp.time_to_shot, sp.routine, sp.marking, sp.video_url, sp.source, sp.import_id,
             sp.owner, int(sp.archived), json.dumps(sp.tags), json.dumps(sp.document)))

    def get(self, sp_id: str) -> SetPiece | None:
        rows = self._db.query("SELECT * FROM set_pieces WHERE id = ?", (sp_id,))
        return self._row(rows[0]) if rows else None

    def delete(self, sp_id: str) -> None:
        self._db.execute("DELETE FROM set_pieces WHERE id = ?", (sp_id,))

    def search(self, *, filters: dict[str, Any] | None = None, archived: bool = False,
               workspace_id: str | None = None, limit: int = 1000) -> list[SetPiece]:
        clauses, params = ["archived = ?"], [int(archived)]
        f = filters or {}
        if workspace_id:
            clauses.append("workspace_id = ?"); params.append(workspace_id)
        for col in ("perspective", "phase", "type", "team", "opponent", "season",
                    "competition", "match_id", "side", "delivery_type", "source"):
            if f.get(col):
                clauses.append(f"lower({col}) = ?"); params.append(str(f[col]).lower())
        if f.get("shot_only"):
            clauses.append("shot = 1")
        if f.get("goal_only"):
            clauses.append("goal = 1")
        sql = (f"SELECT * FROM set_pieces WHERE {' AND '.join(clauses)} "
               f"ORDER BY created_at DESC LIMIT ?")
        params.append(int(limit))
        return [self._row(r) for r in self._db.query(sql, tuple(params))]

    def count(self, *, archived: bool = False, filters: dict[str, Any] | None = None) -> int:
        clauses, params = ["archived = ?"], [int(archived)]
        f = filters or {}
        for col in ("perspective", "phase", "type"):
            if f.get(col):
                clauses.append(f"lower({col}) = ?"); params.append(str(f[col]).lower())
        rows = self._db.query(
            f"SELECT COUNT(*) AS n FROM set_pieces WHERE {' AND '.join(clauses)}", tuple(params))
        return int(rows[0]["n"]) if rows else 0

    def type_breakdown(self, *, perspective: str | None = None,
                       archived: bool = False) -> dict[str, int]:
        clauses, params = ["archived = ?"], [int(archived)]
        if perspective:
            clauses.append("lower(perspective) = ?"); params.append(perspective.lower())
        rows = self._db.query(
            f"SELECT type, COUNT(*) AS n FROM set_pieces WHERE {' AND '.join(clauses)} "
            "GROUP BY type", tuple(params))
        return {str(r["type"]): int(r["n"]) for r in rows}

    @staticmethod
    def _row(r: Any) -> SetPiece:
        d = dict(r)
        return SetPiece(
            id=d["id"], workspace_id=d["workspace_id"], match_id=d["match_id"],
            match_label=d["match_label"], season=d["season"], competition=d["competition"],
            team=d["team"], opponent=d["opponent"], match_date=d["match_date"], venue=d["venue"],
            perspective=d["perspective"], phase=d["phase"], type=d["type"], subtype=d["subtype"],
            side=d["side"], taker=d["taker"], taker_id=d["taker_id"], foot=d["foot"],
            minute=d["minute"], period=d["period"], start_x=d["start_x"], start_y=d["start_y"],
            end_x=d["end_x"], end_y=d["end_y"], delivery_type=d["delivery_type"],
            delivery_height=d["delivery_height"], delivery_length=d["delivery_length"],
            delivery_speed=d["delivery_speed"], players_in_box=d["players_in_box"],
            first_contact_team=d["first_contact_team"], first_contact_x=d["first_contact_x"],
            first_contact_y=d["first_contact_y"], outcome=d["outcome"], shot=_b(d["shot"]),
            goal=_b(d["goal"]), xg=d["xg"], second_ball_team=d["second_ball_team"],
            retained=_b(d["retained"]), time_to_first_contact=d["time_to_first_contact"],
            time_to_shot=d["time_to_shot"], routine=d["routine"], marking=d["marking"],
            video_url=d["video_url"], source=d["source"], import_id=d["import_id"],
            owner=d["owner"], archived=_b(d["archived"]), tags=_load(d["tags"]) or [],
            document=_load(d["document"]) or {}, created_at=d["created_at"],
            updated_at=d["updated_at"], created_by=d["created_by"])


class PositionRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, p: SetPiecePosition) -> None:
        self._db.execute(
            """INSERT INTO set_piece_positions
                 (id, set_piece_id, moment, team, player, player_id, role, zone, x, y,
                  is_gk, marking, run_type, document)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (p.id, p.set_piece_id, p.moment, p.team, p.player, p.player_id, p.role, p.zone,
             p.x, p.y, int(p.is_gk), p.marking, p.run_type, json.dumps(p.document)))

    def list(self, set_piece_id: str, *, moment: str | None = None) -> list[SetPiecePosition]:
        sql = "SELECT * FROM set_piece_positions WHERE set_piece_id = ?"
        params: list[Any] = [set_piece_id]
        if moment:
            sql += " AND moment = ?"; params.append(moment)
        sql += " ORDER BY team, role"
        return [self._row(r) for r in self._db.query(sql, tuple(params))]

    def delete(self, position_id: str) -> None:
        self._db.execute("DELETE FROM set_piece_positions WHERE id = ?", (position_id,))

    def delete_for(self, set_piece_id: str) -> None:
        self._db.execute("DELETE FROM set_piece_positions WHERE set_piece_id = ?", (set_piece_id,))

    @staticmethod
    def _row(r: Any) -> SetPiecePosition:
        d = dict(r)
        return SetPiecePosition(
            id=d["id"], set_piece_id=d["set_piece_id"], moment=d["moment"], team=d["team"],
            player=d["player"], player_id=d["player_id"], role=d["role"], zone=d["zone"],
            x=d["x"], y=d["y"], is_gk=_b(d["is_gk"]), marking=d["marking"],
            run_type=d["run_type"], document=_load(d["document"]) or {}, created_at=d["created_at"])


class ContactRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, c: SetPieceContact) -> None:
        self._db.execute(
            """INSERT INTO set_piece_contacts
                 (id, set_piece_id, kind, sequence, team, player, player_id, x, y,
                  body_part, outcome, won, distance, document)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (c.id, c.set_piece_id, c.kind, c.sequence, c.team, c.player, c.player_id, c.x, c.y,
             c.body_part, c.outcome, int(c.won), c.distance, json.dumps(c.document)))

    def list(self, set_piece_id: str, *, kind: str | None = None) -> list[SetPieceContact]:
        sql = "SELECT * FROM set_piece_contacts WHERE set_piece_id = ?"
        params: list[Any] = [set_piece_id]
        if kind:
            sql += " AND kind = ?"; params.append(kind)
        sql += " ORDER BY sequence"
        return [self._row(r) for r in self._db.query(sql, tuple(params))]

    def delete(self, contact_id: str) -> None:
        self._db.execute("DELETE FROM set_piece_contacts WHERE id = ?", (contact_id,))

    @staticmethod
    def _row(r: Any) -> SetPieceContact:
        d = dict(r)
        return SetPieceContact(
            id=d["id"], set_piece_id=d["set_piece_id"], kind=d["kind"], sequence=d["sequence"],
            team=d["team"], player=d["player"], player_id=d["player_id"], x=d["x"], y=d["y"],
            body_part=d["body_part"], outcome=d["outcome"], won=_b(d["won"]), distance=d["distance"],
            document=_load(d["document"]) or {}, created_at=d["created_at"])


class ImportRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, imp: SetPieceImport) -> None:
        self._db.execute(
            """INSERT INTO set_piece_imports
                 (id, workspace_id, filename, provider, rows, imported, skipped, mapping, document)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (imp.id, imp.workspace_id, imp.filename, imp.provider, imp.rows, imp.imported,
             imp.skipped, json.dumps(imp.mapping), json.dumps(imp.document)))

    def recent(self, *, limit: int = 20) -> list[SetPieceImport]:
        rows = self._db.query(
            "SELECT * FROM set_piece_imports ORDER BY created_at DESC LIMIT ?", (limit,))
        return [self._row(r) for r in rows]

    @staticmethod
    def _row(r: Any) -> SetPieceImport:
        d = dict(r)
        return SetPieceImport(
            id=d["id"], workspace_id=d["workspace_id"], filename=d["filename"],
            provider=d["provider"], rows=d["rows"], imported=d["imported"], skipped=d["skipped"],
            mapping=_load(d["mapping"]) or {}, document=_load(d["document"]) or {},
            created_at=d["created_at"], created_by=d["created_by"])
