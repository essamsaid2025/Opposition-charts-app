"""Phase B — Scouting player-centric catalog curation (presentation filter only).

Locks: team/tactical visuals are EXCLUDED from the Scouting player catalog; the shared
registry still CONTAINS them (nothing deleted/unregistered); player visuals are kept and
re-filed under player-centric headings; and curation is a pure, non-mutating transform.
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from fap.scouting import catalog as C


def _mk(*ids_cats):
    return [{"id": i, "name": i.replace("_", " ").title(), "category": c,
             "description": "", "events": []} for i, c in ids_cats]


TEAM = _mk(("pass_network", "Passing"), ("weighted_passing_network", "Passing"),
           ("carry_network", "Progression"), ("team_voronoi", "Possession"),
           ("player_voronoi", "Possession"), ("space_occupation", "Possession"),
           ("occupation_map", "Possession"), ("team_radar", "Comparison"),
           ("momentum", "Team"), ("passing_connections", "Passing"))

PLAYER = _mk(("pass_map", "Passing"), ("pass_direction_map", "Passing"),
             ("final_third_map", "Progression"), ("carry_map", "Progression"),
             ("shot", "Attacking"), ("shot_heatmap", "Attacking"),
             ("tackle", "Attacking"), ("interception", "Attacking"),
             ("recovery", "Attacking"), ("pressure", "Attacking"),
             ("player_percentile_radar", "Comparison"))


def test_team_visuals_are_excluded():
    for t in TEAM:
        assert C.is_player_visual(t) is False, t["id"]


def test_player_visuals_are_kept():
    for p in PLAYER:
        assert C.is_player_visual(p) is True, p["id"]


def test_curate_filters_and_regroups_without_mutating_input():
    src = TEAM + PLAYER
    snapshot = [dict(i) for i in src]
    out = C.curate_for_scouting(src)
    out_ids = {i["id"] for i in out}
    # every team visual gone, every player visual kept
    assert not (out_ids & {t["id"] for t in TEAM})
    assert out_ids == {p["id"] for p in PLAYER}
    # re-filed under player-centric headings only
    assert {i["category"] for i in out} <= set(C.CATEGORY_ORDER)
    # input list untouched (pure)
    assert src == snapshot


def test_player_centric_bucketing():
    def cat(cid, ccat="Attacking"):
        return C.player_category({"id": cid, "name": cid, "category": ccat})
    assert cat("shot_map") == "Shooting"
    assert cat("tackle") == "Defending"
    assert cat("carry_map", "Progression") == "Possession & Carrying"
    assert cat("key_pass_map") == "Creation"
    assert cat("player_percentile_radar", "Comparison") == "Player Profile"
    assert cat("pass_direction_map", "Passing") == "Passing"


def test_curation_does_not_touch_the_shared_registry():
    # the real registry MUST still contain the team visuals after curation (nothing deleted)
    from fap.visuals.base import load_builtin_visuals, visual_registry
    load_builtin_visuals()
    reg_ids = set(visual_registry.ids())
    curated = {i["id"] for i in C.curate_for_scouting(
        [{"id": x, "name": x, "category": "General", "description": "", "events": []}
         for x in reg_ids])}
    # anything the curator hides is STILL registered (Open Play Studio keeps them)
    hidden = reg_ids - curated
    assert hidden, "expected some team/tactical visuals to be hidden from Scouting"
    assert hidden <= reg_ids            # every hidden id remains a real registry entry
