"""Set-piece visualization GUIDANCE content (Phase 9.6.1) - pure, instructional.

Elite UX helpers layered on top of the Phase 9.6 requirement/validation
infrastructure: example data, download templates, difficulty / tagging-time
info cards, football-focused "learn more" copy, dependency trees, feasibility
and match-coverage scoring. No analytics, no rendering, no engine changes - this
module only *describes and scores* so a first-time user needs no documentation.

Content is keyed by dataset FAMILY (visualizations that share a data shape share
their example/template), with a few per-visualization overrides for the marquee
maps. Requirements themselves stay the single source of truth in viz_requirements.
"""
from __future__ import annotations

from typing import Any


def family_of(kind: str) -> str:
    if kind.startswith("pen_"):
        return "penalty"
    if kind.startswith("gk_"):
        return "gk"
    if kind.startswith("movement"):
        return "movement"
    if kind in ("occ_attack_density", "occ_attack_avg", "def_positions",
                "marking_assignment", "blockers", "screens", "wall"):
        return "positions"
    if kind in ("shot", "threat", "goals", "first_contact", "second_ball",
                "clearance", "flick_on", "shot_assist"):
        return "contacts"
    return "delivery"


# ------------------------------------------------------------------ families
FAMILIES: dict[str, dict[str, Any]] = {
    "delivery": {
        "columns": ["match", "team", "taker", "delivery", "end_x", "end_y", "outcome", "shot", "goal", "xg"],
        "example": [
            ["City v United", "City", "M. Silva", "inswing", 95, 44, "goal", "yes", "yes", 0.34],
            ["City v United", "City", "M. Silva", "inswing", 92, 55, "shot", "yes", "no", 0.11],
            ["City v United", "City", "T. Adeyemi", "outswing", 90, 58, "clearance", "no", "no", ""]],
        "info": {"difficulty": "Easy", "tier": "Event data / CSV", "time": "~10 sec / event",
                 "accuracy": "High"},
        "learn": {
            "what": "Where corner and free-kick deliveries land inside and around the box.",
            "coaches": "To see an opponent's primary target and set the marking and zonal plan.",
            "why": "Delivery location is the most repeatable pattern in set-piece play.",
            "questions": ["Where do they aim most?", "Near or far post?", "Do outswingers target the edge?"],
            "mistakes": ["Recording the taker's spot instead of the landing.",
                         "Leaving out the outcome, so success can't be measured."]}},
    "positions": {
        "columns": ["set_piece", "player", "team", "role", "x", "y", "moment"],
        "example": [
            ["C1", "Haaland", "attack", "near_post", 95, 44, "delivery"],
            ["C1", "Dias", "defence", "six_yard", 96, 50, "delivery"],
            ["C1", "Rodri", "attack", "penalty_spot", 89, 50, "delivery"]],
        "info": {"difficulty": "Advanced", "tier": "Manual tagging", "time": "~2 min / event",
                 "accuracy": "High"},
        "learn": {
            "what": "Where every player stands inside the box at the moment of delivery.",
            "coaches": "To assign marking, spot overloads and identify the most dangerous runners.",
            "why": "Box occupancy predicts who attacks which zone better than any single stat.",
            "questions": ["Which zone do they overload?", "Who is the free man?", "Where is the block set?"],
            "mistakes": ["Tagging after the ball is struck instead of at delivery.",
                         "Forgetting the goalkeeper.", "Confusing attacking and defending roles."]}},
    "contacts": {
        "columns": ["set_piece", "player", "team", "contact_type", "x", "y", "body_part", "outcome"],
        "example": [
            ["C1", "Haaland", "attack", "first_contact", 95, 45, "head", "goal"],
            ["C1", "Dias", "defence", "clearance", 90, 40, "head", "clearance"],
            ["C1", "De Bruyne", "attack", "second_ball", 82, 52, "foot", "shot"]],
        "info": {"difficulty": "Moderate", "tier": "Manual tagging", "time": "~1 min / event",
                 "accuracy": "Medium-High"},
        "learn": {
            "what": "Who touches the ball first, wins the second ball, shoots or clears — and where.",
            "coaches": "To judge who wins first contact and whether second balls are controlled.",
            "why": "First and second contact decide most set-piece chances.",
            "questions": ["Who wins the first header?", "Do we control the second ball?",
                          "Where are clearances landing?"],
            "mistakes": ["Not marking the contact type.", "Skipping the second-ball event."]}},
    "gk": {
        "columns": ["set_piece", "player", "x", "y", "moment", "is_gk"],
        "example": [
            ["C1", "Ederson", 98, 50, "before", "yes"],
            ["C1", "Ederson", 96, 49, "delivery", "yes"]],
        "info": {"difficulty": "Moderate", "tier": "Manual tagging", "time": "~30 sec / event",
                 "accuracy": "High"},
        "learn": {
            "what": "The goalkeeper's starting position and movement on set pieces.",
            "coaches": "To find the space a keeper vacates and judge aggression vs passivity.",
            "why": "A committed keeper leaves exploitable air; a passive one invites near-post flicks.",
            "questions": ["Does the keeper come for crosses?", "Which zone do they leave open?"],
            "mistakes": ["Tagging only one moment (need before AND delivery for movement)."]}},
    "movement": {
        "columns": ["set_piece", "player", "moment", "run_type", "x", "y"],
        "example": [
            ["C1", "Haaland", "before", "near_post", 84, 44],
            ["C1", "Haaland", "delivery", "near_post", 95, 45],
            ["C1", "Foden", "before", "decoy", 86, 52]],
        "info": {"difficulty": "Advanced", "tier": "Manual tagging", "time": "~3 min / event",
                 "accuracy": "Medium"},
        "learn": {
            "what": "Attacking runs before and at delivery — near/far post, screens, decoys, late runs.",
            "coaches": "To recognise the routine and prepare defenders for blocks and late runners.",
            "why": "Movement is what turns box occupancy into a rehearsed routine.",
            "questions": ["What is the first move?", "Who screens the keeper?", "Where is the late run?"],
            "mistakes": ["Tagging one moment only.", "Missing the run_type label."]}},
    "penalty": {
        "columns": ["taker", "foot", "placement", "gk_dive", "goalkeeper", "outcome"],
        "example": [
            ["Kane", "right", "bottom_right", "left", "Neuer", "goal"],
            ["Silva", "left", "top_left", "right", "Neuer", "saved"],
            ["Son", "right", "bottom_left", "stay", "Neuer", "goal"]],
        "info": {"difficulty": "Moderate", "tier": "Manual tagging", "time": "~45 sec / event",
                 "accuracy": "High"},
        "learn": {
            "what": "Penalty placement, shooter tendency and goalkeeper dive behaviour.",
            "coaches": "To brief the keeper on a taker's preferred corner and the taker on a keeper's dive.",
            "why": "Penalties are high-value and highly patterned — small edges convert.",
            "questions": ["Where does this taker place it?", "Does the keeper dive early?"],
            "mistakes": ["Recording only the outcome, not the placement or dive."]}},
}

