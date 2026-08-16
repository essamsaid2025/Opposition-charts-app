"""'Save to player' persistence path (Visual Evidence).

Regression: the 'Save to player' button lived INSIDE ``if st.button('Render'):``.
Streamlit buttons return True only on the run right after their click, so on the
rerun triggered by clicking Save, the Render block was skipped, the Save button was
never instantiated, and the click was dropped - the chart appeared to save but
nothing persisted. The fix stashes the rendered PNG bytes in session_state on the
Render click and draws the image + 'Save to player' button UNCONDITIONALLY every
run, so the Save button exists on the run where it is clicked.

These tests drive the real UI helpers (``_stash_render`` + ``_show_stash``) exactly
as the two runs happen in the app, and assert the asset lands in the player's
persistent visual_assets (scope = single player, tied to the source dataset by id),
survives an active-dataset switch + a full reload, and never stores a DataFrame or
Figure. The chart engine, renderers, themes, matcher and identity system are used
unchanged.
"""
import os
os.environ["FAP_TEST"] = "1"
import base64
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.figure as mf
import pandas as pd
import pytest
import streamlit as st

from fap.scouting import charts, viz
from fap.themes import ThemeManager
from fap.visuals.export import ExportEngine
from fap.ui.components import scouting_viz_workspace as W

_ASSETS = pathlib.Path(__file__).resolve().parent.parent / "assets" / "themes"


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
    return User(email="a@club.com", name="Ana", role=Role.SUPER_ADMIN, provider_id="dev")


def _malta_csv():
    metrics = ["Non-penalty goals per 90", "npxG per 90", "Progressive passes per 90",
               "xA per 90", "Shot assists per 90", "Touches in box per 90", "Duels won, %"]
    names = ["S. Mamadu bah"] + [f"Player {i}" for i in range(32)]
    rows = []
    for i, nm in enumerate(names):
        r = {"Player": nm, "Team": f"Club {i % 12}", "Age": 24,
             "League": "Malta Premier League 25-26", "Position": "CF"}
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
        user, platform.datahub.analyze(_malta_csv(), "Malta CF.csv").scouting,
        name="Malta CF 25-26", workspace_id=ws.id)
    ev = platform.datahub.save_dataset(
        user, platform.datahub.analyze(
            b"event_type,x,y,team,player,minute,match_id\npass,1,2,H,S. Mamadu bah,1,M1\n",
            "ev.csv").import_result, name="PL Events", workspace_id=ws.id, metadata={})
    platform.datahub.choose(user, ds.id)
    p = platform.scouting.create_player(user, "Mamadu Bah", workspace_id=ws.id)
    platform.scouting.link_dataset_identity(user, p.id, "S. Mamadu bah", method="manual")
    platform.datahub.choose(user, ev.id)                # active = event dataset, NOT Malta
    try:
        yield platform, user, ws, ds, ev, p, tmp_path
    finally:
        try:
            platform.db.close()
        except Exception:
            pass


def _theme():
    return ThemeManager(str(_ASSETS)).get("opta_dark")


def _save_ctx(sc, user, p, c):
    return {"user": user, "svc": sc, "player": p, "dataset_id": c["id"],
            "source_name": c["name"], "primary": c["primary"], "theme_id": "opta_dark",
            "on_assign": None}


class _Col:
    """A streamlit column stub: the Save button (key ending '_assign') is 'clicked'."""
    def download_button(self, *a, **k):
        return False

    def button(self, *a, **k):
        return str(k.get("key", "")).endswith("_assign")


def _click_save_across_rerun(monkeypatch, *, stash_key, ui_key, fig, title, viz_id,
                             config, save, ex):
    """Reproduce the two real runs: (run 1) Render click stashes bytes; (run 2) the
    Render button is NOT clicked (block skipped) yet the Save button is drawn and
    clicked. Returns the stashed PNG so callers can assert byte identity."""
    W._stash_render(fig, title, ex, stash_key=stash_key, viz_id=viz_id,
                    config=config)                       # run 1: Render
    png = st.session_state[stash_key]["png"]
    monkeypatch.setattr(st, "image", lambda *a, **k: None)
    monkeypatch.setattr(st, "columns", lambda *a, **k: [_Col(), _Col(), _Col()])
    monkeypatch.setattr(st, "toast", lambda *a, **k: None)
    monkeypatch.setattr(st, "rerun", lambda *a, **k: None)
    W._show_stash(stash_key, key=ui_key, save=save)      # run 2: Render False, Save True
    return png


# --------------------------------------------------------------- the core fix
def test_render_alone_does_not_save(ctx):
    platform, user, ws, ds, ev, p, _ = ctx
    sc = platform.scouting
    st.session_state.clear()
    c = sc.scouting_viz_context(user, p.id, ds.id)
    v = viz.build_view(c["frame"], c["schema"], [c["primary"]], dataset_id=c["id"],
                       dataset_name=c["name"])
    fig = charts.pizza_chart(v, viz.suggest_pizza_metrics(v, 6), _theme())
    W._stash_render(fig, "Pizza", ExportEngine(), stash_key="k_pzstash",
                    viz_id="scouting_pizza", config={"metrics": v.sources()[:6]})
    # rendering only stashes bytes; it must NOT create a persistent asset
    assert st.session_state["k_pzstash"]["png"]
    assert sc.list_player_visualizations(p.id) == []


