"""First-Team Player Intelligence — FT-P5: video, match evidence & event timeline.

Reuses the domain-neutral evidence + video-sync infrastructure. A video's actions
ALWAYS come from its PERSISTED dataset_id/match_id (Player.document['video_sync']),
never the active dataset. Sync survives active-dataset switches and reload; multiple
videos on different datasets never cross-contaminate; timestamps use the shared
event_video_time; legacy/unlinked videos never borrow the active dataset. No new
video engine, no migration, scouting untouched.
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


def _events_csv(match_id, rows):
    head = "event_type,x,y,team,player,minute,second,match_id\n"
    body = "".join(f"{et},1,2,H,S. Mamadu bah,{m},{s},{match_id}\n" for et, m, s in rows)
    return (head + body).encode()


@pytest.fixture()
def ctx(tmp_path):
    from fap.bootstrap import init_platform
    platform = init_platform(settings=_settings(tmp_path))
    user = _user()
    ws = platform.workspace_manager.ensure_workspace(user)
    dh = platform.datahub

    def _save(csv, name):
        return dh.save_dataset(user, dh.analyze(csv, name + ".csv").import_result,
                               name=name, workspace_id=ws.id, metadata={})
    d1 = _save(_events_csv("M1", [("pass", 1, 3), ("carry", 12, 41), ("shot", 27, 18)]), "Event D1")
    d2 = _save(_events_csv("M2", [("pass", 2, 0), ("recovery", 8, 11)]), "Event D2")
    # a player-scouting metric dataset (D3) — must never provide video actions
    d3 = platform.datahub.save_scouting_dataset(
        user, platform.datahub.analyze(
            pd.DataFrame([{"Player": "S. Mamadu bah", "Team": "H", "xG per 90": 0.4,
                           "Passes per 90": 40}]).to_csv(index=False).encode(), "Metrics.csv").scouting,
        name="League Metrics", workspace_id=ws.id)
    platform.datahub.choose(user, d1.id)
    p = platform.players.create_player(user, display_name="Mamadu Bah", primary_position="CF",
                                       workspace_id=ws.id)
    # aliases so identity matches the dataset spelling "S. Mamadu bah"
    pl = platform.players.get_player(p.id)
    doc = dict(pl.document); doc["aliases"] = ["S. Mamadu bah"]; pl.document = doc
    platform.players.players.save(pl)
    try:
        yield platform, user, ws, d1, d2, d3, p, tmp_path
    finally:
        try:
            platform.db.close()
        except Exception:
            pass


def _add_linked_video(sc, user, pid, *, url, dataset_id, match_id, offset=None):
    v = sc.add_video(user, pid, url=url, kind="match", title=f"Video {match_id}")
    sc.link_video_to_match(user, pid, v.id, dataset_id=dataset_id, match_id=match_id)
    if offset is not None:
        sc.set_video_sync(user, pid, v.id, match_id, offset)
    return v


# ---- creation + persistence + linking ----
def test_video_create_and_link_persists(ctx):
    platform, user, ws, d1, d2, d3, p, _ = ctx
    sc = platform.players
    v = _add_linked_video(sc, user, p.id, url="https://youtu.be/abc", dataset_id=d1.id, match_id="M1")
    sync = sc.video_sync_of(p.id, v.id)
    assert sync["dataset_id"] == d1.id and sync["match_id"] == "M1"
    assert sc.list_videos(p.id) and sc.list_videos(p.id)[0].id == v.id


def test_calibration_offset_persists(ctx):
    platform, user, ws, d1, d2, d3, p, _ = ctx
    sc = platform.players
    v = _add_linked_video(sc, user, p.id, url="https://youtu.be/abc", dataset_id=d1.id, match_id="M1")
    sc.set_video_sync(user, p.id, v.id, "M1", 200.0)
    assert sc.video_sync_of(p.id, v.id)["sync_offset_seconds"] == 200.0


# ---- events resolved from video.dataset_id (the mandatory scenario) ----
def test_events_come_from_video_dataset_not_active(ctx):
    platform, user, ws, d1, d2, d3, p, _ = ctx
    sc = platform.players
    v1 = _add_linked_video(sc, user, p.id, url="https://youtu.be/v1", dataset_id=d1.id, match_id="M1", offset=200.0)
    # D1 active: three actions E1/E2/E3
    ev = sc.video_events(user, p.id, v1)
    assert ev is not None and len(ev) == 3
    # switch active to the player-scouting D3 -> V1 STILL shows D1's 3 actions
    platform.datahub.choose(user, d3.id)
    ev = sc.video_events(user, p.id, v1)
    assert ev is not None and len(ev) == 3
    # switch active to D2 -> V1 STILL shows D1's 3 actions
    platform.datahub.choose(user, d2.id)
    ev = sc.video_events(user, p.id, v1)
    assert ev is not None and len(ev) == 3


def test_event_click_timestamp_uses_video_offset(ctx):
    platform, user, ws, d1, d2, d3, p, _ = ctx
    sc = platform.players
    from fap.ui.builtin.video_sync import event_video_time
    v1 = _add_linked_video(sc, user, p.id, url="https://youtu.be/v1", dataset_id=d1.id, match_id="M1", offset=200.0)
    ev = sc.video_events(user, p.id, v1).sort_values(["minute", "second"])
    first = ev.iloc[0]                                    # minute 1, second 3
    assert event_video_time(200.0, first["minute"], first["second"]) == 263.0
    platform.datahub.choose(user, d2.id)                 # active switched
    ev2 = sc.video_events(user, p.id, v1).sort_values(["minute", "second"])
    assert event_video_time(200.0, ev2.iloc[1]["minute"], ev2.iloc[1]["second"]) == 200.0 + 12 * 60 + 41


def test_reload_keeps_video_actions(ctx):
    platform, user, ws, d1, d2, d3, p, tmp_path = ctx
    sc = platform.players
    v1 = _add_linked_video(sc, user, p.id, url="https://youtu.be/v1", dataset_id=d1.id, match_id="M1", offset=200.0)
    platform.db.close()
    from fap.bootstrap import init_platform
    p2 = init_platform(settings=_settings(tmp_path))
    try:
        u2 = _user()
        p2.datahub.choose(u2, d2.id)                     # a different dataset is active after reload
        vv = p2.players.list_videos(p.id)[0]
        ev = p2.players.video_events(u2, p.id, vv)
        assert ev is not None and len(ev) == 3
        assert p2.players.video_sync_of(p.id, v1.id)["sync_offset_seconds"] == 200.0
    finally:
        p2.db.close()


# ---- multiple videos, no cross-contamination ----
def test_multiple_videos_isolated_by_dataset(ctx):
    platform, user, ws, d1, d2, d3, p, _ = ctx
    sc = platform.players
    v1 = _add_linked_video(sc, user, p.id, url="https://youtu.be/v1", dataset_id=d1.id, match_id="M1")
    v2 = _add_linked_video(sc, user, p.id, url="https://youtu.be/v2", dataset_id=d2.id, match_id="M2")
    assert len(sc.video_events(user, p.id, v1)) == 3     # D1/M1
    assert len(sc.video_events(user, p.id, v2)) == 2     # D2/M2
    platform.datahub.choose(user, d3.id)                 # unrelated active
    assert len(sc.video_events(user, p.id, v1)) == 3
    assert len(sc.video_events(user, p.id, v2)) == 2


def test_exact_match_isolation(ctx):
    platform, user, ws, d1, d2, d3, p, _ = ctx
    sc = platform.players
    # link a video to D1 but the WRONG match id -> no events (never falls back)
    v = sc.add_video(user, p.id, url="https://youtu.be/x", kind="match", title="wrong")
    sc.link_video_to_match(user, p.id, v.id, dataset_id=d1.id, match_id="M2")
    ev = sc.video_events(user, p.id, v)
    assert ev is not None and len(ev) == 0               # M2 rows absent from D1


# ---- honest states: legacy/unlinked, missing dataset, player-scouting ----
def test_legacy_video_without_dataset_returns_none(ctx):
    platform, user, ws, d1, d2, d3, p, _ = ctx
    sc = platform.players
    v = sc.add_video(user, p.id, url="https://youtu.be/legacy", kind="match", title="legacy")
    assert sc.video_events(user, p.id, v) is None        # unlinked -> explicit linking, never active
    assert sc.video_sync_of(p.id, v.id) == {}


def test_player_scouting_dataset_yields_no_events(ctx):
    platform, user, ws, d1, d2, d3, p, _ = ctx
    sc = platform.players
    v = sc.add_video(user, p.id, url="https://youtu.be/x", kind="match", title="metrics")
    sc.link_video_to_match(user, p.id, v.id, dataset_id=d3.id, match_id="")
    assert sc.video_events(user, p.id, v) is None        # metric dataset != event data


def test_missing_dataset_keeps_link_returns_none(ctx):
    platform, user, ws, d1, d2, d3, p, _ = ctx
    sc = platform.players
    v = sc.add_video(user, p.id, url="https://youtu.be/x", kind="match", title="ghost")
    sc.link_video_to_match(user, p.id, v.id, dataset_id="ghost-ds", match_id="M9")
    assert sc.video_events(user, p.id, v) is None        # missing -> honest none
    assert sc.video_sync_of(p.id, v.id)["dataset_id"] == "ghost-ds"   # link kept, not dropped


# ---- unlink / notes / delete / match history ----
def test_unlink_and_note(ctx):
    platform, user, ws, d1, d2, d3, p, _ = ctx
    sc = platform.players
    v = _add_linked_video(sc, user, p.id, url="https://youtu.be/v1", dataset_id=d1.id, match_id="M1")
    sc.set_video_note(user, p.id, v.id, "Good movement between lines")
    assert sc.video_sync_of(p.id, v.id)["note"] == "Good movement between lines"
    sc.unlink_video(user, p.id, v.id)
    assert sc.video_sync_of(p.id, v.id)["dataset_id"] == "" and sc.video_events(user, p.id, v) is None


def test_delete_video_removes_sync(ctx):
    platform, user, ws, d1, d2, d3, p, _ = ctx
    sc = platform.players
    v = _add_linked_video(sc, user, p.id, url="https://youtu.be/v1", dataset_id=d1.id, match_id="M1")
    sc.delete_video(user, p.id, v.id)
    assert sc.get_player(p.id) is not None and v.id not in sc._video_sync(sc.get_player(p.id))
    assert not any(x.id == v.id for x in sc.list_videos(p.id))


def test_match_history_aggregates_across_datasets(ctx):
    platform, user, ws, d1, d2, d3, p, _ = ctx
    sc = platform.players
    _add_linked_video(sc, user, p.id, url="https://youtu.be/v1", dataset_id=d1.id, match_id="M1", offset=200.0)
    _add_linked_video(sc, user, p.id, url="https://youtu.be/v2", dataset_id=d2.id, match_id="M2")
    platform.datahub.choose(user, d3.id)                 # active is unrelated
    matches = {(m["dataset_id"], m["match_id"]): m for m in sc.player_matches(user, p.id)}
    assert (d1.id, "M1") in matches and (d2.id, "M2") in matches
    assert matches[(d1.id, "M1")]["event_count"] == 3 and matches[(d1.id, "M1")]["synced"]
    assert matches[(d2.id, "M2")]["event_count"] == 2 and matches[(d1.id, "M1")]["videos"] == 1


def test_no_dataframe_or_figure_in_document(ctx):
    platform, user, ws, d1, d2, d3, p, _ = ctx
    sc = platform.players
    v = _add_linked_video(sc, user, p.id, url="https://youtu.be/v1", dataset_id=d1.id, match_id="M1", offset=200.0)
    sc.set_video_note(user, p.id, v.id, "note")
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


# ---- UI render (bare mode; real tab path) ----
class _Shell:
    def __init__(self, platform, user, ws):
        self.user = user
        self.platform = platform
        self.wm = platform.workspace_manager
        self.workspace_id = ws.id

    def goto(self, _):
        pass


def _page(edit=True):
    from fap.ui.builtin.players import FirstTeamPlayersPage
    pg = FirstTeamPlayersPage()
    pg._can_edit = edit
    pg._can_delete = edit
    pg._can_report = True
    return pg


def test_videos_tab_renders_linked_and_active_independent(ctx):
    import streamlit as st
    platform, user, ws, d1, d2, d3, p, _ = ctx
    st.session_state.clear()
    sc = platform.players
    _add_linked_video(sc, user, p.id, url="https://youtu.be/v1", dataset_id=d1.id, match_id="M1", offset=200.0)
    platform.datahub.choose(user, d3.id)                 # unrelated active dataset
    _page(edit=True)._tab_videos(_Shell(platform, user, ws), sc, p.id)   # must not raise


def test_videos_tab_legacy_player_clean(ctx):
    import streamlit as st
    platform, user, ws, d1, d2, d3, p, _ = ctx
    st.session_state.clear()
    sc = platform.players
    q = sc.create_player(user, display_name="Legacy", primary_position="CF", workspace_id=ws.id)
    _page(edit=True)._tab_videos(_Shell(platform, user, ws), sc, q.id)   # no videos, no raise
