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
from dataclasses import asdict, replace
from typing import Any

import pandas as pd

from fap.identity.capabilities import Capability
from fap.identity.models import User
from fap.setpieces import analysis as A
from fap.setpieces import analytics as AN
from fap.setpieces.models import (
    ImportResult, SetPiece, SetPieceContact, SetPieceFilter, SetPieceImport,
    SetPiecePosition,
)
from fap.setpieces.reporting import build_setpiece_sections
from fap.setpieces.repository import (
    ContactRepository, ImportRepository, PositionRepository, SetPieceRepository,
)


class SetPieceService:
    def __init__(self, db: Any, *, permissions: Any, audit: Any, reports: Any = None,
                 images: Any = None, videos: Any = None, attachments: Any = None,
                 workspaces: Any = None, cache: Any = None, themes: Any = None) -> None:
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
        self._themes = themes

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

    # =============================================================== analytics (9.1)
    def _filtered(self, user: User, filt: SetPieceFilter | None,
                  workspace_id: str | None) -> list[SetPiece]:
        """Resolve a filter to the matching set pieces. Coarse fields push down to
        SQL; ``player`` (a player who appears in the box/contacts, distinct from
        the taker) is resolved here against tagged positions and contacts."""
        filt = filt or SetPieceFilter()
        repo_f = filt.to_repo_filters()
        if filt.half is not None:
            repo_f["half"] = filt.half
        sps = self.set_pieces.search(filters=repo_f or None, workspace_id=workspace_id)
        if filt.has_player:
            pl = filt.player.strip().lower()
            ids = [s.id for s in sps]
            keep = {s.id for s in sps if s.taker.lower() == pl}
            keep |= {p.set_piece_id for p in self.positions.list_many(ids)
                     if p.player.lower() == pl}
            keep |= {c.set_piece_id for c in self.contacts.list_many(ids)
                     if c.player.lower() == pl}
            sps = [s for s in sps if s.id in keep]
        return sps

    def analytics_overview(self, user: User, filt: SetPieceFilter | None = None, *,
                           workspace_id: str | None = None) -> dict[str, Any]:
        """The dashboard bundle: overview KPIs, derived rates, per-type stats,
        delivery and outcome breakdowns. Pure aggregation over filtered rows."""
        self._require(user, Capability.VIEW_SETPIECE)
        sps = self._filtered(user, filt, workspace_id)
        return {
            "count": len(sps),
            "overview": AN.overview(sps),
            "derived": AN.derived_rates(sps),
            "by_type": AN.by_type(sps),
            "delivery": AN.delivery_breakdown(sps),
            "outcome": AN.outcome_breakdown(sps),
        }

    def offensive_dashboard(self, user: User, filt: SetPieceFilter | None = None, *,
                            workspace_id: str | None = None) -> dict[str, Any]:
        return self.analytics_overview(user, replace(filt or SetPieceFilter(),
                                                     phase="offensive"), workspace_id=workspace_id)

    def defensive_dashboard(self, user: User, filt: SetPieceFilter | None = None, *,
                            workspace_id: str | None = None) -> dict[str, Any]:
        return self.analytics_overview(user, replace(filt or SetPieceFilter(),
                                                     phase="defensive"), workspace_id=workspace_id)

    def map_data(self, user: User, kind: str, filt: SetPieceFilter | None = None, *,
                 workspace_id: str | None = None, team: str = "attack",
                 moment: str = "delivery") -> list[dict[str, Any]]:
        """Coordinate dataset for a map (the backend Phase 9.2 renders). ``kind``:
        delivery | shot | first_contact | second_ball | delivery_accuracy |
        occupancy_density | movement | goalkeeper."""
        self._require(user, Capability.VIEW_SETPIECE)
        sps = self._filtered(user, filt, workspace_id)
        ids = [s.id for s in sps]
        if kind == "delivery":
            return AN.delivery_points(sps)
        if kind == "delivery_accuracy":
            return AN.delivery_accuracy(sps)
        if kind in ("shot", "first_contact", "second_ball"):
            contacts = self.contacts.list_many(ids)
            if kind == "shot":
                return AN.shot_points(sps, contacts)
            if kind == "first_contact":
                return AN.first_contact_points(sps, contacts)
            return AN.second_ball_points(contacts)
        if kind in ("occupancy_density", "movement", "goalkeeper"):
            positions = self.positions.list_many(ids)
            if kind == "occupancy_density":
                return AN.occupancy_density_points(positions, team=team, moment=moment)
            if kind == "movement":
                return AN.movement_vectors(positions, team=team)
            return AN.goalkeeper_positions(positions)
        raise ValueError(f"unknown map kind {kind!r}")

    def occupancy(self, user: User, filt: SetPieceFilter | None = None, *,
                  team: str = "attack", workspace_id: str | None = None) -> dict[str, Any]:
        """Box-occupancy analytics bundle (zone counts, player x zone matrix,
        defensive shape, marking classification) - backend for the 9.2 visuals."""
        self._require(user, Capability.VIEW_SETPIECE)
        sps = self._filtered(user, filt, workspace_id)
        n = len(sps)
        positions = self.positions.list_many([s.id for s in sps])
        return {
            "n_set_pieces": n,
            "zone_counts": AN.occupancy_zone_counts(positions, team=team, n_set_pieces=n),
            "matrix": AN.occupancy_matrix(positions, team=team, n_set_pieces=n),
            "defensive_shape": AN.defensive_shape(positions),
            "marking": AN.classify_marking(positions),
        }

    def filter_options(self, user: User) -> dict[str, list[str]]:
        """Distinct values per filterable column - populates the dashboard filter
        bar. Cheap: a handful of DISTINCT queries."""
        self._require(user, Capability.VIEW_SETPIECE)
        r = self.set_pieces
        return {col: r.distinct_values(col) for col in
                ("team", "opponent", "competition", "season", "match_id",
                 "taker", "delivery_type", "outcome", "type", "side")}

    # =============================================================== visualizations (9.2)
    def visual_dataset(self, user: User, kind: str, filt: SetPieceFilter | None = None, *,
                       workspace_id: str | None = None) -> list[dict[str, Any]]:
        """Viz-ready rows for a dataset ``kind`` (the frame a set-piece
        visualization renders). Every plugin declares its kind via ``sp_dataset``;
        this is the single bridge between the analytics datasets and the engine."""
        self._require(user, Capability.VIEW_SETPIECE)
        from fap.setpieces import build_frames as BF
        sps = self._filtered(user, filt, workspace_id)
        return BF.rows(self, sps, kind)

    def _positions_of(self, sps: list[SetPiece]) -> list[SetPiecePosition]:
        return self.positions.list_many([s.id for s in sps])

    def _contacts_of(self, sps: list[SetPiece]) -> list[SetPieceContact]:
        return self.contacts.list_many([s.id for s in sps])

    def visual_catalog(self, user: User) -> list[dict[str, str]]:
        """Every registered set-piece visualization (id, name, category), grouped
        for the picker. Loads the set-piece visuals into the shared registry."""
        self._require(user, Capability.VIEW_SETPIECE)
        from fap.visuals.setpieces import load_setpiece_visuals, setpiece_visual_ids
        load_setpiece_visuals()
        from fap.visuals.base import visual_registry
        out = []
        for viz_id in setpiece_visual_ids():
            viz = visual_registry.create(viz_id)
            out.append({"id": viz.info.id, "name": viz.info.name,
                        "category": getattr(viz, "sp_category", viz.info.category)})
        return sorted(out, key=lambda v: (v["category"], v["name"]))

    def render_visual(self, user: User, viz_id: str, filt: SetPieceFilter | None = None, *,
                      controls: dict[str, Any] | None = None, theme_id: str = "opta_light",
                      dpi: int = 200, fmt: str = "png", workspace_id: str | None = None) -> bytes:
        """Render one set-piece visualization to PNG or PDF bytes, reusing the
        platform Renderer (pitch, theme, tokens, legend, export, figure cache).
        Individual export + interactive preview both go through here."""
        self._require(user, Capability.VIEW_SETPIECE)
        fig, _ = self._figure(user, viz_id, filt, controls, theme_id, workspace_id)
        from io import BytesIO
        import matplotlib.pyplot as plt
        buf = BytesIO()
        fig.savefig(buf, format="pdf" if fmt == "pdf" else "png", dpi=dpi,
                    bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)
        return buf.getvalue()

    def _figure(self, user: User, viz_id: str, filt, controls, theme_id, workspace_id):
        from fap.core.types import RenderContext
        from fap.visuals.base import visual_registry
        from fap.visuals.renderer import Renderer
        from fap.visuals.setpieces import load_setpiece_visuals
        load_setpiece_visuals()
        if viz_id not in visual_registry:
            raise ValueError(f"unknown set-piece visualization {viz_id!r}")
        viz = visual_registry.create(viz_id)
        rows = self.visual_dataset(user, getattr(viz, "sp_dataset", ""), filt,
                                   workspace_id=workspace_id)
        frame = pd.DataFrame(rows) if rows else pd.DataFrame()
        # guarantee the columns this viz needs exist, so an empty/partial dataset
        # renders an empty pitch instead of raising in a layer's dropna(subset=...)
        for col in getattr(viz, "requires", ()) or ():
            if col not in frame.columns:
                frame[col] = pd.NA
        theme = self._theme(theme_id)
        ctx = RenderContext(df=frame, theme=theme, controls=dict(controls or {}))
        return Renderer(self._cache).render(viz, ctx), frame

    def _theme(self, theme_id: str):
        if self._themes is None:
            raise ValueError("Theme manager is not configured.")
        return self._themes.get(theme_id)

    def theme_ids(self, user: User) -> list[str]:
        self._require(user, Capability.VIEW_SETPIECE)
        if self._themes is None:
            return []
        try:
            return list(self._themes.ids())
        except Exception:
            return []

    def embed_visual(self, user: User, report_id: str, viz_id: str,
                     filt: SetPieceFilter | None = None, *, controls: dict[str, Any] | None = None,
                     theme_id: str = "opta_light", title: str = "",
                     workspace_id: str | None = None) -> None:
        """Embed a set-piece visualization into an existing Studio report with NO
        per-viz code: pre-render the PNG through the engine, store it once via the
        report ImageStorage, and append an image block. Works for every viz."""
        self._require(user, Capability.EDIT_SETPIECE)
        if self._reports is None:
            raise ValueError("Reports engine is not configured.")
        png = self.render_visual(user, viz_id, filt, controls=controls, theme_id=theme_id,
                                 dpi=200, fmt="png", workspace_id=workspace_id)
        image = self._reports.upload_image(user, png, f"{viz_id}.png", "image/png",
                                           workspace_id=workspace_id)
        from fap.reports.blocks import image_block
        block = image_block(image.id, caption=title or viz_id, title=title)
        self._reports.update_blocks(user, report_id, lambda doc: doc.blocks.append(block))
        self.audit.record(user, "setpiece.visual.embed", target_type="report",
                          target_id=report_id, detail={"viz": viz_id})

    # =============================================================== reports (Studio)
    def create_report(self, user: User, *, filt: SetPieceFilter | None = None,
                      title: str = "", workspace_id: str | None = None):
        """Create a set-piece analytics report in the EXISTING Report Studio:
        ReportsManager.create() makes a blank report, then update_blocks() injects
        the statistics sections. No second reporting engine, no second editor."""
        self._require(user, Capability.CREATE_REPORT)
        if self._reports is None:
            raise ValueError("Reports engine is not configured.")
        filt = filt or SetPieceFilter()
        bundle = self.analytics_overview(user, filt, workspace_id=workspace_id)
        ov = bundle["overview"]
        title = title or "Set Piece Analysis Report"
        cover = {"title": title, "subtitle": f"{bundle['count']} set pieces",
                 "club": filt.team, "opponent": filt.opponent, "competition": filt.competition,
                 "season": filt.season, "analyst": user.name or user.email, "match_date": ""}
        df = pd.DataFrame([{"total": ov["total"], "goals": ov["goals"], "shots": ov["shots"],
                            "xg": ov["xg"]}])
        templates = [t.info.id for t in self._reports.templates()]
        template = "blank" if "blank" in templates else (templates[0] if templates else "")
        record = self._reports.create(user, template=template, df=df, title=title,
                                      workspace_id=workspace_id, cover=cover)
        sections = build_setpiece_sections(bundle)
        filt_meta = asdict(filt)

        def _inject(doc):
            doc.sections.extend(sections)
            doc.meta["setpiece_filter"] = filt_meta
            doc.meta["source"] = "setpieces"

        self._reports.update_blocks(user, record.id, _inject)
        self.audit.record(user, "setpiece.report.create", target_type="report",
                          target_id=record.id, detail={"title": title, "count": bundle["count"]})
        return record

    # ---------------------------------------------------------------- helpers
    def _or_raise(self, sp_id: str) -> SetPiece:
        sp = self.set_pieces.get(sp_id)
        if sp is None:
            raise ValueError(f"set piece {sp_id!r} not found")
        return sp
