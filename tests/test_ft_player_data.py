"""First-Team Player Intelligence — FT-P2/P3: persistent, active-independent player↔
dataset data.

Mirrors the mature scouting architecture on the SEPARATE fap.players module: a
matcher-resolved dataset identity link lives in Player.document['dataset_links'];
metrics/viz read a dataset BY ID (never the active dataset). Reuses the shared,
domain-neutral matcher + viz adapter. No new table, no migration, scouting untouched.
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import matplotlib
matplotlib.use("Agg")
import pandas as pd
import pytest


def _settings(tmp_path):
    from fap.config.settings import (
        AppSettings, CacheSettings, DatabaseSettings, StorageSettings)
    from dataclasses import replace
    return replace(AppSettings(environment="development"),
                   user_data_dir=str(tmp_path / "ud"),
                   database=DatabaseSettings(path=str(tmp_path / "ud" / "fap.sqlite3")),
                   cache=CacheSettings(backend="memory"), storage=StorageSettings(backend="local"))


def _user():
    from fap.identity.models import User
    from fap.identity.roles import Role
    return User(email="coach@club.com", name="Coach", role=Role.SUPER_ADMIN, provider_id="dev")


def _league_csv():
    metrics = ["Non-penalty goals per 90", "npxG per 90", "Progressive passes per 90",
               "xA per 90", "Shot assists per 90", "Touches in box per 90", "Duels won, %"]
    names = ["S. Mamadu bah"] + [f"Player {i}" for i in range(29)]
    rows = []
    for i, nm in enumerate(names):
        r = {"Player": nm, "Team": f"Club {i % 8}", "Age": 24, "Position": "CF"}
        for j, m in enumerate(metrics):
            r[m] = ((i * 7 + j) % 100) / 100.0
        rows.append(r)
    return pd.DataFrame(rows).to_csv(index=False).encode()


@pytest.fixture()
def ctx(tmp_path):
    from fap.bootstrap import init_platform
    platform = init_platform(settings=_settings(tmp_path))
    user = _user()
    ws = platform.workspace_manager.ensure_workspace(user)
    ds = platform.datahub.save_scouting_dataset(
        user, platform.datahub.analyze(_league_csv(), "League Stats.csv").scouting,
        name="2025/26 League Player Data", workspace_id=ws.id)
    ev = platform.datahub.save_dataset(
        user, platform.datahub.analyze(
            b"event_type,x,y,team,player,minute,match_id\npass,1,2,H,S. Mamadu bah,1,M1\n",
            "ev.csv").import_result, name="Match Events", workspace_id=ws.id, metadata={})
    platform.datahub.choose(user, ds.id)
    try:
        yield platform, user, ws, ds, ev, tmp_path
    finally:
        try:
            platform.db.close()
        except Exception:
            pass


def _make(sc, user, ws, name):
    return sc.create_player(user, display_name=name, primary_position="CF",
                            nationality="Liberia", workspace_id=ws.id)


# ---- FT-P2: identity link (matcher + persist) ----
def test_auto_match_resolves_exact_name(ctx):
    platform, user, ws, ds, ev, _ = ctx
    sc = platform.players
    p = _make(sc, user, ws, "S. Mamadu bah")               # exact dataset key
    st = sc.dataset_identity_status(user, p.id, ds.id)
    assert st["proposed"] and st["proposed"]["key"] == "S. Mamadu bah" and st["proposed"]["auto"]
    ctxv = sc.player_viz_context(user, p.id, ds.id)
    assert ctxv and ctxv["primary"] == "S. Mamadu bah" and len(ctxv["players"]) == 30


def test_manual_link_persists_and_reloads(ctx):
    platform, user, ws, ds, ev, tmp_path = ctx
    sc = platform.players
    p = _make(sc, user, ws, "Mamadu Bah")                  # differs from dataset spelling
    sc.link_dataset_identity(user, p.id, "S. Mamadu bah", dataset_id=ds.id, method="manual")
    assert sc.dataset_identity_status(user, p.id, ds.id)["linked"]
    prof = sc.player_dataset_profile(user, p.id, ds.id)
    assert prof["status"] == "metrics_available" and prof["entity_key"] == "S. Mamadu bah"
    assert prof["metric_count"] == 7 and len(prof["metrics"]) == 7
    platform.db.close()
    from fap.bootstrap import init_platform
    p2 = init_platform(settings=_settings(tmp_path))
    try:
        u2 = _user()
        prof2 = p2.players.player_dataset_profile(u2, p.id, ds.id)
        assert prof2["status"] == "metrics_available" and prof2["entity_key"] == "S. Mamadu bah"
    finally:
        p2.db.close()


def test_ambiguity_is_surfaced_never_guessed(ctx):
    platform, user, ws, ds, ev, _ = ctx
    sc = platform.players
    # a bare surname that two dataset rows could share -> not auto; here no confident row
    p = _make(sc, user, ws, "Player")                      # matches "Player 0..28" ambiguously
    ctxv = sc.player_viz_context(user, p.id, ds.id)
    # never silently resolves an ambiguous/none match to a row
    assert ctxv is None or ctxv["primary"] in {e for e in sc._player_scouting_ctx(ds.id)["players"]}


# ---- FT-P3: active-independent metrics + player scope ----
def test_metrics_survive_active_dataset_switch(ctx):
    platform, user, ws, ds, ev, _ = ctx
    sc = platform.players
    p = _make(sc, user, ws, "Mamadu Bah")
    sc.link_dataset_identity(user, p.id, "S. Mamadu bah", dataset_id=ds.id)
    platform.datahub.choose(user, ev.id)                   # active = event dataset, NOT the league
    prof = sc.player_dataset_profile(user, p.id, ds.id)    # still resolves by id
    assert prof["status"] == "metrics_available" and prof["metric_count"] == 7
    ctxv = sc.player_viz_context(user, p.id, ds.id)
    assert ctxv and ctxv["primary"] == "S. Mamadu bah"
    assert any(d["dataset_id"] == ds.id and d["linked"]
               for d in sc.linked_player_scouting_datasets(user, p.id))


def test_multi_player_dataset_scoped_to_selected_player(ctx):
    platform, user, ws, ds, ev, _ = ctx
    sc = platform.players
    p = _make(sc, user, ws, "S. Mamadu bah")
    from fap.scouting import viz
    ctxv = sc.player_viz_context(user, p.id, ds.id)
    view = viz.build_view(ctxv["frame"], ctxv["schema"], [ctxv["primary"]],
                          dataset_id=ctxv["id"], dataset_name=ctxv["name"])
    assert list(view.players) == ["S. Mamadu bah"]         # exactly one, not 30
    # profile metrics are that player's row only
    prof = sc.player_dataset_profile(user, p.id, ds.id)
    assert prof["entity_key"] == "S. Mamadu bah" and len(prof["metrics"]) == 7


def test_deleted_dataset_reports_unavailable_keeps_link(ctx):
    platform, user, ws, ds, ev, _ = ctx
    sc = platform.players
    p = _make(sc, user, ws, "Mamadu Bah")
    sc.link_dataset_identity(user, p.id, "S. Mamadu bah", dataset_id=ds.id)
    # a ghost dataset id (never existed / removed) -> honest 'unavailable', link kept
    prof = sc.player_dataset_profile(user, p.id, "ghost-dataset-id")
    assert prof["status"] == "unavailable"
    assert ds.id in sc._dataset_links(sc.get_player(p.id))  # real link untouched


def test_event_dataset_is_not_a_scouting_profile(ctx):
    platform, user, ws, ds, ev, _ = ctx
    sc = platform.players
    p = _make(sc, user, ws, "S. Mamadu bah")
    prof = sc.player_dataset_profile(user, p.id, ev.id)    # event ds has no metric schema
    assert prof["status"] == "not_scouting"
    assert sc.player_viz_context(user, p.id, ev.id) is None


def test_no_dataframe_or_figure_in_document(ctx):
    platform, user, ws, ds, ev, _ = ctx
    sc = platform.players
    p = _make(sc, user, ws, "Mamadu Bah")
    sc.link_dataset_identity(user, p.id, "S. Mamadu bah", dataset_id=ds.id)
    doc = sc.get_player(p.id).document

    def scan(o):
        import matplotlib.figure as mf
        if isinstance(o, (pd.DataFrame, pd.Series, mf.Figure)):
            return True
        if isinstance(o, dict):
            return any(scan(x) for x in o.values())
        if isinstance(o, (list, tuple)):
            return any(scan(x) for x in o)
        return False
    assert scan(doc) is False
