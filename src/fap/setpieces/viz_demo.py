"""Per-visualization DEMO dataset generator (Phase 9.6).

Creates the *minimum realistic* data that satisfies ONE visualization's dataset
requirements, using only the existing tagging services (create_set_piece,
add_position, add_contact) - it adds no analytics and no new persistence. Every
record is marked (tag ``demo`` + ``document.demo=True``) so it can be cleared
again. Coordinates are canonical 0-100 with the goal at x=100.
"""
from __future__ import annotations

import random
import uuid
from typing import Any

from fap.setpieces.models import SetPieceContact, SetPiecePosition
from fap.setpieces.viz_requirements import DATASETS

_ROLES = ("near_post", "far_post", "penalty_spot", "six_yard", "edge_box", "central")
_PLACEMENTS = ("bottom_left", "bottom_right", "top_left", "top_right", "middle_left",
               "middle_right", "center")
_DIVES = ("left", "right", "stay")


def generate(svc: Any, user: Any, kind: str, workspace_id: str | None = None) -> int:
    spec = DATASETS.get(kind)
    if spec is None or not spec.demo:
        return 0
    key = spec.demo
    rng = random.Random(hash(kind) & 0xFFFF)
    if key.startswith("movement:"):
        return _movement(svc, user, workspace_id, rng, run_type=key.split(":", 1)[1])
    if key.startswith("runtype:"):
        return _runtype(svc, user, workspace_id, rng, run_type=key.split(":", 1)[1])
    return _BUILDERS[key](svc, user, workspace_id, rng)


# ------------------------------------------------------------------ helpers
def _sp(svc, user, ws, **fields):
    doc = dict(fields.pop("document", {}))
    doc["demo"] = True
    return svc.create_set_piece(user, tags=["demo"], document=doc, workspace_id=ws, **fields)


_ZONE_W = (("near", 35, 95, 44), ("far", 28, 95, 57), ("spot", 15, 89, 50),
           ("six", 12, 96, 50), ("edge", 10, 80, 50))


def _land(rng):
    """Realistic corner landing: near-post heavy, then far post, spot, edge."""
    z = rng.choices([r[0] for r in _ZONE_W], weights=[r[1] for r in _ZONE_W])[0]
    zx, zy = next((r[2], r[3]) for r in _ZONE_W if r[0] == z)
    return round(zx + rng.uniform(-2, 2), 1), round(zy + rng.uniform(-3, 3), 1)


def _corner(svc, user, ws, rng, **extra):
    ex, ey = _land(rng)
    taker = rng.choice(["Demo Silva", "Demo Adeyemi"])
    base = dict(type="corner", phase="offensive", perspective="own", team="Demo FC",
                opponent="Demo Opp", competition="Demo League", taker=taker,
                foot=("left" if taker.endswith("Silva") else "right"),
                side=("right" if taker.endswith("Silva") else "left"),
                delivery_type=rng.choices(["inswing", "outswing", "driven"], weights=[6, 3, 1])[0],
                start_x=100, start_y=(100 if taker.endswith("Silva") else 0),
                end_x=ex, end_y=ey, players_in_box=rng.randint(5, 7),
                minute=rng.randint(1, 90), period=rng.randint(1, 2))
    base.update(extra)
    return _sp(svc, user, ws, **base)


# ------------------------------------------------------------------ builders
def _delivery(svc, user, ws, rng, n=40):
    """Professional distribution: 40 deliveries, ~25 successful, ~6 goals."""
    for i in range(n):
        success = i < 25
        goal = i < 6
        outcome = ("goal" if goal else ("shot" if success
                   else rng.choice(["clearance", "off_target", "lost", "blocked"])))
        _corner(svc, user, ws, rng, shot=success, goal=goal, outcome=outcome,
                first_contact_team=rng.choices(["attack", "defence"], weights=[6, 4])[0],
                second_ball_team=rng.choice(["attack", "defence"]),
                retained=(rng.random() < 0.3),
                xg=(round(0.08 + rng.random() * 0.35, 2) if success else None))
    return n


def _delivery_traj(svc, user, ws, rng, n=10):
    for i in range(n):
        side = "right" if i % 2 else "left"
        _corner(svc, user, ws, rng, side=side, start_x=100, start_y=(100 if side == "right" else 0),
                outcome="shot" if i < 4 else "clearance")
    return n


def _delivery_acc(svc, user, ws, rng, n=8):
    for i in range(n):
        tx, ty = 94, 46
        _corner(svc, user, ws, rng, document={"target_x": tx, "target_y": ty})
    return n


def _occupancy(svc, user, ws, rng, n=8):
    for _ in range(n):
        sp = _corner(svc, user, ws, rng)
        for r in _ROLES:
            svc.add_position(user, sp.id, team="attack", player=f"A-{r}", role=r,
                             x=_role_x(r, rng), y=_role_y(r, rng))
    return n


