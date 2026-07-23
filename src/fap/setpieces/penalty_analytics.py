"""Penalty analytics (Phase 9.4) - PURE, deterministic. Operates on
``PenaltyView`` records (a flattened view over set-piece penalties) and produces
the shooter / goalkeeper / team / shootout intelligence plus the grids and
distributions the penalty visualizations render.

Reuses the 9.2 penalty backend (``penalties``: placement grid, dive grid, cell
geometry) and the 9.3 clustering idea - it does not re-implement statistics that
already exist elsewhere.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from fap.setpieces.penalties import PLACEMENT_CELLS
from fap.setpieces.penalty_model import PenaltyView


# ------------------------------------------------------------------ helpers
def _pct(part: float, whole: float) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


def _avg(values) -> float | None:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def _dist(values) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for v in values:
        if v:
            out[v] += 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _mode(values) -> tuple[str, dict[str, int]]:
    d = _dist(values)
    return (next(iter(d)), d) if d else ("", {})


# ============================================================ shooter analysis
def shooter_profile(vs: list[PenaltyView]) -> dict[str, Any]:
    n = len(vs)
    if not n:
        return {"n": 0}
    goals = sum(1 for v in vs if v.goal)
    saved = sum(1 for v in vs if v.saved)
    missed = sum(1 for v in vs if v.missed)
    xg = round(sum((v.xg or 0.0) for v in vs), 2)
    hard = sum(1 for v in vs if v.power == "hard")
    placed = sum(1 for v in vs if v.power in ("soft", "medium"))
    pv = "power" if hard > placed else ("placement" if placed > hard else "balanced")
    pressured = [v for v in vs if v.pressure]
    calm = [v for v in vs if not v.pressure]
    p_side = _mode([v.side for v in pressured])[0]
    c_side = _mode([v.side for v in calm])[0]
    shootout = [v for v in vs if v.in_shootout]
    return {
        "n": n, "goals": goals, "saved": saved, "missed": missed,
        "conversion_pct": _pct(goals, n), "xg": xg, "xg_vs_goals": round(goals - xg, 2),
        "preferred_side": _mode([v.side for v in vs])[0],
        "preferred_corner": _mode([v.placement for v in vs])[0],
        "preferred_height": _mode([v.height for v in vs])[0],
        "preferred_trajectory": _mode([v.trajectory for v in vs])[0],
        "power_vs_placement": pv, "power_distribution": _dist([v.power for v in vs]),
        "run_up_distance": _avg(v.run_up_distance for v in vs),
        "run_up_angle": _avg(v.run_up_angle for v in vs),
        "last_step": _mode([v.last_step for v in vs])[0],
        "body_orientation": _mode([v.body_orientation for v in vs])[0],
        "body_distribution": _dist([v.body_orientation for v in vs]),
        "technique": _mode([v.technique for v in vs])[0],
        "technique_distribution": _dist([v.technique for v in vs]),
        "miss_reasons": _dist([v.miss_reason for v in vs if v.missed or v.saved]),
        "pressure": {
            "attempts": len(pressured), "conversion_pct": _pct(sum(v.goal for v in pressured), len(pressured)),
            "calm_conversion_pct": _pct(sum(v.goal for v in calm), len(calm)),
            "preferred_side_pressure": p_side, "preferred_side_calm": c_side,
            "changes_direction": bool(p_side and c_side and p_side != c_side),
        },
        "shootout": {"attempts": len(shootout),
                     "conversion_pct": _pct(sum(v.goal for v in shootout), len(shootout))},
        "footedness": {"foot": _mode([v.foot for v in vs])[0],
                       "side_by_foot": _side_by_foot(vs)},
        "placement_grid": _cell_counts(vs),
    }


def _side_by_foot(vs: list[PenaltyView]) -> dict[str, str]:
    out: dict[str, str] = {}
    for foot in ("left", "right"):
        sub = [v for v in vs if v.foot == foot]
        if sub:
            out[foot] = _mode([v.side for v in sub])[0]
    return out


# ============================================================ goalkeeper analysis
def goalkeeper_profile(vs: list[PenaltyView]) -> dict[str, Any]:
    n = len(vs)
    if not n:
        return {"n": 0}
    saved = sum(1 for v in vs if v.saved)
    dives = _dist([v.gk_dive for v in vs])
    stay = sum(1 for v in vs if v.gk_dive in ("stay", "center") or v.gk_stayed_central)
    timings = _dist([v.gk_dive_timing for v in vs])
    saved_pens = [v for v in vs if v.saved]
    return {
        "n": n, "saved": saved, "conceded": n - saved, "save_pct": _pct(saved, n),
        "dive_preference": _mode([v.gk_dive for v in vs])[0], "dive_distribution": dives,
        "stay_vs_dive": {"stay_pct": _pct(stay, n), "dive_pct": _pct(n - stay, n)},
        "central_stay_freq": _pct(stay, n),
        "early_dive_freq": _pct(timings.get("early", 0), n),
        "late_dive_freq": _pct(timings.get("late", 0), n),
        "on_time_freq": _pct(timings.get("on_time", 0), n),
        "preferred_side": _mode([v.gk_dive for v in vs if v.gk_dive in ("left", "right")])[0],
        "save_location": _mode([v.placement for v in saved_pens])[0],
        "starting_position": {"x": _avg(v.gk_start_x for v in vs), "y": _avg(v.gk_start_y for v in vs)},
        "reaction": _avg(v.gk_reaction for v in vs),
        "reach_area": _avg(v.gk_reach for v in vs),
        "correct_guess_pct": _pct(sum(1 for v in vs if v.gk_correct), n),
        "distribution_after": _mode([v.distribution_after for v in vs])[0],
        "distribution_breakdown": _dist([v.distribution_after for v in vs]),
    }


# ============================================================ team analysis
def team_analysis(vs: list[PenaltyView]) -> dict[str, Any]:
    n = len(vs)
    if not n:
        return {"n": 0}

    def success_by(keyfn):
        buckets: dict[str, list[PenaltyView]] = defaultdict(list)
        for v in vs:
            k = keyfn(v)
            if k:
                buckets[k].append(v)
        return {k: {"attempts": len(g), "goals": sum(x.goal for x in g),
                    "conversion_pct": _pct(sum(x.goal for x in g), len(g))}
                for k, g in buckets.items()}

    takers = success_by(lambda v: v.shooter)
    minute_buckets = success_by(lambda v: f"{(v.minute // 15) * 15}-{(v.minute // 15) * 15 + 15}"
                                if v.minute is not None else "")
    home_away = success_by(lambda v: v.venue)
    league_cup = success_by(lambda v: "cup" if v.importance in ("cup", "knockout", "final")
                            else ("league" if v.importance == "league" else ""))
    return {
        "n": n, "conversion_pct": _pct(sum(v.goal for v in vs), n),
        "preferred_takers": sorted(takers.items(), key=lambda kv: -kv[1]["attempts"])[:8],
        "preferred_foot": _mode([v.foot for v in vs])[0],
        "shooter_order": _shooter_order(vs), "rotation": _rotation(vs),
        "success_by_player": takers,
        "success_by_competition": success_by(lambda v: v.competition),
        "success_by_venue": home_away, "home_vs_away": home_away,
        "league_vs_cup": league_cup,
        "success_by_importance": success_by(lambda v: v.importance),
        "success_by_match_state": success_by(lambda v: v.match_state),
        "success_by_minute": minute_buckets,
        "tournament": success_by(lambda v: v.competition),
    }


def _shooter_order(vs: list[PenaltyView]) -> list[dict[str, Any]]:
    order: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for v in vs:
        o = v.shooter_order or v.shootout_order
        if o and v.shooter:
            order[o][v.shooter] += 1
    return [{"order": o, "shooter": max(sh, key=sh.get), "count": sh[max(sh, key=sh.get)]}
            for o, sh in sorted(order.items())]


def _rotation(vs: list[PenaltyView]) -> dict[str, Any]:
    """Does the FIRST taker change across shootouts? (rotation strategy)."""
    firsts: dict[str, str] = {}
    for v in vs:
        if v.in_shootout and (v.shootout_order == 1):
            firsts[v.shootout_id] = v.shooter
    distinct = set(firsts.values())
    return {"shootouts": len(firsts), "distinct_first_takers": len(distinct),
            "rotates": len(distinct) > 1, "first_takers": list(distinct)}


# ============================================================ shootout analysis
def shootout_analysis(vs: list[PenaltyView]) -> list[dict[str, Any]]:
    by_id: dict[str, list[PenaltyView]] = defaultdict(list)
    for v in vs:
        if v.in_shootout:
            by_id[v.shootout_id].append(v)
    out: list[dict[str, Any]] = []
    for sid, attempts in by_id.items():
        attempts = sorted(attempts, key=lambda v: (v.shootout_order or 0))
        score: dict[str, int] = defaultdict(int)
        gk_perf: dict[str, int] = defaultdict(int)
        seq, momentum = [], []
        teams = list(dict.fromkeys(v.team for v in attempts if v.team))
        for i, v in enumerate(attempts, start=1):
            if v.goal:
                score[v.team] += 1
            if v.saved and v.goalkeeper:
                gk_perf[v.goalkeeper] += 1
            others = [t for t in teams if t != v.team]
            diff = score[v.team] - (score[others[0]] if others else 0)
            momentum.append(diff)
            seq.append({
                "order": v.shootout_order or i, "team": v.team, "shooter": v.shooter,
                "outcome": v.outcome, "goal": v.goal, "sudden_death": v.sudden_death,
                "winning_penalty": v.winning_penalty, "deciding_penalty": v.deciding_penalty,
                "equalizing_penalty": v.equalizing_penalty,
                "pressure_index": _pressure_index(v, i, diff),
                "running_score": dict(score),
            })
        winner = max(score, key=score.get) if score else ""
        out.append({
            "shootout_id": sid, "teams": teams, "attempts": len(attempts),
            "score": dict(score), "winner": winner,
            "sudden_death": any(v.sudden_death for v in attempts),
            "sequence": seq, "momentum": momentum,
            "gk_performance": dict(gk_perf),
            "shooter_confidence": _confidence_trend(attempts),
        })
    return out


def _pressure_index(v: PenaltyView, order: int, diff: int) -> int:
    """Deterministic 0-100 pressure score: later kicks, sudden death and decisive
    moments raise it; a close scoreline raises it further."""
    pi = 25 + order * 6
    if v.sudden_death:
        pi += 30
    if v.deciding_penalty or v.winning_penalty:
        pi += 25
    if v.equalizing_penalty:
        pi += 15
    pi += max(0, 15 - abs(diff) * 5)          # closer scoreline = more pressure
    return int(min(100, pi))


def _confidence_trend(attempts: list[PenaltyView]) -> list[dict[str, Any]]:
    by_team: dict[str, list[int]] = defaultdict(list)
    trend = []
    for v in attempts:
        by_team[v.team].append(1 if v.goal else 0)
        made = sum(by_team[v.team])
        taken = len(by_team[v.team])
        trend.append({"team": v.team, "conversion_pct": _pct(made, taken)})
    return trend


# ============================================================ grids / distributions
def _cell_counts(vs: list[PenaltyView]) -> dict[str, int]:
    return _dist([v.placement for v in vs])


def placement_points(vs: list[PenaltyView], *, only=None) -> list[dict[str, Any]]:
    """(gx, gy) points in the 3x3 goal grid for placement/goal/miss heatmaps.
    ``only`` filters to 'goal' or 'miss'."""
    out = []
    for v in vs:
        if only == "goal" and not v.goal:
            continue
        if only == "miss" and v.goal:
            continue
        cell = v.placement
        if cell in PLACEMENT_CELLS:
            gx, gy = PLACEMENT_CELLS[cell]
            out.append({"gx": gx, "gy": gy, "cell": cell, "outcome": v.outcome,
                        "goal": v.goal, "shooter": v.shooter})
    return out


def height_distribution(vs: list[PenaltyView]) -> list[dict[str, Any]]:
    d = _dist([v.height for v in vs])
    return [{"height": k, "count": n} for k, n in d.items()]


def direction_distribution(vs: list[PenaltyView]) -> list[dict[str, Any]]:
    d = _dist([v.side for v in vs])
    return [{"side": k, "count": n} for k, n in d.items()]


def zone_conversion(vs: list[PenaltyView]) -> list[dict[str, Any]]:
    """Per-cell conversion (success vs failure zones)."""
    buckets: dict[str, list[PenaltyView]] = defaultdict(list)
    for v in vs:
        if v.placement in PLACEMENT_CELLS:
            buckets[v.placement].append(v)
    rows = []
    for cell, g in buckets.items():
        gx, gy = PLACEMENT_CELLS[cell]
        rows.append({"cell": cell, "gx": gx, "gy": gy, "attempts": len(g),
                     "goals": sum(v.goal for v in g),
                     "conversion_pct": _pct(sum(v.goal for v in g), len(g))})
    return rows


def reach_points(vs: list[PenaltyView]) -> list[dict[str, Any]]:
    """Goalkeeper reach/dive endpoints in the goal grid (dive side x reach)."""
    dirs = {"left": -1.0, "right": 1.0, "stay": 0.0, "center": 0.0}
    out = []
    for v in vs:
        if not v.gk_dive:
            continue
        reach = (v.gk_reach or 1.0)
        out.append({"gx": 1.0 + dirs.get(v.gk_dive, 0.0) * reach, "gy": 1.0,
                    "saved": v.saved, "goalkeeper": v.goalkeeper, "dive": v.gk_dive})
    return out


def placement_clusters(vs: list[PenaltyView]) -> list[dict[str, Any]]:
    """Deterministic placement clusters = grouping by goal cell with conversion
    (reuses the cell geometry rather than a heavy clustering pass)."""
    rows = zone_conversion(vs)
    return sorted(rows, key=lambda r: -r["attempts"])
