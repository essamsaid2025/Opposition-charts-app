"""Set Piece analytics engine (Phase 9.1) - PURE functions (no Streamlit, no
matplotlib, no DB). Everything a dashboard, a report section or a Phase-9.2
visualization needs is computed here and returned as plain data (dicts / lists of
dicts / DataFrames), so:

  * the dashboards render it with native widgets (no new viz engine),
  * the report section builder turns it into report KPIs/Tables/Insights, and
  * the 9.2 visual layer plugs a pitch renderer onto the SAME datasets without
    re-deriving anything.

Two families of output:
  1. STATISTICS - overview KPIs, per-type breakdowns, delivery/outcome/derived
     rates (success, goal contribution, chance creation, xG).
  2. MAP DATASETS - coordinate collections for delivery / shot / first-contact /
     second-ball / delivery-accuracy maps, plus the box-occupancy backends
     (zone counts, player x zone matrix, density points, movement vectors,
     goalkeeper positions, defensive shape, marking classification).

All inputs are lists of the setpieces domain models; callers fetch them through
the repositories and pass them in. Nothing here touches persistence.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import Any, Iterable

from fap.setpieces.analysis import PENALTY_AREA, in_rect, zone_for
from fap.setpieces.models import (
    CONTACT_KINDS, OCCUPANCY_ROLES, SetPiece, SetPieceContact, SetPiecePosition,
)


# ------------------------------------------------------------------ tiny helpers
def _pct(part: float, whole: float) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


def _avg(values: Iterable[float]) -> float | None:
    vals = [v for v in values if v is not None]
    return round(mean(vals), 2) if vals else None


def _coords(x: Any, y: Any) -> bool:
    return x is not None and y is not None


# ================================================================== statistics
def overview(sps: list[SetPiece]) -> dict[str, Any]:
    """Headline KPIs for a set of set pieces (any filter / phase / type)."""
    total = len(sps)
    goals = sum(1 for s in sps if s.goal)
    shots = sum(1 for s in sps if s.shot)
    fc_known = [s for s in sps if s.first_contact_team in ("attack", "defence")]
    fc_attack = sum(1 for s in fc_known if s.first_contact_team == "attack")
    sb_known = [s for s in sps if s.second_ball_team in ("attack", "defence")]
    sb_attack = sum(1 for s in sb_known if s.second_ball_team == "attack")
    retained = sum(1 for s in sps if s.retained)
    xgs = [s.xg for s in sps if s.xg is not None]
    return {
        "total": total,
        "goals": goals,
        "shots": shots,
        "xg": round(sum(xgs), 2) if xgs else 0.0,
        "xg_per_sp": round(sum(xgs) / total, 3) if (xgs and total) else 0.0,
        "shot_pct": _pct(shots, total),
        "goal_pct": _pct(goals, total),
        "first_contact_pct": _pct(fc_attack, len(fc_known)),
        "second_ball_pct": _pct(sb_attack, len(sb_known)),
        "retention_pct": _pct(retained, total),
        "avg_players_in_box": _avg(s.players_in_box for s in sps),
        "avg_time_to_first_contact": _avg(s.time_to_first_contact for s in sps),
        "avg_time_to_shot": _avg(s.time_to_shot for s in sps),
        # categorical "averages" are reported as modal shares (professional decks
        # show the dominant delivery height/length, not a numeric mean)
        "delivery_height_mode": _mode(s.delivery_height for s in sps),
        "delivery_length_mode": _mode(s.delivery_length for s in sps),
    }


def _mode(values: Iterable[str]) -> str:
    counts: dict[str, int] = defaultdict(int)
    for v in values:
        if v:
            counts[v] += 1
    return max(counts, key=counts.get) if counts else ""


def derived_rates(sps: list[SetPiece]) -> dict[str, Any]:
    """Success rate, goal contribution and chance creation - the three headline
    efficiency metrics. 'Success' = the attacking team keeps the initiative
    (goal, shot or retained possession)."""
    total = len(sps)
    success = sum(1 for s in sps if s.goal or s.shot or s.retained)
    goals = sum(1 for s in sps if s.goal)
    shots = sum(1 for s in sps if s.shot)
    return {
        "success_rate": _pct(success, total),
        "goal_contribution": _pct(goals, total),      # goals per set piece
        "goals_per_10": round(10.0 * goals / total, 2) if total else 0.0,
        "chance_creation": _pct(shots, total),         # shot per set piece
        "shots_per_10": round(10.0 * shots / total, 2) if total else 0.0,
    }


def by_type(sps: list[SetPiece]) -> dict[str, dict[str, Any]]:
    """Per set-piece-type statistics (corner / free_kick / throw_in / kick_off /
    penalty), each a compact overview - drives the per-type stat cards."""
    buckets: dict[str, list[SetPiece]] = defaultdict(list)
    for s in sps:
        buckets[s.type].append(s)
    out: dict[str, dict[str, Any]] = {}
    for t, group in buckets.items():
        ov = overview(group)
        out[t] = {"count": ov["total"], "goals": ov["goals"], "shots": ov["shots"],
                  "shot_pct": ov["shot_pct"], "goal_pct": ov["goal_pct"],
                  "first_contact_pct": ov["first_contact_pct"], "xg": ov["xg"]}
    return out


def _distribution(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for v in values:
        counts[v or "unknown"] += 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def delivery_breakdown(sps: list[SetPiece]) -> dict[str, dict[str, int]]:
    """Distributions across delivery type / height / length / speed / side."""
    return {
        "delivery_type": _distribution(s.delivery_type for s in sps),
        "height": _distribution(s.delivery_height for s in sps),
        "length": _distribution(s.delivery_length for s in sps),
        "speed": _distribution(s.delivery_speed for s in sps),
        "side": _distribution(s.side for s in sps),
    }


def outcome_breakdown(sps: list[SetPiece]) -> dict[str, int]:
    return _distribution(s.outcome for s in sps)


# ================================================================= map datasets
# Each returns a list of {x, y, ...} dicts. 9.2 will feed these straight into
# the pitch density/scatter/arrow layers; 9.1 dashboards show counts/tables.
def delivery_points(sps: list[SetPiece]) -> list[dict[str, Any]]:
    """Landing coordinates of each delivery (end_x/end_y)."""
    return [{"x": s.end_x, "y": s.end_y, "type": s.type, "outcome": s.outcome,
             "goal": s.goal, "shot": s.shot, "delivery_type": s.delivery_type,
             "side": s.side, "set_piece_id": s.id}
            for s in sps if _coords(s.end_x, s.end_y)]


def shot_points(sps: list[SetPiece], contacts: list[SetPieceContact]) -> list[dict[str, Any]]:
    """Shot locations: prefer explicit shot contacts, else the set piece's first
    contact coordinate when it is flagged as a shot."""
    out = [{"x": c.x, "y": c.y, "player": c.player, "body_part": c.body_part,
            "outcome": c.outcome, "set_piece_id": c.set_piece_id}
           for c in contacts if c.kind == "shot" and _coords(c.x, c.y)]
    have = {c.set_piece_id for c in contacts if c.kind == "shot"}
    for s in sps:
        if s.shot and s.id not in have and _coords(s.first_contact_x, s.first_contact_y):
            out.append({"x": s.first_contact_x, "y": s.first_contact_y, "player": s.taker,
                        "body_part": "", "outcome": "goal" if s.goal else "shot",
                        "set_piece_id": s.id})
    return out


def first_contact_points(sps: list[SetPiece],
                         contacts: list[SetPieceContact]) -> list[dict[str, Any]]:
    """Where first contact is won: explicit first_contact contacts, else the set
    piece's first_contact coordinate."""
    out = [{"x": c.x, "y": c.y, "team": c.team, "player": c.player,
            "body_part": c.body_part, "outcome": c.outcome, "won": c.won,
            "set_piece_id": c.set_piece_id}
           for c in contacts if c.kind == "first_contact" and _coords(c.x, c.y)]
    have = {c.set_piece_id for c in contacts if c.kind == "first_contact"}
    for s in sps:
        if s.id not in have and _coords(s.first_contact_x, s.first_contact_y):
            out.append({"x": s.first_contact_x, "y": s.first_contact_y,
                        "team": s.first_contact_team, "player": "", "body_part": "",
                        "outcome": s.outcome, "won": s.first_contact_team == "attack",
                        "set_piece_id": s.id})
    return out


