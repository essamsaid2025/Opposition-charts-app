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

# per-(match, insight) observation status — the fix for 0-padding: a match where an
# insight did not fire is NOT the same as a value of 0.
OBSERVED = "observed"              # the insight fired -> we have a measured value
OBSERVED_ABSENT = "observed_absent"  # family had enough data, pattern just wasn't dominant
INSUFFICIENT = "insufficient"     # family present but sample below the P0 minimum -> unknown
UNAVAILABLE = "unavailable"       # the family's required data is missing this match

# insight id -> analysis family (denominator that gates it)
_FAMILY_OF = {
    "progression.left_dominance": "progression", "progression.right_dominance": "progression",
    "progression.central_dominance": "progression", "progression.dominant_corridor": "progression",
    "progression.primary_player": "progression",
    "final_third.entry_concentration": "final_third", "final_third.preferred_corridor": "final_third",
    "final_third.box_entry_concentration": "box",
    "players.primary_final_third_progressor": "final_third",
    "players.primary_attacking_involvement": "final_third",
    "recoveries.dominant_zone": "recoveries", "recoveries.high_concentration": "recoveries",
    "transitions.recovery_to_progression": "transitions",
    "transitions.recovery_to_final_third": "transitions",
    "transitions.recovery_to_shot": "transitions", "transitions.direction": "transitions",
    "vulnerability.turnover_zone": "turnovers", "vulnerability.route_failure": "turnovers",
    "vulnerability.final_third_inefficiency": "final_third",
}
_FAMILY_FALLBACK = {"progression": "progression", "final_third": "final_third", "box": "final_third",
                    "recoveries": "recoveries", "transitions": "transitions",
                    "vulnerability": "turnovers", "players": "final_third"}


def _family_of(insight_id: str) -> str:
    if insight_id in _FAMILY_OF:
        return _FAMILY_OF[insight_id]
    return _FAMILY_FALLBACK.get(insight_id.split(".", 1)[0], "progression")

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
    families: dict[str, dict] = field(default_factory=dict)         # family -> {available,n,min}

    def status_for(self, insight_id: str) -> str:
        """OBSERVED / OBSERVED_ABSENT / INSUFFICIENT / UNAVAILABLE for this insight in
        this match — the semantic that replaces 0-padding."""
        if insight_id in self.shares:
            return OBSERVED
        fam = self.families.get(_family_of(insight_id))
        if not fam or not fam.get("available", False):
            return UNAVAILABLE
        if int(fam.get("n", 0)) < int(fam.get("min", 0)):
            return INSUFFICIENT
        return OBSERVED_ABSENT               # enough data, pattern simply wasn't dominant here

    def to_dict(self) -> dict:
        return {"match_id": self.match_id, "n_events": self.n_events, "quality": self.quality,
                "usable": self.usable, "reason": self.reason, "subject": self.subject,
                "shares": dict(self.shares), "confidences": dict(self.confidences),
                "families": {k: dict(v) for k, v in self.families.items()}}


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


def _ordered_match_ids(frame: pd.DataFrame) -> list[str]:
    """Chronological match order. Uses the canonical ``date`` field when every match
    carries a parseable date; otherwise falls back to first-appearance order (the
    only deterministic option) — never arbitrary match-id sorting."""
    ids = list(dict.fromkeys(frame["match_id"].astype(str)))
    if "date" not in frame.columns:
        return ids
    dates: dict[str, object] = {}
    mid_col = frame["match_id"].astype(str)
    for mid in ids:
        raw = frame.loc[mid_col == mid, "date"].astype(str)
        raw = raw[raw.str.strip().ne("")]
        d = pd.to_datetime(raw, errors="coerce").min() if len(raw) else pd.NaT
        dates[mid] = d
    if all(pd.notna(d) for d in dates.values()) and len(dates) == len(ids):
        appearance = {mid: k for k, mid in enumerate(ids)}         # stable tiebreak
        return sorted(ids, key=lambda m: (dates[m], appearance[m]))
    return ids


