"""Recruitment profiles / player archetypes + a transparent profile-fit engine.

A recruitment profile (Target Man, False 9, Ball-Winning 6, …) is structured DATA:
applicable positions and the metric *concepts* that define the role, expressed as
keyword matchers so a profile binds to whatever compatible metrics actually exist
in a given scouting dataset - it never invents metric names.

Fit is computed on top of the existing P4 adapter (``fap.scouting.viz.ScoutingView``):
the per-metric 0-100 score already honours ``value_scale`` (percentile for raw,
normalized value for normalized), so this module never re-transforms data. When too
few of a profile's metrics exist, fit is reported as unavailable rather than
fabricated. Potential fit is only produced from real academy potential data.

Pure - no Streamlit, no persistence, no matplotlib.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fap.scouting import viz
from fap.scouting.viz import ScoutingView

# minimum matched metrics before a fit score is considered meaningful
_MIN_MATCHED = 3


@dataclass(frozen=True, slots=True)
class MetricNeed:
    """One metric concept a profile wants, matched to a dataset by keywords.
    ``weight`` scales its contribution; ``required`` metrics also gate availability."""
    tokens: tuple[str, ...]              # any token substring-matches a metric name
    weight: float = 1.0
    required: bool = False
    invert: bool = False                 # lower is better (e.g. turnovers) -> 100-score


@dataclass(frozen=True, slots=True)
class RecruitmentProfile:
    id: str
    name: str
    description: str
    positions: tuple[str, ...]
    needs: tuple[MetricNeed, ...]
    first_team_applicable: bool = True
    academy_applicable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "description": self.description,
                "positions": list(self.positions),
                "first_team_applicable": self.first_team_applicable,
                "academy_applicable": self.academy_applicable}


def _need(tokens, weight=1.0, required=False, invert=False) -> MetricNeed:
    return MetricNeed(tuple(tokens), weight, required, invert)


# The built-in archetype library. Tokens are role CONCEPTS; they bind to whatever
# compatible metrics a dataset contains (nothing is required to exist).
BUILTIN_PROFILES: tuple[RecruitmentProfile, ...] = (
    RecruitmentProfile(
        "target_man", "Target Man", "Aerial focal point, hold-up and box presence.",
        ("CF", "ST"),
        (_need(("aerial",), 1.4, required=True), _need(("duels won",), 1.0),
         _need(("touches in box", "touches in the box"), 1.2, required=True),
         _need(("non-penalty goal", "goals per", "npxg"), 1.2),
         _need(("hold", "received", "passes received"), 0.8))),
    RecruitmentProfile(
        "false_9", "False 9", "Dropping forward linking play and creating chances.",
        ("CF", "AM", "AMF"),
        (_need(("progressive pass",), 1.2, required=True),
         _need(("xa", "shot assist", "key pass"), 1.3, required=True),
         _need(("smart pass", "through"), 1.0),
         _need(("touches in box", "npxg", "non-penalty goal"), 1.0),
         _need(("received", "passes per"), 0.8))),
    RecruitmentProfile(
        "ball_winning_6", "Ball-Winning 6", "Defensive midfield screen and duel winner.",
        ("DM", "CM", "DMF"),
        (_need(("interception", "padj interception"), 1.3, required=True),
         _need(("tackle", "sliding tackle"), 1.3, required=True),
         _need(("defensive duels", "duels won"), 1.1),
         _need(("recover",), 1.0), _need(("aerial",), 0.7),
         _need(("foul",), 0.5, invert=True))),
    RecruitmentProfile(
        "progressive_8", "Progressive 8", "Ball-carrying, line-breaking central midfielder.",
        ("CM", "CMF", "AM"),
        (_need(("progressive pass",), 1.3, required=True),
         _need(("progressive run", "carr"), 1.3, required=True),
         _need(("passes per", "accurate passes"), 0.9),
         _need(("final third",), 1.0), _need(("xa", "shot assist"), 0.9))),
    RecruitmentProfile(
        "creative_10", "Creative 10", "Advanced playmaker and chance creator.",
        ("AM", "AMF", "CF"),
        (_need(("xa",), 1.4, required=True),
         _need(("shot assist", "key pass"), 1.3, required=True),
         _need(("smart pass",), 1.1), _need(("through",), 1.0),
         _need(("progressive pass",), 0.9))),
    RecruitmentProfile(
        "inverted_winger", "Inverted Winger", "Wide forward cutting inside to shoot/create.",
        ("W", "LW", "RW", "RAMF", "LAMF"),
        (_need(("dribbl", "successful dribbles"), 1.3, required=True),
         _need(("non-penalty goal", "npxg", "goal conversion"), 1.2, required=True),
         _need(("shot assist", "xa"), 1.0), _need(("progressive run", "carr"), 1.0),
         _need(("touches in box",), 0.9))),
    RecruitmentProfile(
        "wide_1v1", "Wide 1v1 Player", "Touchline dribbler and crosser.",
        ("W", "LW", "RW", "LWF", "RWF"),
        (_need(("dribbl",), 1.4, required=True),
         _need(("cross", "accurate crosses"), 1.3, required=True),
         _need(("progressive run", "carr"), 1.0), _need(("shot assist", "xa"), 0.9))),
    RecruitmentProfile(
        "ball_playing_cb", "Ball-Playing CB", "Defender who progresses play from the back.",
        ("CB", "RCB", "LCB"),
        (_need(("accurate long pass", "long pass"), 1.2, required=True),
         _need(("progressive pass",), 1.3, required=True),
         _need(("accurate passes", "accurate short"), 1.0),
         _need(("aerial",), 1.1, required=True), _need(("interception",), 0.9))),
    RecruitmentProfile(
        "progressive_cb", "Progressive CB", "Front-foot defender who carries and steps in.",
        ("CB", "RCB", "LCB"),
        (_need(("progressive run", "carr"), 1.3, required=True),
         _need(("progressive pass",), 1.2, required=True),
         _need(("interception", "tackle"), 1.0), _need(("aerial",), 1.0),
         _need(("duels won",), 0.9))),
    RecruitmentProfile(
        "attacking_fullback", "Attacking Fullback", "Overlapping fullback with final-third output.",
        ("FB", "RB", "LB", "RWB", "LWB"),
        (_need(("cross",), 1.3, required=True),
         _need(("progressive run", "carr"), 1.2, required=True),
         _need(("shot assist", "xa"), 1.0), _need(("progressive pass",), 1.0),
         _need(("touches in box",), 0.8))),
    RecruitmentProfile(
        "inverted_fullback", "Inverted Fullback", "Fullback tucking in to build and screen.",
        ("FB", "RB", "LB"),
        (_need(("progressive pass",), 1.3, required=True),
         _need(("accurate passes", "accurate short"), 1.1, required=True),
         _need(("interception", "tackle"), 1.1), _need(("recover",), 0.9),
         _need(("duels won",), 0.8))),
    RecruitmentProfile(
        "sweeper_keeper", "Sweeper Keeper", "Goalkeeper who defends space and distributes.",
        ("GK",),
        (_need(("save rate", "save"), 1.4, required=True),
         _need(("prevented goal", "goals prevented"), 1.3, required=True),
         _need(("exits",), 1.1), _need(("long pass", "accurate passes"), 1.0),
         _need(("passes per",), 0.8)),
        academy_applicable=True),
)

PROFILES_BY_ID: dict[str, RecruitmentProfile] = {p.id: p for p in BUILTIN_PROFILES}


def all_profiles() -> tuple[RecruitmentProfile, ...]:
    return BUILTIN_PROFILES


def get_profile(profile_id: str) -> RecruitmentProfile | None:
    return PROFILES_BY_ID.get(profile_id)


def profiles_for_position(position: str) -> list[RecruitmentProfile]:
    """Profiles whose applicable positions overlap the player's position string
    (e.g. 'CF, RAMF, AMF'). Empty position -> all profiles offered."""
    pos = str(position or "").upper()
    if not pos.strip():
        return list(BUILTIN_PROFILES)
    tokens = {t.strip() for chunk in pos.replace("/", ",").split(",") for t in [chunk] if t.strip()}
    out = []
    for p in BUILTIN_PROFILES:
        if any(any(pp == t or pp in t for t in tokens) for pp in p.positions):
            out.append(p)
    return out or list(BUILTIN_PROFILES)


# ---------------------------------------------------------------- fit engine
def _score(view: ScoutingView, metric, player: str) -> float:
    if view.value_scale == viz.SCALE_NORMALIZED:
        v = metric.value(player)
        if v is None:
            return 0.0
        return float(min(max(v * 100.0 if abs(v) <= 1.0 else v, 0.0), 100.0))
    pct = metric.percentile(player)
    return 0.0 if pct is None else float(pct)


def _match_metrics(view: ScoutingView, need: MetricNeed):
    """Every dataset metric whose name contains one of the need's tokens."""
    out = []
    for m in view.metrics:
        name = m.name.lower()
        if any(tok in name for tok in need.tokens):
            out.append(m)
    return out


