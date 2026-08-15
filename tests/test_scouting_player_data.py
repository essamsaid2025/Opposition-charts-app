"""P4.6 - persistent player data, dataset links & analysis assets.

A player accumulates data from many datasets over time. The persistent relationship
is the dataset LINK, read by dataset_id (never the active dataset). Metrics from a
linked player-scouting dataset stay available when another dataset becomes active
and after reload. Saved visualizations are immutable PNG assets carrying their
source dataset + player-only scope. No DataFrame/Figure is stored in the player.
"""
import os
os.environ["FAP_TEST"] = "1"
import base64
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dataclasses import replace

import pandas as pd
import pytest

from fap.scouting import identity

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def _settings(tmp_path):
    from fap.config.settings import (
        AppSettings, CacheSettings, DatabaseSettings, StorageSettings)
    return replace(AppSettings(environment="development"),
                   user_data_dir=str(tmp_path / "ud"),
                   database=DatabaseSettings(path=str(tmp_path / "ud" / "fap.sqlite3")),
                   cache=CacheSettings(backend="memory"), storage=StorageSettings(backend="local"))


def _user():
    from fap.identity.models import User
    from fap.identity.roles import Role
    return User(email="a@club.com", name="Ana", role=Role.SUPER_ADMIN, provider_id="dev")


@pytest.fixture()
def ctx(tmp_path):
    from fap.bootstrap import init_platform
    platform = init_platform(settings=_settings(tmp_path))
    user = _user()
    ws = platform.workspace_manager.ensure_workspace(user)
    try:
        yield platform, user, ws, tmp_path
    finally:
        try:
            platform.db.close()
        except Exception:
            pass


def _malta_csv(names=None):
    metrics = [f"M{i} per 90" for i in range(47)]
    names = names or (["S. Mamadu bah"] + [f"Player {i}" for i in range(32)])
    rows = []
    for i, nm in enumerate(names):
        r = {"Player": nm, "Team": f"Club {i % 12}", "Age": 24,
             "League": "Malta Premier League 25-26", "Position": "CF"}
        for j, m in enumerate(metrics):
            r[m] = ((i * 7 + j) % 100) / 100.0
        rows.append(r)
    return pd.DataFrame(rows).to_csv(index=False).encode()


def _link_malta(platform, user, ws, name="Malta CF 25-26"):
    ar = platform.datahub.analyze(_malta_csv(), "Malta CF.csv")
    ds = platform.datahub.save_scouting_dataset(user, ar.scouting, name=name, workspace_id=ws.id)
    return ds


def _event_ds(platform, user, ws, match, name):
    csv = ("event_type,x,y,team,player,minute,match_id\n"
           f"pass,1,2,H,S. Mamadu bah,1,{match}\nshot,3,4,H,S. Mamadu bah,2,{match}\n").encode()
    er = platform.datahub.analyze(csv, name + ".csv")
    return platform.datahub.save_dataset(user, er.import_result, name=name, workspace_id=ws.id, metadata={})


# ================================================================ 1-6 persistent metrics
def test_metrics_survive_active_change_and_multi_player_scope(ctx):
    platform, user, ws, _ = ctx
    sc = platform.scouting
    malta = _link_malta(platform, user, ws)
    platform.datahub.choose(user, malta.id)
    p = sc.create_player(user, "Mamadu Bah", workspace_id=ws.id)
    sc.link_dataset_identity(user, p.id, "S. Mamadu bah", method="manual")
    # metrics available; multi-player dataset returns ONLY this player's row
    prof = sc.player_dataset_profile(user, p.id, malta.id)
    assert prof["status"] == "metrics_available" and prof["metric_count"] == 47
    assert prof["entity_key"] == "S. Mamadu bah"
    # switch active to another dataset -> Malta metrics STILL available
    other = _link_malta(platform, user, ws, name="Other")
    platform.datahub.choose(user, other.id)
    prof2 = sc.player_dataset_profile(user, p.id, malta.id)
    assert prof2["status"] == "metrics_available" and prof2["metric_count"] == 47
    # player-not-in-active is not "player doesn't exist"
    assert sc.get_player(p.id) is not None


