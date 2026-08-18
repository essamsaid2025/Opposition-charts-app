"""Scouting player-visual catalog curation (Phase B) — a PRESENTATION filter only.

The shared visual engine (``fap.visuals.visual_registry``) carries the full Open-Play
catalog, including team/tactical visuals (pass networks, Voronoi, team shape, occupation,
momentum, build-up/transition structure). Those belong in Open Play Studio, NOT on a player
page. This module curates the registry catalog into a PLAYER-CENTRIC subset for the Scouting
player workspace's event-dataset path, organized by the analytical question an analyst asks
about a player.

It never deletes, unregisters, or mutates a registry entry — it only decides what appears in
the Scouting catalog and under which player-centric heading. First-Team and Open Play call the
shared workspace WITHOUT this curator, so their catalogs are untouched. Pure & deterministic:
input/output are the plain catalog dicts ``{id,name,category,description,events}``.
"""
from __future__ import annotations

from typing import Any

# team/tactical visuals that must NOT appear on a player page (strict exclusion). Matched as
# substrings against id + name + category (case-insensitive), so a NEW team visual is excluded
# by default rather than leaking in. These stay fully available to Open Play Studio.
_TEAM_HINTS: tuple[str, ...] = (
    "network", "voronoi", "occupation", "momentum", "connection", "team",
    "buildup", "build_up", "build-up", "transition", "compactness", "structure",
    "space_occ", "press_resist", "possession structure",
)
# explicit ids to exclude even if they dodge the hint match (belt-and-braces)
_EXCLUDE_IDS: frozenset[str] = frozenset({
    "pass_network", "weighted_passing_network", "carry_network", "passing_connections",
    "team_voronoi", "player_voronoi", "space_occupation", "occupation_map", "team_radar",
    "team_metric_over_time", "momentum", "match_stats",
})

# player-centric buckets, in display order. A visual is placed by the FIRST rule that matches
# its id/name/category — so the analyst sees "what can I learn about this player", not registry ids.
CATEGORY_ORDER: tuple[str, ...] = (
    "Player Profile", "Passing", "Possession & Carrying", "Creation",
    "Shooting", "Defending", "Goalkeeping", "Spatial",
)


def is_player_visual(info: dict[str, Any]) -> bool:
    """True when a registry catalog entry is player-answerable (not a team/tactical visual)."""
    if info.get("id") in _EXCLUDE_IDS:
        return False
    hay = f"{info.get('id','')} {info.get('name','')} {info.get('category','')}".lower()
    return not any(h in hay for h in _TEAM_HINTS)


def player_category(info: dict[str, Any]) -> str:
    """Map a registry entry onto a player-centric heading (analytical question)."""
    hay = f"{info.get('id','')} {info.get('name','')}".lower()
    cat = (info.get("category") or "").lower()
    if cat == "comparison" or any(k in hay for k in ("radar", "pizza", "percentile", "ranking", "kpi")):
        return "Player Profile"
    if cat == "goalkeeper" or any(k in hay for k in ("save", "goal_mouth", "claim", "punch")):
        return "Goalkeeping"
    if any(k in hay for k in ("key_pass", "assist", "chance", "creat")):
        return "Creation"
    if any(k in hay for k in ("shot", "goal", "xg", "finish")):
        return "Shooting"
    if any(k in hay for k in ("tackle", "intercept", "recover", "pressure", "block",
                              "clear", "defens", "duel")):
        return "Defending"
    if any(k in hay for k in ("carry", "progress", "receiv", "touch", "dribble")):
        return "Possession & Carrying"
    if "pass" in hay or cat == "passing":
        return "Passing"
    return "Spatial"


def curate_for_scouting(infos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter the shared registry catalog to the player-centric subset and re-file each visual
    under its player-centric heading. Returns NEW dicts (originals untouched), sorted by the
    player-centric category order then name — ready for the shared workspace's grouping UI."""
    out: list[dict[str, Any]] = []
    for info in infos:
        if not is_player_visual(info):
            continue
        item = dict(info)
        item["category"] = player_category(info)
        out.append(item)
    order = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    return sorted(out, key=lambda v: (order.get(v["category"], 99), v["name"]))