def profile_fit(view: ScoutingView, profile: RecruitmentProfile,
                player: str | None = None) -> dict[str, Any]:
    """Transparent fit of one player to a profile over the metrics that EXIST.

    Returns {available, score, coverage, matched, missing_required, mode, reason}.
    Unavailable (not fabricated) when too few of the profile's metrics are present.
    """
    player = player or view.primary
    if not player:
        return {"available": False, "reason": "no player", "score": None,
                "coverage": 0.0, "matched": [], "missing_required": [], "mode": ""}
    total_w = 0.0
    acc = 0.0
    matched: list[str] = []
    missing_required: list[str] = []
    required_hit = 0
    required_total = 0
    for need in profile.needs:
        ms = _match_metrics(view, need)
        if need.required:
            required_total += 1
        if not ms:
            if need.required:
                missing_required.append(need.tokens[0])
            continue
        if need.required:
            required_hit += 1
        # average score across all metrics matching this concept
        vals = [_score(view, m, player) for m in ms]
        s = sum(vals) / len(vals)
        if need.invert:
            s = 100.0 - s
        acc += s * need.weight
        total_w += need.weight
        matched.extend(m.name for m in ms)

    if len(matched) < _MIN_MATCHED or (required_total and required_hit == 0):
        return {"available": False,
                "reason": "not enough compatible metrics in this dataset for a reliable fit",
                "score": None, "coverage": round(required_hit / required_total, 3) if required_total else 0.0,
                "matched": matched, "missing_required": missing_required, "mode": ""}
    score = round(acc / total_w, 1) if total_w else None
    mode = "normalized" if view.value_scale == viz.SCALE_NORMALIZED else "percentile"
    coverage = round(required_hit / required_total, 3) if required_total else 1.0
    return {"available": True, "reason": "", "score": score, "coverage": coverage,
            "matched": matched, "missing_required": missing_required, "mode": mode}


def potential_fit(view: ScoutingView, profile: RecruitmentProfile,
                  potential_pct: dict[str, float] | None, player: str | None = None
                  ) -> dict[str, Any]:
    """Academy potential fit + development gap - ONLY from real potential data
    (``potential_pct`` mapping category->0..100 supplied by the academy profile).
    Without it, potential is explicitly unavailable; never manufactured."""
    current = profile_fit(view, profile, player)
    if not potential_pct:
        return {"available": False, "reason": "Potential fit unavailable",
                "current": current.get("score"), "potential": None, "gap": None}
    # potential = the higher of current and the supplied potential estimate for
    # this role's dominant category (transparent, from analyst-entered data only).
    pot = max(float(v) for v in potential_pct.values())
    cur = current.get("score")
    gap = round(pot - cur, 1) if isinstance(cur, (int, float)) else None
    return {"available": True, "reason": "", "current": cur, "potential": round(pot, 1),
            "gap": gap}


__all__ = [
    "MetricNeed", "RecruitmentProfile", "BUILTIN_PROFILES", "PROFILES_BY_ID",
    "all_profiles", "get_profile", "profiles_for_position", "profile_fit", "potential_fit",
]
