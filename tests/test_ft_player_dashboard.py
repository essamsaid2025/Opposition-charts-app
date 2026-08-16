"""First-Team Player Intelligence — FT-P7: premium performance dashboard.

Verifies the dashboard hero/strip/overview/performance/evidence render as the default
landing view, reusing the existing FT-P2..P6 services + shared dossier components. The
A-F rating here is a PERFORMANCE rating (not a recruitment fit). Analytics resolve by
dataset_id (active-independent); saved PNGs are displayed (never regenerated); legacy
players render cleanly; permissions hold; nothing new is persisted in Player.document.
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


def _viewer():
    from fap.identity.models import User
    from fap.identity.roles import Role
    return User(email="v@club.com", name="V", role=Role.READ_ONLY, provider_id="dev")


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
        user, platform.datahub.analyze(_league_csv(), "Malta CF.csv").scouting,
        name="Malta CF — Player Metrics", workspace_id=ws.id)
    ev = platform.datahub.save_dataset(
        user, platform.datahub.analyze(
            b"event_type,x,y,team,player,minute,match_id\npass,1,2,H,S. Mamadu bah,1,M1\n",
            "ev.csv").import_result, name="Match Events", workspace_id=ws.id, metadata={})
    platform.datahub.choose(user, ds.id)
    p = platform.players.create_player(user, display_name="Mamadu Bah", primary_position="CF",
                                       nationality="Liberia", foot="right", shirt_number=9,
                                       height=181, weight=74, workspace_id=ws.id)
    platform.players.link_dataset_identity(user, p.id, "S. Mamadu bah", dataset_id=ds.id, method="manual")
    platform.datahub.choose(user, ev.id)                # active = event ds, NOT the metric ds
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


def _page(edit=True):
    pg = FirstTeamPlayersPage()
    pg._can_edit = edit
    pg._can_delete = edit
    pg._can_medical = True
    pg._can_report = True
    return pg


def _capture(monkeypatch):
    calls = []
    monkeypatch.setattr(st, "markdown", lambda body="", *a, **k: calls.append(str(body)))
    return calls


# ---- performance rating (A-F, PERFORMANCE not recruitment) ----
def test_performance_rating_crud_and_not_fit(ctx):
    platform, user, ws, ds, ev, p, _ = ctx
    sc = platform.players
    for r in ("A", "b", "F"):
        sc.set_performance_rating(user, p.id, r)
        assert sc.performance_rating_of(sc.get_player(p.id)) == r.upper()
    with pytest.raises(ValueError):
        sc.set_performance_rating(user, p.id, "Z")
    # distinct from any dataset metric/fit — it's a stored analyst value
    intel = sc.player_intelligence(user, p.id)
    assert intel["rating"] == "F" and "fit" not in intel


def test_rating_persists_reload(ctx):
    platform, user, ws, ds, ev, p, tmp_path = ctx
    platform.players.set_performance_rating(user, p.id, "B")
    platform.db.close()
    from fap.bootstrap import init_platform
    p2 = init_platform(settings=_settings(tmp_path))
    try:
        assert p2.players.performance_rating_of(p2.players.get_player(p.id)) == "B"
    finally:
        p2.db.close()


# ---- intelligence aggregator ----
def test_player_intelligence_counts_active_independent(ctx):
    platform, user, ws, ds, ev, p, _ = ctx
    sc = platform.players
    sc.add_note(user, p.id, "note", kind="player")
    sc.save_player_visualization(user, p.id, _PNG, dataset_id=ds.id, title="Pizza",
                                 viz_id="scouting_pizza", scope={"player": ["S. Mamadu bah"]},
                                 source_name="Malta CF — Player Metrics")
    intel = sc.player_intelligence(user, p.id)          # active is the event ds
    assert intel["counts"]["data_sources"] >= 1 and intel["counts"]["visuals"] == 1
    assert intel["counts"]["notes"] == 1
    assert intel["rating"] == ""                         # unset -> honest empty


# ---- percentile highlights (data-derived, active-independent) ----
def test_percentile_highlights_from_linked_dataset(ctx):
    platform, user, ws, ds, ev, p, _ = ctx
    sc = platform.players                                 # active is event ds
    strengths, dev = sc.player_percentile_highlights(user, p.id, ds.id)
    assert strengths and all("percentile" in s and "name" in s for s in strengths)
    # switching active dataset does not change the highlights (dataset_id resolves them)
    platform.datahub.choose(user, ev.id)
    s2, _ = sc.player_percentile_highlights(user, p.id, ds.id)
    assert [x["name"] for x in s2] == [x["name"] for x in strengths]


# ---- hero + dashboard UI render ----
def test_hero_renders_identity_and_rating(ctx, monkeypatch):
    platform, user, ws, ds, ev, p, _ = ctx
    sc = platform.players
    sc.set_performance_rating(user, p.id, "B")
    sc.add_image(user, p.id, _PNG, "image/png", kind="profile")
    ov = sc.overview(user, p.id)
    intel = sc.player_intelligence(user, p.id)
    calls = _capture(monkeypatch)
    _page()._hero(_Shell(platform, user, ws), sc, sc.get_player(p.id), ov, intel)
    blob = "\n".join(calls)
    assert "Mamadu Bah" in blob and "Rating B" in blob and "data:image" in blob
    # first-team framing: no recruitment terminology in the hero
    for banned in ("Recruitment", "Shortlisted", "Priority", "Fit "):
        assert banned not in blob


def test_hero_missing_photo_fallback(ctx, monkeypatch):
    platform, user, ws, ds, ev, p, _ = ctx
    sc = platform.players
    ov = sc.overview(user, p.id)
    intel = sc.player_intelligence(user, p.id)
    calls = _capture(monkeypatch)
    _page()._hero(_Shell(platform, user, ws), sc, sc.get_player(p.id), ov, intel)  # no raise
    blob = "\n".join(calls)
    assert '<span class="ini">' in blob and "data:image" not in blob


def test_dashboard_tab_renders_active_independent(ctx):
    platform, user, ws, ds, ev, p, _ = ctx
    st.session_state.clear()
    sc = platform.players
    sc.save_player_visualization(user, p.id, _PNG, dataset_id=ds.id, title="Pizza",
                                 viz_id="scouting_pizza", scope={"player": ["S. Mamadu bah"]},
                                 source_name="Malta CF — Player Metrics")
    sc.add_note(user, p.id, "note", kind="player")
    ov = sc.overview(user, p.id)
    intel = sc.player_intelligence(user, p.id)
    # active is the event dataset; the dashboard must still resolve Malta by link id
    _page()._tab_dashboard(_Shell(platform, user, ws), sc, p.id, ov, intel)  # must not raise


def test_dashboard_visual_preview_uses_stored_png(ctx, monkeypatch):
    platform, user, ws, ds, ev, p, _ = ctx
    sc = platform.players
    a = sc.save_player_visualization(user, p.id, _PNG, dataset_id=ds.id, title="Pizza",
                                     viz_id="scouting_pizza", scope={"player": ["S. Mamadu bah"]},
                                     source_name="Malta CF — Player Metrics")
    imgs = []
    monkeypatch.setattr(st, "image", lambda data=None, *a, **k: imgs.append(data))
    st.session_state.clear()
    _page()._dashboard_visual_preview(_Shell(platform, user, ws), sc, p.id,
                                      sc.list_player_visualizations(p.id))
    assert _PNG in imgs                                  # stored bytes shown, not regenerated
    assert imgs[0] == sc.player_visualization_bytes(p.id, a["id"])


def test_dashboard_legacy_player_clean(ctx):
    platform, user, ws, ds, ev, p, _ = ctx
    st.session_state.clear()
    sc = platform.players
    q = sc.create_player(user, display_name="Legacy", primary_position="CF", workspace_id=ws.id)
    ov = sc.overview(user, q.id)
    intel = sc.player_intelligence(user, q.id)
    _page()._hero(_Shell(platform, user, ws), sc, sc.get_player(q.id), ov, intel)
    _page()._tab_dashboard(_Shell(platform, user, ws), sc, q.id, ov, intel)  # must not raise


# ---- permissions ----
def test_viewer_cannot_set_rating(ctx):
    platform, user, ws, ds, ev, p, _ = ctx
    from fap.core.exceptions import AuthError
    with pytest.raises((AuthError, PermissionError, Exception)):
        platform.players.set_performance_rating(_viewer(), p.id, "A")
    # viewer can read the aggregator
    assert platform.players.player_intelligence(_viewer(), p.id)["counts"]["data_sources"] >= 1


# ---- no new persistence pollution ----
def test_no_dataframe_or_figure_in_document(ctx):
    platform, user, ws, ds, ev, p, _ = ctx
    sc = platform.players
    sc.set_performance_rating(user, p.id, "A")
    sc.player_intelligence(user, p.id)
    sc.player_percentile_highlights(user, p.id, ds.id)
    doc = sc.get_player(p.id).document
    import matplotlib.figure as mf

    def scan(o):
        if isinstance(o, (pd.DataFrame, pd.Series, mf.Figure)):
            return True
        if isinstance(o, dict):
            return any(scan(x) for x in o.values())
        if isinstance(o, (list, tuple)):
            return any(scan(x) for x in o)
        return False
    assert scan(doc) is False
    assert doc.get("performance_rating") == "A"          # only the small metadata was added
