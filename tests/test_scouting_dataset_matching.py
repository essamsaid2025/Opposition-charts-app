"""P4.2.1 - Scouting registration + dataset identity resolution.

The registered Player is the source of truth; the dataset is evidence. A player
resolves to a dataset row through a deterministic, explainable matcher
(exact/normalized/initial-variant/alias), never exact-name-only. Confirmed
mappings persist. Player creation and the profile NEVER depend on a dataset match.
The dataset's spelling never becomes the player's identity.
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dataclasses import replace
from types import SimpleNamespace

import pandas as pd
import pytest

from fap.scouting import identity, matching


def _player(name, aliases=None, display=None, club="", position="", country=""):
    doc = {"aliases": aliases or []}
    if display:
        doc["display_name"] = display
    return SimpleNamespace(name=name, document=doc, club=club, position=position,
                           nationality=country, country=country, league="")


def _ent(key, **dims):
    return matching.DatasetEntity(key, dims)


# ================================================================ pure matcher
def test_normalization_variants():
    assert matching.normalize_name("S. Mamadu bah") == "s mamadu bah"
    assert matching.normalize_name("  S.  MAMADU   BAH ") == "s mamadu bah"
    assert matching.normalize_name("O'Neill-Smith") == "o neill smith"
    assert matching.normalize_name("Zinédine") == "zinedine"


def test_exact_and_normalized_match():
    ents = [_ent("S. Mamadu bah")]
    assert matching.match_player(_player("S. Mamadu bah"), ents).candidate.method == "Exact name"
    assert matching.match_player(_player("s  mamadu BAH"), ents).status == "matched"


def test_initial_variant_match():
    ents = [_ent("S. Mamadu bah")]
    r = matching.match_player(_player("Mamadu Bah"), ents)
    assert r.status == "matched" and r.auto
    assert r.candidate.method == "Initial + normalized name" and r.candidate.confidence == "high"


def test_reverse_initial_variant():
    ents = [_ent("A. Ahmed Mohamed")]
    assert matching.match_player(_player("Ahmed Mohamed"), ents).status == "matched"


def test_alias_match():
    ents = [_ent("S. Mamadu bah")]
    r = matching.match_player(_player("Different Name", aliases=["S. Mamadu bah"]), ents)
    assert r.status == "matched"


def test_surname_initial_is_medium_not_auto():
    ents = [_ent("J. Smith")]
    r = matching.match_player(_player("John Smith"), ents)
    assert r.status == "matched" and r.candidate.confidence == "medium" and r.auto is False


def test_ambiguous_two_initial_variants_surfaced():
    ents = [_ent("S. Mamadu bah", team="Sliema"), _ent("M. Mamadu bah", team="Sirens")]
    r = matching.match_player(_player("Mamadu Bah"), ents)  # no dims -> cannot disambiguate
    assert r.status == "ambiguous" and len(r.candidates) == 2


def test_ambiguous_resolved_by_dimension():
    ents = [_ent("S. Mamadu bah", team="Sliema Wanderers"), _ent("M. Mamadu bah", team="Sirens")]
    r = matching.match_player(_player("Mamadu Bah", club="Sliema Wanderers"), ents)
    assert r.status == "matched" and r.candidate.key == "S. Mamadu bah"


def test_not_found():
    assert matching.match_player(_player("Nobody"), [_ent("S. Mamadu bah")]).status == "not_found"


def test_no_dataset_values_modified():
    df = pd.DataFrame({"Player": ["S. Mamadu bah"], "Team": ["A"]})
    before = df.copy(deep=True)
    matching.dataset_entities(df, {"id_field": "Player", "dimensions": {"team": "Team"}})
    assert df.equals(before)


# ================================================================ integration
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


def _malta_like():
    metrics = ["Non-penalty goals per 90", "npxG per 90", "Progressive passes per 90",
               "xA per 90", "Shot assists per 90", "Touches in box per 90", "Duels won, %"]
    rows = []
    names = ["S. Mamadu bah"] + [f"Player {i}" for i in range(32)]
    for i, nm in enumerate(names):
        r = {"Player": nm, "Team": "Sliema Wanderers" if i == 0 else f"Club {i}",
             "Age": 24, "League": "Malta Premier League 25-26", "Position": "CF"}
        for j, m in enumerate(metrics):
            r[m] = ((i * 7 + j * 3) % 100) / 100.0
        rows.append(r)
    return pd.DataFrame(rows).to_csv(index=False).encode()


def _activate(platform, user, ws, name="Malta CF.csv"):
    ar = platform.datahub.analyze(_malta_like(), name)
    ds = platform.datahub.save_scouting_dataset(user, ar.scouting, name=name, workspace_id=ws.id)
    platform.datahub.choose(user, ds.id)
    return ds


# ---- IDs visible (1/2/3/4/5/6) ----
def test_ids_generated_and_visible_in_registry_and_status(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    ft = sc.create_player(user, "A", workspace_id=ws.id)
    ac = sc.create_player(user, "B", workspace_id=ws.id, player_type="academy")
    tr = sc.create_player(user, "C", workspace_id=ws.id, player_type="trialist")
    assert identity.operational_id_of(ft) == "CLB-000001"
    assert identity.operational_id_of(ac) == "ACD-000001"
    assert identity.operational_id_of(tr) == "TRI-000001"
    reg = {r["name"]: r["operational_id"] for r in sc.player_registry(user, workspace_id=ws.id)}
    assert reg["A"] == "CLB-000001" and reg["B"] == "ACD-000001"


# ---- name-independent resolution (7/8/9/10/11) ----
def test_registered_name_resolves_to_dataset_variant(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    _activate(platform, user, ws)
    p = sc.create_player(user, "Mamadu Bah", workspace_id=ws.id, club="Sliema Wanderers")
    m = sc.match_player_in_active_dataset(user, p.id)
    assert m["match"]["status"] == "matched"
    assert m["match"]["candidate"]["key"] == "S. Mamadu bah"
    # metrics auto-resolve for the high-confidence match (no exact name needed)
    prof = sc.active_scouting_profile(user, p.id)
    assert prof is not None and prof["player"] == "S. Mamadu bah"


# ---- manual confirm + persistence (12/13/14) ----
def test_manual_link_persists_across_reload(ctx, tmp_path):
    platform, user, ws = ctx
    sc = platform.scouting
    _activate(platform, user, ws)
    p = sc.create_player(user, "Mamadou B", workspace_id=ws.id)
    sc.link_dataset_identity(user, p.id, "S. Mamadu bah", method="manual")
    st = sc.dataset_link_status(user, p.id)
    assert st["linked"] and st["entity_key"] == "S. Mamadu bah" and st["method"] == "manual"
    # reload the same DB -> mapping survives
    from fap.config.settings import (
        AppSettings, CacheSettings, DatabaseSettings, StorageSettings)
    from fap.bootstrap import init_platform
    from fap.identity.models import User
    from fap.identity.roles import Role
    ds_path = str(tmp_path / "ud" / "fap.sqlite3")
    settings = replace(AppSettings(environment="development"),
                       user_data_dir=str(tmp_path / "ud"),
                       database=DatabaseSettings(path=ds_path),
                       cache=CacheSettings(backend="memory"), storage=StorageSettings(backend="local"))
    p2 = init_platform(settings=settings)
    try:
        u2 = User(email="a@club.com", name="Ana", role=Role.SUPER_ADMIN, provider_id="dev")
        st2 = p2.scouting.dataset_link_status(u2, p.id)
        assert st2["linked"] and st2["entity_key"] == "S. Mamadu bah"
    finally:
        p2.db.close()


# ---- creation/profile never depend on dataset (15/16/17) ----
def test_creation_and_profile_work_without_dataset_match(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    _activate(platform, user, ws)
    p = sc.create_player(user, "John Smith", workspace_id=ws.id)   # not in dataset
    st = sc.dataset_link_status(user, p.id)
    assert st["player_exists"] is True and st["dataset_active"] is True
    assert st["linked"] is False and st["metrics_available"] is False
    assert sc.active_scouting_profile(user, p.id) is None          # honest, not an error
    # the player and all its assets still work
    sc.add_note(user, p.id, "watch him")
    assert len(sc.list_notes(p.id)) == 1


def test_no_active_dataset_status(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    p = sc.create_player(user, "X", workspace_id=ws.id)
    st = sc.dataset_link_status(user, p.id)
    assert st["player_exists"] and st["dataset_active"] is False and st["linked"] is False


# ---- ambiguity via service (18) ----
def test_ambiguous_surfaced_via_service(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    # dataset with two initial-variants of "Mamadu Bah"
    df = pd.DataFrame({"Player": ["S. Mamadu bah", "M. Mamadu bah"],
                       "Team": ["Sliema", "Sirens"], "Goals per 90": [0.4, 0.3],
                       "xG per 90": [0.3, 0.2], "Passes per 90": [0.5, 0.6]})
    ar = platform.datahub.analyze(df.to_csv(index=False).encode(), "amb.csv")
    ds = platform.datahub.save_scouting_dataset(user, ar.scouting, name="amb", workspace_id=ws.id)
    platform.datahub.choose(user, ds.id)
    p = sc.create_player(user, "Mamadu Bah", workspace_id=ws.id)   # no club -> can't disambiguate
    st = sc.dataset_link_status(user, p.id)
    assert st["linked"] is False and len(st["candidates"]) == 2
    assert sc.active_scouting_profile(user, p.id) is None          # never guesses


# ---- no fabrication (19/20) ----
def test_dataset_not_modified_and_no_fabricated_metrics(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    ds = _activate(platform, user, ws)
    before = platform.workspace_manager.dataset_frame(ds.id).copy(deep=True)
    p = sc.create_player(user, "Mamadu Bah", workspace_id=ws.id, club="Sliema Wanderers")
    sc.active_scouting_profile(user, p.id)
    sc.profile_fit_for(user, p.id, "false_9")
    after = platform.workspace_manager.dataset_frame(ds.id)
    assert before.equals(after)                                    # dataset untouched


# ---- search (21/22/23) ----
def test_search_by_opid_alias_dataset_name(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    _activate(platform, user, ws)
    p = sc.create_player(user, "Mamadu Bah", workspace_id=ws.id, club="Sliema Wanderers")
    sc.add_alias(user, p.id, "Johnny B")
    sc.link_dataset_identity(user, p.id, "S. Mamadu bah", method="manual")
    op = identity.operational_id_of(sc.get_player(p.id))
    assert [r["name"] for r in sc.player_registry(user, filters={"query": op}, workspace_id=ws.id)] == ["Mamadu Bah"]
    assert [r["name"] for r in sc.player_registry(user, filters={"query": "johnny"}, workspace_id=ws.id)] == ["Mamadu Bah"]
    assert [r["name"] for r in sc.player_registry(user, filters={"query": "s. mamadu"}, workspace_id=ws.id)] == ["Mamadu Bah"]


# ---- pathways separate + event unchanged (24/25/26) ----
def test_pathways_separate_and_existing_data_intact(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    ft = sc.create_player(user, "FT", workspace_id=ws.id)
    ac = sc.create_player(user, "AC", workspace_id=ws.id, player_type="academy")
    assert {r["name"] for r in sc.player_registry(user, filters={"player_type": "academy"}, workspace_id=ws.id)} == {"AC"}
    # a pre-existing plain player (no operational id) still loads + registry-safe
    from fap.scouting.models import Player
    legacy = Player(id="legacy-1", name="Legacy", owner=user.email, workspace_id=ws.id)
    sc.players.save(legacy)
    rows = {r["name"] for r in sc.player_registry(user, workspace_id=ws.id)}
    assert "Legacy" in rows


def test_event_capability_unchanged_with_alias(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    p = sc.create_player(user, "Mamadu Bah", workspace_id=ws.id)
    sc.add_alias(user, p.id, "S. Mamadu bah")
    ev = ("event_type,x,y,team,player,minute,match_id\n"
          "pass,10,20,Home,S. Mamadu bah,1,M1\n"
          "shot,90,45,Home,S. Mamadu bah,2,M1\n").encode()
    er = platform.datahub.analyze(ev, "match.csv")
    eds = platform.datahub.save_dataset(user, er.import_result, name="ev",
                                        workspace_id=ws.id, metadata={})
    platform.datahub.choose(user, eds.id)
    frame = sc.player_event_frame(user, p.id)
    assert frame is not None and len(frame) == 2
