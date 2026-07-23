"""Set Piece Intelligence engine (Phase 9.3) - PURE, deterministic, NO LLM.

Sits above the 9.1 analytics and 9.2 visualization datasets and turns raw events
into coaching intelligence: routine detection, clustering, offensive/defensive
tendencies, a similarity engine, automatic insights, coach recommendations and a
rule-based written narrative. It REUSES the analytics primitives (occupancy,
contacts, deliveries) and the penalty backend - no statistic is recomputed from
scratch and no visualization logic is duplicated.

AI-ready by construction: every ``Insight`` and ``Recommendation`` exposes
``evidence``, ``confidence``, ``supporting_statistics`` and
``visualization_references`` (ids of registered 9.2 visualizations). A future LLM
can enrich the ``text``/``rationale`` from those fields, but nothing here depends
on any AI service - the narrative is produced deterministically from templates.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from fap.setpieces import analytics as AN
from fap.setpieces.analysis import zone_for
from fap.setpieces.models import SetPiece, SetPieceContact, SetPiecePosition

# ------------------------------------------------------------------ vocab
ROUTINES = (
    "near_post", "far_post", "crowd_gk", "short_corner", "edge_box", "flick_on",
    "screen", "late_runner", "decoy", "second_ball", "mixed", "custom",
)
ROUTINE_LABELS = {
    "near_post": "Near Post", "far_post": "Far Post", "crowd_gk": "Crowd the Keeper",
    "short_corner": "Short Corner", "edge_box": "Edge of Box", "flick_on": "Near-Post Flick-on",
    "screen": "Screen / Block", "late_runner": "Late Runner", "decoy": "Decoy Run",
    "second_ball": "Second Ball", "mixed": "Mixed", "custom": "Custom Recurring",
}


# ============================================================ AI-ready outputs
@dataclass(slots=True)
class Insight:
    """A single observation. AI-ready: an LLM can rewrite ``text`` from the
    structured fields, but the fields stand alone."""
    id: str
    title: str
    text: str
    kind: str = "neutral"                      # neutral | success | warning | danger
    confidence: float = 0.0                    # 0..1
    evidence: list[str] = field(default_factory=list)
    supporting_statistics: dict[str, Any] = field(default_factory=dict)
    visualization_references: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Recommendation:
    """A coach-ready action. Always explains *why* (``rationale``) and carries the
    same AI-ready evidence contract."""
    id: str
    action: str
    rationale: str
    priority: str = "medium"                   # high | medium | low
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)
    supporting_statistics: dict[str, Any] = field(default_factory=dict)
    visualization_references: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RoutineDetection:
    set_piece_id: str
    routine: str
    confidence: float
    evidence: list[str] = field(default_factory=list)
    features: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Cluster:
    id: int
    label: str
    size: int
    members: list[str]                          # set_piece_ids
    conversion_pct: float
    xg: float
    confidence: float
    signature: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class IntelligenceReport:
    n_set_pieces: int
    routines: dict[str, int]
    detections: list[RoutineDetection]
    clusters: list[Cluster]
    offensive_tendencies: list[Insight]
    defensive_tendencies: list[Insight]
    insights: list[Insight]
    recommendations: list[Recommendation]
    narrative: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_set_pieces": self.n_set_pieces, "routines": self.routines,
            "detections": [asdict(d) for d in self.detections],
            "clusters": [asdict(c) for c in self.clusters],
            "offensive_tendencies": [i.to_dict() for i in self.offensive_tendencies],
            "defensive_tendencies": [i.to_dict() for i in self.defensive_tendencies],
            "insights": [i.to_dict() for i in self.insights],
            "recommendations": [r.to_dict() for r in self.recommendations],
            "narrative": self.narrative,
        }


# ------------------------------------------------------------------ helpers
def _group(items, key):
    out = defaultdict(list)
    for it in items:
        out[getattr(it, key)].append(it)
    return out


def _pct(part: float, whole: float) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


def _mode(values):
    counts: dict[str, int] = defaultdict(int)
    for v in values:
        if v:
            counts[v] += 1
    return (max(counts, key=counts.get), counts) if counts else ("", {})


# ============================================================ feature extraction
def sp_features(sp: SetPiece, positions: list[SetPiecePosition],
                contacts: list[SetPieceContact]) -> dict[str, Any]:
    """Interpretable per-set-piece features shared by detection, clustering and
    similarity. Reuses zone geometry from analysis; adds no new statistics."""
    att = [p for p in positions if p.team == "attack"]
    dfd = [p for p in positions if p.team == "defence" and not p.is_gk]

    def zone_count(roles):
        return sum(1 for p in att if (p.role or p.zone) in roles)

    runs = {rt: sum(1 for p in att if p.run_type == rt)
            for rt in ("near_post", "far_post", "screen", "block", "late", "edge", "decoy")}
    land_zone = zone_for(sp.end_x, sp.end_y) if sp.end_x is not None else ""
    head_first = any(c.kind == "first_contact" and c.body_part == "head" for c in contacts)
    has_second = any(c.kind == "second_ball" for c in contacts)
    return {
        "end_x": sp.end_x, "end_y": sp.end_y, "land_zone": land_zone,
        "delivery_type": sp.delivery_type, "delivery_length": sp.delivery_length,
        "side": sp.side, "players_in_box": sp.players_in_box or len(att),
        "att_near": zone_count(("near_post", "six_yard")),
        "att_far": zone_count(("far_post", "back_post")),
        "att_gk": zone_count(("gk_area",)), "att_edge": zone_count(("edge_box",)),
        "att_central": zone_count(("central", "penalty_spot")),
        "runs": runs, "head_first": head_first, "has_second": has_second,
        "shot": bool(sp.shot), "goal": bool(sp.goal), "xg": sp.xg or 0.0,
        "def_count": len(dfd),
        "marking_mode": _mode([p.marking for p in dfd])[0],
        "second_ball_attack": sp.second_ball_team == "attack",
    }


# ============================================================ routine detection
def detect_routine(sp: SetPiece, positions: list[SetPiecePosition],
                   contacts: list[SetPieceContact]) -> RoutineDetection:
    """Deterministic rule pipeline: score each candidate routine from features,
    pick the strongest; a near-tie is reported as ``mixed``."""
    f = sp_features(sp, positions, contacts)
    scores: dict[str, float] = defaultdict(float)
    ev: dict[str, list[str]] = defaultdict(list)

    def add(routine, weight, reason):
        scores[routine] += weight
        ev[routine].append(reason)

    if f["delivery_length"] == "short" or f["delivery_type"] == "short":
        add("short_corner", 3.0, "short delivery")
    if f["att_gk"] >= 2:
        add("crowd_gk", 2.0 + f["att_gk"] * 0.5, f"{f['att_gk']} attackers in the keeper zone")
    if f["head_first"] and (f["att_far"] > 0 or f["land_zone"] in ("near_post", "six_yard")):
        add("flick_on", 2.5, "headed first contact near post with a far runner")
    if f["runs"]["screen"] or f["runs"]["block"]:
        add("screen", 2.2, "screen/block runners present")
    if f["runs"]["late"]:
        add("late_runner", 2.0, "late run tagged")
    if f["runs"]["decoy"]:
        add("decoy", 2.0, "decoy run tagged")
    if f["second_ball_attack"] and f["has_second"]:
        add("second_ball", 1.8, "second ball won by the attacking team")
    if f["att_near"] or f["land_zone"] in ("near_post", "six_yard"):
        add("near_post", 1.5 + f["att_near"] * 0.6, "attackers/target at the near post")
    if f["att_far"] or f["land_zone"] in ("far_post", "back_post"):
        add("far_post", 1.5 + f["att_far"] * 0.6, "attackers/target at the far post")
    if f["att_edge"] or f["land_zone"] == "edge_box":
        add("edge_box", 1.5 + f["att_edge"] * 0.6, "attackers/target at the edge of the box")

    if not scores:
        return RoutineDetection(sp.id, "mixed", 0.2, ["no dominant signal"], f)
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    top, top_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0
    total = sum(scores.values())
    if second_score >= top_score * 0.8 and len(ranked) > 1:
        return RoutineDetection(sp.id, "mixed", round(top_score / total, 2),
                                ev[top] + ev[ranked[1][0]], f)
    return RoutineDetection(sp.id, top, round(min(1.0, top_score / max(total, 1e-9)), 2),
                            ev[top], f)


def detect_routines(sps: list[SetPiece], positions: list[SetPiecePosition],
                    contacts: list[SetPieceContact]) -> list[RoutineDetection]:
    pos_by = _group(positions, "set_piece_id")
    con_by = _group(contacts, "set_piece_id")
    atts = [s for s in sps if s.phase == "offensive"]
    return [detect_routine(s, pos_by.get(s.id, []), con_by.get(s.id, [])) for s in atts]


# ============================================================ similarity engine
_FEATURE_KEYS = ("end_x", "end_y", "players_in_box", "att_near", "att_far", "att_gk",
                 "att_edge", "att_central", "shot", "goal", "xg")
_DELIVERY_ONEHOT = ("inswing", "outswing", "straight", "driven", "ground", "short", "long")


def feature_vector(f: dict[str, Any]) -> np.ndarray:
    """Fixed-length numeric vector for similarity/clustering (delivery, shape,
    movement, contact, finish components)."""
    base = [float(f.get(k) or 0.0) for k in _FEATURE_KEYS]
    delivery = [1.0 if f.get("delivery_type") == d else 0.0 for d in _DELIVERY_ONEHOT]
    runs = f.get("runs", {})
    movement = [float(runs.get(rt, 0)) for rt in ("near_post", "far_post", "screen", "late", "decoy")]
    contact = [1.0 if f.get("head_first") else 0.0, 1.0 if f.get("has_second") else 0.0]
    return np.array(base + delivery + movement + contact, dtype=float)


def _standardize(mat: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mean = mat.mean(axis=0)
    std = mat.std(axis=0)
    std[std == 0] = 1.0
    return (mat - mean) / std, mean, std


def similarity(a: np.ndarray, b: np.ndarray, scale: np.ndarray | None = None) -> float:
    """0..1 similarity from a standardized euclidean distance."""
    if scale is not None:
        a, b = a / scale, b / scale
    d = float(np.linalg.norm(a - b))
    return round(1.0 / (1.0 + d / max(1, len(a)) ** 0.5), 3)


def similar_set_pieces(target_id: str, detections: list[RoutineDetection], *,
                       top: int = 5) -> list[dict[str, Any]]:
    """Rank set pieces by similarity to a target ('show routines similar to
    this one'). Operates on the detection feature dicts."""
    by_id = {d.set_piece_id: d for d in detections}
    if target_id not in by_id or len(detections) < 2:
        return []
    ids = [d.set_piece_id for d in detections]
    mat = np.vstack([feature_vector(by_id[i].features) for i in ids])
    std_mat, _, std = _standardize(mat)
    ti = ids.index(target_id)
    out = []
    for i, sid in enumerate(ids):
        if sid == target_id:
            continue
        out.append({"set_piece_id": sid, "routine": by_id[sid].routine,
                    "similarity": similarity(std_mat[ti], std_mat[i])})
    return sorted(out, key=lambda r: -r["similarity"])[:top]


def entity_similarity(detections: list[RoutineDetection], sps: list[SetPiece], *,
                      by: str = "team") -> dict[str, dict[str, float]]:
    """Similarity matrix between entities (team/taker/match/player-agnostic mean
    feature vectors). Enables 'teams/matches like this one'."""
    key = {"team": lambda s: s.team, "taker": lambda s: s.taker,
           "match": lambda s: s.match_id or s.match_label}.get(by, lambda s: s.team)
    sp_by = {s.id: s for s in sps}
    groups: dict[str, list[np.ndarray]] = defaultdict(list)
    for d in detections:
        s = sp_by.get(d.set_piece_id)
        if s is not None and key(s):
            groups[key(s)].append(feature_vector(d.features))
    vecs = {k: np.mean(v, axis=0) for k, v in groups.items() if v}
    names = list(vecs)
    out: dict[str, dict[str, float]] = {}
    for a in names:
        out[a] = {b: similarity(vecs[a], vecs[b]) for b in names if b != a}
    return out


# ============================================================ clustering
def cluster_routines(detections: list[RoutineDetection], sps: list[SetPiece], *,
                     threshold: float = 1.4) -> list[Cluster]:
    """Greedy, deterministic clustering on standardized feature vectors (no ML
    dependency). Clusters by delivery/shape/movement/contact/finish jointly.
    A cluster with no dominant known routine is labelled 'custom recurring'."""
    if not detections:
        return []
    dets = sorted(detections, key=lambda d: d.set_piece_id)
    mat = np.vstack([feature_vector(d.features) for d in dets])
    std_mat, _, _ = _standardize(mat)
    assigned = [-1] * len(dets)
    centroids: list[np.ndarray] = []
    members: list[list[int]] = []
    for i, vec in enumerate(std_mat):
        best, best_d = -1, 1e9
        for ci, c in enumerate(centroids):
            dd = float(np.linalg.norm(vec - c))
            if dd < best_d:
                best, best_d = ci, dd
        if best >= 0 and best_d <= threshold:
            assigned[i] = best
            members[best].append(i)
            centroids[best] = std_mat[members[best]].mean(axis=0)
        else:
            assigned[i] = len(centroids)
            centroids.append(vec.copy())
            members.append([i])

    sp_by = {s.id: s for s in sps}
    clusters: list[Cluster] = []
    for ci, idxs in enumerate(members):
        member_ids = [dets[i].set_piece_id for i in idxs]
        routines = [dets[i].routine for i in idxs]
        label_key, counts = _mode(routines)
        dominant = counts.get(label_key, 0) / len(idxs) if idxs else 0
        label = ROUTINE_LABELS.get(label_key, "Custom Recurring") if dominant >= 0.5 else "Custom Recurring"
        member_sps = [sp_by[m] for m in member_ids if m in sp_by]
        goals = sum(1 for s in member_sps if s.goal)
        shots = sum(1 for s in member_sps if s.shot)
        xg = round(sum((s.xg or 0.0) for s in member_sps), 2)
        # intra-cluster tightness -> confidence
        if len(idxs) > 1:
            c = std_mat[idxs].mean(axis=0)
            spread = float(np.mean([np.linalg.norm(std_mat[i] - c) for i in idxs]))
            conf = round(max(0.0, 1.0 - spread / (threshold * 2)), 2)
        else:
            conf = 0.5
        clusters.append(Cluster(
            id=ci, label=label, size=len(idxs), members=member_ids,
            conversion_pct=_pct(goals, len(idxs)), xg=xg, confidence=conf,
            signature={"dominant_routine": label_key, "dominance_pct": _pct(counts.get(label_key, 0), len(idxs)),
                       "shots": shots, "goals": goals}))
    return sorted(clusters, key=lambda c: -c.size)


# ============================================================ tendencies
def offensive_tendencies(sps: list[SetPiece], detections: list[RoutineDetection]) -> list[Insight]:
    atts = [s for s in sps if s.phase == "offensive"]
    n = len(atts)
    out: list[Insight] = []
    if not n:
        return out
    # preferred delivery zone (landing)
    zmode, zc = _mode([zone_for(s.end_x, s.end_y) for s in atts if s.end_x is not None])
    if zmode:
        out.append(Insight(
            "off_delivery_zone", "Preferred delivery zone",
            f"Deliveries most often land in the {zmode.replace('_', ' ')} "
            f"({_pct(zc[zmode], n)}% of set pieces).",
            confidence=round(zc[zmode] / n, 2),
            evidence=[f"{zc[zmode]}/{n} deliveries land in {zmode}"],
            supporting_statistics={"zone": zmode, "share_pct": _pct(zc[zmode], n)},
            visualization_references=["sp_delivery_heatmap", "sp_zone_occupancy"]))
    # preferred delivery type
    dmode, dc = _mode([s.delivery_type for s in atts])
    if dmode:
        out.append(Insight(
            "off_delivery_type", "Preferred delivery type",
            f"{dmode.title()} is the dominant delivery ({_pct(dc[dmode], n)}%).",
            confidence=round(dc[dmode] / n, 2),
            evidence=[f"{dc[dmode]}/{n} deliveries are {dmode}"],
            supporting_statistics={"delivery_type": dmode, "share_pct": _pct(dc[dmode], n)},
            visualization_references=["sp_delivery_scatter"]))
    # preferred taker
    tmode, tc = _mode([s.taker for s in atts])
    if tmode:
        out.append(Insight(
            "off_taker", "Preferred taker",
            f"{tmode} takes {_pct(tc[tmode], n)}% of these set pieces.",
            confidence=round(tc[tmode] / n, 2),
            evidence=[f"{tc[tmode]}/{n} taken by {tmode}"],
            supporting_statistics={"taker": tmode, "share_pct": _pct(tc[tmode], n)},
            visualization_references=["sp_delivery_trajectory"]))
    # preferred routine
    rmode, rc = _mode([d.routine for d in detections])
    if rmode:
        out.append(Insight(
            "off_routine", "Preferred routine",
            f"The {ROUTINE_LABELS.get(rmode, rmode)} routine is used most "
            f"({_pct(rc[rmode], len(detections))}%).",
            confidence=round(rc[rmode] / max(len(detections), 1), 2),
            evidence=[f"{rc[rmode]}/{len(detections)} routines are {rmode}"],
            supporting_statistics={"routine": rmode, "share_pct": _pct(rc[rmode], len(detections))},
            visualization_references=["sp_box_occupancy", "sp_movement_vectors"]))
    # strong side
    left = [s for s in atts if s.side == "left"]
    right = [s for s in atts if s.side == "right"]
    if left or right:
        lg, rg = sum(s.goal for s in left), sum(s.goal for s in right)
        strong = "left" if _pct(lg, len(left) or 1) >= _pct(rg, len(right) or 1) else "right"
        out.append(Insight(
            "off_side", "Strong side",
            f"The {strong} side is more productive "
            f"(L {_pct(lg, len(left) or 1)}% vs R {_pct(rg, len(right) or 1)}% conversion).",
            confidence=0.5,
            evidence=[f"left goals {lg}/{len(left)}", f"right goals {rg}/{len(right)}"],
            supporting_statistics={"strong_side": strong, "left_conv": _pct(lg, len(left) or 1),
                                   "right_conv": _pct(rg, len(right) or 1)},
            visualization_references=["sp_delivery_heatmap"]))
    return out


def defensive_tendencies(sps: list[SetPiece], positions: list[SetPiecePosition],
                         contacts: list[SetPieceContact]) -> list[Insight]:
    defs = [s for s in sps if s.phase == "defensive"]
    out: list[Insight] = []
    n = len(defs)
    marking = AN.classify_marking(positions)
    if marking["n"]:
        out.append(Insight(
            "def_marking", "Marking scheme",
            f"Predominantly {marking['scheme']} marking "
            f"(confidence {int(marking['confidence'] * 100)}%).",
            kind="neutral", confidence=marking["confidence"],
            evidence=[f"man {marking['man']} vs zonal {marking['zonal']} of {marking['n']} tagged defenders"],
            supporting_statistics=marking,
            visualization_references=["sp_marking", "sp_marking_assignment"]))
    if n:
        # second-ball weakness (attacker wins second ball against this team)
        sb_known = [s for s in defs if s.second_ball_team in ("attack", "defence")]
        sb_lost = sum(1 for s in sb_known if s.second_ball_team == "attack")
        if sb_known:
            out.append(Insight(
                "def_second_ball", "Second-ball control",
                f"Opponents win the second ball {_pct(sb_lost, len(sb_known))}% of the time.",
                kind="warning" if _pct(sb_lost, len(sb_known)) >= 50 else "neutral",
                confidence=round(len(sb_known) / n, 2),
                evidence=[f"{sb_lost}/{len(sb_known)} second balls lost"],
                supporting_statistics={"second_ball_lost_pct": _pct(sb_lost, len(sb_known))},
                visualization_references=["sp_second_ball"]))
        # near/far post vulnerability (where shots/goals are conceded)
        conceded = [s for s in defs if s.shot or s.goal]
        zmode, zc = _mode([zone_for(s.first_contact_x, s.first_contact_y)
                           for s in conceded if s.first_contact_x is not None])
        if zmode:
            out.append(Insight(
                "def_vulnerable_zone", "Vulnerable zone",
                f"Most chances conceded originate in the {zmode.replace('_', ' ')}.",
                kind="danger", confidence=round(zc[zmode] / max(len(conceded), 1), 2),
                evidence=[f"{zc[zmode]}/{len(conceded)} conceded chances in {zmode}"],
                supporting_statistics={"zone": zmode, "count": zc[zmode]},
                visualization_references=["sp_dangerous_zones", "sp_first_contact"]))
        # clearance areas
        clr = [c for c in contacts if c.kind == "clearance" or c.outcome == "clearance"]
        cmode, cc = _mode([zone_for(c.x, c.y) for c in clr if c.x is not None])
        if cmode:
            out.append(Insight(
                "def_clearance", "Preferred clearance area",
                f"Clearances mostly go through the {cmode.replace('_', ' ')}.",
                confidence=round(cc[cmode] / max(len(clr), 1), 2),
                evidence=[f"{cc[cmode]}/{len(clr)} clearances in {cmode}"],
                supporting_statistics={"zone": cmode},
                visualization_references=["sp_clearance"]))
        # GK aggressive vs passive (from tagged gk movement / claims)
        gk_conf = _gk_behaviour(defs, positions)
        if gk_conf:
            out.append(gk_conf)
    return out


def _gk_behaviour(defs: list[SetPiece], positions: list[SetPiecePosition]) -> Insight | None:
    gk_moves = defaultdict(dict)
    for p in positions:
        if p.is_gk and p.x is not None:
            gk_moves[p.set_piece_id][p.moment] = p
    dists = []
    for m in gk_moves.values():
        if "before" in m and "delivery" in m:
            a, b = m["before"], m["delivery"]
            dists.append(((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5)
    if not dists:
        return None
    avg = sum(dists) / len(dists)
    aggressive = avg >= 4.0
    return Insight(
        "def_gk", "Goalkeeper behaviour",
        f"The goalkeeper is {'aggressive (commands the area)' if aggressive else 'passive (holds the line)'} "
        f"— average movement {avg:.1f} units.",
        kind="neutral", confidence=round(min(1.0, len(dists) / max(len(defs), 1)), 2),
        evidence=[f"avg GK displacement {avg:.1f} over {len(dists)} set pieces"],
        supporting_statistics={"avg_movement": round(avg, 1), "aggressive": aggressive},
        visualization_references=["sp_gk_start", "sp_gk_movement"])


# ============================================================ automatic insights
def automatic_insights(sps: list[SetPiece], detections: list[RoutineDetection],
                       clusters: list[Cluster]) -> list[Insight]:
    out: list[Insight] = []
    atts = [s for s in sps if s.phase == "offensive"]
    sp_by = {s.id: s for s in sps}
    by_routine: dict[str, list[SetPiece]] = defaultdict(list)
    for d in detections:
        if d.set_piece_id in sp_by:
            by_routine[d.routine].append(sp_by[d.set_piece_id])

    def routine_stats(group):
        n = len(group)
        return n, _pct(sum(s.goal for s in group), n), _pct(sum(s.shot for s in group), n), \
            round(sum((s.xg or 0) for s in group), 2)

    # most used / most dangerous / least effective / highest conversion
    if by_routine:
        most_used = max(by_routine, key=lambda r: len(by_routine[r]))
        n, conv, shotp, xg = routine_stats(by_routine[most_used])
        out.append(Insight("ins_most_used", "Most used routine",
                           f"The {ROUTINE_LABELS.get(most_used, most_used)} routine is used most "
                           f"({n} times, {conv}% conversion).", confidence=round(n / max(len(detections), 1), 2),
                           evidence=[f"{n}/{len(detections)} routines"],
                           supporting_statistics={"routine": most_used, "count": n, "conversion_pct": conv},
                           visualization_references=["sp_box_occupancy"]))
        danger = max(by_routine, key=lambda r: routine_stats(by_routine[r])[3] / max(len(by_routine[r]), 1))
        n, conv, shotp, xg = routine_stats(by_routine[danger])
        out.append(Insight("ins_most_dangerous", "Most dangerous routine",
                           f"The {ROUTINE_LABELS.get(danger, danger)} routine creates the most threat "
                           f"({xg} xG, {conv}% conversion).", kind="success",
                           confidence=0.6, evidence=[f"{xg} xG over {n}"],
                           supporting_statistics={"routine": danger, "xg": xg, "conversion_pct": conv},
                           visualization_references=["sp_goal_probability", "sp_threat_map"]))
        # least effective = most used but lowest conversion
        least = min(by_routine, key=lambda r: routine_stats(by_routine[r])[1] if len(by_routine[r]) >= 2 else 999)
        if len(by_routine[least]) >= 2:
            n, conv, shotp, xg = routine_stats(by_routine[least])
            out.append(Insight("ins_least_effective", "Least effective routine",
                               f"The {ROUTINE_LABELS.get(least, least)} routine underperforms "
                               f"({n} uses, only {conv}% conversion).", kind="warning",
                               confidence=round(n / max(len(detections), 1), 2),
                               evidence=[f"{conv}% conversion over {n} uses"],
                               supporting_statistics={"routine": least, "count": n, "conversion_pct": conv},
                               visualization_references=["sp_delivery_heatmap"]))
        highest = max(by_routine, key=lambda r: routine_stats(by_routine[r])[1])
        n, conv, shotp, xg = routine_stats(by_routine[highest])
        out.append(Insight("ins_highest_conversion", "Highest-conversion routine",
                           f"The {ROUTINE_LABELS.get(highest, highest)} routine converts best ({conv}%).",
                           kind="success", confidence=0.6,
                           evidence=[f"{conv}% over {n}"],
                           supporting_statistics={"routine": highest, "conversion_pct": conv},
                           visualization_references=["sp_goal_location"]))
    # best taker
    by_taker = _group([s for s in atts if s.taker], "taker")
    if by_taker:
        best = max(by_taker, key=lambda t: _pct(sum(s.goal for s in by_taker[t]), len(by_taker[t])))
        conv = _pct(sum(s.goal for s in by_taker[best]), len(by_taker[best]))
        out.append(Insight("ins_best_taker", "Best taker",
                           f"{best} has the best return ({conv}% conversion over {len(by_taker[best])}).",
                           kind="success", confidence=0.5, evidence=[f"{conv}% conversion"],
                           supporting_statistics={"taker": best, "conversion_pct": conv},
                           visualization_references=["sp_delivery_trajectory"]))
    # best attacking zone (where goals come from)
    goals = [s for s in atts if s.goal]
    zmode, zc = _mode([zone_for(s.first_contact_x, s.first_contact_y)
                       for s in goals if s.first_contact_x is not None])
    if zmode:
        out.append(Insight("ins_best_zone", "Best attacking zone",
                           f"Most goals are scored from the {zmode.replace('_', ' ')}.",
                           kind="success", confidence=round(zc[zmode] / max(len(goals), 1), 2),
                           evidence=[f"{zc[zmode]}/{len(goals)} goals from {zmode}"],
                           supporting_statistics={"zone": zmode, "goals": zc[zmode]},
                           visualization_references=["sp_goal_location", "sp_dangerous_zones"]))
    return out


# ============================================================ recommendations
def recommendations(sps: list[SetPiece], detections: list[RoutineDetection],
                    off: list[Insight], deff: list[Insight],
                    insights: list[Insight]) -> list[Recommendation]:
    out: list[Recommendation] = []
    idx = {i.id: i for i in (off + deff + insights)}

    def stat(iid, key, default=None):
        return idx[iid].supporting_statistics.get(key, default) if iid in idx else default

    # 1) lean into the highest-conversion routine
    if "ins_highest_conversion" in idx and "ins_most_used" in idx:
        best = stat("ins_highest_conversion", "routine")
        used = stat("ins_most_used", "routine")
        if best and best != used:
            out.append(Recommendation(
                "rec_use_best_routine",
                f"Use the {ROUTINE_LABELS.get(best, best)} routine more often.",
                f"It converts at {stat('ins_highest_conversion', 'conversion_pct')}% but is not your most-used "
                f"routine ({ROUTINE_LABELS.get(used, used)}). Shifting volume to it should raise output.",
                priority="high", confidence=0.6,
                evidence=idx["ins_highest_conversion"].evidence,
                supporting_statistics=idx["ins_highest_conversion"].supporting_statistics,
                visualization_references=["sp_box_occupancy", "sp_goal_probability"]))
    # 2) drop the least effective routine / delivery
    if "ins_least_effective" in idx:
        r = stat("ins_least_effective", "routine")
        out.append(Recommendation(
            "rec_drop_routine",
            f"Reduce the {ROUTINE_LABELS.get(r, r)} routine.",
            f"It is used {stat('ins_least_effective', 'count')} times for only "
            f"{stat('ins_least_effective', 'conversion_pct')}% conversion — predictable and low-yield.",
            priority="medium", confidence=0.55,
            evidence=idx["ins_least_effective"].evidence,
            supporting_statistics=idx["ins_least_effective"].supporting_statistics,
            visualization_references=["sp_delivery_heatmap"]))
    # 3) target the best attacking zone
    if "ins_best_zone" in idx:
        z = stat("ins_best_zone", "zone")
        out.append(Recommendation(
            "rec_target_zone", f"Target the {str(z).replace('_', ' ')} more deliberately.",
            f"Most goals already come from the {str(z).replace('_', ' ')}; increasing service there "
            f"compounds a proven strength.", priority="high", confidence=0.6,
            evidence=idx["ins_best_zone"].evidence,
            supporting_statistics=idx["ins_best_zone"].supporting_statistics,
            visualization_references=["sp_dangerous_zones", "sp_goal_location"]))
    # 4) defensive: press the keeper if passive
    gk = idx.get("def_gk")
    if gk and gk.supporting_statistics.get("aggressive") is False:
        out.append(Recommendation(
            "rec_press_gk", "Press / occupy the goalkeeper.",
            "The keeper stays passive on the line; a body in the six-yard box reduces their reach "
            "and delays the claim.", priority="medium", confidence=gk.confidence,
            evidence=gk.evidence, supporting_statistics=gk.supporting_statistics,
            visualization_references=["sp_gk_start", "sp_crowded_box"]))
    # 5) defensive: second balls
    sb = idx.get("def_second_ball")
    if sb and sb.supporting_statistics.get("second_ball_lost_pct", 0) >= 50:
        out.append(Recommendation(
            "rec_second_balls", "Defend second balls tighter (add an edge screener).",
            f"Opponents win {sb.supporting_statistics['second_ball_lost_pct']}% of second balls; a dedicated "
            f"edge-of-box player recovers loose clearances.", priority="high", confidence=sb.confidence,
            evidence=sb.evidence, supporting_statistics=sb.supporting_statistics,
            visualization_references=["sp_second_ball"]))
    # 6) attacking: avoid over-used weak delivery
    dt = idx.get("off_delivery_type")
    if dt and "ins_least_effective" in idx:
        out.append(Recommendation(
            "rec_vary_delivery",
            f"Vary away from the {stat('off_delivery_type', 'delivery_type')} delivery.",
            f"It accounts for {stat('off_delivery_type', 'share_pct')}% of deliveries — the opposition can "
            f"set up for it. Mixing height/length breaks the pattern.", priority="medium", confidence=0.5,
            evidence=dt.evidence, supporting_statistics=dt.supporting_statistics,
            visualization_references=["sp_delivery_scatter"]))
    return out


# ============================================================ narrative
def narrative(sps: list[SetPiece], detections: list[RoutineDetection],
              off: list[Insight], deff: list[Insight], insights: list[Insight]) -> list[str]:
    """Deterministic, rule-based written observations (no LLM). Each sentence is
    assembled from the structured statistics above."""
    idx = {i.id: i for i in (off + deff + insights)}
    lines: list[str] = []
    atts = [s for s in sps if s.phase == "offensive"]
    n = len(atts)
    if n:
        lead = f"Across {n} offensive set pieces"
        dz = idx.get("off_delivery_zone")
        if dz:
            share = dz.supporting_statistics["share_pct"]
            zone = dz.supporting_statistics["zone"].replace("_", " ")
            conv = _pct(sum(s.goal for s in atts), n)
            qual = ("a predictable pattern" if share >= 50 else "a clear primary target")
            lines.append(f"{lead}, {share}% target the {zone} corridor — {qual}. "
                         f"Conversion across all set pieces is {conv}%"
                         + (", suggesting predictable execution." if share >= 50 and conv < 10
                            else "."))
        if "ins_most_dangerous" in idx:
            r = idx["ins_most_dangerous"].supporting_statistics
            lines.append(f"The {ROUTINE_LABELS.get(r.get('routine'), r.get('routine'))} routine is the most "
                         f"dangerous, generating {r.get('xg')} xG at {r.get('conversion_pct')}% conversion.")
        if "ins_best_taker" in idx:
            t = idx["ins_best_taker"].supporting_statistics
            lines.append(f"{t.get('taker')} is the most productive taker "
                         f"({t.get('conversion_pct')}% conversion).")
    defs = [s for s in sps if s.phase == "defensive"]
    if defs:
        dm = idx.get("def_marking")
        vz = idx.get("def_vulnerable_zone")
        parts = []
        if dm:
            parts.append(f"defends set pieces with a {dm.supporting_statistics.get('scheme')} scheme")
        if vz:
            parts.append(f"concedes most chances through the "
                         f"{vz.supporting_statistics.get('zone', '').replace('_', ' ')}")
        if parts:
            lines.append("Defensively, the team " + " and ".join(parts) + ".")
        sb = idx.get("def_second_ball")
        if sb and sb.supporting_statistics.get("second_ball_lost_pct", 0) >= 50:
            lines.append(f"Second-ball control is a weakness — opponents recover "
                         f"{sb.supporting_statistics['second_ball_lost_pct']}% of loose balls.")
    if not lines:
        lines.append("Not enough tagged detail yet to generate a narrative; tag deliveries, "
                     "box positions and contacts to unlock intelligence.")
    return lines


# ============================================================ orchestration
def build_report(sps: list[SetPiece], positions: list[SetPiecePosition],
                 contacts: list[SetPieceContact]) -> IntelligenceReport:
    """The full intelligence pass over a filtered set. Everything above, composed
    once, into an AI-ready report."""
    detections = detect_routines(sps, positions, contacts)
    clusters = cluster_routines(detections, sps)
    off = offensive_tendencies(sps, detections)
    deff = defensive_tendencies(sps, positions, contacts)
    insights = automatic_insights(sps, detections, clusters)
    recs = recommendations(sps, detections, off, deff, insights)
    story = narrative(sps, detections, off, deff, insights)
    routine_counts: dict[str, int] = defaultdict(int)
    for d in detections:
        routine_counts[d.routine] += 1
    return IntelligenceReport(
        n_set_pieces=len(sps), routines=dict(routine_counts), detections=detections,
        clusters=clusters, offensive_tendencies=off, defensive_tendencies=deff,
        insights=insights, recommendations=recs, narrative=story)