def test_save_button_persists_after_render_rerun(ctx, monkeypatch):
    platform, user, ws, ds, ev, p, _ = ctx
    sc = platform.scouting
    st.session_state.clear()
    c = sc.scouting_viz_context(user, p.id, ds.id)
    v = viz.build_view(c["frame"], c["schema"], [c["primary"]], dataset_id=c["id"],
                       dataset_name=c["name"])
    fig = charts.pizza_chart(v, viz.suggest_pizza_metrics(v, 6), _theme())
    png = _click_save_across_rerun(
        monkeypatch, stash_key="k_pzstash", ui_key="k_pz", fig=fig, title="Pizza",
        viz_id="scouting_pizza", config={"metrics": v.sources()[:6]},
        save=_save_ctx(sc, user, p, c), ex=ExportEngine())
    vs = sc.list_player_visualizations(p.id)
    assert len(vs) == 1                                  # THE FIX: click actually saved
    a = vs[0]
    assert a["scope"] == {"player": ["S. Mamadu bah"]}   # single player, not 33
    assert a["dataset_id"] == ds.id                       # tied to the source dataset
    assert a["source_dataset_name"] == "Malta CF 25-26"
    assert a["player_id"] == p.id                         # anchored to the player id
    assert sc.player_visualization_bytes(p.id, a["id"]) == png   # immutable PNG


def test_saved_asset_shows_in_dashboard_visual_evidence(ctx, monkeypatch):
    platform, user, ws, ds, ev, p, _ = ctx
    sc = platform.scouting
    st.session_state.clear()
    c = sc.scouting_viz_context(user, p.id, ds.id)
    v = viz.build_view(c["frame"], c["schema"], [c["primary"]], dataset_id=c["id"],
                       dataset_name=c["name"])
    fig = charts.pizza_chart(v, viz.suggest_pizza_metrics(v, 6), _theme())
    _click_save_across_rerun(
        monkeypatch, stash_key="k_pzstash", ui_key="k_pz", fig=fig, title="Pizza",
        viz_id="scouting_pizza", config={"metrics": v.sources()[:6]},
        save=_save_ctx(sc, user, p, c), ex=ExportEngine())
    dash = sc.player_dashboard(user, p.id)               # exactly what the UI reads
    assert dash["counts"]["visualizations"] == 1
    assert len(dash["visualizations"]) == 1
    a = dash["visualizations"][0]
    assert sc.player_visualization_bytes(p.id, a["id"])  # bytes render, not regenerated


# --------------------------------------------------------------- independence
def test_three_charts_saved_are_independent(ctx, monkeypatch):
    platform, user, ws, ds, ev, p, _ = ctx
    sc = platform.scouting
    st.session_state.clear()
    c = sc.scouting_viz_context(user, p.id, ds.id)
    v = viz.build_view(c["frame"], c["schema"], [c["primary"]], dataset_id=c["id"],
                       dataset_name=c["name"])
    theme, ex, sug = _theme(), ExportEngine(), viz.suggest_pizza_metrics(v, 6)
    save = _save_ctx(sc, user, p, c)
    for i, (fig, title, vid) in enumerate([
            (charts.pizza_chart(v, sug, theme), "Pizza", "scouting_pizza"),
            (charts.radar_chart(v, sug, theme), "Radar", "scouting_radar"),
            (charts.bar_chart(v, sug, theme), "Bar", "scouting_bar")]):
        _click_save_across_rerun(
            monkeypatch, stash_key=f"stash_{i}", ui_key=f"ui_{i}", fig=fig, title=title,
            viz_id=vid, config={"metrics": sug}, save=save, ex=ex)
    vs = sc.list_player_visualizations(p.id)
    assert len(vs) == 3
    assert {a["viz_id"] for a in vs} == {"scouting_pizza", "scouting_radar", "scouting_bar"}
    assert all(a["scope"] == {"player": ["S. Mamadu bah"]} for a in vs)
    # deleting one removes ONLY that one
    sc.delete_player_visualization(user, p.id, vs[0]["id"])
    rest = sc.list_player_visualizations(p.id)
    assert len(rest) == 2 and vs[0]["id"] not in {a["id"] for a in rest}