# per-visualization learn overrides (marquee maps)
LEARN_OVERRIDE: dict[str, dict[str, Any]] = {
    "occ_attack_density": {"what": "A heatmap of where attackers gather in the box at delivery."},
    "def_positions": {"what": "Average defending positions — the block shape you must break."},
    "gk_move": {"what": "The keeper's path from start to delivery — how far they commit."},
    "pen_placement": {"what": "A 3×3 goal grid of where a taker places penalties."},
    "first_contact": {"what": "Who wins the first contact on the delivery, and where."},
}

# template column overrides (datasets whose shape differs from the family)
TEMPLATE_OVERRIDE: dict[str, list[str]] = {
    "delivery_trajectory": ["match", "team", "taker", "delivery", "start_x", "start_y",
                            "end_x", "end_y", "outcome"],
    "delivery_accuracy": ["match", "team", "taker", "end_x", "end_y", "target_x", "target_y"],
}


# ------------------------------------------------------------------ resolvers
def guidance_for(kind: str) -> dict[str, Any]:
    fam = FAMILIES.get(family_of(kind), FAMILIES["delivery"])
    learn = dict(fam["learn"])
    learn.update(LEARN_OVERRIDE.get(kind, {}))
    return {
        "family": family_of(kind),
        "columns": TEMPLATE_OVERRIDE.get(kind, fam["columns"]),
        "example_columns": fam["columns"],
        "example_rows": fam["example"],
        "info": dict(fam["info"]),
        "learn": learn,
    }


