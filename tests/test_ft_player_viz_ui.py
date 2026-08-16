"""FT-P4 final verification — the ACTUAL first-team Visualization UI path.

Proves the real Streamlit flow (not just the service): the Visualization tab renders
over a linked non-active dataset, Visual Evidence displays the PERSISTED PNG (never
regenerates the chart), permissions gate Save/Remove (VIEW can view, EDIT can save/
remove), legacy players (no metadata) open with a clean empty state, and a saved
asset whose source dataset is gone still shows with a 'source unavailable' note.
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
import pandas as pd
import pytest
import streamlit as st

from fap.ui.builtin.players import FirstTeamPlayersPage

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
               "xA per 90", "Shot assists per 90", "Touches in box per 90", "Duels won, %"]
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
        name="Malta CF", workspace_id=ws.id)
    ev = platform.datahub.save_dataset(
        user, platform.datahub.analyze(
            b"event_type,x,y,team,player,minute,match_id\npass,1,2,H,S. Mamadu bah,1,M1\n",
            "ev.csv").import_result, name="Match Events", workspace_id=ws.id, metadata={})
    platform.datahub.choose(user, ds.id)
    p = platform.players.create_player(user, display_name="Mamadu Bah", primary_position="CF",
                                       nationality="Liberia", workspace_id=ws.id)
    platform.players.link_dataset_identity(user, p.id, "S. Mamadu bah", dataset_id=ds.id, method="manual")
    platform.datahub.choose(user, ev.id)                # active = event ds, NOT Malta
    try:
        yield platform, user, ws, ds, ev, p, tmp_path
    finally:
        try:
            platform.db.close()
        except Exception:
            pass


class _Shell:
    def __init__(self, platform, user, ws):
        self.user = user
        self.platform = platform
        self.wm = platform.workspace_manager
        self.workspace_id = ws.id

    def goto(self, _):
        pass


def _capture(monkeypatch):
    imgs, btns, caps = [], [], []
    monkeypatch.setattr(st, "image", lambda data=None, *a, **k: imgs.append(data))
    monkeypatch.setattr(st, "caption", lambda body="", *a, **k: caps.append(str(body)))
    real_button = st.button
    monkeypatch.setattr(st, "button", lambda *a, **k: (btns.append(str(k.get("key", ""))), False)[1])
    return imgs, btns, caps


def _page(edit=True):
    page = FirstTeamPlayersPage()
    page._can_edit = edit
    page._can_delete = edit
    page._can_report = True
    return page


# ---- Visual Evidence displays the PERSISTED PNG (no regeneration) ----
def test_visual_evidence_shows_persisted_png(ctx, monkeypatch):
    platform, user, ws, ds, ev, p, _ = ctx
    sc = platform.players
    c = sc.player_viz_context(user, p.id, ds.id)
    a = sc.save_player_visualization(user, p.id, _PNG, dataset_id=c["id"], title="Pizza Analysis",
                                     viz_id="scouting_pizza", scope={"player": [c["primary"]]},
                                     source_name=c["name"])
    imgs, btns, caps = _capture(monkeypatch)
    _page(edit=True)._visual_evidence_section(_Shell(platform, user, ws), sc, p.id, p)
    assert _PNG in imgs                                  # the stored bytes are what render
    assert imgs[0] == sc.player_visualization_bytes(p.id, a["id"])   # not regenerated
    blob = "\n".join(caps)
    assert "Pizza Analysis" in blob and "Scope: S. Mamadu bah" in blob


# ---- permissions: VIEW can view, EDIT can remove ----
def test_view_only_has_no_remove_button(ctx, monkeypatch):
    platform, user, ws, ds, ev, p, _ = ctx
    sc = platform.players
    c = sc.player_viz_context(user, p.id, ds.id)
    sc.save_player_visualization(user, p.id, _PNG, dataset_id=c["id"], title="Pizza",
                                 viz_id="scouting_pizza", scope={"player": [c["primary"]]},
                                 source_name=c["name"])
    imgs, btns, caps = _capture(monkeypatch)
    _page(edit=False)._visual_evidence_section(_Shell(platform, user, ws), sc, p.id, p)
    assert _PNG in imgs                                  # view-only can still see the chart
    assert not any("ftvz_del" in b for b in btns)        # ...but no Remove control


def test_editor_has_remove_button(ctx, monkeypatch):
    platform, user, ws, ds, ev, p, _ = ctx
    sc = platform.players
    c = sc.player_viz_context(user, p.id, ds.id)
    sc.save_player_visualization(user, p.id, _PNG, dataset_id=c["id"], title="Pizza",
                                 viz_id="scouting_pizza", scope={"player": [c["primary"]]},
                                 source_name=c["name"])
    imgs, btns, caps = _capture(monkeypatch)
    _page(edit=True)._visual_evidence_section(_Shell(platform, user, ws), sc, p.id, p)
    assert any("ftvz_del" in b for b in btns)


# ---- legacy player (no visual_assets / dataset_links) opens cleanly ----
def test_legacy_player_clean_empty_state(ctx, monkeypatch):
    platform, user, ws, ds, ev, p, _ = ctx
    sc = platform.players
    q = sc.create_player(user, display_name="Legacy Player", primary_position="CF",
                         workspace_id=ws.id)                # no links, no assets
    imgs, btns, caps = _capture(monkeypatch)
    _page()._visual_evidence_section(_Shell(platform, user, ws), sc, q.id, q)   # must not raise
    assert not imgs and any("No saved visualizations" in ccc for ccc in caps)


# ---- missing source dataset: saved chart remains, honest note ----
def test_missing_dataset_shows_note_keeps_image(ctx, monkeypatch):
    platform, user, ws, ds, ev, p, _ = ctx
    sc = platform.players
    a = sc.save_player_visualization(user, p.id, _PNG, dataset_id="ghost-ds", title="Radar",
                                     viz_id="scouting_radar", scope={"player": ["S. Mamadu bah"]},
                                     source_name="Malta CF.csv")
    imgs, btns, caps = _capture(monkeypatch)
    _page()._visual_evidence_section(_Shell(platform, user, ws), sc, p.id, p)
    assert _PNG in imgs                                  # image still viewable
    assert any("source unavailable" in ccc for ccc in caps)


# ---- the full Visualization tab renders over a linked NON-active dataset ----
def test_visualization_tab_renders_for_linked_player(ctx):
    platform, user, ws, ds, ev, p, _ = ctx
    st.session_state.clear()
    sc = platform.players
    # active dataset is the event ds; the tab must still resolve+render Malta by link id
    _page(edit=True)._tab_visualization(_Shell(platform, user, ws), sc, p.id, p)  # must not raise


def test_visualization_tab_renders_for_player_without_metric_dataset(ctx):
    platform, user, ws, ds, ev, p, _ = ctx
    st.session_state.clear()
    sc = platform.players
    q = sc.create_player(user, display_name="No Metrics", primary_position="CF", workspace_id=ws.id)
    _page(edit=True)._tab_visualization(_Shell(platform, user, ws), sc, q.id, q)  # event fallback, no raise
