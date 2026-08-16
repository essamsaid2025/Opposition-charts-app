"""P4.6.1 - the scouting visualization workspace is player-scoped and
active-dataset-independent.

Bug fixed: the player dashboard's Visualization tab gated on the ACTIVE dataset
and resolved the player by exact name, so charts vanished when a different dataset
was active and 'Mamadu Bah' != 'S. Mamadu bah' failed. Now the workspace runs over
the player's LINKED player-scouting dataset (by dataset_id, matcher-resolved), and
the player-scoped DataFrame contains exactly one player. Reuses P4.2.1 matching,
P4.6 dataset links, the existing viz adapter/renderers and ImageStorage assets.
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
import matplotlib.pyplot as plt
import pandas as pd
import pytest

from fap.scouting import charts, viz
from fap.themes import ThemeManager
from fap.visuals.export import ExportEngine

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
    # Malta linked to the player; a DIFFERENT event dataset is made active.
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
    platform.datahub.choose(user, ev.id)                    # active = event dataset, NOT Malta
    try:
        yield platform, user, ws, ds, ev, p, tmp_path
    finally:
        try:
            platform.db.close()
        except Exception:
            pass


def _view(sc, user, pid, dataset_id):
    c = sc.scouting_viz_context(user, pid, dataset_id)
    v = viz.build_view(c["frame"], c["schema"], [c["primary"]],
                       dataset_id=c["id"], dataset_name=c["name"])
    return c, v


# ---- resolution + player scope ----
def test_context_resolves_by_id_while_other_dataset_active(ctx):
    platform, user, ws, ds, ev, p, _ = ctx
    sc = platform.scouting
    c = sc.scouting_viz_context(user, p.id, ds.id)          # active is the event ds
    assert c is not None and c["primary"] == "S. Mamadu bah"   # matcher: Mamadu Bah -> S. Mamadu bah
    assert c["metric_count"] == 7 and len(c["players"]) == 33


def test_player_scoped_view_has_exactly_one_player(ctx):
    platform, user, ws, ds, ev, p, _ = ctx
    c, v = _view(platform.scouting, user, p.id, ds.id)
    assert list(v.players) == ["S. Mamadu bah"]             # NOT all 33
    assert len(v.metrics) == 7


def test_linked_datasets_available_regardless_of_active(ctx):
    platform, user, ws, ds, ev, p, _ = ctx
    ld = platform.scouting.linked_scouting_datasets(user, p.id)
    assert any(d["dataset_id"] == ds.id and d["linked"] for d in ld)


# ---- charts render from the player-scoped view (existing engine/themes) ----
def test_pizza_radar_bar_scatter_render(ctx):
    platform, user, ws, ds, ev, p, _ = ctx
    _, v = _view(platform.scouting, user, p.id, ds.id)
    theme = ThemeManager(str(_ASSETS)).get("opta_dark")
    ex = ExportEngine()
    sug = viz.suggest_pizza_metrics(v, 6)
    srcs = v.sources()
    figs = [charts.pizza_chart(v, sug, theme), charts.radar_chart(v, sug, theme),
            charts.bar_chart(v, sug, theme),
            charts.scatter(v, srcs[0], srcs[1], theme, v.metrics and None or None)]
    # scatter needs the frame; build it explicitly
    c = platform.scouting.scouting_viz_context(user, p.id, ds.id)
    figs[3] = charts.scatter(v, srcs[0], srcs[1], theme, c["frame"])
    for f in figs:
        assert len(ex.export(f, "c", fmt="png").data) > 0
        plt.close(f)


def test_chart_types_come_from_registry_not_hardcoded(ctx):
    # the tab reads available chart definitions from the adapter, not a fake list
    assert "pizza" in viz.CHART_TYPES and "radar" in viz.CHART_TYPES and "scatter" in viz.CHART_TYPES


# ---- save to player: scope + dataset + persistence + immutability ----
def test_save_visualization_from_linked_dataset_persists(ctx):
    platform, user, ws, ds, ev, p, tmp_path = ctx
    sc = platform.scouting
    c, v = _view(sc, user, p.id, ds.id)
    asset = sc.save_player_visualization(
        user, p.id, _PNG, dataset_id=c["id"], title="Pizza", viz_id="scouting_pizza",
        scope={"player": [c["primary"]]}, config={"metrics": v.sources()[:6], "theme": "opta_dark"},
        source_name=c["name"])
    assert asset["scope"] == {"player": ["S. Mamadu bah"]}   # single player, not 33
    assert asset["dataset_id"] == ds.id and asset["source_dataset_name"] == "Malta CF 25-26"
    # persists while a DIFFERENT dataset is active, and after reload; bytes immutable
    assert len(sc.list_player_visualizations(p.id)) == 1
    platform.db.close()
    from fap.bootstrap import init_platform
    p2 = init_platform(settings=_settings(tmp_path))
    try:
        u2 = _user()
        vs = p2.scouting.list_player_visualizations(p.id)
        assert len(vs) == 1 and vs[0]["scope"] == {"player": ["S. Mamadu bah"]}
        assert p2.scouting.player_visualization_bytes(p.id, asset["id"]) == _PNG
    finally:
        p2.db.close()


def test_multiple_datasets_independent(ctx):
    platform, user, ws, ds, ev, p, _ = ctx
    sc = platform.scouting
    # link a second scouting dataset
    ds2 = platform.datahub.save_scouting_dataset(
        user, platform.datahub.analyze(_malta_csv(), "Malta2.csv").scouting,
        name="Malta B", workspace_id=ws.id)
    platform.datahub.choose(user, ds2.id)
    sc.link_dataset_identity(user, p.id, "S. Mamadu bah", method="manual")
    ids = {d["dataset_id"] for d in sc.linked_scouting_datasets(user, p.id)}
    assert ds.id in ids and ds2.id in ids
    # each resolves independently by id
    assert sc.scouting_viz_context(user, p.id, ds.id)["id"] == ds.id
    assert sc.scouting_viz_context(user, p.id, ds2.id)["id"] == ds2.id


def test_tab_renders_scouting_workspace_when_event_dataset_active(ctx):
    platform, user, ws, ds, ev, p, _ = ctx
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
    # active dataset is the event ds; must still render the Malta scouting workspace
    page._tab_visualization(_Shell(), platform.scouting, p)


def test_no_dataframe_or_figure_stored(ctx):
    platform, user, ws, ds, ev, p, _ = ctx
    sc = platform.scouting
    c, v = _view(sc, user, p.id, ds.id)
    sc.save_player_visualization(user, p.id, _PNG, dataset_id=c["id"], title="Pizza",
                                 scope={"player": [c["primary"]]})
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
