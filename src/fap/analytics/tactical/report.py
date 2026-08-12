"""Professional Opposition Scouting Report (P3).

A deterministic, Streamlit-free ORCHESTRATION layer. It consumes the existing
analytical layers — P0 :class:`InsightReport`, P1 :class:`TacticalProfile`, P2/P2.1
:class:`TacticalEvolution` — and structures them into a coherent scouting
deliverable (executive summary, prioritized takeaways, tactical DNA, vulnerabilities,
evolution, key players and analyst-facing focus points).

It performs NO new analytics, holds NO DataFrames/figures, and invents nothing: every
claim carries the underlying P0 insight ids (and, for multi-match claims, the match
scope), so the UI can open the exact same evidence via the existing evidence pathway.
No LLM — all narrative is template-assembled from measured evidence, so the report is
reproducible, auditable and testable. P2.1 semantics are preserved: an insufficient
match is never read as a value of 0.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from fap.analytics.tactical.model import Confidence, InsightReport
from fap.analytics.tactical.multimatch import EvidenceRef, PatternTrend, TacticalEvolution
from fap.analytics.tactical.profile import CoverageItem, SummaryLine, TacticalProfile, build_profile

_CONF_RANK = {Confidence.HIGH: 0, Confidence.MEDIUM: 1, Confidence.LOW: 2}
_CONF_SCORE = {"High": 3, "Medium": 2, "Low": 1}

# the tactical QUESTION each report section's supporting chart answers (viz_hint reused
# by the UI to open an EXISTING registry visualization — no new chart system)
_SECTION_CHART = {
    "attacking_identity": ("progress", "Where does the opponent attack?"),
    "build_up": ("progress", "How does the opponent build up?"),
    "progression": ("progress", "Where does the opponent progress?"),
    "final_third": ("final third", "How does the opponent enter the final third?"),
    "transitions": ("recovery", "What happens after the opponent recovers the ball?"),
    "recoveries": ("recovery", "Where does the opponent win the ball back?"),
}

# canonical report section order (Tactical DNA block)
_DNA_ORDER = ("attacking_identity", "build_up", "progression", "final_third",
              "transitions", "recoveries")

DEFAULT_SECTIONS = (
    "executive_summary", "key_takeaways", "tactical_dna", "build_up", "progression",
    "final_third", "transitions", "recoveries", "vulnerabilities", "tactical_evolution",
    "key_players", "strengths", "focus_points", "set_pieces", "data_quality",
)


# ================================================================ value objects
@dataclass(frozen=True)
class EvidenceLink:
    """Traceability + interactive 'View evidence'. ``insight_ids`` point at the P0
    insights behind a claim; ``ref`` (optional) is a multi-match evidence reference
    carrying the exact team/player/match scope, so the UI opens the corrected,
    player-scoped evidence pathway without a second viewer."""
    insight_ids: tuple[str, ...] = ()
    match_id: str = ""
    ref: EvidenceRef | None = None

    def to_dict(self) -> dict:
        return {"insight_ids": list(self.insight_ids), "match_id": self.match_id,
                "ref": self.ref.to_dict() if self.ref else None}


@dataclass(frozen=True)
class ReportMetadata:
    title: str = "Opposition Scouting Report"
    opponent: str = ""
    team: str = ""
    competition: str = ""
    match: str = ""
    date: str = ""
    analyst: str = ""
    analysis_window: str = ""
    generated_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Takeaway:
    title: str
    observation: str
    why_it_matters: str
    confidence: str
    evidence: EvidenceLink

    def to_dict(self) -> dict:
        return {"title": self.title, "observation": self.observation,
                "why_it_matters": self.why_it_matters, "confidence": self.confidence,
                "evidence": self.evidence.to_dict()}


@dataclass(frozen=True)
class ReportItem:
    """An observation with (optionally) a separate tactical implication — the two are
    never conflated, matching the P0/P1 evidence discipline."""
    heading: str
    observation: str
    implication: str = ""
    confidence: str = "Low"
    evidence: EvidenceLink = field(default_factory=EvidenceLink)

    def to_dict(self) -> dict:
        return {"heading": self.heading, "observation": self.observation,
                "implication": self.implication, "confidence": self.confidence,
                "evidence": self.evidence.to_dict()}


@dataclass(frozen=True)
class ReportPlayer:
    name: str
    role: str
    metrics: tuple[str, ...]
    confidence: str
    evidence: EvidenceLink

    def to_dict(self) -> dict:
        return {"name": self.name, "role": self.role, "metrics": list(self.metrics),
                "confidence": self.confidence, "evidence": self.evidence.to_dict()}


@dataclass(frozen=True)
class ReportTrend:
    label: str
    category: str
    classification: str
    trend: str
    recurrence: str                 # "4 / 4 observed matches"
    current_display: str            # "58%" or "insufficient"
    baseline_display: str
    delta_pp: float | None
    confidence: str
    evidence: EvidenceLink

    def to_dict(self) -> dict:
        return {"label": self.label, "category": self.category, "classification": self.classification,
                "trend": self.trend, "recurrence": self.recurrence,
                "current_display": self.current_display, "baseline_display": self.baseline_display,
                "delta_pp": self.delta_pp, "confidence": self.confidence,
                "evidence": self.evidence.to_dict()}


@dataclass(frozen=True)
class FocusPoint:
    title: str
    evidence_text: str
    consistency: str
    implication: str
    confidence: str
    evidence: EvidenceLink

    def to_dict(self) -> dict:
        return {"title": self.title, "evidence_text": self.evidence_text,
                "consistency": self.consistency, "implication": self.implication,
                "confidence": self.confidence, "evidence": self.evidence.to_dict()}


@dataclass(frozen=True)
class ReportSection:
    id: str
    title: str
    available: bool = True
    reason: str = ""
    headline: str = ""
    lines: tuple[str, ...] = ()
    chart_hint: str = ""            # existing-registry viz hint for the section's evidence chart
    chart_question: str = ""
    evidence: EvidenceLink = field(default_factory=EvidenceLink)

    def to_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "available": self.available, "reason": self.reason,
                "headline": self.headline, "lines": list(self.lines), "chart_hint": self.chart_hint,
                "chart_question": self.chart_question, "evidence": self.evidence.to_dict()}


@dataclass(frozen=True)
class OppositionReport:
    metadata: ReportMetadata
    subject: str
    overall_confidence: str
    limited_evidence: bool
    executive_summary: tuple[SummaryLine, ...] = ()
    key_takeaways: tuple[Takeaway, ...] = ()
    sections: tuple[ReportSection, ...] = ()          # Tactical DNA block
    strengths: tuple[ReportItem, ...] = ()
    vulnerabilities: tuple[ReportItem, ...] = ()
    key_players: tuple[ReportPlayer, ...] = ()
    evolution: tuple[ReportTrend, ...] = ()
    focus_points: tuple[FocusPoint, ...] = ()
    set_pieces: ReportSection | None = None
    data_quality: tuple[CoverageItem, ...] = ()
    excluded_matches: tuple[tuple[str, str], ...] = ()
    notices: tuple[str, ...] = ()
    included: tuple[str, ...] = ()

    def section(self, sid: str) -> ReportSection | None:
        return next((s for s in self.sections if s.id == sid), None)

    def to_dict(self) -> dict:
        return {
            "metadata": self.metadata.to_dict(), "subject": self.subject,
            "overall_confidence": self.overall_confidence, "limited_evidence": self.limited_evidence,
            "executive_summary": [s.to_dict() for s in self.executive_summary],
            "key_takeaways": [t.to_dict() for t in self.key_takeaways],
            "sections": [s.to_dict() for s in self.sections],
            "strengths": [s.to_dict() for s in self.strengths],
            "vulnerabilities": [v.to_dict() for v in self.vulnerabilities],
            "key_players": [p.to_dict() for p in self.key_players],
            "evolution": [e.to_dict() for e in self.evolution],
            "focus_points": [f.to_dict() for f in self.focus_points],
            "set_pieces": self.set_pieces.to_dict() if self.set_pieces else None,
            "data_quality": [c.to_dict() for c in self.data_quality],
            "excluded_matches": [list(e) for e in self.excluded_matches],
            "notices": list(self.notices), "included": list(self.included),
        }


# ================================================================ builder
class OppositionReportBuilder:
    def __init__(self, metadata: ReportMetadata | None = None,
                 include: tuple[str, ...] | None = None) -> None:
        self.metadata = metadata or ReportMetadata()
        self.include = tuple(include) if include is not None else DEFAULT_SECTIONS

    def build(self, insight_report: InsightReport, profile: TacticalProfile,
              evolution: TacticalEvolution | None, *, setpieces: dict | None = None) -> OppositionReport:
        by_id = {i.id: i for i in insight_report.insights}
        subject = profile.subject or insight_report.subject or "the opponent"
        evo = evolution
        meta = self._filled_metadata(subject)

        sections = self._dna_sections(profile, evo)
        strengths = self._strengths(profile)
        vulns = self._vulnerabilities(profile, by_id)
        players = self._players(profile)
        evo_trends = self._evolution(evo)
        summary = self._executive_summary(profile, evo, players)
        takeaways = self._takeaways(profile, evo, by_id, players)
        focus = self._focus_points(profile, evo, by_id)
        setp = self._set_pieces(setpieces)
        coverage = self._data_quality(profile, setpieces)
        excluded = tuple(evo.excluded) if evo else ()

        return OppositionReport(
            metadata=meta, subject=subject,
            overall_confidence=profile.confidence.value, limited_evidence=profile.limited_evidence,
            executive_summary=summary, key_takeaways=takeaways, sections=sections,
            strengths=strengths, vulnerabilities=vulns, key_players=players, evolution=evo_trends,
            focus_points=focus, set_pieces=setp, data_quality=coverage, excluded_matches=excluded,
            notices=profile.notices, included=self.include)

    # ---- metadata -------------------------------------------------------------
    def _filled_metadata(self, subject: str) -> ReportMetadata:
        import datetime as _dt
        m = self.metadata
        gen = m.generated_at or _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        opp = m.opponent or subject
        return ReportMetadata(title=m.title, opponent=opp, team=m.team, competition=m.competition,
                              match=m.match, date=m.date, analyst=m.analyst,
                              analysis_window=m.analysis_window, generated_at=gen)

    # ---- Tactical DNA sections (consume P1 directly) --------------------------
    def _dna_sections(self, profile: TacticalProfile, evo) -> tuple[ReportSection, ...]:
        out: list[ReportSection] = []
        for sid in _DNA_ORDER:
            ps = profile.section(sid)
            if ps is None:
                continue
            hint, question = _SECTION_CHART.get(sid, ("", ""))
            lines = list(ps.lines)
            if sid == "progression" and evo is not None:      # enrich with multi-match consistency
                lines += self._progression_consistency_lines(evo)
            out.append(ReportSection(
                id=sid, title=ps.title, available=ps.available, reason=ps.reason,
                headline=ps.headline, lines=tuple(lines),
                chart_hint=hint if ps.available else "", chart_question=question if ps.available else "",
                evidence=EvidenceLink(insight_ids=tuple(ps.insight_ids))))
        return tuple(out)

    @staticmethod
    def _progression_consistency_lines(evo) -> list[str]:
        pats = [p for p in evo.patterns if p.category == "progression"
                and p.insight_id.endswith("_dominance")]
        out: list[str] = []
        for p in sorted(pats, key=lambda x: -(x.present_count)):
            out.append(f"Observed in {p.recurrence} observed matches ({p.classification}).")
            if p.delta is not None and p.current_share is not None and p.baseline_share is not None:
                out.append(f"Current {p.current_share * 100:.0f}% vs baseline "
                           f"{p.baseline_share * 100:.0f}% ({p.delta_pp:+g} pp).")
            break                                             # only the leading progression pattern
        return out

    # ---- strengths / vulnerabilities / players (reuse P1) ---------------------
    @staticmethod
    def _strengths(profile: TacticalProfile) -> tuple[ReportItem, ...]:
        return tuple(ReportItem(heading=s.text, observation=s.detail, confidence=s.confidence.value,
                                evidence=EvidenceLink(insight_ids=tuple(s.insight_ids)))
                     for s in profile.key_strengths)

    @staticmethod
    def _vulnerabilities(profile: TacticalProfile, by_id: dict) -> tuple[ReportItem, ...]:
        out: list[ReportItem] = []
        for v in profile.vulnerabilities:
            ins = by_id.get(v.primary_insight_id) if v.primary_insight_id else None
            # keep OBSERVATION and TACTICAL IMPLICATION separate (from the P0 insight when present)
            observation = ins.observation if ins else v.detail
            implication = ins.interpretation if ins else ""
            out.append(ReportItem(heading=v.text, observation=observation, implication=implication,
                                  confidence=v.confidence.value,
                                  evidence=EvidenceLink(insight_ids=tuple(v.insight_ids))))
        return tuple(out)

    @staticmethod
    def _players(profile: TacticalProfile) -> tuple[ReportPlayer, ...]:
        return tuple(ReportPlayer(name=p.name, role=p.role, metrics=tuple(p.metrics[:3]),
                                  confidence=p.confidence.value,
                                  evidence=EvidenceLink(insight_ids=tuple(p.insight_ids)))
                     for p in profile.key_players[:6])

    # ---- tactical evolution (consume P2/P2.1; never treat insufficient as 0) ---
    def _evolution(self, evo) -> tuple[ReportTrend, ...]:
        if evo is None:
            return ()
        # prioritize: consistent + changing + notable current-vs-baseline, deduped
        picked: dict[str, PatternTrend] = {}
        for p in (*evo.consistent(), *evo.changing(), *evo.emerging(), *evo.current_vs_baseline()):
            picked.setdefault(p.insight_id, p)
        out: list[ReportTrend] = []
        for p in list(picked.values())[:10]:
            out.append(ReportTrend(
                label=p.label, category=p.category, classification=p.classification, trend=p.trend,
                recurrence=p.recurrence, current_display=_share_display(p.current_status, p.current_share),
                baseline_display=_baseline_display(p.baseline_status, p.baseline_share),
                delta_pp=p.delta_pp, confidence=p.confidence,
                evidence=EvidenceLink(insight_ids=(p.insight_id,), match_id=p.evidence[0].match_id
                                      if p.evidence else "",
                                      ref=p.evidence[0] if p.evidence else None)))
        return tuple(out)

    # ---- executive summary (the most important page) --------------------------
    def _executive_summary(self, profile: TacticalProfile, evo, players) -> tuple[SummaryLine, ...]:
        lines: list[SummaryLine] = []
        ai = profile.section("attacking_identity")
        if ai and ai.available:
            lines.append(SummaryLine("Primary attacking identity", ai.headline))
        if players:
            lines.append(SummaryLine("Key progression player",
                                     f"{players[0].name} — {players[0].role.split(' · ')[0].lower()}."))
        if evo is not None:
            cons = evo.consistent()
            if cons:
                c = cons[0]
                lines.append(SummaryLine("Recurring pattern",
                                         f"{c.label} appears in {c.recurrence} observed matches."))
            cvb = evo.current_vs_baseline()
            if cvb and cvb[0].delta_pp is not None:
                d = cvb[0]
                lines.append(SummaryLine("Match-specific change",
                                         f"Current match shows {d.delta_pp:+g} pp {d.label.lower()} "
                                         f"versus the selected baseline."))
        if profile.vulnerabilities:
            v = profile.vulnerabilities[0]
            lines.append(SummaryLine("Important vulnerability", v.detail or v.text))
        if not lines:
            lines.append(SummaryLine("Overview",
                                     f"Evidence on {profile.subject} is limited in the current selection."))
        return tuple(lines)

    # ---- prioritized key takeaways -------------------------------------------
    def _takeaways(self, profile: TacticalProfile, evo, by_id: dict, players) -> tuple[Takeaway, ...]:
        cands: list[tuple[float, Takeaway]] = []
        consistent_ids = {p.insight_id for p in (evo.consistent() if evo else [])}

        for s in profile.key_strengths:                       # already P0-prioritized
            ins = by_id.get(s.primary_insight_id)
            base = _CONF_SCORE.get(s.confidence.value, 1) + (2 if s.primary_insight_id in consistent_ids else 0)
            why = (ins.interpretation if ins else "")
            cands.append((base + 3, Takeaway(
                title=s.text, observation=s.detail, why_it_matters=why or "A defining opponent tendency.",
                confidence=s.confidence.value, evidence=EvidenceLink(insight_ids=tuple(s.insight_ids)))))

        for v in profile.vulnerabilities:
            ins = by_id.get(v.primary_insight_id) if v.primary_insight_id else None
            cands.append((_CONF_SCORE.get(v.confidence.value, 1) + 2, Takeaway(
                title=v.text, observation=(ins.observation if ins else v.detail),
                why_it_matters=(ins.interpretation if ins else "A potential opportunity to exploit."),
                confidence=v.confidence.value, evidence=EvidenceLink(insight_ids=tuple(v.insight_ids)))))

        if evo is not None:
            for p in evo.current_vs_baseline()[:1]:
                if p.delta_pp is not None:
                    cands.append((3.5, Takeaway(
                        title=f"Match-specific: {p.label.lower()}",
                        observation=f"{p.current_share * 100:.0f}% vs baseline "
                                    f"{p.baseline_share * 100:.0f}% ({p.delta_pp:+g} pp).",
                        why_it_matters="This match differs from the opponent's baseline tendency.",
                        confidence=p.confidence,
                        evidence=EvidenceLink(insight_ids=(p.insight_id,), match_id=p.evidence[0].match_id
                                              if p.evidence else "",
                                              ref=p.evidence[0] if p.evidence else None))))

        cands.sort(key=lambda t: -t[0])
        seen: set[str] = set()
        out: list[Takeaway] = []
        for _score, tk in cands:
            key = tk.evidence.insight_ids[0] if tk.evidence.insight_ids else tk.title
            if key in seen:
                continue
            seen.add(key)
            out.append(tk)
            if len(out) >= 6:
                break
        return tuple(out)

    # ---- analyst-facing focus points (NOT instructions) -----------------------
    def _focus_points(self, profile: TacticalProfile, evo, by_id: dict) -> tuple[FocusPoint, ...]:
        out: list[FocusPoint] = []
        prog = _first(profile, "progression")
        if prog is not None and prog.available:
            side = _side_from_headline(prog.headline)
            cons = ""
            ev_link = EvidenceLink(insight_ids=tuple(prog.insight_ids))
            if evo is not None:
                p = next((x for x in evo.consistent() if x.category == "progression"), None)
                if p is not None:
                    cons = f"{p.recurrence} observed matches ({p.classification})."
            out.append(FocusPoint(
                title=f"Protect the {side} progression corridor" if side else "Contest the opponent's "
                      "main progression route",
                evidence_text=prog.headline, consistency=cons,
                implication="Their build-up is concentrated here.",
                confidence=profile.confidence.value, evidence=ev_link))

        for v in profile.vulnerabilities[:2]:
            ins = by_id.get(v.primary_insight_id) if v.primary_insight_id else None
            out.append(FocusPoint(
                title=_focus_title_for_vulnerability(v.primary_insight_id or "", v.text),
                evidence_text=(ins.observation if ins else v.detail),
                consistency="", implication=(ins.interpretation if ins else "Potential pressure opportunity."),
                confidence=v.confidence.value,
                evidence=EvidenceLink(insight_ids=tuple(v.insight_ids))))
        return tuple(out[:4])

    # ---- set pieces (integrate existing analysis if supplied; else honest) -----
    @staticmethod
    def _set_pieces(setpieces: dict | None) -> ReportSection:
        if not setpieces:
            return ReportSection("set_pieces", "Set Pieces", available=False,
                                 reason="No set-piece analysis available for this selection.")
        lines = tuple(str(x) for x in setpieces.get("lines", []))
        return ReportSection("set_pieces", "Set Pieces", available=True,
                             headline=str(setpieces.get("headline", "")), lines=lines)

    # ---- data quality (reuse P1 coverage + P2 excluded matches) ---------------
    @staticmethod
    def _data_quality(profile: TacticalProfile, setpieces: dict | None) -> tuple[CoverageItem, ...]:
        items = list(profile.coverage)
        items.append(CoverageItem("Set-piece data", "ok" if setpieces else "missing"))
        return tuple(items)


# ---- helpers ----------------------------------------------------------------
def _first(profile: TacticalProfile, sid: str):
    return profile.section(sid)


def _side_from_headline(headline: str) -> str:
    low = (headline or "").lower()
    for side in ("left", "central", "right"):
        if side in low:
            return side
    return ""


def _share_display(status: str, share) -> str:
    if status in ("Observed", "Absent") and share is not None:
        return f"{share * 100:.0f}%"
    return status.lower()                     # insufficient / unavailable


def _baseline_display(status: str, share) -> str:
    if status == "Observed" and share is not None:
        return f"{share * 100:.0f}%"
    return "insufficient evidence"


def _focus_title_for_vulnerability(insight_id: str, fallback: str) -> str:
    if insight_id == "vulnerability.turnover_zone":
        return "Monitor the opponent's main possession-loss zone"
    if insight_id == "vulnerability.route_failure":
        return "Contest the opponent's high-loss corridor"
    if insight_id == "vulnerability.final_third_inefficiency":
        return "Force the opponent's final-third play backwards"
    if insight_id.startswith("progression."):
        return "Exploit the opponent's one-sided progression"
    return fallback


# ================================================================ convenience
def build_report(insight_report: InsightReport, profile: TacticalProfile,
                 evolution: TacticalEvolution | None = None, *, metadata: ReportMetadata | None = None,
                 include: tuple[str, ...] | None = None, setpieces: dict | None = None) -> OppositionReport:
    return OppositionReportBuilder(metadata, include).build(insight_report, profile, evolution,
                                                            setpieces=setpieces)


def build_report_from_frame(frame, *, metadata: ReportMetadata | None = None,
                            include: tuple[str, ...] | None = None, current_match: str | None = None,
                            multi_match: bool = True, setpieces: dict | None = None,
                            thresholds=None) -> OppositionReport:
    """Convenience orchestration: frame -> P0 -> P1 -> P2 -> P3, one pass each. Each
    layer stays independently testable; this only wires them for callers who have a
    frame rather than pre-built analysis objects."""
    from fap.analytics.tactical.engine import TacticalInsightEngine
    from fap.analytics.tactical.multimatch import build_evolution

    rep = TacticalInsightEngine(thresholds).analyze(frame)
    profile = build_profile(rep)
    evo = None
    if multi_match:
        try:
            evo = build_evolution(frame, current_match=current_match, thresholds=thresholds)
        except Exception:
            evo = None
    return build_report(rep, profile, evo, metadata=metadata, include=include, setpieces=setpieces)
