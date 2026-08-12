"""Multi-match tactical consistency & evolution (P2).

A deterministic orchestration layer that runs the EXISTING P0 engine once per
match, then aggregates the per-match insight results into consistency / trend /
current-vs-baseline signals. No new analytics: every value comes from P0 insight
metadata (effect share + confidence). No DataFrames are stored on the result —
only lightweight per-match extracts and evidence references (which preserve player
scope, so the corrected P0 player-evidence pathway is not bypassed).

    frame (already filtered, split by match_id)
        -> P0 InsightReport per match  (reused, not re-implemented)
        -> MatchInsights (shares/confidences/evidence, no frames)
        -> TacticalEvolution (consistent / emerging / declining / stable / volatile
           / match-specific + current-vs-baseline), data-quality aware.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

import pandas as pd

from fap.analytics.tactical.engine import TacticalInsightEngine
from fap.analytics.tactical.model import Confidence
from fap.analytics.tactical.thresholds import DEFAULT_THRESHOLDS, InsightThresholds

_CONF_RANK = {"High": 0, "Medium": 1, "Low": 2}

# stable, match-independent labels for the ids that vary in title (player names etc.)
_ID_LABELS = {
    "progression.left_dominance": "Left-sided progression",
    "progression.right_dominance": "Right-sided progression",
    "progression.central_dominance": "Central progression",
    "progression.dominant_corridor": "Dominant progression corridor",
    "progression.primary_player": "Primary progression player",
    "final_third.entry_concentration": "Final-third entry side",
    "final_third.preferred_corridor": "Preferred attacking corridor",
    "final_third.box_entry_concentration": "Box-entry side",
    "recoveries.dominant_zone": "Dominant recovery zone",
    "recoveries.high_concentration": "High/final-third recoveries",
    "players.primary_final_third_progressor": "Primary final-third outlet",
    "players.primary_attacking_involvement": "Primary attacking involvement",
    "transitions.recovery_to_progression": "Recovery → progression",
    "transitions.recovery_to_final_third": "Recovery → final third",
    "transitions.recovery_to_shot": "Recovery → shot",
    "transitions.direction": "Transition direction",
    "vulnerability.turnover_zone": "Turnover concentration zone",
    "vulnerability.route_failure": "Favoured-route losses",
    "vulnerability.final_third_inefficiency": "Final-third inefficiency",
}


def _label(insight_id: str) -> str:
    return _ID_LABELS.get(insight_id, insight_id.replace(".", " · ").replace("_", " ").title())


def _effect(meta: dict, confidence_score: float) -> float:
    for k in ("share", "rate", "box_conversion"):
        if k in meta:
            try:
                return float(meta[k])
            except (TypeError, ValueError):
                pass
    return float(confidence_score)


# ================================================================ per-match extract
@dataclass(frozen=True)
class EvidenceRef:
    match_id: str
    insight_id: str
    viz_hint: str = ""
    event_types: tuple[str, ...] = ()
    players: tuple[str, ...] = ()
    lane: str | None = None
    third: str | None = None

    def to_dict(self) -> dict:
        return {"match_id": self.match_id, "insight_id": self.insight_id, "viz_hint": self.viz_hint,
                "event_types": list(self.event_types), "players": list(self.players),
                "lane": self.lane, "third": self.third}


@dataclass(frozen=True)
class MatchInsights:
    match_id: str
    n_events: int
    quality: float
    usable: bool
    reason: str
    subject: str
    shares: dict[str, float] = field(default_factory=dict)          # insight_id -> effect (0-1)
    confidences: dict[str, str] = field(default_factory=dict)       # insight_id -> "High"/…
    evidence: dict[str, EvidenceRef] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"match_id": self.match_id, "n_events": self.n_events, "quality": self.quality,
                "usable": self.usable, "reason": self.reason, "subject": self.subject,
                "shares": dict(self.shares), "confidences": dict(self.confidences)}


@dataclass(frozen=True)
class MultiMatchContext:
    subject: str
    matches: tuple[MatchInsights, ...]
    current_id: str
    thresholds: InsightThresholds

    def usable(self) -> list[MatchInsights]:
        return [m for m in self.matches if m.usable]

    def excluded(self) -> list[tuple[str, str]]:
        return [(m.match_id, m.reason) for m in self.matches if not m.usable]


def build_multimatch(frame: pd.DataFrame | None, *, current_match: str | None = None,
                     thresholds: InsightThresholds | None = None) -> MultiMatchContext:
    """Run P0 once per match_id in ``frame`` (already filtered by the caller) and
    collect lightweight per-match extracts. ``frame`` should be the derived active
    frame with the analyst's non-match filters already applied."""
    th = thresholds or DEFAULT_THRESHOLDS
    if frame is None or getattr(frame, "empty", True) or "match_id" not in frame.columns:
        return MultiMatchContext("the selected events", (), current_match or "", th)

    engine = TacticalInsightEngine(th)
    ids = list(dict.fromkeys(frame["match_id"].astype(str)))       # preserve appearance order
    matches: list[MatchInsights] = []
    for mid in ids:
        mframe = frame[frame["match_id"].astype(str) == mid]
        rep = engine.analyze(mframe)
        cov = rep.coverage or {}
        if rep.n_events < th.min_events_per_match:
            usable, reason = False, f"insufficient events ({rep.n_events})"
        elif not cov.get("coords"):
            usable, reason = False, "insufficient coordinates"
        else:
            usable, reason = True, ""
        shares, confs, evid = {}, {}, {}
        for ins in rep.insights:
            shares[ins.id] = _effect(ins.meta, ins.confidence_score)
            confs[ins.id] = ins.confidence.value
            sv = ins.supporting_viz
            evid[ins.id] = EvidenceRef(
                match_id=mid, insight_id=ins.id,
                viz_hint=sv.viz_hint if sv else "", event_types=sv.event_types if sv else (),
                players=sv.players if sv else (), lane=sv.lane if sv else None,
                third=sv.third if sv else None)
        matches.append(MatchInsights(mid, rep.n_events, rep.quality, usable, reason, rep.subject,
                                     shares, confs, evid))

    usable_ids = [m.match_id for m in matches if m.usable]
    if current_match and current_match in {m.match_id for m in matches}:
        current = current_match
    else:
        current = usable_ids[-1] if usable_ids else (ids[-1] if ids else "")
    subjects = [m.subject for m in matches if m.usable and m.subject]
    subject = statistics.mode(subjects) if subjects else "the selected events"
    return MultiMatchContext(subject, tuple(matches), current, th)


