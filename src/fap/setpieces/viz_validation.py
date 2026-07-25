"""Set-piece visualization VALIDATION layer (Phase 9.6).

Runs before a visualization renders and answers: is it READY, or is it empty
because there are NOT ENOUGH EVENTS, MISSING DATA, or an UNSUPPORTED DATA SOURCE?
It reuses the service's existing data access (dataset row counts + repository
reads) purely to *count and inspect* - it computes no new analytics and touches
no rendering. The result carries the event counter, five-axis coverage, missing
columns/tags, a data-quality score and a validation report for the UI.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from fap.setpieces.viz_requirements import COVERAGE_AXES

READY = "READY"
NOT_ENOUGH_EVENTS = "NOT_ENOUGH_EVENTS"
MISSING_DATA = "MISSING_DATA"
UNSUPPORTED_DATA_SOURCE = "UNSUPPORTED_DATA_SOURCE"

STATUS_LABEL = {READY: "Ready", NOT_ENOUGH_EVENTS: "Not enough events",
                MISSING_DATA: "Missing data", UNSUPPORTED_DATA_SOURCE: "Unsupported data source"}


@dataclass(slots=True)
class ValidationResult:
    viz_id: str
    status: str
    events_available: int
    events_required: int
    coverage: dict[str, float]           # axis -> 0..1
    coverage_required: dict[str, bool]   # axis -> is it needed by this viz
    tracking_available: bool
    missing_columns: list[str]
    missing_tags: list[str]
    quality: int
    quality_label: str
    reason: str
    guidance: list[str]
    report: dict[str, Any]

    @property
    def progress(self) -> float:
        return min(1.0, self.events_available / self.events_required) if self.events_required else 1.0

    @property
    def can_render(self) -> bool:
        return self.status == READY

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["progress"] = self.progress
        d["can_render"] = self.can_render
        d["status_label"] = STATUS_LABEL.get(self.status, self.status)
        return d


def _frac(part: int, whole: int) -> float:
    return round(part / whole, 3) if whole else 0.0


def coverage_counts(svc: Any, user: Any, filt: Any, workspace_id: str | None) -> dict[str, Any]:
    """Live per-axis counts + fractions over the filtered set pieces (count and
    inspect only). Powers the data-health dashboard, live status and dependency
    trees. Reuses the service's existing reads - no new analytics."""
    sps = svc._filtered(user, filt, workspace_id)
    n = len(sps)
    positions = svc._positions_of(sps) if n else []
    contacts = svc._contacts_of(sps) if n else []
    pos_ids = {p.set_piece_id for p in positions if p.x is not None}
    gk_ids = {p.set_piece_id for p in positions if p.is_gk and p.x is not None}
    con_ids = {c.set_piece_id for c in contacts}
    coord = sum(1 for s in sps if s.end_x is not None and s.end_y is not None)
    outcome = sum(1 for s in sps if s.outcome)
    pens = [s for s in sps if s.type == "penalty"]
    pen_detail = sum(1 for s in pens if (s.document or {}).get("placement")
                     or (s.document or {}).get("gk_dive"))

    def axis(k, whole):
        return {"n": k, "pct": _frac(k, whole)}

    return {
        "events": n,
        "coordinates": axis(coord, n), "outcome": axis(outcome, n),
        "contacts": axis(len(con_ids), n), "positions": axis(len(pos_ids), n),
        "goalkeeper": axis(len(gk_ids), n),
        "penalty": {"n": pen_detail, "pct": _frac(pen_detail, len(pens)) if pens else 0.0,
                    "total": len(pens)},
    }


def _pen_has(sp: Any, field: str) -> bool:
    """Does a penalty carry the field a dataset requires?"""
    if field == "outcome":
        return bool(sp.outcome or sp.goal)
    if field == "taker":
        return bool(sp.taker)
    return bool((sp.document or {}).get(field))


def _quality_label(score: int) -> str:
    if score >= 85:
        return "Excellent"
    if score >= 60:
        return "Good"
    if score >= 40:
        return "Fair"
    return "Insufficient"


