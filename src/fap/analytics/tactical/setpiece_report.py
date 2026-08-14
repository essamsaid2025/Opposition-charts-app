"""Set Piece Scouting Report (P3.1 refactor).

A SEPARATE, dedicated report — independent of the Open Play ``OppositionReport``.
It reuses the EXISTING set-piece analysis (``fap.setpieces.analytics`` over
``SetPiece`` records produced by ``SetPieceService``); it performs NO new set-piece
calculations. Its evidence is set-piece record ids / analysis references — never P0
insight ids, so the two evidence systems stay cleanly separate.

    SetPieceService.search(...) -> list[SetPiece]
            -> build_setpiece_report(...)  (reuses fap.setpieces.analytics)
            -> SetPieceReport  -> to_setpiece_document -> existing exporters
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from fap.analytics.tactical.profile import CoverageItem

# evidence-strength thresholds (transparent; nothing invented below these)
_STRONG_SIDE = 0.60
_GOOD_SUCCESS = 45.0
_WEAK_SUCCESS = 20.0
_HIGH_CONCEDE_FIRST_CONTACT = 55.0

DEFAULT_SETPIECE_SECTIONS = (
    "overview", "attacking_corners", "defensive_corners", "attacking_free_kicks",
    "defensive_free_kicks", "key_takers", "routines", "strengths", "weaknesses",
    "match_prep", "data_quality",
)


# ================================================================ value objects
@dataclass(frozen=True)
class SetPieceEvidence:
    """Traceable set-piece evidence — real record ids + optional analysis/viz ids.
    Deliberately distinct from the Open Play ``EvidenceLink`` (no P0 insight ids)."""
    record_ids: tuple[str, ...] = ()
    viz_id: str = ""
    note: str = ""

    def to_dict(self) -> dict:
        return {"record_ids": list(self.record_ids), "viz_id": self.viz_id, "note": self.note}


@dataclass(frozen=True)
class SetPieceItem:
    heading: str
    observation: str
    implication: str = ""
    evidence: SetPieceEvidence = field(default_factory=SetPieceEvidence)

    def to_dict(self) -> dict:
        return {"heading": self.heading, "observation": self.observation,
                "implication": self.implication, "evidence": self.evidence.to_dict()}


@dataclass(frozen=True)
class SetPieceSection:
    id: str
    title: str
    available: bool = True
    reason: str = ""
    headline: str = ""
    lines: tuple[str, ...] = ()
    table_columns: tuple[str, ...] = ()
    table_rows: tuple[tuple[str, ...], ...] = ()
    evidence: SetPieceEvidence = field(default_factory=SetPieceEvidence)

    def to_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "available": self.available, "reason": self.reason,
                "headline": self.headline, "lines": list(self.lines),
                "table_columns": list(self.table_columns),
                "table_rows": [list(r) for r in self.table_rows], "evidence": self.evidence.to_dict()}


@dataclass(frozen=True)
class SetPieceReportMetadata:
    title: str = "Set Piece Scouting Report"
    opponent: str = ""
    team: str = ""
    competition: str = ""
    match: str = ""
    analyst: str = ""
    generated_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SetPieceReport:
    metadata: SetPieceReportMetadata
    subject: str
    available: bool
    sections: tuple[SetPieceSection, ...] = ()
    key_takers: tuple[str, ...] = ()
    routines: tuple[str, ...] = ()
    strengths: tuple[SetPieceItem, ...] = ()
    weaknesses: tuple[SetPieceItem, ...] = ()
    match_prep: tuple[SetPieceItem, ...] = ()
    data_quality: tuple[CoverageItem, ...] = ()
    notices: tuple[str, ...] = ()
    included: tuple[str, ...] = ()

    def section(self, sid: str) -> SetPieceSection | None:
        return next((s for s in self.sections if s.id == sid), None)

    def to_dict(self) -> dict:
        return {
            "metadata": self.metadata.to_dict(), "subject": self.subject, "available": self.available,
            "sections": [s.to_dict() for s in self.sections],
            "key_takers": list(self.key_takers), "routines": list(self.routines),
            "strengths": [s.to_dict() for s in self.strengths],
            "weaknesses": [w.to_dict() for w in self.weaknesses],
            "match_prep": [m.to_dict() for m in self.match_prep],
            "data_quality": [c.to_dict() for c in self.data_quality],
            "notices": list(self.notices), "included": list(self.included),
        }


# ================================================================ builder helpers
def _get(group, attr):
    return [getattr(s, attr, "") for s in group]


def _top(dist: dict) -> tuple[str, int]:
    dist = {k: v for k, v in (dist or {}).items() if k and k != "unknown"}
    if not dist:
        return "", 0
    k = max(dist, key=dist.get)
    return k, dist[k]


def _ids(group) -> tuple[str, ...]:
    return tuple(str(getattr(s, "id", "")) for s in group[:20] if getattr(s, "id", ""))


def _takers(group) -> list[tuple[str, int]]:
    from collections import Counter
    return Counter(t for t in _get(group, "taker") if t).most_common()


def _frac_filled(group, attr) -> float:
    if not group:
        return 0.0
    return sum(1 for v in _get(group, attr) if v not in ("", None)) / len(group)


def _category_section(sid: str, title: str, group: list, *, defensive: bool) -> SetPieceSection:
    if not group:
        return SetPieceSection(sid, title, available=False, reason=f"No {title.lower()} data available.")
    from fap.setpieces import analytics as A
    ov, dr, dl = A.overview(group), A.derived_rates(group), A.delivery_breakdown(group)
    ob = A.outcome_breakdown(group)
    verb = "faced" if defensive else "taken"
    lines = [f"{ov['total']} {verb}; {ov['shots']} shots, {ov['goals']} goals "
             f"({dr['success_rate']:.0f}% {'conceded initiative' if defensive else 'success'})."]
    side, sc = _top(dl.get("side", {}))
    if side:
        lines.append(f"Delivery {'they favour' if defensive else 'preference'}: {side} ({sc}).")
    dtype, dc = _top(dl.get("delivery_type", {}))
    if dtype:
        lines.append(f"Delivery type: {dtype} most common ({dc}).")
    height, hc = _top(dl.get("height", {}))
    if height:
        lines.append(f"Typical height: {height}.")
    if defensive:
        fc = ov.get("first_contact_pct") or 0
        lines.append(f"Opponent (attacking side) wins first contact on {fc:.0f}% of these.")
    else:
        tk = _takers(group)
        if tk:
            lines.append("Takers: " + ", ".join(f"{n} ({c})" for n, c in tk[:3]) + ".")
    top_out, oc = _top(ob)
    if top_out:
        lines.append(f"Most common outcome: {top_out} ({oc}).")
    return SetPieceSection(sid, title, available=True, headline=f"{ov['total']} {title.lower()}",
                           lines=tuple(lines), evidence=SetPieceEvidence(record_ids=_ids(group)))


# ================================================================ builder
def build_setpiece_report(sps: list, *, metadata: SetPieceReportMetadata | None = None,
                          include: tuple[str, ...] | None = None,
                          opponent: str | None = None) -> SetPieceReport:
    """Build the set-piece report from ``SetPiece`` records. Reuses
    ``fap.setpieces.analytics`` only. No data -> an honest 'unavailable' report."""
    import datetime as _dt
    from fap.setpieces import analytics as A

    inc = tuple(include) if include is not None else DEFAULT_SETPIECE_SECTIONS
    meta_in = metadata or SetPieceReportMetadata()
    subject = opponent or meta_in.opponent or (next((getattr(s, "opponent", "") or getattr(s, "team", "")
                                                     for s in sps), "") if sps else "") or "the opponent"
    meta = SetPieceReportMetadata(
        title=meta_in.title, opponent=meta_in.opponent or subject, team=meta_in.team,
        competition=meta_in.competition, match=meta_in.match, analyst=meta_in.analyst,
        generated_at=meta_in.generated_at or _dt.datetime.now().strftime("%Y-%m-%d %H:%M"))

    if not sps:
        return SetPieceReport(metadata=meta, subject=subject, available=False,
                              notices=("Set-piece analysis unavailable — no set-piece data for this "
                                       "opponent/selection.",), included=inc)

    def sub(phase, sp_type):
        return [s for s in sps if getattr(s, "phase", "") == phase and getattr(s, "type", "") == sp_type]

    att_c, def_c = sub("offensive", "corner"), sub("defensive", "corner")
    att_fk, def_fk = sub("offensive", "free_kick"), sub("defensive", "free_kick")
    offensive = [s for s in sps if getattr(s, "phase", "") == "offensive"]
    defensive = [s for s in sps if getattr(s, "phase", "") == "defensive"]

    sections: list[SetPieceSection] = []
    # ---- overview ----
    ov_lines = [f"{len(offensive)} attacking set pieces, {len(defensive)} defensive set pieces "
                f"({len(sps)} total).",
                f"Corners: {len(att_c)} attacking / {len(def_c)} defensive. "
                f"Free kicks: {len(att_fk)} attacking / {len(def_fk)} defensive."]
    sections.append(SetPieceSection("overview", "Overview", available=True,
                                    headline=f"{len(sps)} set pieces analysed", lines=tuple(ov_lines),
                                    evidence=SetPieceEvidence(record_ids=_ids(sps))))
    sections.append(_category_section("attacking_corners", "Attacking Corners", att_c, defensive=False))
    sections.append(_category_section("defensive_corners", "Defensive Corners", def_c, defensive=True))
    sections.append(_category_section("attacking_free_kicks", "Attacking Free Kicks", att_fk,
                                      defensive=False))
    sections.append(_category_section("defensive_free_kicks", "Defensive Free Kicks", def_fk,
                                      defensive=True))

    key_takers = tuple(f"{n} ({c})" for n, c in _takers(offensive)[:5])
    from collections import Counter
    routine_counts = Counter(r for r in _get(offensive, "routine") if r)
    routines = tuple(f"{r} ({c})" for r, c in routine_counts.most_common(5))

    strengths = _strengths(att_c, att_fk)
    weaknesses = _weaknesses(def_c, att_c)
    prep = _match_prep(att_c, def_c, offensive)
    coverage = _coverage(sps, offensive, defensive)

    return SetPieceReport(metadata=meta, subject=subject, available=True, sections=tuple(sections),
                          key_takers=key_takers, routines=routines, strengths=strengths,
                          weaknesses=weaknesses, match_prep=prep, data_quality=coverage,
                          notices=(), included=inc)


def _strengths(att_c: list, att_fk: list) -> tuple[SetPieceItem, ...]:
    from fap.setpieces import analytics as A
    out: list[SetPieceItem] = []
    if att_c:
        dr = A.derived_rates(att_c)
        if dr["success_rate"] >= _GOOD_SUCCESS:
            out.append(SetPieceItem(
                heading="Threatening attacking corners",
                observation=f"{dr['success_rate']:.0f}% of attacking corners create a shot/goal or retain "
                            f"possession ({A.overview(att_c)['shots']} shots).",
                evidence=SetPieceEvidence(record_ids=_ids(att_c))))
        side, sc = _top(A.delivery_breakdown(att_c).get("side", {}))
        if side and sc / len(att_c) >= _STRONG_SIDE:
            out.append(SetPieceItem(
                heading=f"Consistent {side}-side corner delivery",
                observation=f"{sc} of {len(att_c)} attacking corners are delivered from the {side}.",
                evidence=SetPieceEvidence(record_ids=_ids(att_c))))
    return tuple(out)


def _weaknesses(def_c: list, att_c: list) -> tuple[SetPieceItem, ...]:
    from fap.setpieces import analytics as A
    out: list[SetPieceItem] = []
    if def_c:
        ov = A.overview(def_c)
        fc = ov.get("first_contact_pct") or 0
        if fc >= _HIGH_CONCEDE_FIRST_CONTACT:
            out.append(SetPieceItem(
                heading="Concede first contact on defensive corners",
                observation=f"The attacking side wins first contact on {fc:.0f}% of the {ov['total']} "
                            f"defensive corners faced.",
                implication="This may be a set-piece opportunity to target.",
                evidence=SetPieceEvidence(record_ids=_ids(def_c))))
    if att_c:
        dr = A.derived_rates(att_c)
        if dr["success_rate"] <= _WEAK_SUCCESS:
            out.append(SetPieceItem(
                heading="Low attacking-corner threat",
                observation=f"Only {dr['success_rate']:.0f}% of attacking corners produce a shot/goal or "
                            f"retention.",
                evidence=SetPieceEvidence(record_ids=_ids(att_c))))
    return tuple(out)


def _match_prep(att_c: list, def_c: list, offensive: list) -> tuple[SetPieceItem, ...]:
    from fap.setpieces import analytics as A
    out: list[SetPieceItem] = []
    if att_c:
        side, _ = _top(A.delivery_breakdown(att_c).get("side", {}))
        dtype, _ = _top(A.delivery_breakdown(att_c).get("delivery_type", {}))
        takers = _takers(att_c)
        detail = f"{side} " if side else ""
        detail += f"{dtype} " if dtype else ""
        taker_txt = f" to {takers[0][0]}" if takers else ""
        out.append(SetPieceItem(
            heading="Prepare for their attacking corners",
            observation=f"They favour {detail}corner deliveries{taker_txt}.",
            evidence=SetPieceEvidence(record_ids=_ids(att_c))))
    if def_c:
        ov = A.overview(def_c)
        if (ov.get("first_contact_pct") or 0) >= _HIGH_CONCEDE_FIRST_CONTACT:
            out.append(SetPieceItem(
                heading="Target their defensive-corner first contact",
                observation="They concede first contact on defensive corners more often than not.",
                evidence=SetPieceEvidence(record_ids=_ids(def_c))))
    return tuple(out[:4])


def _coverage(sps: list, offensive: list, defensive: list):
    def st(frac: float) -> str:
        return "ok" if frac >= 0.6 else ("limited" if frac > 0 else "missing")
    return (
        CoverageItem("Set-piece events", "ok" if sps else "missing"),
        CoverageItem("Attacking set pieces", "ok" if offensive else "missing"),
        CoverageItem("Defensive set pieces", "ok" if defensive else "missing"),
        CoverageItem("Delivery detail", st(_frac_filled(sps, "delivery_type"))),
        CoverageItem("Outcomes", st(_frac_filled(sps, "outcome"))),
        CoverageItem("Takers", st(_frac_filled(sps, "taker"))),
        CoverageItem("Routines", st(_frac_filled(sps, "routine"))),
    )


def build_setpiece_report_from_service(service, user, *, opponent: str | None = None, filt=None,
                                       metadata: SetPieceReportMetadata | None = None,
                                       include: tuple[str, ...] | None = None) -> SetPieceReport:
    """Fetch the opponent's set pieces via the EXISTING service and build the report.
    On failure/no data, returns an honest 'unavailable' report (never fabricated)."""
    try:
        sps = list(service.search(user, filters=filt))
    except Exception:
        sps = []
    if opponent and sps:
        low = str(opponent).strip().lower()
        scoped = [s for s in sps if str(getattr(s, "opponent", "")).strip().lower() == low
                  or str(getattr(s, "team", "")).strip().lower() == low]
        sps = scoped or sps
    return build_setpiece_report(sps, metadata=metadata, include=include, opponent=opponent)
