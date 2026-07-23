"""Penalty analytics backend (Phase 9.2) - PURE functions.

Set piece rows of type ``penalty`` carry their shot/keeper detail in the
extensible ``document`` (so no schema migration is needed until the Phase 9.4
penalty UI lands, which will populate the same keys):

    document = {
        "placement": "top_left" | "top_center" | "top_right" |
                     "bottom_left" | "bottom_center" | "bottom_right" |
                     "middle_left" | "center" | "middle_right",
        "gk_dive":   "left" | "right" | "stay" | "center",
        "gk_correct": bool,          # dived to the correct side
        "reaction":  float,          # seconds
        "power":     "hard" | "medium" | "soft",
        "body_part": "left" | "right",
        "goalkeeper": "<name>",
    }
    outcome = "goal" | "saved" | "miss" | "post" | "bar"

These helpers turn a list of penalty SetPieces into the datasets the penalty
visualizations render; 9.4 reuses the exact same functions for its dashboards.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from fap.setpieces.models import SetPiece

# 3x3 goal grid in normalized goal coordinates: gx in [0,3), gy in [0,3) with
# gy=2 the top row. Cell centers are used to place heat / markers.
PLACEMENT_CELLS: dict[str, tuple[int, int]] = {
    "top_left": (0, 2), "top_center": (1, 2), "top_right": (2, 2),
    "middle_left": (0, 1), "center": (1, 1), "middle_right": (2, 1),
    "bottom_left": (0, 0), "bottom_center": (1, 0), "bottom_right": (2, 0),
}
DIVE_DIRECTIONS = ("left", "stay", "center", "right")
PENALTY_OUTCOMES = ("goal", "saved", "miss", "post", "bar")


def _penalties(sps: list[SetPiece]) -> list[SetPiece]:
    return [s for s in sps if s.type == "penalty"]


def _doc(s: SetPiece, key: str, default: Any = None) -> Any:
    return (s.document or {}).get(key, default)


def placement_grid(sps: list[SetPiece]) -> dict[str, Any]:
    """Counts per goal cell (for the Penalty Placement Heatmap) + raw points."""
    pens = _penalties(sps)
    counts: dict[str, int] = defaultdict(int)
    points: list[dict[str, Any]] = []
    for s in pens:
        cell = _doc(s, "placement")
        if cell in PLACEMENT_CELLS:
            counts[cell] += 1
            gx, gy = PLACEMENT_CELLS[cell]
            points.append({"cell": cell, "gx": gx, "gy": gy, "outcome": s.outcome,
                           "shooter": s.taker, "goalkeeper": _doc(s, "goalkeeper", "")})
    return {"n": len(pens), "counts": dict(counts), "points": points,
            "cells": PLACEMENT_CELLS}


def dive_grid(sps: list[SetPiece]) -> dict[str, Any]:
    """Goalkeeper dive distribution + correct-side rate."""
    pens = _penalties(sps)
    dives: dict[str, int] = defaultdict(int)
    correct = 0
    known = 0
    for s in pens:
        d = _doc(s, "gk_dive")
        if d in DIVE_DIRECTIONS:
            dives[d] += 1
        if _doc(s, "gk_correct") is not None:
            known += 1
            correct += 1 if _doc(s, "gk_correct") else 0
    return {"n": len(pens), "dives": dict(dives),
            "correct_pct": round(100.0 * correct / known, 1) if known else 0.0,
            "reaction_avg": _avg(_doc(s, "reaction") for s in pens)}


def dive_direction(sps: list[SetPiece]) -> list[dict[str, Any]]:
    """Directional vectors from goal center for the GK Dive Direction map."""
    grid = dive_grid(sps)
    vecs = {"left": (-1, 0), "right": (1, 0), "center": (0, 0), "stay": (0, -0.3)}
    return [{"direction": d, "count": n, "dx": vecs[d][0], "dy": vecs[d][1]}
            for d, n in grid["dives"].items()]


def outcomes(sps: list[SetPiece]) -> dict[str, Any]:
    pens = _penalties(sps)
    counts: dict[str, int] = defaultdict(int)
    for s in pens:
        counts[s.outcome or "unknown"] += 1
    scored = counts.get("goal", 0)
    return {"n": len(pens), "counts": dict(counts),
            "conversion_pct": round(100.0 * scored / len(pens), 1) if pens else 0.0}


def shooter_preference(sps: list[SetPiece]) -> dict[str, Any]:
    """Per-shooter placement/side preference + conversion."""
    return _preference(sps, key=lambda s: s.taker or "unknown")


def goalkeeper_preference(sps: list[SetPiece]) -> dict[str, Any]:
    """Per-goalkeeper dive preference + save rate."""
    pens = _penalties(sps)
    by_gk: dict[str, dict[str, Any]] = {}
    for s in pens:
        gk = _doc(s, "goalkeeper") or "unknown"
        rec = by_gk.setdefault(gk, {"faced": 0, "saved": 0, "dives": defaultdict(int)})
        rec["faced"] += 1
        if s.outcome == "saved":
            rec["saved"] += 1
        d = _doc(s, "gk_dive")
        if d in DIVE_DIRECTIONS:
            rec["dives"][d] += 1
    out = {}
    for gk, rec in by_gk.items():
        dives = rec["dives"]
        out[gk] = {"faced": rec["faced"], "saved": rec["saved"],
                   "save_pct": round(100.0 * rec["saved"] / rec["faced"], 1) if rec["faced"] else 0.0,
                   "preferred_dive": max(dives, key=dives.get) if dives else "",
                   "dives": dict(dives)}
    return out


def _preference(sps: list[SetPiece], key) -> dict[str, Any]:
    pens = _penalties(sps)
    by: dict[str, dict[str, Any]] = {}
    for s in pens:
        k = key(s)
        rec = by.setdefault(k, {"taken": 0, "scored": 0, "placements": defaultdict(int),
                                "sides": defaultdict(int)})
        rec["taken"] += 1
        if s.outcome == "goal":
            rec["scored"] += 1
        cell = _doc(s, "placement")
        if cell in PLACEMENT_CELLS:
            rec["placements"][cell] += 1
            side = "left" if "left" in cell else ("right" if "right" in cell else "center")
            rec["sides"][side] += 1
    out = {}
    for k, rec in by.items():
        placements = rec["placements"]
        sides = rec["sides"]
        out[k] = {"taken": rec["taken"], "scored": rec["scored"],
                  "conversion_pct": round(100.0 * rec["scored"] / rec["taken"], 1) if rec["taken"] else 0.0,
                  "preferred_placement": max(placements, key=placements.get) if placements else "",
                  "preferred_side": max(sides, key=sides.get) if sides else "",
                  "placements": dict(placements)}
    return out


def _avg(values) -> float | None:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else None