def _defence(svc, user, ws, rng, n=8):
    for _ in range(n):
        sp = _corner(svc, user, ws, rng, phase="defensive")
        for j, r in enumerate(("near_post", "far_post", "six_yard", "central", "penalty_spot")):
            svc.add_position(user, sp.id, team="defence", player=f"D{j}",
                             marking=("man" if j % 2 else "zonal"),
                             x=_role_x(r, rng), y=_role_y(r, rng))
        svc.add_position(user, sp.id, team="defence", player="GK", is_gk=True, x=98, y=50)
    return n


def _marking(svc, user, ws, rng, n=8):
    for _ in range(n):
        sp = _corner(svc, user, ws, rng)
        for j, r in enumerate(("near_post", "far_post", "central")):
            svc.add_position(user, sp.id, team="attack", player=f"A{j}", role=r,
                             x=_role_x(r, rng), y=_role_y(r, rng))
            svc.add_position(user, sp.id, team="defence", player=f"D{j}", marking="man",
                             x=_role_x(r, rng) - 1, y=_role_y(r, rng) + 1)
    return n


def _movement(svc, user, ws, rng, run_type=None):
    n = 8
    rts = [run_type] if run_type else ["near_post", "far_post", "late", "edge"]
    for _ in range(n):
        sp = _corner(svc, user, ws, rng)
        for j in range(4):
            rt = run_type or rts[j % len(rts)]
            bx, by = 84 + rng.uniform(-3, 3), 40 + j * 6
            svc.add_position(user, sp.id, team="attack", player=f"R{j}", moment="before", x=bx, y=by)
            svc.add_position(user, sp.id, team="attack", player=f"R{j}", moment="delivery",
                             run_type=rt, x=bx + 8, y=by + rng.uniform(-2, 2))
    return n


def _runtype(svc, user, ws, rng, run_type):
    n = 8
    for _ in range(n):
        sp = _corner(svc, user, ws, rng)
        for j in range(3):
            svc.add_position(user, sp.id, team="defence", player=f"B{j}", run_type=run_type,
                             x=90 + rng.uniform(-3, 4), y=46 + j * 4)
    return n


def _wall(svc, user, ws, rng, n=8):
    for _ in range(n):
        sp = _sp(svc, user, ws, type="free_kick", phase="defensive", perspective="own",
                 team="Demo FC", opponent="Demo Opp", end_x=88, end_y=50, minute=rng.randint(1, 90))
        for j in range(4):
            svc.add_position(user, sp.id, team="defence", player=f"W{j}", role="wall",
                             run_type="wall", x=78, y=44 + j * 3)
    return n


def _gk(svc, user, ws, rng, n=8):
    for _ in range(n):
        sp = _corner(svc, user, ws, rng, phase="defensive")
        svc.add_position(user, sp.id, team="defence", player="GK", is_gk=True,
                         x=97 + rng.uniform(-1, 1.5), y=50 + rng.uniform(-3, 3))
    return n


def _gk_move(svc, user, ws, rng, n=8):
    for _ in range(n):
        sp = _corner(svc, user, ws, rng, phase="defensive")
        svc.add_position(user, sp.id, team="defence", player="GK", is_gk=True, moment="before",
                         x=98, y=50)
        svc.add_position(user, sp.id, team="defence", player="GK", is_gk=True, moment="delivery",
                         x=95 + rng.uniform(-1, 2), y=50 + rng.uniform(-4, 4))
    return n


def _contacts(kind):
    def build(svc, user, ws, rng, n=12):
        for i in range(n):
            sp = _corner(svc, user, ws, rng, shot=(kind == "shot"),
                         goal=(kind == "shot" and i < 3), xg=round(0.1 + rng.random() * 0.3, 2))
            x, y = 93 + rng.uniform(-2, 3), 46 + rng.uniform(-6, 8)
            if kind == "shot":
                svc.add_contact(user, sp.id, kind="shot", team="attack", player=f"S{i}",
                                x=x, y=y, outcome=("goal" if i < 3 else "miss"))
            elif kind == "first_contact":
                svc.add_contact(user, sp.id, kind="first_contact", team=("attack" if i % 2 else "defence"),
                                player=f"C{i}", x=x, y=y, body_part="head", won=(i % 2 == 0),
                                outcome=("goal" if i < 2 else "clearance"))
            elif kind == "second_ball":
                svc.add_contact(user, sp.id, kind="second_ball", team=("attack" if i % 2 else "defence"),
                                player=f"C{i}", x=82 + rng.uniform(-4, 6), y=y, won=(i % 2 == 0))
            elif kind == "clearance":
                svc.add_contact(user, sp.id, kind="clearance", team="defence", player=f"D{i}",
                                x=86 + rng.uniform(-4, 4), y=40 + rng.uniform(-6, 20), outcome="clearance")
            elif kind == "flick":
                svc.add_contact(user, sp.id, kind="first_contact", team="attack", player=f"F{i}",
                                x=95, y=44 + rng.uniform(-2, 2), body_part="head", won=True)
        return n
    return build


