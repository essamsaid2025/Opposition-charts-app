"""Frame builder (Phase 9.2) - maps a visualization's ``sp_dataset`` kind to the
viz-ready rows the plugin renders. PURE apart from reading through the service's
repositories. Reuses the 9.1 analytics and the penalty backend; adds no new
statistics of its own beyond light reshaping (renaming to x/y/end_x/end_y).

Every set-piece visualization declares one of these kinds; the service turns the
returned rows into a DataFrame and hands it to the existing Renderer as ctx.df.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from fap.setpieces import analytics as AN
from fap.setpieces import penalties as PEN
from fap.setpieces.models import SetPiece


def rows(svc: Any, sps: list[SetPiece], kind: str) -> list[dict[str, Any]]:
    fn = _KINDS.get(kind)
    return fn(svc, sps) if fn else []


# ------------------------------------------------------------------ occupancy
def _occ_density(svc, sps):
    pos = svc._positions_of(sps)
    return AN.occupancy_density_points(pos, team="attack", moment="delivery")


def _occ_avg(svc, sps):
    pts = _occ_density(svc, sps)
    agg: dict[str, list] = defaultdict(list)
    for p in pts:
        if p.get("player"):
            agg[p["player"]].append((p["x"], p["y"]))
    out = []
    for player, xy in agg.items():
        out.append({"x": sum(a for a, _ in xy) / len(xy),
                    "y": sum(b for _, b in xy) / len(xy), "player": player})
    return out


def _occ_timeline(svc, sps):
    bands: dict[str, int] = defaultdict(int)
    for s in sps:
        m = s.minute if s.minute is not None else 0
        lo = (int(m) // 15) * 15
        bands[f"{lo}-{lo + 15}"] += 1
    order = sorted(bands, key=lambda b: int(b.split("-")[0]))
    return [{"label": b, "value": bands[b]} for b in order]


def _def_positions(svc, sps):
    pos = svc._positions_of(sps)
    return [{"x": p.x, "y": p.y, "role": p.role or p.zone, "marking": p.marking,
             "player": p.player} for p in pos
            if p.team == "defence" and not p.is_gk and p.x is not None and p.y is not None]


# ------------------------------------------------------------------ delivery
def _delivery(svc, sps):
    return AN.delivery_points(sps)


def _delivery_success(svc, sps):
    out = AN.delivery_points(sps)
    for r in out:
        r["success"] = bool(r.get("goal") or r.get("shot"))
    return out


def _delivery_accuracy(svc, sps):
    return [{"x": r["target_x"], "y": r["target_y"], "end_x": r["actual_x"],
             "end_y": r["actual_y"], "error": r["error"]}
            for r in AN.delivery_accuracy(sps)]


def _delivery_trajectory(svc, sps):
    return [{"x": s.start_x, "y": s.start_y, "end_x": s.end_x, "end_y": s.end_y,
             "outcome": s.outcome, "goal": s.goal}
            for s in sps
            if None not in (s.start_x, s.start_y, s.end_x, s.end_y)]


# ------------------------------------------------------------------ contacts
def _shot(svc, sps):
    contacts = svc._contacts_of(sps)
    by_id = {s.id: s for s in sps}
    out = AN.shot_points(sps, contacts)
    for r in out:
        s = by_id.get(r.get("set_piece_id"))
        r["xg"] = s.xg if s else None
        r["goal"] = (r.get("outcome") == "goal")
    return out


def _goals(svc, sps):
    return [r for r in _shot(svc, sps) if r.get("goal")]


def _first_contact(svc, sps):
    return AN.first_contact_points(sps, svc._contacts_of(sps))


def _second_ball(svc, sps):
    return AN.second_ball_points(svc._contacts_of(sps))


def _clearance(svc, sps):
    out = [{"x": c.x, "y": c.y, "player": c.player, "team": c.team}
           for c in svc._contacts_of(sps)
           if (c.kind == "clearance" or c.outcome == "clearance")
           and c.x is not None and c.y is not None]
    return out


def _flick_on(svc, sps):
    return [{"x": c.x, "y": c.y, "player": c.player}
            for c in svc._contacts_of(sps)
            if c.kind == "first_contact" and c.body_part == "head"
            and c.x is not None and c.y is not None]


def _shot_assist(svc, sps):
    shots = {r["set_piece_id"]: r for r in _shot(svc, sps) if r.get("set_piece_id")}
    out = []
    for s in sps:
        sh = shots.get(s.id)
        if sh and None not in (s.end_x, s.end_y, sh["x"], sh["y"]):
            out.append({"x": s.end_x, "y": s.end_y, "end_x": sh["x"], "end_y": sh["y"]})
    return out


def _threat(svc, sps):
    return _shot(svc, sps)


# ------------------------------------------------------------------ movement
def _movement(svc, sps, run_type=None):
    vecs = AN.movement_vectors(svc._positions_of(sps), team="attack")
    out = []
    for v in vecs:
        if run_type and (v.get("run_type") != run_type):
            continue
        out.append({"x": v["x0"], "y": v["y0"], "end_x": v["x1"], "end_y": v["y1"],
                    "run_type": v.get("run_type"), "player": v.get("player"), "team": "attack"})
    return out


def _movement_posts(svc, sps):
    vecs = AN.movement_vectors(svc._positions_of(sps), team="attack")
    return [{"x": v["x0"], "y": v["y0"], "end_x": v["x1"], "end_y": v["y1"],
             "player": v.get("player"), "team": "attack"}
            for v in vecs if v.get("run_type") in ("near_post", "far_post")]


def _blockers(svc, sps):
    return _by_run(svc, sps, "block")


def _screens(svc, sps):
    return _by_run(svc, sps, "screen")


def _by_run(svc, sps, run_type):
    return [{"x": p.x, "y": p.y, "player": p.player}
            for p in svc._positions_of(sps)
            if p.run_type == run_type and p.x is not None and p.y is not None]


def _wall(svc, sps):
    fk_ids = {s.id for s in sps if s.type == "free_kick"}
    out = []
    for p in svc._positions_of(sps):
        is_wall = p.run_type == "wall" or p.role == "wall" or \
            (p.set_piece_id in fk_ids and p.team == "defence" and not p.is_gk)
        if is_wall and p.x is not None and p.y is not None:
            out.append({"x": p.x, "y": p.y, "player": p.player})
    return out


def _marking_assignment(svc, sps):
    """Arrow each defender -> nearest attacker within the same set piece."""
    by_sp: dict[str, dict[str, list]] = defaultdict(lambda: {"attack": [], "defence": []})
    for p in svc._positions_of(sps):
        if p.x is None or p.y is None or p.is_gk:
            continue
        by_sp[p.set_piece_id][p.team].append(p)
    out = []
    for groups in by_sp.values():
        atts = groups["attack"]
        for d in groups["defence"]:
            if not atts:
                continue
            nearest = min(atts, key=lambda a: (a.x - d.x) ** 2 + (a.y - d.y) ** 2)
            out.append({"x": d.x, "y": d.y, "end_x": nearest.x, "end_y": nearest.y,
                        "player": d.player})
    return out


# ------------------------------------------------------------------ goalkeeper
def _gk_start(svc, sps):
    return AN.goalkeeper_positions(svc._positions_of(sps))


def _gk_move(svc, sps):
    by_key: dict[tuple, dict] = defaultdict(dict)
    for p in svc._positions_of(sps):
        if p.is_gk and p.x is not None and p.y is not None:
            by_key[p.set_piece_id][p.moment] = p
    order = ("before", "delivery", "after")
    out = []
    for moments in by_key.values():
        seq = [moments[m] for m in order if m in moments]
        for a, b in zip(seq, seq[1:]):
            out.append({"x": a.x, "y": a.y, "end_x": b.x, "end_y": b.y})
    return out


# ------------------------------------------------------------------ penalties
def _pen_placement(svc, sps):
    return PEN.placement_grid(sps)["points"]


def _pen_dive(svc, sps):
    return [{"direction": d, "count": n} for d, n in PEN.dive_grid(sps)["dives"].items()]


def _pen_dive_direction(svc, sps):
    return PEN.dive_direction(sps)


def _pen_outcome(svc, sps):
    return [{"outcome": o, "count": n} for o, n in PEN.outcomes(sps)["counts"].items()]


def _pen_shooter(svc, sps):
    return [{"name": k, **v} for k, v in PEN.shooter_preference(sps).items()]


def _pen_gk(svc, sps):
    return [{"name": k, **v} for k, v in PEN.goalkeeper_preference(sps).items()]


# --- Phase 9.4 penalty module datasets (view-based) --------------------------
def _pviews(sps):
    from fap.setpieces import penalty_model as PM
    return PM.views(sps)


def _pen_goal(svc, sps):
    from fap.setpieces import penalty_analytics as PA
    return PA.placement_points(_pviews(sps), only="goal")


def _pen_miss(svc, sps):
    from fap.setpieces import penalty_analytics as PA
    return PA.placement_points(_pviews(sps), only="miss")


def _pen_shots(svc, sps):
    from fap.setpieces import penalty_analytics as PA
    return PA.placement_points(_pviews(sps))


def _pen_reach(svc, sps):
    from fap.setpieces import penalty_analytics as PA
    return PA.reach_points(_pviews(sps))


def _pen_clusters(svc, sps):
    from fap.setpieces import penalty_analytics as PA
    return PA.placement_clusters(_pviews(sps))


def _pen_height(svc, sps):
    from fap.setpieces import penalty_analytics as PA
    return PA.height_distribution(_pviews(sps))


def _pen_direction(svc, sps):
    from fap.setpieces import penalty_analytics as PA
    return PA.direction_distribution(_pviews(sps))


def _pen_zones(svc, sps):
    from fap.setpieces import penalty_analytics as PA
    return PA.zone_conversion(_pviews(sps))


_KINDS = {
    "occ_attack_density": _occ_density, "occ_attack_avg": _occ_avg,
    "occ_timeline": _occ_timeline, "def_positions": _def_positions,
    "delivery": _delivery, "delivery_success": _delivery_success,
    "delivery_accuracy": _delivery_accuracy, "delivery_trajectory": _delivery_trajectory,
    "shot": _shot, "goals": _goals, "first_contact": _first_contact,
    "second_ball": _second_ball, "clearance": _clearance, "flick_on": _flick_on,
    "shot_assist": _shot_assist, "threat": _threat,
    "movement": _movement, "movement_screen": lambda s, x: _movement(s, x, "screen"),
    "movement_decoy": lambda s, x: _movement(s, x, "decoy"),
    "movement_edge": lambda s, x: _movement(s, x, "edge"),
    "movement_post": _movement_posts, "blockers": _blockers, "screens": _screens,
    "wall": _wall, "marking_assignment": _marking_assignment,
    "gk_start": _gk_start, "gk_move": _gk_move,
    "pen_placement": _pen_placement, "pen_dive": _pen_dive,
    "pen_dive_direction": _pen_dive_direction, "pen_outcome": _pen_outcome,
    "pen_shooter": _pen_shooter, "pen_gk": _pen_gk,
    # Phase 9.4 penalty module
    "pen_goal": _pen_goal, "pen_miss": _pen_miss, "pen_shots": _pen_shots,
    "pen_reach": _pen_reach, "pen_clusters": _pen_clusters, "pen_height": _pen_height,
    "pen_direction": _pen_direction, "pen_zones": _pen_zones,
}