def build_multimatch(frame: pd.DataFrame | None, *, current_match: str | None = None,
                     thresholds: InsightThresholds | None = None) -> MultiMatchContext:
    """Run P0 once per match_id in ``frame`` (already filtered by the caller) and
    collect lightweight per-match extracts. ``frame`` should be the derived active
    frame with the analyst's non-match filters already applied."""
    th = thresholds or DEFAULT_THRESHOLDS
    if frame is None or getattr(frame, "empty", True) or "match_id" not in frame.columns:
        return MultiMatchContext("the selected events", (), current_match or "", th)

    engine = TacticalInsightEngine(th)
    ids = _ordered_match_ids(frame)                                # chronological when dated
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
                                     shares, confs, evid, {k: dict(v) for k, v in rep.families.items()}))

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
    present_count: int             # matches where the insight was OBSERVED (fired)
    observable_count: int          # matches where the family had enough data to judge (denominator)
    insufficient_count: int        # usable matches with insufficient family sample for this pattern
    unavailable_count: int         # usable matches where the family was unavailable
    usable_count: int              # all usable (data-quality-passing) matches
    current_status: str            # Observed / Absent / Insufficient / Unavailable
    current_share: float | None    # None unless the current match is observable
    baseline_status: str           # Observed / Insufficient
    baseline_share: float | None   # None when the baseline has no observable match
    delta: float | None            # None when a reliable delta cannot be computed
    confidence: str
    match_ids: tuple[str, ...]     # usable matches, chronological
    shares: tuple[float, ...]      # per OBSERVABLE match (0 for genuine absence; insufficient excluded)
    observable_match_ids: tuple[str, ...]
    present_match_ids: tuple[str, ...]
    evidence: tuple[EvidenceRef, ...]
    match_statuses: tuple[tuple[str, str], ...] = ()   # (match_id, Observed/Absent/Insufficient/Unavailable)

    @property
    def delta_pp(self) -> float | None:
        return None if self.delta is None else round(self.delta * 100, 1)

    @property
    def recurrence(self) -> str:
        return f"{self.present_count} / {self.observable_count}"

    def to_dict(self) -> dict:
        return {"insight_id": self.insight_id, "label": self.label, "category": self.category,
                "classification": self.classification, "trend": self.trend,
                "present_count": self.present_count, "observable_count": self.observable_count,
                "insufficient_count": self.insufficient_count, "unavailable_count": self.unavailable_count,
                "usable_count": self.usable_count, "current_status": self.current_status,
                "current_share": None if self.current_share is None else round(self.current_share, 4),
                "baseline_status": self.baseline_status,
                "baseline_share": None if self.baseline_share is None else round(self.baseline_share, 4),
                "delta": None if self.delta is None else round(self.delta, 4), "delta_pp": self.delta_pp,
                "confidence": self.confidence, "match_ids": list(self.match_ids),
                "shares": [round(s, 4) for s in self.shares],
                "observable_match_ids": list(self.observable_match_ids),
                "present_match_ids": list(self.present_match_ids),
                "match_statuses": [list(s) for s in self.match_statuses],
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
        out = [p for p in self.patterns if p.delta is not None and abs(p.delta) >= min_delta]
        return sorted(out, key=lambda p: -abs(p.delta))

    def to_dict(self) -> dict:
        return {"subject": self.subject, "match_count": self.match_count,
                "usable_count": self.usable_count, "excluded": [list(e) for e in self.excluded],
                "current_id": self.current_id, "insufficient": self.insufficient,
                "patterns": [p.to_dict() for p in self.patterns]}


def _category_of(insight_id: str) -> str:
    return insight_id.split(".", 1)[0]


# (analyze_evolution below classifies each usable match per pattern rather than 0-padding
#  non-firing matches — see status_for / _classify.)


_STATUS_LABEL = {OBSERVED: "Observed", OBSERVED_ABSENT: "Absent",
                 INSUFFICIENT: "Insufficient", UNAVAILABLE: "Unavailable"}


def analyze_evolution(context: MultiMatchContext,
                      thresholds: InsightThresholds | None = None) -> TacticalEvolution:
    """Aggregate per-match P0 results into trends WITHOUT 0-padding. Every usable match
    is classified per pattern (observed / genuinely-absent / insufficient / unavailable);
    recurrence, trend and baseline use only the matches where the pattern could actually
    be judged, so an insufficient-sample match is never read as a value of 0."""
    th = thresholds or context.thresholds
    usable = context.usable()                        # data-quality-passing matches, chronological
    U = len(usable)
    excluded = tuple(context.excluded())
    if U == 0:
        return TacticalEvolution(context.subject, len(context.matches), 0, excluded,
                                 context.current_id, (), True)

    order_ids = [m.match_id for m in usable]
    current = context.current_id if context.current_id in order_ids else order_ids[-1]
    cur_m = next((m for m in usable if m.match_id == current), None)
    all_ids = sorted({iid for m in usable for iid in m.shares})

    patterns: list[PatternTrend] = []
    for iid in all_ids:
        statuses = [(m, m.status_for(iid)) for m in usable]
        observable = [m for m, s in statuses if s in (OBSERVED, OBSERVED_ABSENT)]
        present = [m for m, s in statuses if s is OBSERVED]
        insufficient_n = sum(1 for _, s in statuses if s is INSUFFICIENT)
        unavailable_n = sum(1 for _, s in statuses if s is UNAVAILABLE)
        obs_count, present_count = len(observable), len(present)

        # trend series over OBSERVABLE matches only: measured share when observed, 0 for a
        # genuine (data-backed) absence; insufficient/unavailable matches are NOT included.
        series = [float(m.shares.get(iid, 0.0)) for m in observable]
        present_ids = tuple(m.match_id for m in present)
        obs_ids = tuple(m.match_id for m in observable)

        confs = [m.confidences.get(iid, "Low") for m in present]
        confidence = min(confs, key=lambda c: _CONF_RANK.get(c, 2)) if confs else "Low"

        classification = _classify(observable, present_ids, current, th)
        trend = _trend(series, obs_count, th)

        cur_status = cur_m.status_for(iid) if cur_m else UNAVAILABLE
        current_share = (float(cur_m.shares.get(iid, 0.0))
                         if cur_m and cur_status in (OBSERVED, OBSERVED_ABSENT) else None)
        baseline_obs = [m for m in observable if m.match_id != current]
        if baseline_obs:
            baseline_share = statistics.fmean(m.shares.get(iid, 0.0) for m in baseline_obs)
            baseline_status = "Observed"
        else:
            baseline_share, baseline_status = None, "Insufficient"
        delta = (current_share - baseline_share
                 if current_share is not None and baseline_share is not None else None)

        evidence = tuple(m.evidence[iid] for m in present if iid in m.evidence)
        match_statuses = tuple((m.match_id, _STATUS_LABEL[s]) for m, s in statuses)
        patterns.append(PatternTrend(
            insight_id=iid, label=_label(iid), category=_category_of(iid),
            classification=classification, trend=trend, present_count=present_count,
            observable_count=obs_count, insufficient_count=insufficient_n,
            unavailable_count=unavailable_n, usable_count=U,
            current_status=_STATUS_LABEL[cur_status], current_share=current_share,
            baseline_status=baseline_status, baseline_share=baseline_share, delta=delta,
            confidence=confidence, match_ids=tuple(order_ids), shares=tuple(series),
            observable_match_ids=obs_ids, present_match_ids=present_ids, evidence=evidence,
            match_statuses=match_statuses))

    # most tactically significant first: recurrence x strength
    patterns.sort(key=lambda p: (-(p.present_count * (max(p.shares) if p.shares else 0)), p.insight_id))
    insufficient = U < th.min_matches
    return TacticalEvolution(context.subject, len(context.matches), U, excluded, current,
                             tuple(patterns), insufficient)


def _classify(observable: list[MatchInsights], present_ids: tuple[str, ...], current: str,
              th: InsightThresholds) -> str:
    """Recurrence over OBSERVABLE matches only (family had enough data to judge the
    pattern). An insufficient-sample match is neither a presence nor an absence — it is
    simply not in the denominator."""
    obs_count = len(observable)
    if obs_count < th.min_matches:
        return "Insufficient"
    present_count = len(present_ids)
    if present_count == 0:
        return "Mixed"
    if present_count / obs_count >= th.consistent_fraction:
        return "Consistent"
    if present_count == 1 and current in present_ids:
        return "Match-specific"
    order = [m.match_id for m in observable]         # chronological among observable
    present_idx = [order.index(mid) for mid in present_ids]
    half = obs_count / 2
    early = any(k < half for k in present_idx)
    late = any(k >= half for k in present_idx)
    if late and not early:
        return "Emerging"
    if early and not late:
        return "Declining"
    return "Mixed"


def _trend(shares: list[float], obs_count: int, th: InsightThresholds) -> str:
    """Direction of the per-match effect. 'Volatile' means genuine oscillation (up AND
    down), not merely a large one-off step — so a monotonic emergence/decline reads as
    Increasing/Decreasing, while a saw-tooth series reads as Volatile."""
    if obs_count < th.min_matches or len(shares) < 2:
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