# ================================================================ evolution result
@dataclass(frozen=True)
class PatternTrend:
    insight_id: str
    label: str
    category: str
    classification: str            # Consistent / Emerging / Declining / Match-specific / Mixed / Insufficient
    trend: str                     # Increasing / Decreasing / Stable / Volatile / —
    present_count: int
    usable_count: int
    current_share: float
    baseline_share: float
    delta: float                   # current - baseline (share fraction)
    confidence: str
    match_ids: tuple[str, ...]     # usable match order
    shares: tuple[float, ...]      # per usable match (0 when the pattern didn't fire)
    present_match_ids: tuple[str, ...]
    evidence: tuple[EvidenceRef, ...]

    @property
    def delta_pp(self) -> float:
        return round(self.delta * 100, 1)

    def to_dict(self) -> dict:
        return {"insight_id": self.insight_id, "label": self.label, "category": self.category,
                "classification": self.classification, "trend": self.trend,
                "present_count": self.present_count, "usable_count": self.usable_count,
                "current_share": round(self.current_share, 4), "baseline_share": round(self.baseline_share, 4),
                "delta": round(self.delta, 4), "delta_pp": self.delta_pp, "confidence": self.confidence,
                "match_ids": list(self.match_ids), "shares": [round(s, 4) for s in self.shares],
                "present_match_ids": list(self.present_match_ids),
                "evidence": [e.to_dict() for e in self.evidence]}


@dataclass(frozen=True)
class TacticalEvolution:
    subject: str
    match_count: int
    usable_count: int
    excluded: tuple[tuple[str, str], ...]
    current_id: str
    patterns: tuple[PatternTrend, ...]
    insufficient: bool

    def consistent(self) -> list[PatternTrend]:
        return [p for p in self.patterns if p.classification == "Consistent"]

    def emerging(self) -> list[PatternTrend]:
        return [p for p in self.patterns if p.classification == "Emerging"]

    def declining(self) -> list[PatternTrend]:
        return [p for p in self.patterns if p.classification == "Declining"]

    def changing(self) -> list[PatternTrend]:
        return [p for p in self.patterns if p.trend in ("Increasing", "Decreasing")]

    def match_specific(self) -> list[PatternTrend]:
        return [p for p in self.patterns if p.classification == "Match-specific"]

    def current_vs_baseline(self, *, min_delta: float = 0.08) -> list[PatternTrend]:
        out = [p for p in self.patterns if abs(p.delta) >= min_delta]
        return sorted(out, key=lambda p: -abs(p.delta))

    def to_dict(self) -> dict:
        return {"subject": self.subject, "match_count": self.match_count,
                "usable_count": self.usable_count, "excluded": [list(e) for e in self.excluded],
                "current_id": self.current_id, "insufficient": self.insufficient,
                "patterns": [p.to_dict() for p in self.patterns]}


