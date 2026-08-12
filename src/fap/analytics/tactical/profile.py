"""Opponent Tactical DNA / Tactical Profile (P1).

A deterministic, Streamlit-free orchestration layer that turns the P0
:class:`InsightReport` into a coherent Opponent Tactical Profile. P1 is a
*consumer* of P0 — it re-uses P0's insights, confidence, thresholds and
data-quality/coverage; it performs NO new event analytics and scans no
DataFrame. Every profile statement traces back to the underlying P0 insight ids,
so nothing is claimed that P0 did not measure.

No LLM, no generative text: the summary is assembled from structured rules and
templates, so it is reproducible, auditable and testable.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from fap.analytics.tactical.model import (
    Confidence, Insight, InsightCategory, InsightReport, Priority,
)
from fap.analytics.tactical.thresholds import DEFAULT_THRESHOLDS

_PRIORITY_RANK = {Priority.HIGH: 0, Priority.MEDIUM: 1, Priority.LOW: 2}
_CONFIDENCE_RANK = {Confidence.HIGH: 0, Confidence.MEDIUM: 1, Confidence.LOW: 2}

# a side is "unusually low" (a genuine, exploitable one-sidedness) below this share
_ONE_SIDED_LANE_SHARE = 0.15
_MAX_STRENGTHS = 5
_MIN_STRENGTHS_STRONG = 1


# ================================================================ value objects
@dataclass(frozen=True)
class ProfileSection:
    id: str
    title: str
    headline: str
    lines: tuple[str, ...] = ()
    insight_ids: tuple[str, ...] = ()
    primary_insight_id: str | None = None   # drives the section's "View evidence"
    available: bool = True
    reason: str = ""                         # why unavailable (when available is False)

    def to_dict(self) -> dict:
        return asdict(self) | {"insight_ids": list(self.insight_ids)}


@dataclass(frozen=True)
class KeyPlayer:
    name: str
    role: str
    metrics: tuple[str, ...] = ()
    confidence: Confidence = Confidence.LOW
    insight_ids: tuple[str, ...] = ()
    primary_insight_id: str | None = None

    def to_dict(self) -> dict:
        return {"name": self.name, "role": self.role, "metrics": list(self.metrics),
                "confidence": self.confidence.value, "insight_ids": list(self.insight_ids),
                "primary_insight_id": self.primary_insight_id}


@dataclass(frozen=True)
class ProfileItem:
    """A strength or vulnerability, always evidence-backed."""
    text: str
    detail: str = ""
    confidence: Confidence = Confidence.LOW
    insight_ids: tuple[str, ...] = ()
    primary_insight_id: str | None = None

    def to_dict(self) -> dict:
        return {"text": self.text, "detail": self.detail, "confidence": self.confidence.value,
                "insight_ids": list(self.insight_ids), "primary_insight_id": self.primary_insight_id}


@dataclass(frozen=True)
class SummaryLine:
    heading: str
    text: str

    def to_dict(self) -> dict:
        return {"heading": self.heading, "text": self.text}


@dataclass(frozen=True)
class CoverageItem:
    label: str
    status: str                              # "ok" | "limited" | "missing"

    def to_dict(self) -> dict:
        return {"label": self.label, "status": self.status}


@dataclass(frozen=True)
class TacticalProfile:
    subject: str
    summary: tuple[SummaryLine, ...] = ()
    sections: tuple[ProfileSection, ...] = ()
    key_players: tuple[KeyPlayer, ...] = ()
    key_strengths: tuple[ProfileItem, ...] = ()
    vulnerabilities: tuple[ProfileItem, ...] = ()
    confidence: Confidence = Confidence.LOW
    confidence_label: str = "Limited evidence"
    limited_evidence: bool = True
    data_quality: float = 0.0
    coverage: tuple[CoverageItem, ...] = ()
    n_events: int = 0
    insights_used: int = 0
    notices: tuple[str, ...] = ()

    def section(self, sid: str) -> ProfileSection | None:
        return next((s for s in self.sections if s.id == sid), None)

    def to_dict(self) -> dict:
        return {
            "subject": self.subject,
            "summary": [s.to_dict() for s in self.summary],
            "sections": [s.to_dict() for s in self.sections],
            "key_players": [p.to_dict() for p in self.key_players],
            "key_strengths": [s.to_dict() for s in self.key_strengths],
            "vulnerabilities": [v.to_dict() for v in self.vulnerabilities],
            "confidence": self.confidence.value,
            "confidence_label": self.confidence_label,
            "limited_evidence": self.limited_evidence,
            "data_quality": self.data_quality,
            "coverage": [c.to_dict() for c in self.coverage],
            "n_events": self.n_events,
            "insights_used": self.insights_used,
            "notices": list(self.notices),
        }


# ================================================================ builder
class TacticalProfileBuilder:
    """Assembles a :class:`TacticalProfile` from a P0 :class:`InsightReport`."""

    def __init__(self, min_quality: float | None = None) -> None:
        self.min_quality = DEFAULT_THRESHOLDS.min_quality if min_quality is None else min_quality

    def build(self, report: InsightReport) -> TacticalProfile:
        ins = {i.id: i for i in report.insights}
        subject = report.subject or "the selected events"

        sections = (
            self._attacking_identity(ins, subject),
            self._build_up(ins, subject),
            self._progression(ins, subject),
            self._final_third(ins, subject),
            self._transitions(report, subject),
            self._recoveries(ins, subject, bool((report.coverage or {}).get("recovery_events"))),
        )
        key_players = self._key_players(ins)
        strengths = self._strengths(report)
        vulns = self._vulnerabilities(report, ins, subject)
        summary = self._summary(sections, key_players, subject)

        referenced: set[str] = set()
        for s in sections:
            referenced.update(s.insight_ids)
        for p in key_players:
            referenced.update(p.insight_ids)
        for it in (*strengths, *vulns):
            referenced.update(it.insight_ids)

        confidence, label, limited = self._confidence(report)
        return TacticalProfile(
            subject=subject, summary=summary, sections=sections, key_players=key_players,
            key_strengths=strengths, vulnerabilities=vulns,
            confidence=confidence, confidence_label=label, limited_evidence=limited,
            data_quality=report.quality, coverage=self._coverage(report),
            n_events=report.n_events, insights_used=len(referenced), notices=report.notices)

    # ---- helpers --------------------------------------------------------------
    @staticmethod
    def _first(ins: dict, *ids: str) -> Insight | None:
        for i in ids:
            if i in ins:
                return ins[i]
        return None

    @staticmethod
    def _lane_ranking(insight: Insight) -> list[tuple[str, float]]:
        """Read the lane shares P0 already put in the insight's evidence (labels
        ending in 'Lane', with the share in Evidence.raw) — consuming P0 evidence,
        not recomputing it."""
        lanes = [(e.label, float(e.raw)) for e in insight.evidence
                 if e.label.endswith("Lane") and e.raw is not None]
        return sorted(lanes, key=lambda kv: kv[1], reverse=True)

    # ---- sections -------------------------------------------------------------
    def _attacking_identity(self, ins: dict, subject: str) -> ProfileSection:
        prog = self._first(ins, "progression.left_dominance", "progression.right_dominance",
                           "progression.central_dominance")
        corridor = ins.get("progression.dominant_corridor")
        ft_side = ins.get("final_third.entry_concentration")
        ft_corr = ins.get("final_third.preferred_corridor")
        box = ins.get("final_third.box_entry_concentration")
        contributors = [x for x in (prog, corridor, ft_side, ft_corr, box) if x]
        if not contributors:
            return ProfileSection("attacking_identity", "Attacking Identity", "", available=False,
                                  reason="Not enough attacking evidence in the current selection.")
        sides = [x.meta.get("side") for x in (prog, ft_side, box) if x and x.meta.get("side")]
        if sides and all(s == sides[0] for s in sides):
            headline = (f"{subject} shows a strong {sides[0]}-sided attacking identity: progression and "
                        f"final-third play are concentrated through the {sides[0]} corridor.")
        elif corridor and corridor.meta.get("channel"):
            headline = f"{subject} concentrates attacks through the {corridor.meta['channel'].lower()}."
        elif prog and prog.meta.get("side"):
            headline = f"{subject} favours {prog.meta['side']}-sided progression into the final third."
        else:
            headline = f"{subject}'s attacking play is spread rather than strongly one-sided."
        return ProfileSection(
            "attacking_identity", "Attacking Identity", headline,
            lines=tuple(c.short_explanation for c in contributors),
            insight_ids=tuple(c.id for c in contributors),
            primary_insight_id=contributors[0].id)

    def _build_up(self, ins: dict, subject: str) -> ProfileSection:
        prog = self._first(ins, "progression.left_dominance", "progression.right_dominance",
                           "progression.central_dominance")
        corridor = ins.get("progression.dominant_corridor")
        player = ins.get("progression.primary_player")
        contributors = [x for x in (prog, corridor, player) if x]
        if not contributors:
            return ProfileSection("build_up", "Build-up", "", available=False,
                                  reason="No progression evidence to describe build-up.")
        route = (prog.meta.get("side") + " corridor") if prog else \
            (corridor.meta.get("channel", "").lower() if corridor else "the pitch")
        headline = f"{subject} builds mainly through the {route}."
        lines = [c.short_explanation for c in contributors]
        lines.append("Formation and role assignments are not inferred — no formation data is available.")
        return ProfileSection("build_up", "Build-up", headline, tuple(lines),
                              tuple(c.id for c in contributors), contributors[0].id)

    def _progression(self, ins: dict, subject: str) -> ProfileSection:
        prog = self._first(ins, "progression.left_dominance", "progression.right_dominance",
                           "progression.central_dominance")
        corridor = ins.get("progression.dominant_corridor")
        player = ins.get("progression.primary_player")
        if not (prog or corridor):
            return ProfileSection("progression", "Progression", "", available=False,
                                  reason="Insufficient progressive actions to profile progression.")
        primary = (prog.meta["side"] + " corridor") if prog else corridor.meta["channel"].lower()
        lines = [f"Primary route: {primary}"]
        if prog:
            ranking = self._lane_ranking(prog)
            if len(ranking) >= 2:
                lines.append(f"Secondary route: {ranking[1][0]} ({ranking[1][1] * 100:.0f}%)")
        if player:
            lines.append(f"Main progression player: {player.subject}")
        base = prog or corridor
        lines.append(f"Evidence: {base.short_explanation}")
        headline = f"Progression is dominated by the {primary}."
        ids = tuple(c.id for c in (prog, corridor, player) if c)
        return ProfileSection("progression", "Progression", headline, tuple(lines), ids, base.id)

    def _final_third(self, ins: dict, subject: str) -> ProfileSection:
        side = ins.get("final_third.entry_concentration")
        corr = ins.get("final_third.preferred_corridor")
        box = ins.get("final_third.box_entry_concentration")
        player = ins.get("players.primary_final_third_progressor")
        contributors = [x for x in (side, corr, box, player) if x]
        if not contributors:
            return ProfileSection("final_third", "Final Third", "", available=False,
                                  reason="Not enough final-third entries to profile.")
        route = corr.meta["channel"].lower() if corr else (side.meta["side"] + " side" if side else "")
        headline = f"Final-third play is focused on the {route}." if route else \
            f"{subject} enters the final third from varied areas."
        lines = [c.short_explanation for c in contributors]
        if box:
            lines.append(f"Box-entry tendency: {box.meta.get('side', '')} side")
        if player:
            lines.append(f"Primary contributor: {player.subject}")
        return ProfileSection("final_third", "Final Third", headline, tuple(lines),
                              tuple(c.id for c in contributors), contributors[0].id)

    def _transitions(self, report: InsightReport, subject: str) -> ProfileSection:
        trans = [i for i in report.insights if i.category is InsightCategory.TRANSITIONS]
        if trans:                                     # populated by the P2 transition rules
            primary = trans[0]                        # report is priority/confidence ordered
            return ProfileSection(
                "transitions", "Transitions", primary.short_explanation,
                lines=tuple(t.short_explanation for t in trans),
                insight_ids=tuple(t.id for t in trans), primary_insight_id=primary.id)
        cov = report.coverage or {}
        if not (cov.get("sequence") or cov.get("timestamps")):
            reason = ("The current dataset does not contain sufficient sequence/timestamp information "
                      "to profile transitions.")
        elif not cov.get("recovery_events"):
            reason = "No ball-recovery events are present to build transitions from."
        else:
            reason = "Not enough post-recovery evidence cleared the thresholds to profile transitions."
        return ProfileSection("transitions", "Transitions", "", available=False, reason=reason)

    def _recoveries(self, ins: dict, subject: str, has_recovery_events: bool) -> ProfileSection:
        zone = ins.get("recoveries.dominant_zone")
        high = ins.get("recoveries.high_concentration")
        contributors = [x for x in (zone, high) if x]
        if not contributors:
            reason = ("No ball-recovery events (recovery / interception / tackle) are present."
                      if not has_recovery_events else
                      "Ball-recovery events are present, but no dominant recovery zone or high-recovery "
                      "concentration cleared the thresholds.")
            return ProfileSection("recoveries", "Recoveries", "", available=False, reason=reason)
        headline = (zone.short_explanation if zone else high.short_explanation)
        lines = [c.short_explanation for c in contributors]
        if high:
            # carry P0's own careful, non-pressing interpretation verbatim
            lines.append(high.interpretation)
        return ProfileSection("recoveries", "Recoveries", headline, tuple(lines),
                              tuple(c.id for c in contributors), contributors[0].id)

    # ---- key players ----------------------------------------------------------
    def _key_players(self, ins: dict) -> tuple[KeyPlayer, ...]:
        specs = [
            ("progression.primary_player", "Primary progression contributor"),
            ("players.primary_final_third_progressor", "Primary final-third outlet"),
            ("players.primary_attacking_involvement", "Leads attacking involvement"),
        ]
        merged: dict[str, dict] = {}
        for iid, role in specs:
            i = ins.get(iid)
            if not i:
                continue
            name = i.subject or i.meta.get("player", "")
            if not name:
                continue
            rec = merged.setdefault(name, {"roles": [], "ids": [], "metrics": [],
                                           "conf": Confidence.LOW})
            rec["roles"].append(role)
            rec["ids"].append(iid)
            rec["metrics"] = [f"{e.label}: {e.value}" for e in i.evidence]  # latest, richest set
            if _CONFIDENCE_RANK[i.confidence] < _CONFIDENCE_RANK[rec["conf"]]:
                rec["conf"] = i.confidence
        return tuple(
            KeyPlayer(name=name, role=" · ".join(r["roles"]), metrics=tuple(r["metrics"]),
                      confidence=r["conf"], insight_ids=tuple(r["ids"]), primary_insight_id=r["ids"][0])
            for name, r in merged.items())

    # ---- strengths ------------------------------------------------------------
    def _strengths(self, report: InsightReport) -> tuple[ProfileItem, ...]:
        pool = [i for i in report.insights if i.confidence is not Confidence.LOW]
        pool.sort(key=lambda i: (_PRIORITY_RANK[i.priority], _CONFIDENCE_RANK[i.confidence],
                                 -i.confidence_score))
        out = [ProfileItem(text=i.title, detail=i.short_explanation, confidence=i.confidence,
                           insight_ids=(i.id,), primary_insight_id=i.id) for i in pool[:_MAX_STRENGTHS]]
        return tuple(out)

    # ---- vulnerabilities (only when genuinely evidenced) ----------------------
    def _vulnerabilities(self, report: InsightReport, ins: dict, subject: str) -> tuple[ProfileItem, ...]:
        items: list[ProfileItem] = []
        # 1) evidence-backed P0 vulnerability insights (turnover zone / route failure /
        #    final-third inefficiency) — each already sample- and effect-guarded by P0
        for i in report.insights:
            if i.category is InsightCategory.VULNERABILITY:
                items.append(ProfileItem(text=i.title, detail=i.short_explanation, confidence=i.confidence,
                                         insight_ids=(i.id,), primary_insight_id=i.id))
        # 2) the interpretive one-sided-progression case (derived from progression evidence)
        items.extend(self._one_sided_vulnerability(ins))
        # strongest first; never surface a vulnerability without evidence
        items.sort(key=lambda it: _CONFIDENCE_RANK[it.confidence])
        return tuple(items)

    def _one_sided_vulnerability(self, ins: dict) -> list[ProfileItem]:
        prog = self._first(ins, "progression.left_dominance", "progression.right_dominance",
                           "progression.central_dominance")
        if prog is None or prog.confidence is Confidence.LOW:
            return []
        ranking = self._lane_ranking(prog)
        if len(ranking) < 2:
            return []
        weak_lane, weak_share = ranking[-1]
        strong_side = prog.meta.get("side", "one side")
        if weak_share > _ONE_SIDED_LANE_SHARE:
            return []                        # no genuinely under-used side => no vulnerability
        conf = Confidence.MEDIUM if prog.confidence is Confidence.HIGH else Confidence.LOW
        weak_word = weak_lane.replace(" Lane", "").lower()
        return [ProfileItem(
            text=f"One-sided progression (little threat down the {weak_word})",
            detail=(f"Only {weak_share * 100:.0f}% of progression comes through the {weak_word}; build-up "
                    f"is heavily {strong_side}-sided, which may make their progression predictable and "
                    f"easier to prepare for."),
            confidence=conf, insight_ids=(prog.id,), primary_insight_id=prog.id)]

    # ---- DNA summary ----------------------------------------------------------
    def _summary(self, sections: tuple[ProfileSection, ...], players: tuple[KeyPlayer, ...],
                 subject: str) -> tuple[SummaryLine, ...]:
        by_id = {s.id: s for s in sections}
        lines: list[SummaryLine] = []

        def add(heading: str, sid: str) -> None:
            s = by_id.get(sid)
            if s and s.available and s.headline:
                lines.append(SummaryLine(heading, s.headline))

        add("Attacking Identity", "attacking_identity")
        prog = by_id.get("progression")
        if prog and prog.available:
            txt = prog.headline
            if players:
                txt += f" {players[0].name} is the {players[0].role.split(' · ')[0].lower()}."
            lines.append(SummaryLine("Progression", txt))
        add("Final Third", "final_third")
        add("Transitions", "transitions")
        add("Recoveries", "recoveries")
        if players:
            p = players[0]
            lines.append(SummaryLine("Key Player", f"{p.name} — {p.role}."))
        if not lines:
            lines.append(SummaryLine("Summary",
                                     f"Not enough high-confidence evidence to profile {subject}."))
        return tuple(lines)

    # ---- confidence & coverage ------------------------------------------------
    def _confidence(self, report: InsightReport) -> tuple[Confidence, str, bool]:
        used = report.insights
        if not used:
            return Confidence.LOW, "Limited evidence", True
        high = sum(1 for i in used if i.confidence is Confidence.HIGH)
        med = sum(1 for i in used if i.confidence is Confidence.MEDIUM)
        total = len(used)
        score = (2 * high + med) / (2 * total)
        q = report.quality
        limited = total < 3 or q < self.min_quality or high == 0
        if not limited and score >= 0.6 and high >= 2:
            level = Confidence.HIGH
        elif score >= 0.35 and q >= self.min_quality:
            level = Confidence.MEDIUM
        else:
            level = Confidence.LOW
        label = "Limited evidence" if limited else level.value
        return level, label, limited

    def _coverage(self, report: InsightReport) -> tuple[CoverageItem, ...]:
        cov = report.coverage or {}

        def st(flag) -> str:
            return "ok" if flag else "missing"

        transition = "limited" if (cov.get("sequence") and cov.get("timestamps")) else "missing"
        return (
            CoverageItem("Event data", "ok" if report.n_events > 0 else "missing"),
            CoverageItem("Coordinates", st(cov.get("coords"))),
            CoverageItem("End coordinates", st(cov.get("end_coords"))),
            CoverageItem("Player identity", st(cov.get("players"))),
            CoverageItem("Timestamps", st(cov.get("timestamps"))),
            CoverageItem("Sequence data", st(cov.get("sequence"))),
            CoverageItem("Recovery events", st(cov.get("recovery_events"))),
            CoverageItem("Transition data", transition),
        )


# module-level convenience
def build_profile(report: InsightReport, *, min_quality: float | None = None) -> TacticalProfile:
    return TacticalProfileBuilder(min_quality=min_quality).build(report)