def second_ball_points(contacts: list[SetPieceContact]) -> list[dict[str, Any]]:
    return [{"x": c.x, "y": c.y, "team": c.team, "player": c.player,
             "outcome": c.outcome, "won": c.won, "distance": c.distance,
             "set_piece_id": c.set_piece_id}
            for c in contacts if c.kind == "second_ball" and _coords(c.x, c.y)]


def delivery_accuracy(sps: list[SetPiece]) -> list[dict[str, Any]]:
    """Expected target vs actual landing. Expected target is read from the set
    piece document ('target_x'/'target_y') when the analyst tagged one; deviation
    is the euclidean error. Backend for the 9.2 Delivery Accuracy map."""
    out: list[dict[str, Any]] = []
    for s in sps:
        tx = s.document.get("target_x")
        ty = s.document.get("target_y")
        if _coords(tx, ty) and _coords(s.end_x, s.end_y):
            dx, dy = float(s.end_x) - float(tx), float(s.end_y) - float(ty)
            out.append({"target_x": tx, "target_y": ty, "actual_x": s.end_x,
                        "actual_y": s.end_y, "error": round((dx * dx + dy * dy) ** 0.5, 2),
                        "set_piece_id": s.id})
    return out


# ============================================================ occupancy backends
# The professional box-occupancy analytics. These consume tagged positions
# (SetPiecePosition). 9.2 renders them; 9.1 exposes the numbers and tables.
def occupancy_zone_counts(positions: list[SetPiecePosition], *, team: str = "attack",
                          n_set_pieces: int = 0) -> list[dict[str, Any]]:
    """Per-zone occupancy: total appearances, average players per set piece and
    frequency share. ``n_set_pieces`` lets us report an average-per-delivery."""
    rel = [p for p in positions if p.team == team]
    by_zone: dict[str, int] = defaultdict(int)
    for p in rel:
        by_zone[p.role or p.zone or "unassigned"] += 1
    total = sum(by_zone.values()) or 1
    rows = []
    for role in (*OCCUPANCY_ROLES, "unassigned"):
        n = by_zone.get(role, 0)
        if n == 0 and role == "unassigned":
            continue
        rows.append({
            "zone": role, "appearances": n,
            "avg_per_set_piece": round(n / n_set_pieces, 2) if n_set_pieces else None,
            "frequency_pct": _pct(n, total),
        })
    return sorted(rows, key=lambda r: -r["appearances"])