def validate(svc: Any, user: Any, viz_id: str, req: dict[str, Any],
             filt: Any, workspace_id: str | None) -> ValidationResult:
    """``req`` is the resolved requirement dict from
    ``viz_requirements.requirements_for``. Everything else is read through the
    service (no new analytics)."""
    kind = req.get("dataset", "")
    min_events = int(req.get("min_events", 1))

    if not req.get("known"):
        return ValidationResult(
            viz_id, UNSUPPORTED_DATA_SOURCE, 0, min_events, {a: 0.0 for a in COVERAGE_AXES},
            {a: False for a in COVERAGE_AXES}, False, [], [], 0, "Insufficient",
            "This visualization has no registered requirement metadata.", [],
            {"dataset": kind, "rows_found": 0, "rows_required": min_events})

    # -- event count -------------------------------------------------------
    # Point maps count renderable rows; aggregated datasets (bars, dive grids,
    # per-entity) bucket into a few rows, so they count the underlying events.
    rows = svc.visual_dataset(user, kind, filt, workspace_id=workspace_id)
    sps = svc._filtered(user, filt, workspace_id)
    n = len(sps)
    count_by = req.get("count_by", "rows")
    if count_by == "set_pieces":
        available = n
    elif count_by == "penalties":
        field = (req.get("required_inputs") or ["placement"])[0]
        available = sum(1 for s in sps if s.type == "penalty" and _pen_has(s, field))
    else:
        available = len(rows)
    positions = svc._positions_of(sps) if n else []
    contacts = svc._contacts_of(sps) if n else []
    pos_ids = {p.set_piece_id for p in positions if p.x is not None and p.y is not None}
    gk_ids = {p.set_piece_id for p in positions if p.is_gk and p.x is not None}
    con_ids = {c.set_piece_id for c in contacts}
    pens = [s for s in sps if s.type == "penalty"]
    pen_detail = sum(1 for s in pens if (s.document or {}).get("placement")
                     or (s.document or {}).get("gk_dive"))
    coverage = {
        "coordinates": _frac(sum(1 for s in sps if s.end_x is not None and s.end_y is not None), n),
        "contacts": _frac(len(con_ids), n),
        "positions": _frac(len(pos_ids), n),
        "goalkeeper": _frac(len(gk_ids), n),
        "penalty": _frac(pen_detail, len(pens)) if pens else 0.0,
    }
    required = {
        "coordinates": not (req["needs_positions"] or req["needs_contacts"] or req["needs_penalty"]),
        "contacts": req["needs_contacts"],
        "positions": req["needs_positions"],
        "goalkeeper": req["needs_goalkeeper"],
        "penalty": req["needs_penalty"],
    }

    # -- missing tags / columns -------------------------------------------
    missing_tags: list[str] = []
    if req["needs_positions"] and coverage["positions"] == 0:
        missing_tags.append("player positions")
    if req["needs_goalkeeper"] and coverage["goalkeeper"] == 0:
        missing_tags.append("goalkeeper position")
    if req["needs_contacts"] and coverage["contacts"] == 0:
        missing_tags.append("contact events")
    if req["needs_penalty"] and coverage["penalty"] == 0 and req["tier"] == "B":
        missing_tags.append("penalty detail")
    missing_columns = list(req["required_inputs"]) if available == 0 else []

    # -- status -----------------------------------------------------------
    if available >= min_events:
        status = READY
    elif available > 0:
        status = NOT_ENOUGH_EVENTS
    elif req["needs_tracking"] and not req["can_tracking"]:
        status = UNSUPPORTED_DATA_SOURCE
    else:
        status = MISSING_DATA

    # -- data quality -----------------------------------------------------
    event_score = min(1.0, available / min_events) if min_events else 1.0
    req_axes = [a for a, need in required.items() if need] or ["coordinates"]
    cov_score = sum(coverage[a] for a in req_axes) / len(req_axes)
    quality = int(round(100 * (0.5 * event_score + 0.5 * cov_score)))

    # -- guidance ---------------------------------------------------------
    if status == READY:
        guidance: list[str] = []
    elif req["can_csv_only"] and available == 0:
        guidance = ["Import an event file (CSV / Excel / JSON) that includes: "
                    + ", ".join(req["required_inputs"]) + ".",
                    "Or add set pieces manually.", "Or generate a demo dataset below."]
    else:
        guidance = list(req["guidance"]) or ["Tag the required data on your set pieces."]
        guidance.append("Or generate a demo dataset below.")

    report = {
        "dataset": req.get("dataset_label", kind),
        "rows_found": available, "rows_required": min_events,
        "missing_columns": missing_columns, "missing_tags": missing_tags,
        "missing_positions": bool(req["needs_positions"] and coverage["positions"] == 0),
        "missing_contacts": bool(req["needs_contacts"] and coverage["contacts"] == 0),
        "missing_goalkeeper": bool(req["needs_goalkeeper"] and coverage["goalkeeper"] == 0),
        "missing_penalty": bool(req["needs_penalty"] and coverage["penalty"] == 0 and req["tier"] == "B"),
        "missing_tracking": "not available (tracking not wired)",
        "suggested_fix": guidance[0] if guidance else "Ready to render.",
    }

    return ValidationResult(
        viz_id=viz_id, status=status, events_available=available, events_required=min_events,
        coverage=coverage, coverage_required=required, tracking_available=False,
        missing_columns=missing_columns, missing_tags=missing_tags,
        quality=quality, quality_label=_quality_label(quality),
        reason=req.get("reason", ""), guidance=guidance, report=report)
