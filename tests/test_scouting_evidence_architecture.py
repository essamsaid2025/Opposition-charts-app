"""P4.4 - Scouting match & evidence architecture (production-safety).

Invariant: PLAYER IDENTITY != DATASET ID != MATCH ID != EVENT ID, with evidence
anchored to the persistent player_id + (dataset_id, match_id) - NEVER the active
dataset. Importing/switching a dataset must never hide, overwrite or reassign
another dataset's evidence. Player-scouting datasets never yield event evidence.
Nothing is fabricated. Includes the mandatory dataset-switch scenario.
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dataclasses import replace

import pandas as pd
import pytest

from fap.scouting import evidence


# ---------------------------------------------------------------- pure model
def test_event_rows_scopes_by_identity_team_match():
    df = pd.DataFrame({
        "player": ["S. Mamadu bah", "S. Mamadu bah", "Other"], "team": ["Home", "Home", "Away"],
        "match_id": ["M001", "M002", "M001"], "event_type": ["pass", "shot", "pass"],
        "x": [1, 2, 3], "y": [1, 2, 3]})
    keys = {"mamadu bah", "s. mamadu bah"}
    assert len(evidence.event_rows(df, keys)) == 2
    assert len(evidence.event_rows(df, keys, match_id="M001")) == 1
    assert len(evidence.event_rows(df, keys, team="away")) == 0     # player isn't Away


def test_matches_in_uses_real_match_id_never_fabricated():
    df = pd.DataFrame({"player": ["S. Mamadu bah"] * 3, "match_id": ["M001", "M001", "M002"],
                       "opponent": ["A", "A", "B"], "event_type": ["pass"] * 3, "x": [1, 2, 3], "y": [1, 2, 3]})
    ms = {m["match_id"]: m for m in evidence.matches_in(df, {"s. mamadu bah"})}
    assert set(ms) == {"M001", "M002"}
    assert ms["M001"]["event_count"] == 2 and ms["M001"]["opponent"] == "A"


def test_matches_in_no_match_id_column_is_legacy_not_fabricated():
    df = pd.DataFrame({"player": ["S. Mamadu bah", "S. Mamadu bah"], "event_type": ["pass", "shot"],
                       "x": [1, 2], "y": [1, 2]})
    ms = evidence.matches_in(df, {"s. mamadu bah"})
    assert len(ms) == 1 and ms[0]["match_id"] == evidence.LEGACY_MATCH


# ---------------------------------------------------------------- integration
@pytest.fixture()
def ctx(tmp_path):
    from fap.config.settings import (
        AppSettings, CacheSettings, DatabaseSettings, StorageSettings)
    from fap.bootstrap import init_platform
    from fap.identity.models import User
    from fap.identity.roles import Role
    settings = replace(AppSettings(environment="development"),
                       user_data_dir=str(tmp_path / "ud"),
                       database=DatabaseSettings(path=str(tmp_path / "ud" / "fap.sqlite3")),
                       cache=CacheSettings(backend="memory"),
                       storage=StorageSettings(backend="local"))
    platform = init_platform(settings=settings)
    user = User(email="a@club.com", name="Ana", role=Role.SUPER_ADMIN, provider_id="dev")
    ws = platform.workspace_manager.ensure_workspace(user)
    try:
        yield platform, user, ws
    finally:
        platform.db.close()


def _event_csv(match, opponent, n, player="S. Mamadu bah"):
    rows = "event_type,x,y,team,player,minute,match_id,opponent\n"
    for i in range(n):
        rows += f"pass,{10 + i},20,Home,{player},{i + 1},{match},{opponent}\n"
    return rows.encode()


def _import_event(platform, user, ws, csv, name, opponent):
    er = platform.datahub.analyze(csv, name + ".csv")
    return platform.datahub.save_dataset(user, er.import_result, name=name, workspace_id=ws.id,
                                         metadata={"opponent": opponent})


def _setup_two_matches(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    p = sc.create_player(user, "Mamadu Bah", workspace_id=ws.id)   # registry name differs from dataset
    sc.add_alias(user, p.id, "S. Mamadu bah")
    d1 = _import_event(platform, user, ws, _event_csv("M001", "Team A", 15), "Malta vs A", "Team A")
    d2 = _import_event(platform, user, ws, _event_csv("M002", "Team B", 23), "Malta vs B", "Team B")
    platform.datahub.choose(user, d1.id)
    sc.link_match_evidence(user, p.id, d1.id, match_id="M001")
    platform.datahub.choose(user, d2.id)                           # switch active BEFORE linking d2
    sc.link_match_evidence(user, p.id, d2.id, match_id="M002")
    return platform, user, ws, sc, p, d1, d2


# ---- the MANDATORY dataset-switch scenario (spec §11) ----
def test_mandatory_dataset_switch_scenario(ctx):
    platform, user, ws, sc, p, d1, d2 = _setup_two_matches(ctx)
    # 9-10: with D002 active, player-wide evidence still has BOTH matches
    allm = {e["match_id"]: e["event_count"] for e in sc.player_evidence(user, p.id)["matches"]}
    assert allm == {"M001": 15, "M002": 23}
    # 11-12: M001 query returns ONLY M001
    m1 = sc.player_evidence(user, p.id, match_id="M001")["matches"]
    assert [(e["match_id"], e["event_count"]) for e in m1] == [("M001", 15)]
    # 13-14: M002 query returns ONLY M002
    m2 = sc.player_evidence(user, p.id, match_id="M002")["matches"]
    assert [(e["match_id"], e["event_count"]) for e in m2] == [("M002", 23)]
    # 15-16: switch active back to D001 -> M002 evidence STILL exists
    platform.datahub.choose(user, d1.id)
    assert sc.player_evidence(user, p.id, match_id="M002")["matches"][0]["event_count"] == 23
    assert sc.player_evidence(user, p.id, match_id="M001")["matches"][0]["event_count"] == 15


def test_importing_second_dataset_does_not_touch_first(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    p = sc.create_player(user, "Mamadu Bah", workspace_id=ws.id)
    sc.add_alias(user, p.id, "S. Mamadu bah")
    d1 = _import_event(platform, user, ws, _event_csv("M001", "Team A", 15), "A", "Team A")
    sc.link_match_evidence(user, p.id, d1.id, match_id="M001")
    link1 = sc._evidence_links(sc.get_player(p.id))[0].to_dict()
    # import + link a SECOND dataset
    d2 = _import_event(platform, user, ws, _event_csv("M002", "Team B", 23), "B", "Team B")
    sc.link_match_evidence(user, p.id, d2.id, match_id="M002")
    link1_after = next(l.to_dict() for l in sc._evidence_links(sc.get_player(p.id))
                       if l.dataset_id == d1.id)
    assert link1_after == link1                                    # D001 link byte-identical


def test_exact_scope_never_falls_back(ctx):
    platform, user, ws, sc, p, d1, d2 = _setup_two_matches(ctx)
    assert sc.player_evidence(user, p.id, match_id="M999")["matches"] == []
    assert sc.player_evidence(user, p.id, dataset_id="nonexistent")["matches"] == []
    # dataset-specific query is exact
    only_d1 = sc.player_evidence(user, p.id, dataset_id=d1.id)["matches"]
    assert len(only_d1) == 1 and only_d1[0]["dataset_id"] == d1.id


def test_player_matches_aggregates_and_is_canonical(ctx):
    platform, user, ws, sc, p, d1, d2 = _setup_two_matches(ctx)
    ms = {m["match_id"]: m for m in sc.player_matches(user, p.id)}
    assert set(ms) == {"M001", "M002"}
    assert ms["M001"]["opponent"] == "Team A" and ms["M001"]["event_count"] == 15
    # player_id is canonical: rename display, evidence unchanged
    sc.set_display_name(user, p.id, "Mamadu")
    ms2 = {m["match_id"]: m["event_count"] for m in sc.player_matches(user, p.id)}
    assert ms2 == {"M001": 15, "M002": 23}


def test_alias_resolution_keeps_evidence(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    p = sc.create_player(user, "Mamadu Bah", workspace_id=ws.id)   # no alias yet
    d1 = _import_event(platform, user, ws, _event_csv("M001", "A", 10), "A", "A")
    # without the alias, the dataset name "S. Mamadu bah" doesn't match -> 0 events
    sc.link_match_evidence(user, p.id, d1.id, match_id="M001")
    assert sc.player_evidence(user, p.id, match_id="M001")["matches"] == []
    # add the alias -> re-link recomputes and evidence resolves
    sc.add_alias(user, p.id, "S. Mamadu bah")
    sc.link_match_evidence(user, p.id, d1.id, match_id="M001")
    assert sc.player_evidence(user, p.id, match_id="M001")["matches"][0]["event_count"] == 10


def test_two_datasets_one_match_and_two_matches(ctx):
    platform, user, ws, sc, p, d1, d2 = _setup_two_matches(ctx)
    # two datasets -> two matches already (M001, M002)
    assert len({m["match_id"] for m in sc.player_matches(user, p.id)}) == 2
    # two datasets -> ONE match: link a tracking dataset also to M001
    d3 = _import_event(platform, user, ws, _event_csv("M001", "Team A", 7), "A tracking", "Team A")
    sc.link_match_evidence(user, p.id, d3.id, match_id="M001")
    m1 = next(m for m in sc.player_matches(user, p.id) if m["match_id"] == "M001")
    assert len(m1["datasets"]) == 2 and m1["event_count"] == 22   # 15 + 7


def test_player_scouting_dataset_yields_no_event_evidence(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    p = sc.create_player(user, "Mamadu Bah", workspace_id=ws.id)
    sc.add_alias(user, p.id, "S. Mamadu bah")
    ps = ("Player,Team,Goals per 90\nS. Mamadu bah,Sliema,0.4\nX,Y,0.2\n").encode()
    psds = platform.datahub.save_scouting_dataset(
        user, platform.datahub.analyze(ps, "ps.csv").scouting, name="metrics", workspace_id=ws.id)
    link = sc.link_match_evidence(user, p.id, psds.id)
    assert link["dataset_type"] == "player_scouting" and link["event_count"] == 0
    assert sc.player_matches(user, p.id) == []                    # contributes no matches
    entry = sc.player_evidence(user, p.id, dataset_id=psds.id)["matches"]
    assert entry and entry[0]["event_count"] == 0 and "no event evidence" in entry[0]["note"]


def test_legacy_evidence_without_match_id_accessible(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    p = sc.create_player(user, "Mamadu Bah", workspace_id=ws.id)
    sc.add_alias(user, p.id, "S. Mamadu bah")
    # dataset with NO match_id column -> legacy scope, still accessible, not fabricated
    csv = "event_type,x,y,team,player\npass,1,2,Home,S. Mamadu bah\nshot,3,4,Home,S. Mamadu bah\n".encode()
    d = _import_event(platform, user, ws, csv, "legacy", "?") if False else \
        platform.datahub.save_dataset(user, platform.datahub.analyze(csv, "legacy.csv").import_result,
                                      name="legacy", workspace_id=ws.id, metadata={})
    sc.link_match_evidence(user, p.id, d.id)
    ms = sc.player_matches(user, p.id)
    assert len(ms) == 1 and ms[0]["match_id"] == evidence.LEGACY_MATCH and ms[0]["event_count"] == 2


def test_active_dataset_is_only_query_context(ctx):
    platform, user, ws, sc, p, d1, d2 = _setup_two_matches(ctx)
    # clear the active dataset entirely -> evidence still fully available
    platform.workspace_manager.clear_active_dataset(user)
    allm = {e["match_id"]: e["event_count"] for e in sc.player_evidence(user, p.id)["matches"]}
    assert allm == {"M001": 15, "M002": 23}


def test_event_capability_and_manual_tag(ctx):
    platform, user, ws, sc, p, d1, d2 = _setup_two_matches(ctx)
    link = sc._evidence_links(sc.get_player(p.id))[0]
    rec = sc.add_evidence_tag(user, p.id, link.id, event_id="0", tag="line-break", note="good")
    tags = sc._evidence_links(sc.get_player(p.id))[0].tags
    assert tags and tags[0]["tag"] == "line-break" and tags[0]["event_id"] == "0"


def test_evidence_ui_renders(ctx):
    platform, user, ws, sc, p, d1, d2 = _setup_two_matches(ctx)
    import matplotlib
    matplotlib.use("Agg")
    import streamlit as st
    st.session_state.clear()
    from fap.ui.builtin.scouting import ScoutingPage

    class _Shell:
        def __init__(self):
            self.user = user
            self.platform = platform
            self.wm = platform.workspace_manager
            self.workspace_id = ws.id

        def goto(self, _):
            pass
    page = ScoutingPage()
    page._can_edit = True
    page._evidence_section(_Shell(), sc, p)          # matches list renders
    # empty state renders too
    p2 = sc.create_player(user, "No Evidence", workspace_id=ws.id)
    page._evidence_section(_Shell(), sc, p2)