def occupancy_matrix(positions: list[SetPiecePosition], *, team: str = "attack",
                     n_set_pieces: int = 0) -> dict[str, Any]:
    """Player x zone matrix - rows players, columns zones, values appearances (+
    %). Backend for the Zone Occupancy Matrix visual."""
    rel = [p for p in positions if p.team == team and p.player]
    zones = list(OCCUPANCY_ROLES)
    players = sorted({p.player for p in rel})
    grid: dict[str, dict[str, int]] = {pl: defaultdict(int) for pl in players}
    for p in rel:
        z = p.role or p.zone
        if z in zones:
            grid[p.player][z] += 1
    rows = []
    for pl in players:
        appearances = sum(grid[pl].values())
        rows.append({"player": pl, "total": appearances,
                     "cells": {z: grid[pl].get(z, 0) for z in zones},
                     "pct": {z: _pct(grid[pl].get(z, 0), appearances) for z in zones}})
    return {"zones": zones, "players": players, "rows": rows,
            "n_set_pieces": n_set_pieces}


def occupancy_density_points(positions: list[SetPiecePosition], *,
                             team: str = "attack", moment: str = "delivery") -> list[dict[str, Any]]:
    """Raw (x, y) points for the box-occupancy heatmap density layer."""
    return [{"x": p.x, "y": p.y, "player": p.player, "role": p.role or p.zone}
            for p in positions
            if p.team == team and p.moment == moment and _coords(p.x, p.y)]