def test_saved_via_button_survives_active_switch_and_reload(ctx, monkeypatch):
    platform, user, ws, ds, ev, p, tmp_path = ctx
    sc = platform.scouting
    st.session_state.clear()
    c = sc.scouting_viz_context(user, p.id, ds.id)
    v = viz.build_view(c["frame"], c["schema"], [c["primary"]], dataset_id=c["id"],
                       dataset_name=c["name"])
    fig = charts.pizza_chart(v, viz.suggest_pizza_metrics(v, 6), _theme())
    png = _click_save_across_rerun(
        monkeypatch, stash_key="k_pzstash", ui_key="k_pz", fig=fig, title="Pizza",
        viz_id="scouting_pizza", config={"metrics": v.sources()[:6]},
        save=_save_ctx(sc, user, p, c), ex=ExportEngine())
    platform.datahub.choose(user, ev.id)                 # switch active to the event ds
    assert len(sc.list_player_visualizations(p.id)) == 1  # still there, active-independent
    # full reload (new platform on the same on-disk store)
    platform.db.close()
    from fap.bootstrap import init_platform
    p2 = init_platform(settings=_settings(tmp_path))
    try:
        vs = p2.scouting.list_player_visualizations(p.id)
        assert len(vs) == 1
        assert vs[0]["dataset_id"] == ds.id and vs[0]["scope"] == {"player": ["S. Mamadu bah"]}
        assert p2.scouting.player_visualization_bytes(p.id, vs[0]["id"]) == png
    finally:
        p2.db.close()


def test_no_dataframe_or_figure_persisted_via_button(ctx, monkeypatch):
    platform, user, ws, ds, ev, p, _ = ctx
    sc = platform.scouting
    st.session_state.clear()
    c = sc.scouting_viz_context(user, p.id, ds.id)
    v = viz.build_view(c["frame"], c["schema"], [c["primary"]], dataset_id=c["id"],
                       dataset_name=c["name"])
    fig = charts.pizza_chart(v, viz.suggest_pizza_metrics(v, 6), _theme())
    _click_save_across_rerun(
        monkeypatch, stash_key="k_pzstash", ui_key="k_pz", fig=fig, title="Pizza",
        viz_id="scouting_pizza", config={"metrics": v.sources()[:6]},
        save=_save_ctx(sc, user, p, c), ex=ExportEngine())
    doc = sc.get_player(p.id).document

    def scan(o):
        if isinstance(o, (pd.DataFrame, pd.Series, mf.Figure)):
            return True
        if isinstance(o, dict):
            return any(scan(x) for x in o.values())
        if isinstance(o, (list, tuple)):
            return any(scan(x) for x in o)
        return False
    assert scan(doc) is False


# --------------------------------------------------------------- Malta CF scenario
def test_malta_cf_scenario_pizza_then_radar(ctx, monkeypatch):
    """Mandatory real scenario: save Pizza via the button -> appears in Visual
    Evidence -> switch active dataset -> still there -> reload -> still there ->
    save Radar -> both appear, each scoped to the single player + Malta dataset."""
    platform, user, ws, ds, ev, p, tmp_path = ctx
    sc = platform.scouting
    st.session_state.clear()
    c = sc.scouting_viz_context(user, p.id, ds.id)
    v = viz.build_view(c["frame"], c["schema"], [c["primary"]], dataset_id=c["id"],
                       dataset_name=c["name"])
    theme, ex, sug = _theme(), ExportEngine(), viz.suggest_pizza_metrics(v, 6)
    save = _save_ctx(sc, user, p, c)

    # 1) save Pizza -> Visual Evidence shows it
    _click_save_across_rerun(monkeypatch, stash_key="s0", ui_key="u0",
                             fig=charts.pizza_chart(v, sug, theme), title="Pizza",
                             viz_id="scouting_pizza", config={"metrics": sug},
                             save=save, ex=ex)
    assert sc.player_dashboard(user, p.id)["counts"]["visualizations"] == 1

    # 2) switch active dataset -> still there
    platform.datahub.choose(user, ev.id)
    assert len(sc.list_player_visualizations(p.id)) == 1

    # 3) reload -> still there
    platform.db.close()
    from fap.bootstrap import init_platform
    plat2 = init_platform(settings=_settings(tmp_path))
    sc2 = plat2.scouting
    assert len(sc2.list_player_visualizations(p.id)) == 1

    # 4) save Radar on the reloaded platform -> BOTH appear
    c2 = sc2.scouting_viz_context(user, p.id, ds.id)
    v2 = viz.build_view(c2["frame"], c2["schema"], [c2["primary"]], dataset_id=c2["id"],
                        dataset_name=c2["name"])
    _click_save_across_rerun(monkeypatch, stash_key="s1", ui_key="u1",
                             fig=charts.radar_chart(v2, viz.suggest_pizza_metrics(v2, 6), theme),
                             title="Radar", viz_id="scouting_radar",
                             config={"metrics": viz.suggest_pizza_metrics(v2, 6)},
                             save=_save_ctx(sc2, user, p, c2), ex=ex)
    try:
        vs = sc2.list_player_visualizations(p.id)
        assert len(vs) == 2
        assert {a["viz_id"] for a in vs} == {"scouting_pizza", "scouting_radar"}
        assert all(a["scope"] == {"player": ["S. Mamadu bah"]} for a in vs)
        assert all(a["dataset_id"] == ds.id for a in vs)
    finally:
        plat2.db.close()