def _penalty(svc, user, ws, rng, n=25):
    """25 penalties with a realistic corner-weighted placement distribution
    (takers favour the bottom corners; centre is rare)."""
    shooters = ["Demo Kane", "Demo Silva", "Demo Sonny"]
    # corners heavy, centre light — as in professional data
    place_w = {"bottom_left": 22, "bottom_right": 24, "top_left": 14, "top_right": 15,
               "middle_left": 10, "middle_right": 9, "center": 6}
    for i in range(n):
        placement = rng.choices(list(place_w), weights=list(place_w.values()))[0]
        dive = rng.choices(_DIVES, weights=[40, 40, 20])[0]
        # keeper saves when they go the right way (~ realistic conversion ~78%)
        correct = dive in placement
        outcome = "goal" if not correct or rng.random() < 0.55 else \
            rng.choice(["saved", "saved", "miss"])
        _sp(svc, user, ws, type="penalty", phase="offensive", perspective="own", team="Demo FC",
            taker=rng.choice(shooters), foot=rng.choice(["left", "right"]),
            outcome=outcome, goal=(outcome == "goal"), shot=True, xg=0.78,
            minute=rng.randint(1, 90),
            document={"placement": placement, "gk_dive": dive, "goalkeeper": "Demo Keeper",
                      "gk_dive_timing": rng.choices(["early", "on_time", "late"], weights=[3, 5, 2])[0],
                      "gk_correct": correct})
    return n


_BUILDERS = {
    "delivery": _delivery, "delivery_traj": _delivery_traj, "delivery_acc": _delivery_acc,
    "occupancy": _occupancy, "defence": _defence, "marking": _marking, "wall": _wall,
    "gk": _gk, "gk_move": _gk_move, "penalty": _penalty,
    "movement": lambda svc, user, ws, rng: _movement(svc, user, ws, rng, None),
    "shot": _contacts("shot"), "first_contact": _contacts("first_contact"),
    "second_ball": _contacts("second_ball"), "clearance": _contacts("clearance"),
    "flick": _contacts("flick"),
}


# ------------------------------------------------------------------ fill-missing
# Add a single missing component to an EXISTING set piece (Part 13). Child rows
# are marked document.demo=True so they can be cleared without touching the
# real parent set piece.
def fill_positions(svc, sp_id, rng) -> None:
    for r in _ROLES:
        svc.positions.add(SetPiecePosition(
            id=str(uuid.uuid4()), set_piece_id=sp_id, team="attack", player=f"A-{r}", role=r,
            x=_role_x(r, rng), y=_role_y(r, rng), moment="delivery", document={"demo": True}))
    for j, r in enumerate(("near_post", "far_post", "six_yard")):
        svc.positions.add(SetPiecePosition(
            id=str(uuid.uuid4()), set_piece_id=sp_id, team="defence", player=f"D{j}", role=r,
            marking=("man" if j % 2 else "zonal"), x=_role_x(r, rng) - 1, y=_role_y(r, rng) + 1,
            moment="delivery", document={"demo": True}))


def fill_goalkeeper(svc, sp_id, rng) -> None:
    svc.positions.add(SetPiecePosition(id=str(uuid.uuid4()), set_piece_id=sp_id, team="defence",
                                       player="GK", is_gk=True, moment="before", x=98, y=50,
                                       document={"demo": True}))
    svc.positions.add(SetPiecePosition(id=str(uuid.uuid4()), set_piece_id=sp_id, team="defence",
                                       player="GK", is_gk=True, moment="delivery",
                                       x=round(96 + rng.uniform(-1, 2), 1),
                                       y=round(50 + rng.uniform(-4, 4), 1), document={"demo": True}))


def fill_contacts(svc, sp_id, rng, goal=False) -> None:
    x, y = round(93 + rng.uniform(-2, 3), 1), round(46 + rng.uniform(-6, 8), 1)
    svc.contacts.add(SetPieceContact(id=str(uuid.uuid4()), set_piece_id=sp_id, kind="first_contact",
                                     team="attack", player="C", x=x, y=y, body_part="head", won=True,
                                     outcome=("goal" if goal else "shot"), document={"demo": True}))
    svc.contacts.add(SetPieceContact(id=str(uuid.uuid4()), set_piece_id=sp_id, kind="second_ball",
                                     team="attack", x=round(82 + rng.uniform(-3, 5), 1), y=y, won=True,
                                     document={"demo": True}))
    if goal or rng.random() < 0.4:
        svc.contacts.add(SetPieceContact(id=str(uuid.uuid4()), set_piece_id=sp_id, kind="shot",
                                         team="attack", x=x, y=y, outcome=("goal" if goal else "miss"),
                                         document={"demo": True}))


# ------------------------------------------------------------------ geometry
def _role_x(role, rng):
    base = {"near_post": 95, "far_post": 95, "penalty_spot": 89, "six_yard": 96,
            "edge_box": 80, "central": 90, "gk_area": 98}.get(role, 90)
    return round(base + rng.uniform(-1.5, 1.5), 1)


def _role_y(role, rng):
    base = {"near_post": 44, "far_post": 57, "penalty_spot": 50, "six_yard": 50,
            "edge_box": 50, "central": 50, "gk_area": 50}.get(role, 50)
    return round(base + rng.uniform(-2, 2), 1)
