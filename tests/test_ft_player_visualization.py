"""First-Team Player Intelligence — FT-P4: visual analysis + Save to Player.

Reuses the SHARED player-scoped viz workspace and chart engine (no second engine).
Charts render from the player's LINKED dataset resolved by id (active-independent);
Save-to-Player persists an immutable PNG (ImageStorage) + metadata (Player.document
['visual_assets']) scoped to the SINGLE resolved player, and it survives an active-
dataset switch, reload, and the source dataset disappearing. No DataFrame/Figure is
ever stored in the player document. Scouting is untouched.
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
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


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
               "xA per 90", "Shot assists per 90", "Touches in box per 90", "Duels won, %",
               "Passes per 90", "Dribbles per 90"]
    names = ["S. Mamadu bah"] + [f"Player {i}" for i in range(32)]
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
        user, platform.datahub.analyze(_league_csv(), "Malta CF.csv").scouting,
        name="2025/26 League Player Data", workspace_id=ws.id)
    ev = platform.datahub.save_dataset(
        user, platform.datahub.analyze(
            b"event_type,x,y,team,player,minute,match_id\npass,1,2,H,S. Mamadu bah,1,M1\n",
            "ev.csv").import_result, name="Match Events", workspace_id=ws.id, metadata={})
    platform.datahub.choose(user, ds.id)
    p = platform.players.create_player(user, display_name="Mamadu Bah", primary_position="CF",
                                       nationality="Liberia", workspace_id=ws.id)
    platform.players.link_dataset_identity(user, p.id, "S. Mamadu bah", dataset_id=ds.id, method="manual")
    platform.datahub.choose(user, ev.id)                # active = event ds, NOT the league
    try:
        yield platform, user, ws, ds, ev, p, tmp_path
    finally:
        try:
            platform.db.close()
        except Exception:
            pass


def _theme():
    return ThemeManager(str(_ASSETS)).get("opta_dark")


def _view(sc, user, pid, ds_id):
    c = sc.player_viz_context(user, pid, ds_id)
    v = viz.build_view(c["frame"], c["schema"], [c["primary"]], dataset_id=c["id"], dataset_name=c["name"])
    return c, v


# ---- charts render from a linked NON-active dataset ----
def test_pizza_radar_bar_scatter_render_from_linked_dataset(ctx):
    platform, user, ws, ds, ev, p, _ = ctx
    sc = platform.players                               # active dataset is the event ds
    c, v = _view(sc, user, p.id, ds.id)                 # league ds resolved by id, active-independent
    assert list(v.players) == ["S. Mamadu bah"]         # single player, not 33
    theme, ex = _theme(), ExportEngine()
    sug = viz.suggest_pizza_metrics(v, 6)
    srcs = v.sources()
    figs = [charts.pizza_chart(v, sug, theme), charts.radar_chart(v, sug, theme),
            charts.bar_chart(v, srcs[:8], theme),
            charts.scatter(v, srcs[0], srcs[1], theme, c["frame"])]
    import matplotlib.pyplot as plt
    for f in figs:
        assert len(ex.export(f, "c", fmt="png").data) > 0
        plt.close(f)


def test_chart_types_from_registry_not_hardcoded(ctx):
    assert "pizza" in viz.CHART_TYPES and "radar" in viz.CHART_TYPES and "scatter" in viz.CHART_TYPES


# ---- Save to Player (service round-trip) ----
def test_save_persists_metadata_and_png_single_scope(ctx):
    platform, user, ws, ds, ev, p, _ = ctx
    sc = platform.players
    c, v = _view(sc, user, p.id, ds.id)
    asset = sc.save_player_visualization(
        user, p.id, _PNG, dataset_id=c["id"], title="Pizza Analysis", viz_id="scouting_pizza",
        scope={"player": [c["primary"]]}, config={"metrics": v.sources()[:6], "theme": "opta_dark"},
        source_name=c["name"])
    assert asset["scope"] == {"player": ["S. Mamadu bah"]}    # single player, not 33
    assert asset["dataset_id"] == ds.id and asset["source_dataset_name"] == "2025/26 League Player Data"
    assert asset["player_id"] == p.id and asset["chart_type"] == "scouting_pizza"
    vs = sc.list_player_visualizations(p.id)
    assert len(vs) == 1
    assert sc.player_visualization_bytes(p.id, asset["id"]) == _PNG


def test_saved_survives_active_switch_and_reload(ctx):
    platform, user, ws, ds, ev, p, tmp_path = ctx
    sc = platform.players
    c, _ = _view(sc, user, p.id, ds.id)
    a = sc.save_player_visualization(user, p.id, _PNG, dataset_id=c["id"], title="Pizza",
                                     viz_id="scouting_pizza", scope={"player": [c["primary"]]},
                                     source_name=c["name"])
    platform.datahub.choose(user, ev.id)                # switch active away
    assert len(sc.list_player_visualizations(p.id)) == 1
    platform.db.close()
    from fap.bootstrap import init_platform
    p2 = init_platform(settings=_settings(tmp_path))
    try:
        vs = p2.players.list_player_visualizations(p.id)
        assert len(vs) == 1 and vs[0]["scope"] == {"player": ["S. Mamadu bah"]}
        assert p2.players.player_visualization_bytes(p.id, a["id"]) == _PNG
    finally:
        p2.db.close()


def test_missing_source_dataset_keeps_saved_visual(ctx):
    platform, user, ws, ds, ev, p, _ = ctx
    sc = platform.players
    # a saved asset whose source dataset id no longer resolves -> the PNG still loads
    a = sc.save_player_visualization(user, p.id, _PNG, dataset_id="ghost-ds",
                                     title="Radar", viz_id="scouting_radar",
                                     scope={"player": ["S. Mamadu bah"]}, source_name="Malta CF.csv")
    assert sc._wm.get_dataset("ghost-ds") is None        # source unavailable
    assert len(sc.list_player_visualizations(p.id)) == 1
    assert sc.player_visualization_bytes(p.id, a["id"]) == _PNG   # remains, not regenerated


def test_remove_only_targeted_asset(ctx):
    platform, user, ws, ds, ev, p, _ = ctx
    sc = platform.players
    c, _ = _view(sc, user, p.id, ds.id)
    ids = [sc.save_player_visualization(user, p.id, _PNG, dataset_id=c["id"], title=t,
                                        viz_id=f"scouting_{t.lower()}", scope={"player": [c["primary"]]},
                                        source_name=c["name"])["id"]
           for t in ("Pizza", "Radar", "Bar")]
    sc.delete_player_visualization(user, p.id, ids[1])
    rest = {a["id"] for a in sc.list_player_visualizations(p.id)}
    assert rest == {ids[0], ids[2]} and ids[1] not in rest


def test_no_dataframe_or_figure_in_document(ctx):
    platform, user, ws, ds, ev, p, _ = ctx
    sc = platform.players
    c, _ = _view(sc, user, p.id, ds.id)
    sc.save_player_visualization(user, p.id, _PNG, dataset_id=c["id"], title="Pizza",
                                 scope={"player": [c["primary"]]})
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


# ---- Save-to-Player UI round-trip through the SHARED workspace (nested-button safe) ----
class _Shell:
    def __init__(self, platform, user, ws):
        self.user = user
        self.platform = platform
        self.wm = platform.workspace_manager
        self.workspace_id = ws.id

    def goto(self, _):
        pass


class _Col:
    def download_button(self, *a, **k):
        return False

    def button(self, *a, **k):
        return str(k.get("key", "")).endswith("_assign")   # click the Save button


def test_ui_save_button_persists_via_workspace(ctx, monkeypatch):
    platform, user, ws, ds, ev, p, _ = ctx
    sc = platform.players
    st.session_state.clear()
    c, v = _view(sc, user, p.id, ds.id)
    fig = charts.pizza_chart(v, viz.suggest_pizza_metrics(v, 6), _theme())
    # run 1: Render stashes the PNG bytes
    W._stash_render(fig, "Pizza", ExportEngine(), stash_key="k_pz", viz_id="scouting_pizza",
                    config={"metrics": v.sources()[:6]})
    assert sc.list_player_visualizations(p.id) == []      # render alone must not save
    # run 2: Render is False, Save button is drawn + clicked -> must actually persist
    save = {"user": user, "svc": sc, "player": p, "dataset_id": c["id"], "source_name": c["name"],
            "primary": c["primary"], "theme_id": "opta_dark", "on_assign": None}
    monkeypatch.setattr(st, "image", lambda *a, **k: None)
    monkeypatch.setattr(st, "columns", lambda *a, **k: [_Col(), _Col(), _Col()])
    monkeypatch.setattr(st, "toast", lambda *a, **k: None)
    monkeypatch.setattr(st, "rerun", lambda *a, **k: None)
    W._show_stash("k_pz", key="ui", save=save)
    vs = sc.list_player_visualizations(p.id)
    assert len(vs) == 1                                    # THE FIX: click actually saved
    assert vs[0]["scope"] == {"player": ["S. Mamadu bah"]} and vs[0]["dataset_id"] == ds.id


def test_workspace_allow_save_defaults_keep_scouting_behavior():
    # allow_save=None must default to (on_assign is not None) so Scouting is unchanged
    import inspect
    sig = inspect.signature(W.render_scouting_viz_workspace)
    assert "allow_save" in sig.parameters and sig.parameters["allow_save"].default is None
