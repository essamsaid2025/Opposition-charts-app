"""Penalty intelligence (Phase 9.4) - deterministic, NO LLM. REUSES the 9.3
``Insight`` / ``Recommendation`` AI-ready dataclasses (evidence, confidence,
supporting_statistics, visualization_references) - it does not define a second
intelligence type. Turns the penalty analytics profiles into shooter, goalkeeper
and team observations plus coach recommendations, every one referencing real
registered penalty visualizations.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from fap.setpieces.intelligence import Insight, Recommendation
from fap.setpieces import penalty_analytics as PA
from fap.setpieces.penalty_model import PenaltyView

_CORNER_LABEL = {
    "top_left": "top-left", "top_center": "top-centre", "top_right": "top-right",
    "middle_left": "left", "center": "centre", "middle_right": "right",
    "bottom_left": "bottom-left", "bottom_center": "bottom-centre", "bottom_right": "bottom-right",
}


@dataclass(slots=True)
class PenaltyIntelligence:
    shooter_insights: list[Insight] = field(default_factory=list)
    goalkeeper_insights: list[Insight] = field(default_factory=list)
    team_insights: list[Insight] = field(default_factory=list)
    recommendations: list[Recommendation] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "shooter_insights": [i.to_dict() for i in self.shooter_insights],
            "goalkeeper_insights": [i.to_dict() for i in self.goalkeeper_insights],
            "team_insights": [i.to_dict() for i in self.team_insights],
            "recommendations": [r.to_dict() for r in self.recommendations],
        }


# ============================================================ shooter insights
def shooter_insights(name: str, vs: list[PenaltyView]) -> list[Insight]:
    p = PA.shooter_profile(vs)
    if not p.get("n"):
        return []
    out: list[Insight] = []
    corner = p["preferred_corner"]
    if corner:
        share = p["placement_grid"].get(corner, 0)
        out.append(Insight(
            "pen_shooter_corner", f"{name} — preferred corner",
            f"{name} prefers the {_CORNER_LABEL.get(corner, corner)} corner "
            f"({share}/{p['n']} penalties).",
            confidence=round(share / p["n"], 2),
            evidence=[f"{share}/{p['n']} placed {corner}"],
            supporting_statistics={"corner": corner, "count": share, "conversion_pct": p["conversion_pct"]},
            visualization_references=["sp_pen_placement", "sp_pen_clusters"]))
    if p["pressure"]["changes_direction"]:
        out.append(Insight(
            "pen_shooter_pressure", f"{name} — changes direction under pressure",
            f"Under pressure {name} favours the {p['pressure']['preferred_side_pressure']} side "
            f"versus the {p['pressure']['preferred_side_calm']} side when calm.",
            kind="warning", confidence=0.6,
            evidence=[f"pressure side {p['pressure']['preferred_side_pressure']}",
                      f"calm side {p['pressure']['preferred_side_calm']}"],
            supporting_statistics=p["pressure"],
            visualization_references=["sp_pen_direction", "sp_pen_placement"]))
    if _avoids_repeats(vs):
        out.append(Insight(
            "pen_shooter_norepeat", f"{name} — avoids repeating direction",
            f"{name} rarely places two consecutive penalties on the same side.",
            confidence=0.55, evidence=["low consecutive-same-side rate"],
            supporting_statistics={"repeat_rate_pct": _repeat_rate(vs)},
            visualization_references=["sp_pen_direction"]))
    pv = p["power_vs_placement"]
    out.append(Insight(
        "pen_shooter_power", f"{name} — {pv} taker",
        f"{name} is a {pv}-oriented taker "
        f"(height {p['preferred_height'] or 'n/a'}, {p['conversion_pct']}% conversion).",
        confidence=0.5, evidence=[f"power dist {p['power_distribution']}"],
        supporting_statistics={"power_vs_placement": pv, "preferred_height": p["preferred_height"],
                               "conversion_pct": p["conversion_pct"], "xg_vs_goals": p["xg_vs_goals"]},
        visualization_references=["sp_pen_height", "sp_pen_success_zones"]))
    return out


def _repeat_rate(vs: list[PenaltyView]) -> float:
    ordered = [v for v in sorted(vs, key=lambda v: (v.shootout_order or 0, v.id)) if v.side]
    if len(ordered) < 2:
        return 0.0
    repeats = sum(1 for a, b in zip(ordered, ordered[1:]) if a.side == b.side)
    return round(100.0 * repeats / (len(ordered) - 1), 1)


def _avoids_repeats(vs: list[PenaltyView]) -> bool:
    ordered = [v for v in vs if v.side]
    return len(ordered) >= 3 and _repeat_rate(vs) <= 34.0


# ============================================================ goalkeeper insights
def goalkeeper_insights(name: str, vs: list[PenaltyView]) -> list[Insight]:
    p = PA.goalkeeper_profile(vs)
    if not p.get("n"):
        return []
    out: list[Insight] = []
    if p["dive_preference"]:
        out.append(Insight(
            "pen_gk_dive", f"{name} — dive preference",
            f"{name} favours diving {p['dive_preference']} "
            f"({p['dive_distribution'].get(p['dive_preference'], 0)}/{p['n']}).",
            confidence=round(p["dive_distribution"].get(p["dive_preference"], 0) / p["n"], 2),
            evidence=[f"dive distribution {p['dive_distribution']}"],
            supporting_statistics={"dive_preference": p["dive_preference"], "save_pct": p["save_pct"]},
            visualization_references=["sp_gk_dive_heatmap", "sp_gk_dive_direction"]))
    if p["central_stay_freq"] < 15:
        out.append(Insight(
            "pen_gk_central", f"{name} — rarely stays central",
            f"{name} stays central only {p['central_stay_freq']}% of the time — commits to a side early.",
            kind="warning", confidence=0.6,
            evidence=[f"central stay {p['central_stay_freq']}%"],
            supporting_statistics={"central_stay_freq": p["central_stay_freq"]},
            visualization_references=["sp_gk_reach", "sp_gk_dive_direction"]))
    early = _early_vs_foot(vs)
    if early:
        out.append(early)
    if p["early_dive_freq"] >= 40:
        out.append(Insight(
            "pen_gk_early", f"{name} — early diver",
            f"{name} dives early on {p['early_dive_freq']}% of penalties, exploitable by delayed shots.",
            kind="warning", confidence=0.6,
            evidence=[f"early dive {p['early_dive_freq']}%"],
            supporting_statistics={"early_dive_freq": p["early_dive_freq"]},
            visualization_references=["sp_gk_dive_direction"]))
    return out


def _early_vs_foot(vs: list[PenaltyView]) -> Insight | None:
    by_foot: dict[str, list[PenaltyView]] = defaultdict(list)
    for v in vs:
        if v.foot:
            by_foot[v.foot].append(v)
    for foot, group in by_foot.items():
        early = sum(1 for v in group if v.gk_dive_timing == "early")
        if len(group) >= 3 and PA._pct(early, len(group)) >= 50:
            return Insight(
                "pen_gk_early_foot", "Dives early against a foot",
                f"The goalkeeper dives early against {foot}-footed takers "
                f"({PA._pct(early, len(group))}%).",
                kind="warning", confidence=0.6,
                evidence=[f"{early}/{len(group)} early vs {foot}-footed"],
                supporting_statistics={"foot": foot, "early_pct": PA._pct(early, len(group))},
                visualization_references=["sp_gk_dive_direction"])
    return None


# ============================================================ team insights
def team_insights(vs: list[PenaltyView]) -> list[Insight]:
    t = PA.team_analysis(vs)
    if not t.get("n"):
        return []
    out: list[Insight] = []
    if t["preferred_takers"]:
        top, stats = t["preferred_takers"][0]
        out.append(Insight(
            "pen_team_taker", "Primary penalty taker",
            f"{top} takes most penalties ({stats['attempts']}, {stats['conversion_pct']}% conversion).",
            confidence=round(stats["attempts"] / t["n"], 2),
            evidence=[f"{stats['attempts']}/{t['n']} taken by {top}"],
            supporting_statistics={"taker": top, **stats},
            visualization_references=["sp_pen_shooter"]))
    if t["rotation"]["rotates"]:
        out.append(Insight(
            "pen_team_rotation", "Rotates the first taker",
            f"The first taker changes across shootouts "
            f"({t['rotation']['distinct_first_takers']} different first takers).",
            confidence=0.55, evidence=[f"first takers {t['rotation']['first_takers']}"],
            supporting_statistics=t["rotation"],
            visualization_references=["sp_pen_shooter"]))
    lc = t["league_vs_cup"]
    if "league" in lc and "cup" in lc:
        out.append(Insight(
            "pen_team_context", "League vs cup conversion",
            f"Conversion differs by context: league {lc['league']['conversion_pct']}% "
            f"vs cup/knockout {lc['cup']['conversion_pct']}%.",
            confidence=0.5,
            evidence=[f"league {lc['league']}", f"cup {lc['cup']}"],
            supporting_statistics=lc,
            visualization_references=["sp_pen_outcome"]))
    return out


# ============================================================ recommendations
def recommendations(vs: list[PenaltyView]) -> list[Recommendation]:
    out: list[Recommendation] = []
    # analyse the dominant shooter and goalkeeper of the set
    top_shooter = _mode_name([v.shooter for v in vs])
    top_gk = _mode_name([v.goalkeeper for v in vs])
    sh = PA.shooter_profile([v for v in vs if v.shooter == top_shooter]) if top_shooter else {}
    gk = PA.goalkeeper_profile([v for v in vs if v.goalkeeper == top_gk]) if top_gk else {}

    if sh.get("preferred_corner"):
        corner = sh["preferred_corner"]
        out.append(Recommendation(
            "pen_rec_expect", f"Brief the keeper: expect {_CORNER_LABEL.get(corner, corner)} placement.",
            f"{top_shooter} places {sh['placement_grid'].get(corner, 0)}/{sh['n']} penalties there — "
            f"the single most likely target.", priority="high", confidence=0.6,
            evidence=[f"{sh['placement_grid'].get(corner, 0)}/{sh['n']} to {corner}"],
            supporting_statistics={"shooter": top_shooter, "corner": corner},
            visualization_references=["sp_pen_placement", "sp_pen_clusters"]))
        weak = _weak_side(sh["preferred_side"])
        out.append(Recommendation(
            "pen_rec_force_weak", f"Force {top_shooter} to their weak side ({weak}).",
            f"{top_shooter} strongly prefers the {sh['preferred_side']} side; angling the keeper's "
            f"stance nudges them to the less-practised {weak} side.", priority="medium", confidence=0.55,
            evidence=[f"preferred side {sh['preferred_side']}"],
            supporting_statistics={"shooter": top_shooter, "preferred_side": sh["preferred_side"]},
            visualization_references=["sp_pen_direction"]))
    if gk.get("n") and gk.get("early_dive_freq", 0) >= 40:
        out.append(Recommendation(
            "pen_rec_delay", "Delay the shot to beat the keeper's early commitment.",
            f"{top_gk} dives early {gk['early_dive_freq']}% of the time; a stutter/paradinha run "
            f"waits out the commitment.", priority="high", confidence=0.6,
            evidence=[f"early dive {gk['early_dive_freq']}%"],
            supporting_statistics={"goalkeeper": top_gk, "early_dive_freq": gk["early_dive_freq"]},
            visualization_references=["sp_gk_dive_direction"]))
    if gk.get("n") and gk.get("dive_preference"):
        out.append(Recommendation(
            "pen_rec_target_pattern", f"Target {top_gk}'s movement pattern.",
            f"{top_gk} favours diving {gk['dive_preference']}; placing to the opposite side raises the "
            f"odds of an open net.", priority="medium", confidence=0.55,
            evidence=[f"dive pref {gk['dive_preference']}"],
            supporting_statistics={"goalkeeper": top_gk, "dive_preference": gk["dive_preference"]},
            visualization_references=["sp_gk_dive_heatmap"]))
    # sudden death preparation
    if any(v.sudden_death for v in vs):
        out.append(Recommendation(
            "pen_rec_sudden_death", "Increase preparation for sudden death.",
            "This dataset includes sudden-death kicks; rehearse a designated sudden-death order and "
            "high-pressure routine.", priority="medium", confidence=0.5,
            evidence=["sudden-death penalties present"],
            supporting_statistics={"sudden_death_attempts": sum(1 for v in vs if v.sudden_death)},
            visualization_references=["sp_pen_outcome"]))
    return out


def _weak_side(side: str) -> str:
    return {"left": "right", "right": "left"}.get(side, "centre")


def _mode_name(values) -> str:
    counts: dict[str, int] = defaultdict(int)
    for v in values:
        if v:
            counts[v] += 1
    return max(counts, key=counts.get) if counts else ""


# ============================================================ orchestration
def build_penalty_intelligence(vs: list[PenaltyView]) -> PenaltyIntelligence:
    top_shooter = _mode_name([v.shooter for v in vs])
    top_gk = _mode_name([v.goalkeeper for v in vs])
    return PenaltyIntelligence(
        shooter_insights=shooter_insights(top_shooter, [v for v in vs if v.shooter == top_shooter])
        if top_shooter else [],
        goalkeeper_insights=goalkeeper_insights(top_gk, [v for v in vs if v.goalkeeper == top_gk])
        if top_gk else [],
        team_insights=team_insights(vs),
        recommendations=recommendations(vs))
