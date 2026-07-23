"""SetPieceService - the facade the Set Piece UI talks to (Phase 9.0 foundation).

Owns the set-piece event store and everything hanging off a set piece: the
per-delivery player positions (box occupancy) and the contact/second-ball events,
plus provider-agnostic import (CSV/Excel/JSON) and the manual tagging engine.

It REUSES the platform services and never duplicates them - PermissionService for
capability checks (VIEW_SETPIECE / EDIT_SETPIECE, already provisioned),
AuditService for the trail, ReportsManager for reports (opened in the EXISTING
Report Studio in a later phase), ImageStorage / FileStorage for assets and
WorkspaceManager for workspace scoping. No business logic lives in Streamlit.
"""
from __future__ import annotations

import uuid
from typing import Any

import pandas as pd

from fap.identity.capabilities import Capability
from fap.identity.models import User
from fap.setpieces import analysis as A
from fap.setpieces.models import (
    ImportResult, SetPiece, SetPieceContact, SetPieceImport, SetPiecePosition,
)
from fap.setpieces.repository import (
    ContactRepository, ImportRepository, PositionRepository, SetPieceRepository,
)


class SetPieceService:
    def __init__(self, db: Any, *, permissions: Any, audit: Any, reports: Any = None,
                 images: Any = None, videos: Any = None, attachments: Any = None,
                 workspaces: Any = None, cache: Any = None) -> None:
        self._db = db
        self.set_pieces = SetPieceRepository(db)
        self.positions = PositionRepository(db)
        self.contacts = ContactRepository(db)
        self.imports = ImportRepository(db)
        self.perms = permissions
        self.audit = audit
        self._reports = reports
        self._images = images
        self._video_storage = videos
        self._attach_storage = attachments
        self._wm = workspaces
        self._cache = cache

    # ---------------------------------------------------------------- guards
    def _require(self, user: User, cap: Capability, scope: str | None = None) -> None:
        self.perms.require(user, str(cap), scope)

    def _uid(self) -> str:
        return str(uuid.uuid4())

    # =============================================================== set pieces
    def create_set_piece(self, user: User, **fields: Any) -> SetPiece:
        """Manual tagging entry point: create one set piece from tagged fields."""
        self._require(user, Capability.EDIT_SETPIECE)
        sp = self._build(fields, owner=user.email, created_by=user.email, source="manual")
        self.set_pieces.save(sp)
        self.audit.record(user, "setpiece.create", target_type="set_piece", target_id=sp.id,
                          detail={"type": sp.type, "phase": sp.phase, "perspective": sp.perspective})
        return sp

    def _build(self, fields: dict[str, Any], *, owner: str, created_by: str,
               source: str, import_id: str = "") -> SetPiece:
        sp = SetPiece(id=self._uid(), owner=owner, created_by=created_by, source=source,
                      import_id=import_id)
        for k, v in fields.items():
            if hasattr(sp, k) and k not in ("id", "created_by", "owner", "source"):
                setattr(sp, k, v)
        sp.type = A.canonical_type(sp.type)
        sp.phase = A.canonical_phase(sp.phase)
        sp.perspective = A.canonical_perspective(sp.perspective)
        if sp.side:
            sp.side = A.canonical_side(sp.side)
        if sp.delivery_type:
            sp.delivery_type = A.canonical_delivery(sp.delivery_type)
        return sp

    def get_set_piece(self, sp_id: str) -> SetPiece | None:
        return self.set_pieces.get(sp_id)

    def update_set_piece(self, user: User, sp_id: str, **fields: Any) -> SetPiece:
        self._require(user, Capability.EDIT_SETPIECE)
        sp = self._or_raise(sp_id)
        for k, v in fields.items():
            if hasattr(sp, k) and k not in ("id", "created_by", "created_at"):
                setattr(sp, k, v)
        self.set_pieces.save(sp)
        self.audit.record(user, "setpiece.update", target_type="set_piece", target_id=sp_id,
                          detail={"fields": sorted(fields)})
        return sp

    def archive_set_piece(self, user: User, sp_id: str, archived: bool = True) -> None:
        self._require(user, Capability.EDIT_SETPIECE)
        sp = self._or_raise(sp_id)
        sp.archived = archived
        self.set_pieces.save(sp)
        self.audit.record(user, "setpiece.archive" if archived else "setpiece.restore",
                          target_type="set_piece", target_id=sp_id)

    def delete_set_piece(self, user: User, sp_id: str) -> None:
        """Hard delete a set piece; positions and contacts cascade in SQLite."""
        self._require(user, Capability.EDIT_SETPIECE)
        self._or_raise(sp_id)
        self.set_pieces.delete(sp_id)
        self.audit.record(user, "setpiece.delete", target_type="set_piece", target_id=sp_id)

    def search(self, user: User, *, filters: dict[str, Any] | None = None,
               archived: bool = False, workspace_id: str | None = None,
               limit: int = 1000) -> list[SetPiece]:
        self._require(user, Capability.VIEW_SETPIECE)
        return self.set_pieces.search(filters=filters, archived=archived,
                                      workspace_id=workspace_id, limit=limit)

    # ============================================================ tagging: positions
    def add_position(self, user: User, set_piece_id: str, *, team: str = "attack",
                     player: str = "", role: str = "", x: float | None = None,
                     y: float | None = None, moment: str = "delivery", is_gk: bool = False,
                     marking: str = "", run_type: str = "", player_id: str = "") -> SetPiecePosition:
        """Record one player's position at a set piece (the box-occupancy input).
        If no role is given but coordinates are, auto-label the occupancy zone."""
        self._require(user, Capability.EDIT_SETPIECE)
        self._or_raise(set_piece_id)
        zone = A.zone_for(x, y) if (x is not None and y is not None) else ""
        p = SetPiecePosition(id=self._uid(), set_piece_id=set_piece_id, moment=moment, team=team,
                             player=player, player_id=player_id, role=role or zone, zone=zone,
                             x=x, y=y, is_gk=is_gk, marking=marking, run_type=run_type)
        self.positions.add(p)
        self.audit.record(user, "setpiece.position.add", target_type="set_piece",
                          target_id=set_piece_id, detail={"team": team, "role": p.role})
        return p

    def set_positions(self, user: User, set_piece_id: str,
                      positions: list[dict[str, Any]], *, replace: bool = True) -> int:
        """Bulk-record a full box (used by the tagging engine / import)."""
        self._require(user, Capability.EDIT_SETPIECE)
        self._or_raise(set_piece_id)
        if replace:
            self.positions.delete_for(set_piece_id)
        n = 0
        for spec in positions:
            x, y = spec.get("x"), spec.get("y")
            zone = A.zone_for(x, y) if (x is not None and y is not None) else ""
            self.positions.add(SetPiecePosition(
                id=self._uid(), set_piece_id=set_piece_id, moment=spec.get("moment", "delivery"),
                team=spec.get("team", "attack"), player=spec.get("player", ""),
                player_id=spec.get("player_id", ""), role=spec.get("role") or zone, zone=zone,
                x=x, y=y, is_gk=bool(spec.get("is_gk", False)), marking=spec.get("marking", ""),
                run_type=spec.get("run_type", "")))
            n += 1
        self.audit.record(user, "setpiece.positions.set", target_type="set_piece",
                          target_id=set_piece_id, detail={"count": n})
        return n

    def list_positions(self, set_piece_id: str, *, moment: str | None = None) -> list[SetPiecePosition]:
        return self.positions.list(set_piece_id, moment=moment)

    def delete_position(self, user: User, position_id: str) -> None:
        self._require(user, Capability.EDIT_SETPIECE)
        self.positions.delete(position_id)
        self.audit.record(user, "setpiece.position.delete", target_type="position",
                          target_id=position_id)

    # ============================================================ tagging: contacts
    def add_contact(self, user: User, set_piece_id: str, *, kind: str = "first_contact",
                    team: str = "", player: str = "", x: float | None = None,
                    y: float | None = None, body_part: str = "", outcome: str = "",
                    won: bool = False, sequence: int = 0, player_id: str = "",
                    distance: float | None = None) -> SetPieceContact:
        self._require(user, Capability.EDIT_SETPIECE)
        self._or_raise(set_piece_id)
        c = SetPieceContact(id=self._uid(), set_piece_id=set_piece_id, kind=kind, sequence=sequence,
                            team=team, player=player, player_id=player_id, x=x, y=y,
                            body_part=body_part, outcome=outcome, won=won, distance=distance)
        self.contacts.add(c)
        self.audit.record(user, "setpiece.contact.add", target_type="set_piece",
                          target_id=set_piece_id, detail={"kind": kind, "outcome": outcome})
        return c

    def list_contacts(self, set_piece_id: str, *, kind: str | None = None) -> list[SetPieceContact]:
        return self.contacts.list(set_piece_id, kind=kind)

    def delete_contact(self, user: User, contact_id: str) -> None:
        self._require(user, Capability.EDIT_SETPIECE)
        self.contacts.delete(contact_id)
        self.audit.record(user, "setpiece.contact.delete", target_type="contact",
                          target_id=contact_id)

    # =============================================================== import
    def import_file(self, user: User, data: bytes, filename: str, *,
                    perspective: str = "own", phase: str = "offensive",
                    workspace_id: str | None = None, provider: str = "generic",
                    mapping: dict[str, str] | None = None) -> ImportResult:
        """Provider-agnostic ingest: read the file, detect columns, normalize rows
        and persist the set pieces. One import batch row records the provenance."""
        self._require(user, Capability.EDIT_SETPIECE)
        df = A.read_table(data, filename)
        return self._import_frame(user, df, filename=filename, perspective=perspective,
                                  phase=phase, workspace_id=workspace_id, provider=provider,
                                  mapping=mapping)

    def import_dataframe(self, user: User, df: pd.DataFrame, *, filename: str = "dataframe",
                         perspective: str = "own", phase: str = "offensive",
                         workspace_id: str | None = None, provider: str = "generic",
                         mapping: dict[str, str] | None = None) -> ImportResult:
        self._require(user, Capability.EDIT_SETPIECE)
        return self._import_frame(user, df, filename=filename, perspective=perspective,
                                  phase=phase, workspace_id=workspace_id, provider=provider,
                                  mapping=mapping)

    def preview_mapping(self, user: User, data: bytes, filename: str) -> dict[str, Any]:
        """Read a file's header and return the detected field->column mapping so the
        page can show/adjust it before committing the import."""
        self._require(user, Capability.VIEW_SETPIECE)
        df = A.read_table(data, filename)
        return {"columns": list(df.columns), "mapping": A.detect_mapping(list(df.columns)),
                "rows": int(len(df)), "sample": df.head(5).to_dict(orient="records")}

    def _import_frame(self, user: User, df: pd.DataFrame, *, filename: str, perspective: str,
                      phase: str, workspace_id: str | None, provider: str,
                      mapping: dict[str, str] | None) -> ImportResult:
        mapping = mapping or A.detect_mapping(list(df.columns))
        defaults = {"perspective": perspective, "phase": phase, "workspace_id": workspace_id}
        rows, errors = A.normalize_rows(df, mapping, defaults=defaults)
        import_id = self._uid()
        saved: list[SetPiece] = []
        for rec in rows:
            try:
                sp = self._build(rec, owner=user.email, created_by=user.email,
                                 source="import", import_id=import_id)
                self.set_pieces.save(sp)
                saved.append(sp)
            except Exception as exc:
                errors.append(f"save failed: {exc}")
        batch = SetPieceImport(id=import_id, workspace_id=workspace_id, filename=filename,
                               provider=provider, rows=int(len(df)), imported=len(saved),
                               skipped=int(len(df)) - len(saved), mapping=mapping)
        self.imports.add(batch)
        self.audit.record(user, "setpiece.import", target_type="import", target_id=import_id,
                          detail={"filename": filename, "rows": batch.rows, "imported": batch.imported})
        return ImportResult(batch=batch, set_pieces=saved, errors=errors)

    def recent_imports(self, user: User, *, limit: int = 20) -> list[SetPieceImport]:
        self._require(user, Capability.VIEW_SETPIECE)
        return self.imports.recent(limit=limit)

    # =============================================================== dashboard
    def dashboard(self, user: User, *, perspective: str | None = None) -> dict[str, Any]:
        """Counts for the (empty-by-default) dashboard. Real KPIs/maps land in 9.1;
        this proves the store end-to-end and gives an honest empty state."""
        self._require(user, Capability.VIEW_SETPIECE)
        total = self.set_pieces.count()
        by_type = self.set_pieces.type_breakdown(perspective=perspective)
        return {
            "total": total,
            "by_type": by_type,
            "offensive": self.set_pieces.count(filters={"phase": "offensive"}),
            "defensive": self.set_pieces.count(filters={"phase": "defensive"}),
            "own": self.set_pieces.count(filters={"perspective": "own"}),
            "opposition": self.set_pieces.count(filters={"perspective": "opposition"}),
            "recent_imports": self.imports.recent(limit=5),
        }

    # ---------------------------------------------------------------- helpers
    def _or_raise(self, sp_id: str) -> SetPiece:
        sp = self.set_pieces.get(sp_id)
        if sp is None:
            raise ValueError(f"set piece {sp_id!r} not found")
        return sp