def _category_of(insight_id: str) -> str:
    return insight_id.split(".", 1)[0]


def analyze_evolution(context: MultiMatchContext,
                      thresholds: InsightThresholds | None = None) -> TacticalEvolution:
    th = thresholds or context.thresholds
    usable = context.usable()
    U = len(usable)
    excluded = tuple(context.excluded())
    insufficient = U < th.min_matches
    if U == 0:
        return TacticalEvolution(context.subject, len(context.matches), 0, excluded,
                                 context.current_id, (), True)

    order_ids = [m.match_id for m in usable]
    current = context.current_id if context.current_id in order_ids else order_ids[-1]
    all_ids = sorted({iid for m in usable for iid in m.shares})

    patterns: list[PatternTrend] = []
    for iid in all_ids:
        shares = [float(m.shares.get(iid, 0.0)) for m in usable]
        present_idx = [k for k, m in enumerate(usable) if iid in m.shares]
        present_ids = tuple(order_ids[k] for k in present_idx)
        present_count = len(present_idx)
        # confidence = best across present matches
        confs = [m.confidences.get(iid, "Low") for m in usable if iid in m.shares]
        confidence = min(confs, key=lambda c: _CONF_RANK.get(c, 2)) if confs else "Low"

        cur_m = next((m for m in usable if m.match_id == current), None)
        current_share = float(cur_m.shares.get(iid, 0.0)) if cur_m else 0.0
        baseline_matches = [m for m in usable if m.match_id != current]
        baseline_share = (statistics.fmean(m.shares.get(iid, 0.0) for m in baseline_matches)
                          if baseline_matches else statistics.fmean(shares))
        delta = current_share - baseline_share

        classification = _classify(present_idx, present_count, U, current in present_ids, th)
        trend = _trend(shares, present_count, U, th)
        evidence = tuple(m.evidence[iid] for m in usable if iid in m.evidence)
        patterns.append(PatternTrend(
            insight_id=iid, label=_label(iid), category=_category_of(iid),
            classification=classification, trend=trend, present_count=present_count, usable_count=U,
            current_share=current_share, baseline_share=baseline_share, delta=delta,
            confidence=confidence, match_ids=tuple(order_ids), shares=tuple(shares),
            present_match_ids=present_ids, evidence=evidence))

    # most tactically significant first: recurrence x strength
    patterns.sort(key=lambda p: (-(p.present_count * max(p.shares) if p.shares else 0), p.insight_id))
    return TacticalEvolution(context.subject, len(context.matches), U, excluded, current,
                             tuple(patterns), insufficient)


def _classify(present_idx: list[int], present_count: int, U: int, current_present: bool,
              th: InsightThresholds) -> str:
    if U < th.min_matches:
        return "Insufficient"
    if present_count == 0:
        return "Mixed"
    if present_count / U >= th.consistent_fraction:
        return "Consistent"
    if present_count == 1 and current_present:
        return "Match-specific"
    half = U / 2
    early = any(k < half for k in present_idx)
    late = any(k >= half for k in present_idx)
    if late and not early:
        return "Emerging"
    if early and not late:
        return "Declining"
    return "Mixed"


def _trend(shares: list[float], present_count: int, U: int, th: InsightThresholds) -> str:
    """Direction of the per-match effect. 'Volatile' means genuine oscillation (up AND
    down), not merely a large one-off step — so a monotonic emergence/decline reads as
    Increasing/Decreasing, while a saw-tooth series reads as Volatile."""
    if U < th.min_matches or present_count < 2:
        return "—"
    band = th.trend_stable_band
    small = band / 2
    diffs = [b - a for a, b in zip(shares, shares[1:])]
    up = sum(1 for d in diffs if d > small)
    down = sum(1 for d in diffs if d < -small)
    span = shares[-1] - shares[0]
    if up and down:                              # changes direction => oscillation
        std = statistics.pstdev(shares) if len(shares) > 1 else 0.0
        return "Volatile" if std > th.trend_volatile_std else "Stable"
    if span >= band:
        return "Increasing"
    if span <= -band:
        return "Decreasing"
    return "Stable"


# module-level convenience
def build_evolution(frame: pd.DataFrame | None, *, current_match: str | None = None,
                    thresholds: InsightThresholds | None = None) -> TacticalEvolution:
    return analyze_evolution(build_multimatch(frame, current_match=current_match, thresholds=thresholds),
                             thresholds)