def test_link_and_metrics_persist_after_reload(ctx):
    platform, user, ws, tmp_path = ctx
    sc = platform.scouting
    malta = _link_malta(platform, user, ws)
    platform.datahub.choose(user, malta.id)
    p = sc.create_player(user, "Mamadu Bah", workspace_id=ws.id)
    sc.link_dataset_identity(user, p.id, "S. Mamadu bah", method="manual")
    platform.db.close()
    from fap.bootstrap import init_platform
    p2 = init_platform(settings=_settings(tmp_path))
    try:
        u2 = _user()
        prof = p2.scouting.player_dataset_profile(u2, p.id, malta.id)
        assert prof["status"] == "metrics_available" and prof["metric_count"] == 47
        assert any(d["dataset_id"] == malta.id for d in p2.scouting.player_data_sources(u2, p.id))
    finally:
        p2.db.close()


def test_multiple_datasets_linked(ctx):
    platform, user, ws, _ = ctx
    sc = platform.scouting
    malta = _link_malta(platform, user, ws)
    platform.datahub.choose(user, malta.id)
    p = sc.create_player(user, "Mamadu Bah", workspace_id=ws.id)
    sc.add_alias(user, p.id, "S. Mamadu bah")
    sc.link_dataset_identity(user, p.id, "S. Mamadu bah", method="manual")
    e1 = _event_ds(platform, user, ws, "M1", "PL Events A")
    e2 = _event_ds(platform, user, ws, "M2", "PL Events B")
    sc.link_match_evidence(user, p.id, e1.id, match_id="M1")
    sc.link_match_evidence(user, p.id, e2.id, match_id="M2")
    sources = {d["dataset_id"]: d for d in sc.player_data_sources(user, p.id)}
    assert malta.id in sources and e1.id in sources and e2.id in sources
    assert sources[malta.id]["kind"] == "player_scouting" and sources[malta.id]["status"] == "metrics_available"
    assert sources[e1.id]["kind"] == "event"


# ================================================================ 7-13 visualization assets
def test_save_visualization_scope_dataset_and_reload(ctx):
    platform, user, ws, tmp_path = ctx
    sc = platform.scouting
    malta = _link_malta(platform, user, ws)
    platform.datahub.choose(user, malta.id)
    p = sc.create_player(user, "Mamadu Bah", workspace_id=ws.id)
    sc.link_dataset_identity(user, p.id, "S. Mamadu bah", method="manual")
    asset = sc.save_player_visualization(user, p.id, _PNG, title="Pizza", viz_id="scouting_pizza")
    # scope = ONLY this player (never all 33), dataset_id + source captured
    assert asset["scope"] == {"player": ["S. Mamadu bah"]}
    assert asset["dataset_id"] == malta.id and asset["source_dataset_name"] == "Malta CF 25-26"
    assert sc.player_visualization_bytes(p.id, asset["id"]) == _PNG
    # survives active change
    other = _link_malta(platform, user, ws, name="Other")
    platform.datahub.choose(user, other.id)
    assert len(sc.list_player_visualizations(p.id)) == 1
    # survives reload + immutable
    platform.db.close()
    from fap.bootstrap import init_platform
    p2 = init_platform(settings=_settings(tmp_path))
    try:
        vs = p2.scouting.list_player_visualizations(p.id)
        assert len(vs) == 1 and vs[0]["scope"] == {"player": ["S. Mamadu bah"]}
        assert p2.scouting.player_visualization_bytes(p.id, asset["id"]) == _PNG
    finally:
        p2.db.close()


def test_visualization_immutable_after_dataset_change(ctx):
    platform, user, ws, _ = ctx
    sc = platform.scouting
    malta = _link_malta(platform, user, ws)
    platform.datahub.choose(user, malta.id)
    p = sc.create_player(user, "Mamadu Bah", workspace_id=ws.id)
    sc.link_dataset_identity(user, p.id, "S. Mamadu bah", method="manual")
    asset = sc.save_player_visualization(user, p.id, _PNG, title="Pizza")
    # re-import a DIFFERENT malta with same name -> the saved PNG bytes are unchanged
    _link_malta(platform, user, ws, name="Malta CF 25-26 v2")
    assert sc.player_visualization_bytes(p.id, asset["id"]) == _PNG