# ------------------------------------------------------------------ dependency tree
def dependency_tree(req: dict[str, Any], counts: dict[str, Any], can_render: bool) -> list[dict[str, str]]:
    """Ordered dependency chain with live status (ok | missing | na)."""
    def st(ok: bool) -> str:
        return "ok" if ok else "missing"

    tree = [
        {"label": f"Set Piece Events ({counts['events']})", "status": st(counts["events"] > 0)},
        {"label": "Coordinates", "status": st(counts["coordinates"]["n"] > 0)},
    ]
    if not (req["needs_positions"] or req["needs_contacts"] or req["needs_penalty"]):
        tree.append({"label": "Outcome", "status": st(counts["outcome"]["n"] > 0)})
    if req["needs_positions"]:
        tree.append({"label": "Player Positions", "status": st(counts["positions"]["n"] > 0)})
    if req["needs_goalkeeper"]:
        tree.append({"label": "Goalkeeper", "status": st(counts["goalkeeper"]["n"] > 0)})
    if req["needs_contacts"]:
        tree.append({"label": "Contacts", "status": st(counts["contacts"]["n"] > 0)})
    if req["needs_penalty"]:
        tree.append({"label": "Penalty Detail", "status": st(counts["penalty"]["n"] > 0)})
    tree.append({"label": "Render", "status": st(can_render)})
    return tree


# ------------------------------------------------------------------ feasibility
def feasible(req: dict[str, Any], counts: dict[str, Any]) -> tuple[bool, str]:
    """Can this dataset produce the visualization at all (data-type level)?"""
    if req["needs_positions"] and counts["positions"]["n"] == 0:
        return False, "Player positions missing"
    if req["needs_goalkeeper"] and counts["goalkeeper"]["n"] == 0:
        return False, "Goalkeeper coordinates missing"
    if req["needs_contacts"] and counts["contacts"]["n"] == 0:
        return False, "Contact data missing"
    if req["needs_penalty"] and counts["penalty"]["n"] == 0:
        return False, "Penalty detail missing"
    if not (req["needs_positions"] or req["needs_contacts"] or req["needs_penalty"]) \
            and counts["coordinates"]["n"] == 0:
        return False, "Delivery coordinates missing"
    return True, "Ready"


# ------------------------------------------------------------------ match coverage
_WEIGHTS = {"coordinates": 0.30, "outcome": 0.10, "contacts": 0.15,
            "positions": 0.25, "goalkeeper": 0.10, "penalty": 0.10}
_AXIS_LABEL = {"coordinates": "Delivery coordinates", "outcome": "Outcome data",
               "contacts": "Contact events", "positions": "Player positions",
               "goalkeeper": "Goalkeeper position", "penalty": "Penalty detail"}


def match_coverage(counts: dict[str, Any]) -> dict[str, Any]:
    """A single 0-100 score for how suitable the dataset is for a full,
    professional report, plus what is still missing."""
    if not counts["events"]:
        return {"score": 0, "label": "No data", "missing": list(_AXIS_LABEL.values())}
    score = sum(_WEIGHTS[a] * counts[a]["pct"] for a in _WEIGHTS) * 100
    score = int(round(score))
    label = ("Excellent" if score >= 85 else "Very Good" if score >= 70 else
             "Good" if score >= 55 else "Fair" if score >= 35 else "Insufficient")
    missing = [_AXIS_LABEL[a] for a in _WEIGHTS if counts[a]["pct"] == 0]
    return {"score": score, "label": label, "missing": missing}