def movement_vectors(positions: list[SetPiecePosition], *,
                     team: str = "attack") -> list[dict[str, Any]]:
    """Per-player movement across moments (before -> delivery -> after) as arrows.
    Backend for the Player Movement Map. Groups by (set_piece_id, player)."""
    by_key: dict[tuple[str, str], dict[str, SetPiecePosition]] = defaultdict(dict)
    for p in positions:
        if p.team == team and p.player and _coords(p.x, p.y):
            by_key[(p.set_piece_id, p.player)][p.moment] = p
    order = ("before", "delivery", "after")
    out: list[dict[str, Any]] = []
    for (sp_id, player), moments in by_key.items():
        seq = [moments[m] for m in order if m in moments]
        for a, b in zip(seq, seq[1:]):
            out.append({"x0": a.x, "y0": a.y, "x1": b.x, "y1": b.y, "player": player,
                        "run_type": b.run_type or a.run_type, "set_piece_id": sp_id,
                        "from": a.moment, "to": b.moment})
    return out


def goalkeeper_positions(positions: list[SetPiecePosition]) -> list[dict[str, Any]]:
    """Goalkeeper coordinates (defensive side) - Goalkeeper Position Map backend."""
    return [{"x": p.x, "y": p.y, "moment": p.moment, "set_piece_id": p.set_piece_id}
            for p in positions if p.is_gk and _coords(p.x, p.y)]


def defensive_shape(positions: list[SetPiecePosition]) -> dict[str, Any]:
    """Average defending positions + line height + near/far post presence.
    Backend for the Defensive Shape visual."""
    defenders = [p for p in positions if p.team == "defence" and _coords(p.x, p.y)
                 and not p.is_gk]
    if not defenders:
        return {"count": 0, "line_height": None, "avg_x": None, "avg_y": None,
                "near_post": 0, "far_post": 0, "six_yard": 0, "positions": []}
    xs = [float(p.x) for p in defenders]
    ys = [float(p.y) for p in defenders]
    return {
        "count": len(defenders),
        "line_height": round(min(xs), 1),          # deepest defender = line height
        "avg_x": round(mean(xs), 1),
        "avg_y": round(mean(ys), 1),
        "near_post": sum(1 for p in defenders if (p.role or p.zone) == "near_post"),
        "far_post": sum(1 for p in defenders if (p.role or p.zone) in ("far_post", "back_post")),
        "six_yard": sum(1 for p in defenders if (p.role or p.zone) in ("six_yard", "gk_area")),
        "positions": [{"x": p.x, "y": p.y, "role": p.role or p.zone,
                       "marking": p.marking} for p in defenders],
    }


def classify_marking(positions: list[SetPiecePosition]) -> dict[str, Any]:
    """Classify a defensive setup as man / zonal / hybrid from the per-defender
    marking tags, with a confidence score. Backend for Marking Detection.

    Heuristic (deterministic, no ML dependency): the share of defenders tagged
    'man' vs 'zonal' decides the scheme; a near-even split is 'hybrid'. Confidence
    is the dominant share (or the balance, for hybrid)."""
    defenders = [p for p in positions if p.team == "defence" and not p.is_gk]
    tags = [p.marking for p in defenders if p.marking in ("man", "zonal")]
    n = len(tags)
    if n == 0:
        return {"scheme": "unknown", "confidence": 0.0, "man": 0, "zonal": 0, "n": 0}
    man = tags.count("man")
    zonal = tags.count("zonal")
    man_share, zonal_share = man / n, zonal / n
    if 0.35 <= man_share <= 0.65:
        scheme, confidence = "hybrid", round(1.0 - abs(man_share - 0.5) * 2, 2)
    elif man_share > zonal_share:
        scheme, confidence = "man", round(man_share, 2)
    else:
        scheme, confidence = "zonal", round(zonal_share, 2)
    return {"scheme": scheme, "confidence": confidence, "man": man, "zonal": zonal, "n": n}


def players_in_box_estimate(positions: list[SetPiecePosition], *, team: str = "attack") -> int:
    """Count tagged players inside the penalty area (fallback when the set piece
    row did not record players_in_box)."""
    return sum(1 for p in positions
               if p.team == team and in_rect(p.x, p.y, PENALTY_AREA))