# ================================================================ 14-15 video/evidence intact
def test_video_and_evidence_still_dataset_scoped(ctx):
    platform, user, ws, _ = ctx
    sc = platform.scouting
    p = sc.create_player(user, "Mamadu Bah", workspace_id=ws.id)
    sc.add_alias(user, p.id, "S. Mamadu bah")
    e1 = _event_ds(platform, user, ws, "M1", "Match 1")
    platform.datahub.choose(user, e1.id)
    v = sc.add_external_video(user, p.id, "https://youtu.be/abc123XYZ00")
    sc.link_video_to_match(user, v.id, e1.id, "M1")
    # switch active elsewhere -> video events still from its dataset
    malta = _link_malta(platform, user, ws)
    platform.datahub.choose(user, malta.id)
    assert len(sc.video_events(user, p.id, sc.videos_repo.get(v.id))) == 2
    assert sc.player_evidence(user, p.id, match_id="M1")["matches"][0]["event_count"] == 2


# ================================================================ 16-17 deleted/missing dataset honest
def test_missing_dataset_is_honest_and_assets_survive(ctx):
    platform, user, ws, _ = ctx
    sc = platform.scouting
    malta = _link_malta(platform, user, ws)
    platform.datahub.choose(user, malta.id)
    p = sc.create_player(user, "Mamadu Bah", workspace_id=ws.id)
    sc.link_dataset_identity(user, p.id, "S. Mamadu bah", method="manual")
    asset = sc.save_player_visualization(user, p.id, _PNG, title="Pizza")
    # simulate the linked dataset becoming unavailable: point the link at a ghost id
    doc = dict(sc.get_player(p.id).document)
    doc["dataset_links"] = {"ghost": {"entity_key": "S. Mamadu bah", "dataset_name": "Ghost"}}
    sc._save_doc(user, p.id, doc, "test")
    prof = sc.player_dataset_profile(user, p.id, "ghost")
    assert prof["status"] == "unavailable"                    # honest, not "player not found"
    sources = sc.player_data_sources(user, p.id)
    assert sources and sources[0]["status"] == "unavailable" and sources[0]["exists"] is False
    assert sc.get_player(p.id) is not None                    # player kept
    assert sc.player_visualization_bytes(p.id, asset["id"]) == _PNG   # saved artifact survives


# ================================================================ 18-19 search
def test_search_by_opid_and_linked_dataset(ctx):
    platform, user, ws, _ = ctx
    sc = platform.scouting
    malta = _link_malta(platform, user, ws)
    platform.datahub.choose(user, malta.id)
    p = sc.create_player(user, "Mamadu Bah", workspace_id=ws.id)
    sc.link_dataset_identity(user, p.id, "S. Mamadu bah", method="manual")
    op = identity.operational_id_of(sc.get_player(p.id))
    assert [r["name"] for r in sc.player_registry(user, filters={"query": op}, workspace_id=ws.id)] == ["Mamadu Bah"]
    # linked dataset name is searchable (stored on the dataset_link)
    assert [r["name"] for r in sc.player_registry(user, filters={"query": "Malta CF"}, workspace_id=ws.id)] == ["Mamadu Bah"]


# ================================================================ 20-21 no DataFrame / Figure stored
def test_no_dataframe_or_figure_in_player_document(ctx):
    platform, user, ws, _ = ctx
    sc = platform.scouting
    malta = _link_malta(platform, user, ws)
    platform.datahub.choose(user, malta.id)
    p = sc.create_player(user, "Mamadu Bah", workspace_id=ws.id)
    sc.link_dataset_identity(user, p.id, "S. Mamadu bah", method="manual")
    sc.save_player_visualization(user, p.id, _PNG, title="Pizza")
    doc = sc.get_player(p.id).document

    def scan(o):
        import matplotlib.figure as mf
        if isinstance(o, (pd.DataFrame, pd.Series, mf.Figure)):
            return True
        if isinstance(o, dict):
            return any(scan(v) for v in o.values())
        if isinstance(o, (list, tuple)):
            return any(scan(v) for v in o)
        return False
    assert scan(doc) is False


def test_active_scouting_profile_still_works_backcompat(ctx):
    platform, user, ws, _ = ctx
    sc = platform.scouting
    malta = _link_malta(platform, user, ws)
    platform.datahub.choose(user, malta.id)
    p = sc.create_player(user, "Mamadu Bah", workspace_id=ws.id)
    sc.add_alias(user, p.id, "S. Mamadu bah")
    prof = sc.active_scouting_profile(user, p.id)          # active convenience unchanged
    assert prof is not None and len(prof["metrics"]) == 47 and prof["player"] == "S. Mamadu bah"
